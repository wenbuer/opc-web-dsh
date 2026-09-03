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

EXEC_TIMEOUT = 900          # 单个子任务的 headless 执行超时（秒）

def _flat(s):
    """dsh headless 把输入当命令行参数：Windows 命令行遇换行即截断，任何给 headless 的文本必须压成单行。"""
    return re.sub(r"\s+", " ", s or "").strip()


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


# 点名直派：只认任务开头的角色编号（「R6 开始设计…」是点名，「参考 R6 的设计…」是提及）。
# (?![\dA-Za-z]) 挡掉 R2D2 这类；连接词字符类允许「R2 和 R6 一起做」点两个人。
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


def head_named(task_text):
    """任务开头点名的全部编号（含 R0/R1，不做可承接校验）。"""
    m = _NAMED_HEAD.match(task_text or "")
    if not m:
        return []
    return list(dict.fromkeys(re.findall(r"R\d+", m.group(1))))


# 「请 R1 / 让 R1 / 由 R1 / 交给 R1 / R1 你来负责…」= 指定 R1（默认枢纽），不必要求 R1 写在任务开头
_R1_ASK = re.compile(r"(?:请|让|叫|由|交(?:给)?|安排|指派|命)\s*R1\b|R1\s*(?:你)?\s*(?:来|去|负责|牵头|处理|跟进|安排|做)")


def asks_r1(task_text):
    """任务是否指定了 R1（开头点名 R1，或出现「请 R1 …」等指示语）。"""
    return "R1" in head_named(task_text) or bool(_R1_ASK.search(task_text or ""))


