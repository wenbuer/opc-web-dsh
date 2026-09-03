# -*- coding: utf-8 -*-
"""知识库 md 解析器：批阅台 / 角色架构 / 派发单 / 决策日志 / 时间线 / 任务清单。"""
import datetime
import re

from . import config, knowledge, store

# ---------- 批阅台 ----------
# 条目分两类：### 工作 N（例行进展，进「工作内容查看」）｜### 待决 N（R1 认为需 R0 拍板，进「决策裁决」）
HEAD_RE = re.compile(r"^###\s+待决\s+(\d+)\s*[｜|]\s*(.+)$")
HEAD_WORK_RE = re.compile(r"^###\s+工作\s+(\d+)\s*[｜|]\s*(.+)$")
JUDGE_RE = re.compile(r"^\s*-\s*\*\*[^：]*批阅[^：]*\*\*[:：]\s*(.*)$")
SECTION_RE = re.compile(r"^##\s+")


def _flush(cur, out):
    if cur is None:
        return
    item = {"n": cur["n"], "title": cur["title"], "lines": cur["lines"], "kind": cur["kind"]}
    if cur["judged"]:                       # 已有实质批阅/已阅 → 归档区
        out["archive"].append(item)
    elif cur["kind"] == "工作":             # 例行进展（无批阅栏）→ 工作内容
        out["work"].append(item)
    else:
        out["pending"].append(item)         # 待决未裁决 → 决策裁决


def parse_piyuetai(text: str) -> dict:
    """解析《批阅台/批阅台.md》 → {work:[例行进展], pending:[待决策], archive:[已批阅归档]}。"""
    lines = text.split("\n")
    out = {"work": [], "pending": [], "archive": []}
    cur = None
    for ln in lines:
        if SECTION_RE.match(ln):                     # 章节边界
            _flush(cur, out)
            cur = None
            continue
        m = HEAD_RE.match(ln)
        wm = HEAD_WORK_RE.match(ln) if not m else None
        if m or wm:
            _flush(cur, out)
            cur = {"n": int((m or wm).group(1)), "title": (m or wm).group(2).strip(),
                   "judged": False, "lines": [], "kind": "待决" if m else "工作"}
            continue
        if cur is not None:
            if ln.startswith("  ") and cur["lines"]:
                # 两空格缩进 = 上一字段值的续行（md 多行字段）：并入上一行，保留换行
                cur["lines"][-1] += "\n" + ln.strip()
                continue
            jm = JUDGE_RE.match(ln)
            if jm:
                val = jm.group(1).strip()
                if val and "待填" not in val:
                    cur["judged"] = True             # 已批阅/已阅：有实质内容
                cur["lines"].append(ln)              # 批阅行本身也保留 —— 决策归档要展示 裁决/意见
            elif ln.strip() and ln.strip() != "---":
                cur["lines"].append(ln)              # 收集背景/R 建议/需要拍板/进展
    _flush(cur, out)
    for bucket in (out["work"], out["pending"], out["archive"]):
        for it in bucket:
            it.pop("judged", None)
    return out


