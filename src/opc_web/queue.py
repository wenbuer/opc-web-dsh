# -*- coding: utf-8 -*-
"""任务下达队列（决策/任务下达队列.md）读写。"""
import datetime
import re

from . import config


def next_task_no() -> int:
    try:
        text = config.queue_file().read_text(encoding="utf-8")
        nos = [int(m) for m in re.findall(r"T-(\d+)", text)]
        return (max(nos) + 1) if nos else 1
    except Exception:
        return 1


def parse_queue() -> list:
    try:
        lines = config.queue_file().read_text(encoding="utf-8").split("\n")
    except Exception:
        return []
    out = []
    for ln in lines:
        m = re.match(r"^\|\s*(T-\d+)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|\s*([^|]*)\s*\|", ln)
        if m:
            out.append({"no": m.group(1), "time": m.group(2).strip(), "task": m.group(3).strip(),
                        "expect": m.group(4).strip(), "status": m.group(5).strip(), "report": m.group(6).strip()})
    return out


def append_queue(task_text: str, expect: str = "R1 判断") -> str:
    no = "T-%03d" % next_task_no()
    row = "| %s | %s | %s | %s | 待派 | — |" % (no, datetime.date.today().isoformat(), task_text, expect)
    with open(config.queue_file(), "a", encoding="utf-8") as f:
        f.write(row + "\n")
    return no


def update_queue(no: str, status: str, report: str = "—") -> bool:
    lines = config.queue_file().read_text(encoding="utf-8").split("\n")
    for i, ln in enumerate(lines):
        if ("| " + no + " |") in ln:
            parts = ln.split("|")
            if len(parts) >= 7:
                parts[5] = " " + status + " "
                parts[6] = " " + report + " "
                lines[i] = "|".join(parts)
            break
    config.queue_file().write_text("\n".join(lines), encoding="utf-8")
    return True


def dispatch_task(text: str, expect: str) -> str:
    """首页「任务下达」→ 追加队列（R1 判断为默认期望）。"""
    return append_queue(text, expect)
