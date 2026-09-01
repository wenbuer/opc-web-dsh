# -*- coding: utf-8 -*-
"""自动执行链 v1.15：拆解 → 落台账 → 逐子任务生成 subagent 派发指令 → 预置产出文件。

执行模型（v1.14 起未变）：控制台负责拆解并生成派发指令，常驻主会话 R1 用 DSH
subagent 实际派发；子 agent 边执行边把进度追加进自己的产出文件，有实时输出即
视为存活，不按"无输出超时"判阻塞。

v1.15 的改动只在存储层：
  - 任务/子任务状态从 md 表格搬进 SQLite（store.py），幂等由主键保证，
    不再需要「删掉旧 ### 节」「整行字符串去重」这类字符串手术；
  - 产出文件按子任务编号命名（T-001-S1.md），不再全角色共用「回报-待落库.md」；
  - 元数据由中枢预生成 .meta.json，子 agent 只回填 status，不再复述回报尾行。
"""
import datetime
import json
import re

from . import agent, config, runner, scheduler as sch, store


def set_state(**kw):
    """带锁更新调度状态。"""
    with sch.SCHED_LOCK:
        sch.SCHED_STATE.update(kw)


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


# 点名直派：只认任务开头的角色编号（「R8 开始设计…」是点名，「参考 R8 的设计…」是提及）。
# (?![\dA-Za-z]) 挡掉 R2D2 这类；连接词字符类允许「R2 和 R8 一起做」点两个人。
_NAMED_HEAD = re.compile(r"^\s*((?:R\d+(?![\dA-Za-z])[\s、,，和与/&+]*)+)")


def named_roles(task_text, ok):
    """任务开头点名的角色（按出现顺序去重，只保留候选表里真实存在的编号）。"""
    m = _NAMED_HEAD.match(task_text or "")
    if not m:
        return []
    out = []
    for r in re.findall(r"R\d+", m.group(1)):
        if r in ok and r not in out:
            out.append(r)
    return out


def decompose(task_no, task_text):
    """拆解任务 → 子任务行；拿不到合法角色时返回 []（由 execute 置阻塞，不再兜底 R2）。

    v1.17 三处修正：
      1. 角色表带上一句话职责 —— 原先只给编号+名称（83 字），模型只能靠名字猜，
         「本周产品动态提纲」该给 R3 内容工厂还是 R6 数据分析官全凭运气；
      2. 点名只认任务开头 —— 原正则 re.search(r"R(\d+)") 会被「参考 R8 的设计」
         「2024 R1 季度」「R2D2 玩具」误命中并直接直派；
      3. 拆不出合法角色不再硬回退 R2 —— 静默错分比明确阻塞更糟。"""
    try:
        from . import roles as _roles
        digest = _roles.role_digest()          # 已剔除 R0/R1：派发者不可被派发
    except Exception:
        digest = []
    if not digest:
        return []
    ok = set(no for no, _, _ in digest)
    named = named_roles(task_text, ok)
    if named:                                  # 「我说了让谁执行就谁执行」：开头点名，支持多个
        return [{"sub": task_text[:160], "role": r, "expect": "交付任务成果并回报"} for r in named]
    table = "\n".join("- %s %s：%s" % (no, name, duty or "（角色卡未写职责）")
                      for no, name, duty in digest)
    max_subs = config.tune("maxSubtasks")
    prompt = (
        "你是任务拆解器。只拆下面这一个任务，不得引用任何历史任务编号。\n"
        "可指派的角色（必须从中选真实编号，不许编造；R0/R1 是决策与派发方，不可承接）：\n"
        "%s\n"
        "按职责匹配选人，不要只看角色名。拆解为最多 %d 个可并行子任务，"
        "输出严格的派发单表格行（每行一条，无多余内容）：\n"
        "| %s | 子任务描述 | R? | 期望产出 | 待派 |\n"
        "任务：%s" % (table, max_subs, task_no, task_text))
    text = runner.run_headless_sync(prompt, config.tune("decomposeTimeout"))
    return [row for row in parse_dispatch_rows(text) if row["role"] in ok][:max_subs]


