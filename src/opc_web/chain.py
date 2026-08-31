# -*- coding: utf-8 -*-
"""自动执行链（v1.12 主路径）：控制台直跑 headless —— 拆解 → 逐子任务按角色卡执行 → 回报落工作区 → 状态回填。

v1.9 曾改为"仅生成指令待主会话 R1 执行"，导致主会话不在线时任务永远待派；
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
    """headless 拆解任务 → 子任务行列表。

    规则（v1.13）：任务文本中已点名角色编号（如「R8 设计一个…」）→ 不拆解、直接单子任务
    直派该角色（"我说了让谁执行就谁执行"）；未点名才让模型按真实角色表拆解。"""
    named = re.search(r"R(\d+)", task_text)
    if named:
        role = "R" + named.group(1)
        return [{"sub": task_text[:160], "role": role, "expect": "交付任务成果并回报"}]
    try:
        from . import roles as _roles
        role_cards = _roles.role_files()
    except Exception:
        role_cards = []
    table = "；".join("%s %s" % (no, name) for no, name in role_cards) if role_cards else \
        "R2 需求研究员 / R3 内容工厂 / R4 增长运营 / R5 用户洞察官 / R6 数据分析官 / R7 财务与合规 / R8 产品设计师(前端实现) / R9 技术评估与实现"
    prompt = (
        "你是任务拆解器。只拆下面这一个任务，不得引用任何历史任务编号。"
        "现有角色表（每个子任务必须指派表中真实存在的编号，不许编造）：%s。\n"
        "拆解为最多 2 个可并行子任务，输出严格的派发单表格行（每行一条，无多余内容）：\n"
        "| %s | 子任务描述 | R? | 期望产出 | 待派 |\n"
        "任务：%s" % (table, task_no, task_text))
    text = run_headless(prompt, 480)
    rows = parse_dispatch_rows(text)
    # 校验：模型若拆出表中不存在的角色编号 → 丢弃该行（防旧映射/编造编号）
    ok_roles = dict(role_cards) if role_cards else {}
    rows = [row for row in rows if not ok_roles or row["role"] in ok_roles]
    if not rows:
        rows = [{"sub": task_text[:120], "role": "R2", "expect": "交付任务成果并回报"}]
    return rows


def execute(task_no, task_text):
    """一键自动执行链（headless 直跑，主路径）：
    拆解 → 逐子任务按角色卡执行 → 回报落工作区 → 派发单 / 回报队列 / 任务队列状态回填。
    全程把阶段事件写入 runner 事件流（工作台「agent 执行监听」面板实时可见）。"""
    with sch.SCHED_LOCK:
        if sch.SCHED_STATE.get("busy"):
            return
        sch.SCHED_STATE.update({"busy": True, "paused": False, "lastOk": None,
                                "tag": "启动执行链 %s" % task_no})
    try:
        runner.emit({"type": "run/start", "task": "%s · 自动执行链" % task_no,
                     "provider": "opc-web", "model": "chain"})
        runner.emit({"type": "step/start", "data": {"turn": 1, "step": 1}})
        runner.emit({"type": "assistant/chunk", "data": {"text": "▶ R1 拆解 %s：%s" % (task_no, task_text[:80])}})
        set_state(tag="R1 拆解中…")
        subs = decompose(task_no, task_text)
        total = len(subs)
        names = ", ".join("%s→%s" % (s["role"], s["sub"][:18]) for s in subs)
        runner.emit({"type": "assistant/chunk", "data": {"text": "✔ 拆解完成 %d 项：%s" % (total, names)}})
        runner.emit({"type": "step/end", "data": {"turn": 1, "step": 1}})
        # 派发单追加节
        # 幂等：追加前先清除该任务编号的旧拆解节（防重复执行累积多节、执行角色重复显示）
        dfile = config.dispatch_file()
        if dfile.exists():
            _dtxt = dfile.read_text(encoding="utf-8")
            _secs = _dtxt.split("\n### ")
            _kept = [_secs[0]]
            for _s in _secs[1:]:
                if _s.startswith(task_no + " · 自动执行链拆解"):
                    continue
                _kept.append(_s)
            dfile.write_text("\n### ".join(_kept), encoding="utf-8")
        rows_md = "\n".join("| %s | %s | %s | %s | 待派 |" % (task_no, s["sub"], s["role"], s["expect"]) for s in subs)
        with open(dfile, "a", encoding="utf-8") as fh:
            fh.write("\n\n### %s · 自动执行链拆解（%s）\n\n%s\n" % (
                task_no, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), rows_md))
        rep_rows = []
        ok_cnt = 0
        for i, s in enumerate(subs):
            set_state(tag="执行中 %d/%d：%s → %s" % (i + 1, total, s["sub"][:16], s["role"]))
            runner.emit({"type": "step/start", "data": {"turn": i + 2, "step": 1}})
            runner.emit({"type": "assistant/chunk", "data": {"text": "▶ 派发 %s：%s（期望 %s）" % (s["role"], s["sub"][:60], s["expect"][:40])}})
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
            runner.emit({"type": "assistant/chunk", "data": {"text": "↳ %s 回报：%s" % (s["role"], brf[:70])}})
            runner.emit({"type": "step/end", "data": {"turn": i + 2, "step": 1, "reason": {"kind": "完成" if ok else "阻塞"}}})
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
        runner.emit({"type": "run/end", "text": "执行链完成 %s：%d/%d 子任务 · 回报已落工作区" % (task_no, ok_cnt, total)})
    except Exception as e:
        set_state(lastOk=False, tag="执行链异常：" + str(e)[:80])
        runner.emit({"type": "run/exited", "data": {"code": -1}, "error": str(e)[:120]})
    finally:
        with sch.SCHED_LOCK:
            sch.SCHED_STATE["busy"] = False