def decompose(task_no, task_text):
    """拆解任务 → 子任务行；拿不到合法角色时返回 []（由 execute 置阻塞，不再兜底 R2）。

    v1.17 三处修正：
      1. 角色表带上一句话职责 —— 原先只给编号+名称（83 字），模型只能靠名字猜，
         「本周产品动态提纲」该给 R3 内容工厂还是 R4 增长与数据全凭运气；
      2. 点名只认任务开头 —— 原正则 re.search(r"R(\\d+)") 会被「参考 R6 的设计」
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
    # 注意：dsh headless 把 prompt 作为命令行参数传入，Windows 命令行遇换行即截断，
    # 所以给模型的 prompt 必须压成单行（模型输出不受限，可自由换行）。
    role_list = "；".join("%s %s（职责：%s）" % (no, name, duty or "未填写")
                          for no, name, duty in digest)
    max_subs = config.tune("maxSubtasks")
    lead = "你是任务拆解器，只拆下面这一个任务，不得引用历史任务编号。可指派的业务角色如下（R0/R1 是决策与派发方，不可承接、不要选它们）："
    if asks_r1(task_text):
        lead += "用户指定由 R1（枢纽·老板助理）牵头派发——R1 只拆解派发不直接执行，请忽略任务里的 R1 字样，直接按职责从下列业务角色选人："
    prompt = (lead + role_list +
              "。按职能合理拆分：能由一个角色一次完成（如单点调研/资料检索）就拆 1 个，"
              "只有确实需要多个职能并行或接力、单角色覆盖不了时才拆多个 —— 宁少勿多，总数不超过 %d 个。"
              "只输出派发单表格行，每行格式：| %s | 子任务描述 | R编号 | 期望产出 | 待派 |；"
              "示例：| %s | 设计产品落地页 | R6 | 界面设计稿 | 待派 |。"
              "不要输出任何解释、提问或多余文字。任务：%s" % (max_subs, task_no, task_no, task_text))
    try:
        text = runner.run_headless_sync(prompt, config.tune("decomposeTimeout"))
    except Exception:
        return []                       # 拆解通道不可用 → 走 execute 的统一兜底/阻塞，不留待派反复重触发
    return [row for row in parse_dispatch_rows(text) if row["role"] in ok][:max_subs]


def prepare_files(sub_no, task_no, sub, spec):
    """为一个子任务预置产出文件与元数据骨架，返回 (正文路径, 元数据路径)。

    元数据由中枢写全（任务号/角色中枢本来就知道），子 agent 只回填 status。"""
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
        # 指定 R1（含「请 R1 / 让 R1 …」）= R1 牵头派发：同样走模型拆解选业务角色（decompose 内已引导模型忽略 R1）
        head = head_named(task_text)
        subs = decompose(task_no, task_text)
        if not subs:
            # 拆解失败：区分「指定 R1」「点名了不可执行编号」「完全未点名」给出针对性提示
            if asks_r1(task_text):
                msg = "R1 派发拆解暂无输出：模型未返回子任务（请确认 dsh 可用，或直接点名业务角色如「R6 …」让 R1 直派）"
            elif head:
                msg = "点名了 " + "、".join(head) + "（R1 只拆解派发、不承接执行），且模型拆解暂无输出：请点名 R2~R7 之一，或配置模型后重试"
            else:
                msg = "拆解未得到合法角色：模型拆解暂无输出（请确认 dsh 与模型可用，或点名业务角色如「R6 …」让 R1 直派）"
            store.set_task(task_no, "阻塞", msg)
            runner.emit({"type": "assistant/chunk",
                         "data": {"text": "✗ " + msg + " —— 任务置阻塞，等待手动指派"}})
            runner.emit({"type": "run/end", "text": "%s 拆解失败：%s" % (task_no, msg[:60])})
            set_state(lastOk=False, tag="拆解失败 %s" % task_no)
            return
        total = len(subs)
        names = ", ".join("%s→%s" % (s["role"], s["sub"][:18]) for s in subs)
        runner.emit({"type": "assistant/chunk", "data": {"text": "✔ 拆解完成 %d 项：%s" % (total, names)}})
        runner.emit({"type": "step/end", "data": {"turn": 1, "step": 1}})
        sub_nos = store.replace_subtasks(task_no, subs)     # 幂等：重复执行直接覆盖
        ok_cnt, fail = 0, []
        for i, (sub_no, s) in enumerate(zip(sub_nos, subs)):
            set_state(tag="执行 %d/%d：%s %s" % (i + 1, total, s["role"], s["sub"][:20]))
            runner.emit({"type": "step/start", "data": {"turn": i + 2, "step": 1}})
            runner.emit({"type": "assistant/chunk",
                         "data": {"text": "▶ 自动执行 %s（%s）：%s —— headless 直跑" % (sub_no, s["role"], s["sub"][:70])}})
            spec = agent.subtask_spec(s["role"], "执行子任务：%s。期望产出：%s。" % (s["sub"], s["expect"]),
                                      expect=s["expect"], sub_no=sub_no)
            prepare_files(sub_no, task_no, s, spec)
            body_p = config.ROOT / spec["output"]
            meta_p = config.ROOT / spec["meta"]
            store.set_subtask(sub_no, "执行中")
            store.open_execution(sub_no, task_no, s["role"])
            try:
                text, usage = runner.run_headless_task(_flat(spec["prompt"]), EXEC_TIMEOUT)
            except Exception:
                text, usage = "", None
            if text:
                with open(body_p, "a", encoding="utf-8") as fh:          # 完成回报（唯一的子任务产出文件）
                    fh.write("\n\n## 完成回报（控制台自动执行 %s）\n\n%s\n" % (sub_no, text))
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                    meta["status"] = "完成"
                    if usage:
                        # token 用量写入 meta.json（输入=含缓存读取的计费口径，另存拆分）
                        meta["tokensIn"] = usage["inputTokens"] + usage["cacheReadTokens"]
                        meta["tokensOut"] = usage["outputTokens"]
                        meta["tokensCacheRead"] = usage["cacheReadTokens"]
                        meta["tokensReasoning"] = usage["reasoningTokens"]
                    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except Exception:
                    pass
                store.settle_execution(sub_no, "完成")
                ok_cnt += 1
                runner.emit({"type": "assistant/chunk",
                             "data": {"text": "✔ %s（%s）执行完成，产出回报已写入：%s（归档时改名 output）" % (sub_no, s["role"], spec["output"])}})
            else:
                try:
                    with open(body_p, "a", encoding="utf-8") as fh:
                        fh.write("\n\n## 执行结果\n\n【本子任务 headless 执行无输出，置阻塞】\n")
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                    meta["status"] = "阻塞"
                    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except Exception:
                    pass
                store.settle_execution(sub_no, "阻塞", "headless 无输出")
                fail.append(sub_no)
                runner.emit({"type": "assistant/chunk",
                             "data": {"text": "✗ %s 执行无输出（已置阻塞，可删除或点名重试）" % sub_no}})
            agent.log_schedule("自动执行 %s" % sub_no,
                               "角色 %s %s 执行子任务：%s\n产出文件：%s\n结果：%s"
                               % (s["role"], spec["roleName"], s["sub"], spec["output"],
                                  "完成" if text else "阻塞（headless 无输出）"))
            runner.emit({"type": "step/end", "data": {"turn": i + 2, "step": 1,
                        "reason": {"kind": "完成" if text else "阻塞"}}})
        # 归档入库：已完成/阻塞子任务回报落库、正文与元数据移入 已归档/（幂等，会顺带做任务级回填）
        try:
            sch.r1_archive()
        except Exception:
            pass
        # R1 整理回报 → 呈报 R0（批阅台新增「待决」段落，UI 批阅台可见并可裁决）
        piyue_no = None
        if ok_cnt > 0:
            try:
                piyue_no = sch.piyue_report(task_no, task_text, ok_cnt, total, fail)
            except Exception:
                piyue_no = None
            if piyue_no:
                runner.emit({"type": "assistant/chunk",
                             "data": {"text": "📤 回报已整理并呈报 R0：批阅台 待决 #%d（可到批阅台 批准/驳回/修改）" % piyue_no}})
        # R1 自动收尾：汇总当日日报 + 从产出提炼知识库（失败不阻断主流程）
        try:
            sch.kb_digest(task_no)
        except Exception:
            pass
        try:
            sch.build_daily_report()
        except Exception:
            pass

        if not fail:
            store.set_task(task_no, "完成", "%d/%d 子任务完成" % (ok_cnt, total))
            set_state(lastOk=True, tag="任务 %s 完成：%d/%d" % (task_no, ok_cnt, total))
        else:
            store.set_task(task_no, "部分" if ok_cnt else "阻塞",
                           "%d/%d 完成；阻塞：%s" % (ok_cnt, total, ",".join(fail)))
            set_state(lastOk=ok_cnt > 0, tag="任务 %s：%d/%d 完成，%s 阻塞" % (task_no, ok_cnt, total, ",".join(fail)))
        agent.log_schedule("自动执行链 %s" % task_no,
                           "拆解 %d 个子任务，headless 自动执行：%d 完成，%s"
                           % (total, ok_cnt, "全部完成" if not fail else "阻塞 " + ",".join(fail)))
        runner.emit({"type": "run/end",
                     "text": "任务 %s 执行完毕：%d/%d 子任务完成%s"
                     % (task_no, ok_cnt, total, " ✅" if not fail else "（含阻塞，可删除或重试）")})

    except Exception as e:
        set_state(lastOk=False, tag="执行链异常：" + str(e)[:80])
        runner.emit({"type": "run/exited", "data": {"code": -1}, "error": str(e)[:120]})
    finally:
        with sch.SCHED_LOCK:
            sch.SCHED_STATE["busy"] = False
