# -*- coding: utf-8 -*-
"""R0 批阅写入：唯一写操作（写入《决策/批阅台.md》对应待决的「R0 批阅」栏）。"""
import datetime
import re

from . import config, knowledge
from .parsers import HEAD_RE, JUDGE_RE, SECTION_RE


def _verb_of(judge: str) -> str:
    """从批阅判断文本提取动词（批准 / 驳回 / 修改，md 不落表情符）。"""
    if "驳回" in judge:
        return "驳回"
    if "批准" in judge or "同意" in judge:
        return "批准"
    return "修改"


def write_piyue(item: str, judge: str, opinion: str) -> str:
    """向《批阅台/批阅台.md》对应待决写入 R0 批阅（纯文字，不带表情符），返回写入行。"""
    rel = config.PIYUETAI_REL
    text = knowledge.read_md(rel)
    lines = text.split("\n")
    today = datetime.date.today().isoformat()
    new_line = f"- **R0 批阅**：{today}：{_verb_of(judge)}" + (f"。意见：{opinion.strip()}" if opinion.strip() else "")
    target = None
    for i, ln in enumerate(lines):
        if HEAD_RE.match(ln) and re.match(rf"^###\s+待决\s+{re.escape(item)}\s*[｜|]", ln):
            target = i
            break
    if target is None:
        raise ValueError(f"未找到 待决 #{item}")
    for j in range(target + 1, len(lines)):
        if HEAD_RE.match(lines[j]) or SECTION_RE.match(lines[j]):
            break
        if JUDGE_RE.match(lines[j]):
            lines[j] = new_line
            break
    else:
        raise ValueError(f"待决 #{item} 缺少「R0 批阅」栏")
    (config.ROOT / rel).write_text("\n".join(lines), encoding="utf-8")
    return new_line


_WORK_HEAD = re.compile(r"^###\s+工作\s+(\d+)\s*[｜|]\s*(.+)$")


def archive_work(item_no) -> str:
    """R0 看完例行进展 → 把「### 工作 N」段从工作内容区移到已批阅归档区（标记已阅）。

    返回归档标题；找不到条目抛 ValueError。"""
    rel = config.PIYUETAI_REL
    text = knowledge.read_md(rel)
    lines = text.split("\n")
    start = end = None
    for i, ln in enumerate(lines):
        m = _WORK_HEAD.match(ln)
        if m and int(m.group(1)) == item_no:
            start = i
            title = m.group(2).strip()
            break
    if start is None:
        raise ValueError("未找到 工作 #%d" % item_no)
    for j in range(start + 1, len(lines)):
        if HEAD_RE.match(lines[j]) or _WORK_HEAD.match(lines[j]) or SECTION_RE.match(lines[j]):
            end = j
            break
    if end is None:
        end = len(lines)
    block = lines[start:end]
    # 归档段：加「R0 批阅：日期：已阅归档」行（judged → parse 归入 archive）
    today = datetime.date.today().isoformat()
    mark = "- **R0 批阅**：" + today + "：已阅归档"
    kept = [ln for ln in block if not JUDGE_RE.match(ln)]
    kept.append(mark)
    # 从原处移除
    rest = lines[:start] + lines[end:]
    # 插到「## 已批阅归档」区末尾
    out = []
    inserted = False
    for i, ln in enumerate(rest):
        if not inserted and SECTION_RE.match(ln) and "已批阅归档" in ln:
            # 找到该区段结束（下一个 ## 或文件尾），在其前插入
            j = i + 1
            while j < len(rest) and not SECTION_RE.match(rest[j]):
                j += 1
            out.extend(rest[:j])
            out.append("")
            out.extend(kept)
            out.extend(rest[j:])
            inserted = True
            break
    if not inserted:
        out = rest + [""] + kept
    (config.ROOT / rel).write_text("\n".join(out), encoding="utf-8")
    return title
