# -*- coding: utf-8 -*-
"""R0 批阅写入：唯一写操作（写入《决策/批阅台.md》对应待决的「R0 批阅」栏）。"""
import datetime
import re

from . import config, knowledge
from .parsers import HEAD_RE, JUDGE_RE, SECTION_RE


def write_piyue(item: str, judge: str, opinion: str) -> str:
    """向《决策/批阅台.md》对应待决写入 R0 批阅，返回写入行。"""
    rel = config.PIYUETAI_REL
    text = knowledge.read_md(rel)
    lines = text.split("\n")
    mark = "✅" if "✅" in judge else ("❌" if "❌" in judge else "✏️")
    verb = "批准" if mark == "✅" else ("驳回" if mark == "❌" else "修改")
    today = datetime.date.today().isoformat()
    new_line = f"- **R0 批阅**：{mark} {today}：{verb}" + (f"。意见：{opinion.strip()}" if opinion.strip() else "")
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