# ---------- 角色架构 ----------
def parse_roles() -> list:
    """解析《知识库/OPC智能体角色架构.md》→ 角色清单（编号/名称/职责/产出/详情/状态/当前工作）。"""
    text = knowledge.read_md(config.ARCH_REL)
    lines = text.split("\n")
    rows = []
    reRow = re.compile(r"^\|\s*(R\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")
    for ln in lines:
        m = reRow.match(ln)
        if m:
            rows.append({"code": m.group(1), "name": m.group(2).strip(),
                         "duty": m.group(3).strip(), "target": m.group(4).strip(), "desc": ""})
    reCard = re.compile(r"^###\s+(R\d+)\s+(.+)$")
    reDuty = re.compile(r"^-\s*\*\*职责\*\*[:：]\s*(.+)$")
    for i in range(len(lines)):
        m = reCard.match(lines[i])
        if m:
            for j in range(i + 1, min(i + 8, len(lines))):
                dm = reDuty.match(lines[j])
                if dm:
                    for item in rows:
                        if item["code"] == m.group(1):
                            item["desc"] = dm.group(1).strip()
                    break
    # v1.18：状态只有两种 —— 有未完成子任务 = 执行中，否则待命中；R0/R1 固定指挥中。
    # 原先是一张写死的 st_def/cur_def（R4/R5「暂不激活」、R9「未激活」、「深访阶段未到」…），
    # 跟角色实际有没有活干毫无关系；决策日志里靠文本匹配出的状态同样早就对不上，一并弃用。
    busy, latest_sub = set(), {}
    for p in store.subtasks():                 # 已按编号排序，后写覆盖 = 该角色最新的子任务
        if p["st"] in ("待派", "已派"):
            busy.add(p["role"])
        latest_sub[p["role"]] = p
    last_exec = store.last_execution_by_role()
    for it in rows:
        code = it["code"]
        it["status"] = "指挥中" if code in ("R0", "R1") else ("执行中" if code in busy else "待命中")
        e = last_exec.get(code)
        if e and e.get("sub"):                 # 最近一次执行：执行中=正在做的，待命中=上次做的
            it["current"] = (e["sub_no"].rsplit("-S", 1)[0] if "-S" in e["sub_no"] else e["sub_no"])
        elif code in latest_sub:               # 无执行记录（如 md 迁移来的历史数据）→ 退到最新子任务
            it["current"] = latest_sub[code]["taskNo"]
        else:
            it["current"] = "无"
    return rows


# ---------- 决策日志（R0 公文，仍是 md：人读人写） ----------
def parse_timeline() -> list:
    """从《批阅台/决策日志.md》生成 OPC 时间线节点。"""
    text = knowledge.read_md(config.LOG_REL)
    lines = text.split("\n")
    # 项目建立日：取《决策日志.md》/项目根的创建时间（不再写死），回退今天。
    start = datetime.date.today().isoformat()
    for _p in (config.ROOT / config.LOG_REL, config.ROOT):
        try:
            start = datetime.datetime.fromtimestamp(_p.stat().st_ctime).date().isoformat()
            break
        except Exception:
            continue
    events = [{"date": start, "title": "OPC 建立（启动日）",
               "detail": "角色架构 v1.0、知识库索引、批阅台、决策日志、简报模板、需求假设清单 25 条落地"}]
    reD = re.compile(r"^##\s+D-\d+｜(.+?)（(\d{4}-\d{2}-\d{2})")
    reC = re.compile(r"^-\s*\*\*裁决内容\*\*[:：]\s*(.+)$")
    for i in range(len(lines)):
        m = reD.match(lines[i])
        if m:
            title = m.group(1).strip()
            detail = title[:40]
            for k in range(i + 1, min(i + 10, len(lines))):
                cm = reC.match(lines[k])
                if cm:
                    detail = cm.group(1).strip()[:90]
                    break
            events.append({"date": m.group(2), "title": title[:32], "detail": detail})
    # 并入「日报」时间线节点：产生《批阅台/每日简报-*.md》即出现一个节点；
    # 同一天只保留一条（与前面的日报节点合并），避免重复生成时累积多条。
    seen = {(e.get("date"), e.get("title")) for e in events}
    try:
        for p in sorted(config.BATCH_ROOT.glob("每日简报-*.md")):
            dm = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
            date = dm.group(1) if dm else ""
            detail = ""
            try:
                detail = config.read_text(p).split("\n")[0].strip()[:90]
            except Exception:
                detail = ""
            detail = detail or "当日各角色回报汇总"
            key = (date, "日报")
            if date and key not in seen:
                events.append({"date": date, "title": "日报", "detail": detail})
                seen.add(key)
    except Exception:
        pass
    events.sort(key=lambda x: x["date"])
    return events


