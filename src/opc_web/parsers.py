# -*- coding: utf-8 -*-
"""知识库 md 解析器：批阅台 / 角色架构 / 派发单 / 决策日志 / 时间线 / 任务清单。"""
import re

from . import config, knowledge

# ---------- 批阅台 ----------
HEAD_RE = re.compile(r"^###\s+待决\s+(\d+)\s*[｜|]\s*(.+)$")
JUDGE_RE = re.compile(r"^\s*-\s*\*\*[^：]*批阅[^：]*\*\*[:：]\s*(.*)$")
SECTION_RE = re.compile(r"^##\s+")


def parse_piyuetai(text: str) -> dict:
    """解析《批阅台/批阅台.md》 → {pending:[{n,title,lines}], archive:[{n,title}]}。"""
    lines = text.split("\n")
    pending, archive, cur = [], [], None
    for ln in lines:
        if SECTION_RE.match(ln):                     # 章节边界（待决区/归档区/流程区）
            if cur is not None:
                (archive if cur["judged"] else pending).append({k: cur[k] for k in ("n", "title", "lines")})
            cur = None
            continue
        m = HEAD_RE.match(ln)
        if m:
            if cur is not None:
                (archive if cur["judged"] else pending).append({k: cur[k] for k in ("n", "title", "lines")})
            cur = {"n": int(m.group(1)), "title": m.group(2).strip(), "judged": False, "lines": []}
            continue
        if cur is not None:
            jm = JUDGE_RE.match(ln)
            if jm:
                val = jm.group(1).strip()
                if val and "待填" not in val:
                    cur["judged"] = True             # 已批阅：有实质内容（✅/❌/✏️ + 日期）
                else:
                    cur["lines"].append(ln)          # 未批阅：保留“待填”占位行
            elif ln.strip() and ln.strip() != "---":
                cur["lines"].append(ln)              # 收集背景/R 建议/需要拍板
    if cur is not None:
        (archive if cur["judged"] else pending).append({k: cur[k] for k in ("n", "title", "lines")})
    for it in pending:
        it.pop("judged", None)
    for it in archive:
        it.pop("judged", None)
    return {"pending": pending, "archive": archive}


def pending_items() -> list:
    """快捷读取当前待决清单。"""
    return parse_piyuetai(knowledge.read_md(config.PIYUETAI_REL))["pending"]


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
    dispatch = {}
    for d in parse_dispatch():
        dispatch[d["roleCode"]] = d
    st_def = {"R0": "指挥中", "R1": "执行中", "R2": "执行中", "R3": "执行中", "R4": "暂不激活",
              "R5": "暂不激活", "R6": "执行中", "R7": "执行中", "R8": "执行中", "R9": "未激活"}
    cur_def = {"R0": "待批阅待决 8-15；发布/投放终审闸门", "R1": "D-009 已落实；日常调度+简报",
               "R4": "等应用设计完成后讨论投放", "R5": "深访阶段未到", "R9": "是否激活待 R0 批阅（待决 9）"}
    plan = {}
    for p in parse_plan_rows():
        plan.setdefault(p["role"], p)
    for it in rows:
        d = dispatch.get(it["code"]); p = plan.get(it["code"])
        if p:
            it["status"] = "执行中" if p["st"] and "完成" not in p["st"] else "执行中"
            it["current"] = p["sub"][:44]
            it["ref"] = "派发单-动态 " + p["no"]
        else:
            it["status"] = d["status"] if d else st_def.get(it["code"], "待命")
            it["current"] = d["current"] if d else cur_def.get(it["code"], "待命")
            it["ref"] = d["ref"] if d else ""
    return rows


# ---------- 派发单与决策日志 ----------
def parse_plan_rows() -> list:
    """读取《批阅台/派发单-动态.md》表行 → [{no, sub, role, expect, st}]。"""
    p = config.dispatch_file()
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^\|\s*(T-\S+)\s*\|\s*([^|]+?)\s*\|\s*(R\d+)[^|]*\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|$", ln)
        if m:
            out.append({"no": m.group(1).strip(), "sub": m.group(2).strip(),
                        "role": m.group(3).strip(), "expect": m.group(4).strip(),
                        "st": m.group(5).strip()})
    return out


def parse_dispatch() -> list:
    """解析《批阅台/决策日志.md》派发单 → [{role, roleCode, task, ref, target, status, current}]。"""
    text = knowledge.read_md(config.LOG_REL)
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("## 派发单"):
            start = i
            break
    if start is None:
        return []
    out = []
    reRow = re.compile(r"^\|\s*(R\d+)\s+([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        m = reRow.match(ln)
        if m:
            task = m.group(3).strip()
            status = "暂不激活" if ("暂不激活" in task or "未激活" in task) else "执行中"
            out.append({"role": m.group(1) + " " + m.group(2).strip(),
                        "roleCode": m.group(1), "task": task,
                        "ref": m.group(4).strip(), "target": m.group(5).strip(),
                        "status": status, "current": task[:44]})
    return out


def parse_timeline() -> list:
    """从《批阅台/决策日志.md》生成 OPC 时间线节点。"""
    text = knowledge.read_md(config.LOG_REL)
    lines = text.split("\n")
    events = [{"date": "2026-08-24", "title": "OPC 建立（启动日）",
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
    events.sort(key=lambda x: x["date"])
    return events


def parse_tasks() -> list:
    """当前任务清单 = 派发单 + 待批阅项。"""
    tasks = []
    for d in parse_dispatch():
        tasks.append({"type": "派发", "role": d["role"], "task": d["task"],
                      "ref": d["ref"], "target": d["target"], "status": d["status"]})
    data = parse_piyuetai(knowledge.read_md(config.PIYUETAI_REL))
    for it in data["pending"]:
        tasks.append({"type": "待批", "role": "R0", "task": "待决 #" + str(it["n"]) + "：" + it["title"],
                      "ref": "批阅台", "target": "", "status": "待 R0 批阅"})
    return tasks
