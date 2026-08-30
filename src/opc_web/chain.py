# -*- coding: utf-8 -*-
"""自动执行链（v1.12 主路径）：控制台直跑 headless —— 拆解 → 逐子任务按角色卡执行 → 回报落工作区 → 状态回填。

v1.9 曾改为“仅生成指令待主会话 R1 执行”，导致主会话不在线时任务永远待派；
本模块恢复控制台 headless 直跑为主路径，常驻主会话 R1 变为可选增强。
"""
import datetime
import re

from . import agent, config, queue, runner, scheduler as sch


def set_state(**kw):
    """带锁更新调度状态。"""
    with sch.SCHED_LOCK:
        sch.SCHED_STATE.update(kw)


def run_headless(task_text, timeout=480.0):
    """同步直跑 dsh headless（最终文本模式），返回 stdout 文本。"""
    return runner.run_headless_sync(task_text, timeout)


def brief(text, n=140):
    """从 headless 产出提炼回报摘要（单行）。"""
    t = (text or "").strip().replace("\n", " ").replace("|", "／")
    return t[:n]


def parse_dispatch_rows(text):
    """解析 headless 拆解输出的派发单表格行。"""
    out = []
    pat = re.compile(r"^\|?\s*(T-\S+)?\s*\|\s*([^|]+?)\s*\|\s*(R\d+)[^|]*\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|?$")
    for ln in (text or "").split("\n"):
        m = pat.match(ln.strip())
        if m:
            out.append({"sub": m.group(2).strip(), "role": m.group(3).strip(),
                        "expect": m.group(4).strip()})
    return out


def decompose(task_no, task_text):
    """headless 拆解任务 → 子任务行列表；失败兜底单子任务。"""
    prompt = (
        "你是任务拆解器。只拆下面这一个任务，不得引用任何历史任务编号。"
        "拆解为最多 2 个可并行子任务，每个子任务指派一个现有角色编号，"
        "角色编号用 agents/ 下已有角色卡（如 R2 需求研究员 / R3 内容工厂 / R4 视觉设计 / R5 产品设计 / "
        "R6 技术架构 / R7 前端实现 / R8 后端实现 / R9 测试）。"
        "输出严格的派发单表格行（每行一条，无多余内容）：\n"
        "| %s | 子任务描述 | R? | 期望产出 | 待派 |\n"
        "任务：%s" % (task_no, task_text))
    text = run_headless(prompt, 480)
    rows = parse_dispatch_rows(text)
    if not rows:
        m = re.search(r"R(\d+)", task_text)
        role = "R" + m.group(1) if m else "R2"
        rows = [{"sub": task_text[:120], "role": role, "expect": "交付任务成果并回报"}]
    return rows


def execute(task_no, task_text):
    """一键自动执行链（headless 直跑，主路径）：
    拆解 → 逐子任务按角色卡执行 → 回报落工作区 → 派发单 / 回报队列 / 任务队列状态回填。"""
    with sch.SCHED_LOCK:
        if sch.SCHED_STATE.get("busy"):
            return
        sch.SCHED_STATE.update({"busy": True, "paused": False, "lastOk": None,
                                "tag": "启动执行链 %s" % task_no})
    try:
        set_state(tag="R1 拆解中…")
        subs = decompose(task_no, task_text)
        total = len(subs)
        # 派发单追加节
        dfile = config.dispatch_file()
        rows_md = "\n".join("| %s | %s | %s | %s | 待派 |" % (task_no, s["sub"], s["role"], s["expect"]) for s in subs)
        with open(dfile, "a", encoding="utf-8") as fh:
            fh.write("\n\n### %s · 自动执行链拆解（%s）\n\n%s\n" % (
                task_no, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), rows_md))
        rep_rows = []
        ok_cnt = 0
        for i, s in enumerate(subs):
            set_state(tag="执行中 %d/%d：%s → %s" % (i + 1, total, s["sub"][:16], s["role"]))
            t = "执行子任务：%s。期望产出：%s。完成后回报（含固定尾行）。" % (s["sub"], s["expect"])
            text = run_headless(agent.agent_prompt(s["role"], t), 480)
            ok = bool(text and text.strip())
            brf = brief(text) if ok else "（无产出）"
            wdir = config.wb_root() / config.role_ws_dir(s["role"])
            wdir.mkdir(parents=True, exist_ok=True)
            tail = "\n\n回报人：%s｜任务：%s｜状态：%s" % (s["role"], task_no, "完成" if ok else "阻塞")
            (wdir / "回报-待落库.md").write_text((text or "").rstrip() + tail + "\n", encoding="utf-8")
            rep_rows.append("| %s | %s | R%s | %s | %s |" % (
                datetime.date.today().isoformat(), task_no, s["role"][1:], brf[:70], "完成" if ok else "阻塞"))
            if ok:
                ok_cnt += 1
        # 任务队列回填
        queue.update_queue(task_no, "完成" if ok_cnt == total else "阻塞",
                           "%d/%d 子任务完成" % (ok_cnt, total))
        # 回报队列追加（去重）
        rfile = config.report_file()
        cur = rfile.read_text(encoding="utf-8") if rfile.exists() else ""
        with open(rfile, "a", encoding="utf-8") as fh:
            if cur and not cur.endswith("\n"):
                fh.write("\n")
            for r in rep_rows:
                if r not in cur:
                    fh.write(r + "\n")
        set_state(lastOk=True, tag="执行链完成 %s → %d/%d 子任务" % (task_no, ok_cnt, total))
        agent.log_schedule("自动执行链完成 %s" % task_no,
                           "拆解 %d 个子任务，完成 %d。见《工作区/<角色名称>/回报-待落库.md》。" % (total, ok_cnt))
    except Exception as e:
        set_state(lastOk=False, tag="执行链异常：" + str(e)[:80])
    finally:
        with sch.SCHED_LOCK:
            sch.SCHED_STATE["busy"] = False