def prepare_files(sub_no, task_no, sub, spec):
    """为一个子任务预置产出文件与元数据骨架，返回 (正文路径, 元数据路径)。

    元数据由中枢写全（任务号/角色/preset 中枢本来就知道），子 agent 只回填 status。"""
    body = config.ROOT / spec["output"]
    meta = config.ROOT / spec["meta"]
    body.parent.mkdir(parents=True, exist_ok=True)
    if not body.exists():
        body.write_text("# %s · %s %s\n\n子任务：%s\n期望产出：%s\n\n---\n\n"
                        % (sub_no, sub["role"], config.role_name(sub["role"]),
                           sub["sub"], sub["expect"]), encoding="utf-8")
    meta.write_text(json.dumps({
        "subNo": sub_no,
        "taskNo": task_no,
        "role": sub["role"],
        "roleName": config.role_name(sub["role"]),
        "preset": spec["preset"],
        "sub": sub["sub"],
        "expect": sub["expect"],
        "output": spec["output"],
        "status": "待执行",
        "createdAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return body, meta


def execute(task_no, task_text):
    """一键自动执行链：拆解 → 台账落库 → 逐子任务生成派发指令并预置产出文件。
    全程把阶段事件写入 runner 事件流（工作台详情面板的「实时事件」区可见）。"""
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
        if not subs:
            # v1.17：不再硬回退 R2 —— 静默错分比明确阻塞更糟，你根本看不出它分错了
            store.set_task(task_no, "阻塞", "拆解未得到合法角色，请在任务里点名角色（如「R8 …」）后重试")
            runner.emit({"type": "assistant/chunk",
                         "data": {"text": "✗ 拆解未得到合法角色 —— 任务置阻塞，等待手动指派"}})
            runner.emit({"type": "run/end", "text": "%s 拆解失败：无合法角色" % task_no})
            set_state(lastOk=False, tag="拆解失败 %s：无合法角色（原兜底派 R2 已取消）" % task_no)
            return
        total = len(subs)
        names = ", ".join("%s→%s" % (s["role"], s["sub"][:18]) for s in subs)
        runner.emit({"type": "assistant/chunk", "data": {"text": "✔ 拆解完成 %d 项：%s" % (total, names)}})
        runner.emit({"type": "step/end", "data": {"turn": 1, "step": 1}})
        sub_nos = store.replace_subtasks(task_no, subs)     # 幂等：重复执行直接覆盖
        for i, (sub_no, s) in enumerate(zip(sub_nos, subs)):
            set_state(tag="生成派发指令 %d/%d：%s → %s" % (i + 1, total, s["sub"][:16], s["role"]))
            runner.emit({"type": "step/start", "data": {"turn": i + 2, "step": 1}})
            runner.emit({"type": "assistant/chunk", "data": {"text": "▶ 生成 subagent 派发指令：%s → %s（期望 %s）" % (s["role"], s["sub"][:60], s["expect"][:40])}})
            spec = agent.subtask_spec(s["role"], "执行子任务：%s。期望产出：%s。" % (s["sub"], s["expect"]),
                                      expect=s["expect"], sub_no=sub_no)
            prepare_files(sub_no, task_no, s, spec)
            agent.log_schedule("子任务派发指令 %s" % sub_no,
                "【待常驻主会话 R1 用 DSH subagent 派发】角色 %s（preset %s）\n"
                "子任务：%s\nprompt 注入：%s\n产出文件：%s\n元数据：%s\n"
                "执行要求：子 agent 边执行边把进度追加进产出文件；完成后把元数据 status "
                "改为 完成/部分/阻塞。"
                % (s["role"], spec["preset"], s["sub"], spec["prompt"][:300],
                   spec["output"], spec["meta"]))
            store.set_subtask(sub_no, "已派")
            store.open_execution(sub_no, task_no, s["role"])   # 重试开新记录，不覆盖上次
            runner.emit({"type": "assistant/chunk", "data": {"text": "↳ 派发指令已写入调度日志，产出文件已预置：%s" % spec["output"]}})
            runner.emit({"type": "step/end", "data": {"turn": i + 2, "step": 1, "reason": {"kind": "已派"}}})
        store.set_task(task_no, "已派", "已拆解 %d 个子任务，待主会话 R1 subagent 派发" % total)
        set_state(lastOk=True, tag="派发指令已生成 %s → %d 子任务，待主会话 R1 派发" % (task_no, total))
        agent.log_schedule("自动执行链完成 %s" % task_no,
                           "拆解 %d 个子任务，派发指令已全部生成（待主会话 R1 用 subagent 派发执行，进度实时写入各子任务产出文件）。" % total)
        runner.emit({"type": "run/end", "text": "派发指令已生成 %s：%d 子任务 · 待主会话 R1 subagent 派发" % (task_no, total)})
    except Exception as e:
        set_state(lastOk=False, tag="执行链异常：" + str(e)[:80])
        runner.emit({"type": "run/exited", "data": {"code": -1}, "error": str(e)[:120]})
    finally:
        with sch.SCHED_LOCK:
            sch.SCHED_STATE["busy"] = False
