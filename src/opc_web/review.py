# -*- coding: utf-8 -*-
"""R0 批阅写入：唯一写操作（写入《决策/批阅台.md》对应待决的「R0 批阅」栏）。"""
import datetime
import re

from . import config, knowledge
from .parsers import HEAD_RE, JUDGE_RE, SECTION_RE


def _verb_of(judge: str) -> str:
    """从批阅判断文本提取动词（兼容 ✅ 批准 / 批准 / ❌ 驳回 等形态，md 不落表情符）。"""
    if "驳回" in judge or "❌" in judge:
        return "驳回"
    if "批准" in judge or "同意" in judge or "✅" in judge:
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
