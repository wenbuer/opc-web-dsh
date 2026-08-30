# -*- coding: utf-8 -*-
"""知识库只读层：md 文件树与单文件读取（路径白名单约束；只读纪律在此强制）。"""
import re
from pathlib import Path

from . import config


def scan_md_files(root: Path) -> list:
    """返回 [{dir, files:[{name, rel}]}]，按顶层目录分组；根目录平铺归入 [根]。"""
    groups = {}
    for p in sorted(root.rglob("*.md")):
        if "legacy" in p.parts or "归档" in p.parts or "archive" in p.parts:
            continue
        if "工作区" in p.parts:          # 角色作业区不入知识库树（与旧版一致）
            continue
        rel = p.relative_to(config.ROOT).as_posix()
        top = rel.split("/")[0] if "/" in rel else "[根]"
        groups.setdefault(top, []).append({"name": p.name, "rel": rel})
    return [{"dir": d, "files": sorted(groups[d], key=lambda x: x["name"])} for d in sorted(groups)]


def read_md(rel: str) -> str:
    """读取知识库 md（仅限权威根内 .md，防路径逃逸）。"""
    p = (config.ROOT / rel).resolve()
    if not str(p).startswith(str(config.ROOT.resolve())) or not p.is_file() or p.suffix != ".md":
        raise ValueError("非根目录范 md 文件")
    return p.read_text(encoding="utf-8")


def latest_daily() -> list:
    """返回《批阅台/每日简报-*.md》列表（按文件名日期降序，无日期兜底按修改时间）。"""
    d = config.BATCH_ROOT
    if not d.is_dir():
        return []
    items = []
    for p in d.glob("每日简报-*.md"):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        items.append({"name": p.name, "rel": p.relative_to(config.ROOT).as_posix(),
                      "date": m.group(1) if m else "", "mtime": p.stat().st_mtime})
    items.sort(key=lambda x: (x["date"] or "", x["mtime"]), reverse=True)
    return items


def kb_entries() -> list:
    """知识库档案条目（卡片视角）：{rel, name, mtime, size, top, head}。
    知识库由老板助理（R1）统一管理、全体角色共同维护：角色产出先落工作区回报，
    经 R1 审核归档后进入《知识库/》，所有角色只读档案。"""
    out = []
    root = config.KB_ROOT
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*.md")):
        if "legacy" in p.parts or "归档" in p.parts or "archive" in p.parts:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except Exception:
            continue
        body_lines = [ln.strip() for ln in t.split("\n") if ln.strip() and not ln.strip().startswith("#")]
        table_rows = [ln for ln in body_lines if ln.startswith("|")]
        head = []
        for ln in body_lines:
            if ln.startswith("|") or ln.startswith("---"):
                continue
            head.append(ln)
            if len(head) >= 3:
                break
        if head:
            htxt = " ".join(head)[:240]
        elif table_rows:
            htxt = "（表格档案：" + str(len(table_rows) - 1) + " 行）" + " " + (table_rows[0] if table_rows else "")
        else:
            htxt = "（档案以标题为主，点击卡片查看全文）"
        rel = p.relative_to(config.ROOT).as_posix()
        krel = p.relative_to(root).as_posix()
        # top 相对知识库根计算：根目录内平铺文件 top=""（不再产生占位分组头）；
        # 只有真正的子目录（如 知识库/档案/）才作为分组名。
        top = krel.split("/")[0] if "/" in krel else ""
        st = p.stat()
        out.append({
            "rel": rel,
            "name": p.stem,
            "mtime": st.st_mtime,
            "size": st.st_size,
            "top": top,
            "head": htxt,
        })
    return out
