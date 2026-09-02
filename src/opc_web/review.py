# -*- coding: utf-8 -*-
"""R0 批阅写入：唯一写操作（写入《批阅台/批阅台.md》对应待决的「R0 批阅」栏）。"""
import datetime
import re

from . import config, knowledge
from .parsers import HEAD_RE, HEAD_WORK_RE, JUDGE_RE, SECTION_RE


def verb_of(judge: str) -> str:
    """从批阅判断文本提取动词（批准 / 驳回 / 修改，md 不落表情符）。"""
    if "驳回" in judge:
        return "驳回"
    if "批准" in judge or "同意" in judge:
        return "批准"
    return "修改"


def _find_item(lines: list, no, kind: str) -> int:
    """定位「### 待决/工作 #no」条目标题行下标（找不到返回 -1）。"""
    pat = HEAD_RE if kind == "待决" else HEAD_WORK_RE
    try:
        want = int(no)
    except (TypeError, ValueError):
        return -1
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m and int(m.group(1)) == want:
            return i
    return -1


def _block_end(lines: list, start: int) -> int:
    """start 处条目的段尾：下一个 ### 待决/工作 条目或 ## 章节即边界，越界取文件尾。"""
    for i in range(start + 1, len(lines)):
        if HEAD_RE.match(lines[i]) or HEAD_WORK_RE.match(lines[i]) or SECTION_RE.match(lines[i]):
            return i
    return len(lines)


def _write(rel: str, lines: list) -> None:
    (config.ROOT / rel).write_text("\n".join(lines), encoding="utf-8")


def write_piyue(item: str, judge: str, opinion: str) -> str:
    """向《批阅台/批阅台.md》对应待决写入 R0 批阅（纯文字，不带表情符），返回写入行。"""
    rel = config.PIYUETAI_REL
    lines = knowledge.read_md(rel).split("\n")
    today = datetime.date.today().isoformat()
    new_line = f"- **R0 批阅**：{today}：{verb_of(judge)}" + (f"。意见：{opinion.strip()}" if opinion.strip() else "")
    start = _find_item(lines, item, "待决")
    if start < 0:
        raise ValueError(f"未找到 待决 #{item}")
    for j in range(start + 1, _block_end(lines, start)):
        if JUDGE_RE.match(lines[j]):
            lines[j] = new_line
            break
    else:
        raise ValueError(f"待决 #{item} 缺少「R0 批阅」栏")
    _write(rel, lines)
    return new_line


def append_r1_exec(item: str, text: str) -> str:
    """向 待决 #item 段尾追加（已有则替换）「R1 执行」行，供归档时展示 R1 是否执行。"""
    rel = config.PIYUETAI_REL
    lines = knowledge.read_md(rel).split("\n")
    start = _find_item(lines, item, "待决")
    if start < 0:
        raise ValueError(f"未找到 待决 #{item}")
    end = _block_end(lines, start)
    new_line = "- **R1 执行**：" + text
    for k in range(start + 1, end):
        if re.match(r"^\s*-\s*\*\*R1 执行\*\*\s*[:：]", lines[k]):
            lines[k] = new_line
            break
    else:
        lines.insert(end, new_line)
    _write(rel, lines)
    return new_line


def archive_work(item_no) -> str:
    """R0 看完例行进展 → 把「### 工作 N」段从工作内容区移到已批阅归档区（标记已阅）。

    返回归档标题；找不到条目抛 ValueError。"""
    rel = config.PIYUETAI_REL
    lines = knowledge.read_md(rel).split("\n")
    start = _find_item(lines, item_no, "工作")
    if start < 0:
        raise ValueError("未找到 工作 #%d" % item_no)
    end = _block_end(lines, start)
    title = HEAD_WORK_RE.match(lines[start]).group(2).strip()
    # 归档段：加「R0 批阅：日期：已阅归档」行（judged → parse 归入 archive）
    mark = "- **R0 批阅**：" + datetime.date.today().isoformat() + "：已阅归档"
    kept = [ln for ln in lines[start:end] if not JUDGE_RE.match(ln)]
    kept.append(mark)
    rest = lines[:start] + lines[end:]
    # 插到「## 已批阅归档」区末尾（无该区则追加文件尾）
    insert_at = None
    for i, ln in enumerate(rest):
        if SECTION_RE.match(ln) and "已批阅归档" in ln:
            j = i + 1
            while j < len(rest) and not SECTION_RE.match(rest[j]):
                j += 1
            insert_at = j
            break
    if insert_at is None:
        out = rest + [""] + kept
    else:
        out = rest[:insert_at] + [""] + kept + rest[insert_at:]
    _write(rel, out)
    return title
