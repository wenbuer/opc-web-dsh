# -*- coding: utf-8 -*-
"""调度中枢 v1.9（subagent 化 + 名称工作区）：不再 spawn headless one-shot。

执行模型：常驻会话主 agent（R1 助理）是唯一执行方 —— 控制台只负责把
「R0 指令」落地为队列/派发单，并把「待执行指令」记入调度日志；
R1 主会话读取队列+派发单后，用 DSH subagent 体系向下派活（角色卡按
preset 继承 / persona / prompt 注入三通道装配），子 agent 产出《工作区/<角色名称>/回报-待落库.md》，
R1 最终归档（r1_apply / r1_archive 仍由控制台按钮或主会话触发，纯文件操作）。
"""
import datetime
import re
import threading
import time

from . import agent, config, parsers, queue


def _wb_role_dirs():
    """《工作区/》下所有角色输出目录（v1.10：按角色名称命名）。"""
    wb = config.wb_root()
    if not wb.is_dir():
        return []
    return sorted(d for d in wb.iterdir() if d.is_dir())


SCHED_LOCK = threading.Lock()
SCHED_STATE = {"busy": False, "tag": "", "at": "", "lastOk": None, "paused": False,
               "issuedTasks": ""}   # 已生成指令的任务编号串（防 auto_pilot 重复刷指令）


def run_r1_job():
    """R1 调度指令：读待派任务 → 生成「请常驻主会话 R1 拆解派发」指令日志（不 spawn）。"""
    with SCHED_LOCK:
        if SCHED_STATE["busy"]:
            return
    tasks = [t for t in queue.parse_queue() if t["status"] == "待派"]
    now = datetime.datetime.now().strftime("%H:%M:%S")
    if not tasks:
        SCHED_STATE.update({"busy": False, "tag": "R1-调度(无待派)", "at": now, "lastOk": None})
        return
    keys = ",".join(t["no"] for t in tasks[:5])
    if SCHED_STATE["issuedTasks"] == keys:
        return                       # 同批任务指令已生成过，不重复刷日志
    joined = "\n".join("- %s｜%s｜期望 %s" % (t["no"], t["task"], t["expect"]) for t in tasks[:5])
    kb = str(config.ROOT).replace("\\", "/")
    text = ("【调度指令 · 待常驻主会话 R1 执行】当前待派任务：\n" + joined +
            "\n请主会话 R1（本常驻 agent）执行：\n"
            "1) 读取《批阅台/任务下达队列.md》确认待派清单（根目录 %s/，下同）；\n" % kb +
            "2) 逐项拆解为子任务，写入《批阅台/派发单-动态.md》（任务编号|子任务|承接角色|期望产出|状态）；\n"
            "3) 用 DSH subagent 体系派发：每个子任务一次 subagent 调用，prompt 按角色卡注入\n"
            "   （子 agent 自动继承本会话 preset=opc-r1 的体系 persona；具体角色卡取本项目 agents/R?.role.md），"
            "   产出目标《工作区/<角色名称>/回报-待落库.md》（角色名称，如 需求研究员；R 编号仅为 Id）；\n"
            "4) 子任务回报尾行固定：回报人：R?｜任务：T-xxx｜状态：完成/部分/阻塞。")
    agent.log_schedule("R1-调度指令", text)
    SCHED_STATE.update({"busy": False, "tag": "R1-调度(指令已生成·待主会话执行)", "at": now,
                        "lastOk": None, "issuedTasks": keys})


def run_child_job(no: str, task_text: str):
    """子任务派发指令：按角色(no)生成 subagent 派发规格并记入调度日志（不 spawn）。"""
    with SCHED_LOCK:
        if SCHED_STATE["busy"]:
            return
    spec = agent.subtask_spec(no, task_text)
    text = ("【子任务派发指令 · 待常驻主会话执行】角色 %s（preset: %s）\n"
            "任务：%s\n派发方式：主会话 R1 调 DSH subagent 一次，prompt 注入如下：\n%s\n期望产出：%s")
    text = text % (no, spec["preset"], task_text, spec["prompt"], spec["output"])
    agent.log_schedule("子任务派发指令 " + no, text)
    SCHED_STATE.update({"busy": False, "tag": "子任务 %s 指令已生成·待主会话派发" % no,
                        "at": datetime.datetime.now().strftime("%H:%M:%S"), "lastOk": None})


def plan_execute() -> dict:
    """派发单 → 逐行生成 subagent 派发指令（不启动执行线程；由主会话 R1 逐个派发）。"""
    target = config.dispatch_file()
    if not target.exists():
        return {"issued": [], "msg": "派发单不存在（先运行 R1 调度并点“落地 R1 产出”）"}
    rows = []
    for ln in target.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^\|\s*(T-\S+)\s*\|\s*([^|]+?)\s*\|\s*(R\d+)[^|]*\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|$", ln)
        if m:
            rows.append({"no": m.group(1).strip(), "sub": m.group(2).strip(),
                         "role": m.group(3).strip(), "expect": m.group(4).strip(),
                         "st": m.group(5).strip()})
    pending = [r for r in rows if ("待派" in r["st"] or "已派" in r["st"] or not r["st"])]
    spec_lines = []
    for r in pending:
        spec = agent.subtask_spec(r["role"], "执行子任务：%s。期望产出：%s。" % (r["sub"], r["expect"]))
        spec_lines.append("- %s → %s（preset %s）：%s" % (r["no"], r["role"], spec["preset"], spec["output"]))
    if spec_lines:
        agent.log_schedule("派发单执行指令", "【待常驻主会话 R1 按派发单逐行 subagent 派发】\n" + "\n".join(spec_lines))
    return {"issued": [r["no"] + "→" + r["role"] for r in pending], "total": len(rows)}


def scan_once():
    """一轮调度扫描：队列有待派 → 立即启动自动执行链（控制台 headless 直跑，主路径）。"""
    try:
        if SCHED_STATE.get("paused") or SCHED_STATE.get("busy"):
            return
        q = queue.parse_queue()
        if not q:
            return
        for t in q:
            if t["status"] == "待派":
                from . import chain
                threading.Thread(target=chain.execute, args=(t["no"], t["task"]), daemon=True).start()
                return
    except Exception:
        pass


def schedule_once():
    """定时任务触发检查：到期任务 → 写入《任务下达队列》+ 调度日志（生成调度指令，由常驻主会话 R1 执行）。"""
    try:
        now = datetime.datetime.now()
        jobs = config.load_schedules()
        changed = False
        for j in jobs:
            if not j.get("enabled", True):
                continue
            nxt = config.schedule_next(j, now)
            if nxt is None or nxt > now:
                continue
            task = str(j.get("task") or "").strip() or "定时任务"
            no = queue.append_queue(task, "定时任务（R1 执行）")
            j["lastRun"] = now.strftime("%Y-%m-%d %H:%M:%S")
            agent.log_schedule("定时任务 %s" % (j.get("id") or "?"),
                               "【定时任务到期】%s → 已下达 %s 待常驻主会话 R1 执行：%s"
                               % (j.get("id") or "?", no, task))
            changed = True
        if changed:
            config.save_schedules(jobs)
    except Exception:
        pass


def auto_pilot():
    """常驻调度守护：8s 轮询队列 + 定时任务触发检查；有待派任务即启动自动执行链。"""
    while True:
        time.sleep(8)
        schedule_once()
        scan_once()


def r1_apply() -> dict:
    """把 R1 在输出目录（《工作区/老板助理（枢纽）/》）的待落库产物搬运进知识库（派发单/回报队列/队列回填）。"""
    out = []
    d = config.wb_root() / config.role_ws_dir("R1")     # 名称工作区（新生）；旧目录兼容
    if not d.exists():
        for legacy in ("R1-枢纽-输出", "R1-输出"):
            d2 = config.wb_root() / legacy
            if d2.exists():
                d = d2
                break
    k1 = d / "01-派发单-动态-待落库.md"
    if k1.exists():
        text = k1.read_text(encoding="utf-8")
        body = text.split("## 正文（可直接落库）", 1)[-1].strip()
        target = config.dispatch_file()
        if not target.exists():
            target.write_text(body + "\n", encoding="utf-8")
            out.append("批阅台/派发单-动态.md 已创建")
        else:
            cur_t = target.read_text(encoding="utf-8")
            if "T-" in body and "T-" not in cur_t:
                with open(target, "a", encoding="utf-8") as fh:
                    fh.write("\n\n" + body + "\n")
                out.append("批阅台/派发单-动态.md 已追加")
            else:
                out.append("批阅台/派发单-动态.md 已含 T 行，跳过")
    k2 = d / "02-回报队列-追加-待落库.md"
    if k2.exists():
        seg = k2.read_text(encoding="utf-8")
        rows = [ln for ln in seg.split("\n") if ln.startswith("|") and "---" not in ln[:3]]
        cur_t = config.report_file().read_text(encoding="utf-8") if config.report_file().exists() else ""
        if cur_t and not cur_t.endswith("\n"):
            with open(config.report_file(), "a", encoding="utf-8") as fh:
                fh.write("\n")
        n = 0
        with open(config.report_file(), "a", encoding="utf-8") as fh:
            for ln in rows:
                if ln.strip() and ln not in cur_t:
                    fh.write(ln + "\n")
                    n += 1
        out.append("批阅台/回报队列.md 追加 " + str(n) + " 行")
    k3 = d / "03-任务队列回填-待落库.md"
    if not k3.exists() or True:
        n2 = 0
        for t in queue.parse_queue():
            if t["status"] == "待派":
                queue.update_queue(t["no"], "已派", "R1 已拆解派发单（批阅台/派发单-动态.md）")
                n2 += 1
        if n2:
            out.append("队列回填 " + str(n2) + " 项 → 已派")
    k4 = d / "04-R1回报-闭环验证.md"
    if k4.exists():
        out.append("R1 汇报已就绪（/api/r1-output 可见）")
    return {"applied": out}


def r1_archive() -> dict:
    """R1 整理归档：各角色输出目录（名称工作区/）待落库产出归位知识库。
    回报类 → 《批阅台/回报队列.md》追加；内容类 → 按「产出文件路径/落库目标」线索或主题推测归位；无线索 → 登记《批阅台/归档登记-<date>.md》。"""
    out = []
    ledger = []
    today = datetime.date.today().isoformat()
    sep = "[｜|│]"
    for d in _wb_role_dirs():
        for f in sorted(d.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            if "回报" in f.name:
                mrep = re.search("回报人：R(\\d+)" + sep + "任务：" + sep + "([^｜|│\\n]+)" + sep + "状态：([^｜|│\\n]+)", text)
                if mrep:
                    nno = mrep.group(1)
                    tn = mrep.group(2).strip()
                    st = mrep.group(3).strip()
                    title = re.search(r"^#\s*(.+)$", text, re.M)
                    brief = (title.group(1).strip() if title else f.name)[:70].replace("|", "／")
                    row = "| %s | %s | R%s | %s | %s |" % (today, tn, nno, brief, st)
                    cur_t = config.report_file().read_text(encoding="utf-8") if config.report_file().exists() else ""
                    if row not in cur_t:
                        if cur_t and not cur_t.endswith("\n"):
                            with open(config.report_file(), "a", encoding="utf-8") as fh:
                                fh.write("\n")
                        with open(config.report_file(), "a", encoding="utf-8") as fh:
                            fh.write(row + "\n")
                        out.append(f.relative_to(config.wb_root()).as_posix() + " → 回报队列(1 行)")
                    else:
                        out.append(f.name + " → 回报行已在")
                else:
                    ledger.append(f.relative_to(config.wb_root()).as_posix())
                    out.append(f.name + " → 回报文件缺固定尾行，待登记")
            else:
                rel_infer = ""
                if "内容稿" in f.name:
                    rel_infer = ""
                elif "原声" in f.name:
                    rel_infer = ""
                m = re.search(r"(?:产出文件路径|落库目标)[：:]\s*([^\n| ，,]+?\.md)", text)
                if m:
                    rel = m.group(1).strip().lstrip("./")
                elif rel_infer:
                    rel = rel_infer
                else:
                    ledger.append(f.relative_to(config.wb_root()).as_posix())
                    out.append(f.name + " → 无目标线索，待登记")
                    continue
                if ".." in rel:
                    ledger.append(f.relative_to(config.wb_root()).as_posix() + "（非法目标）")
                    continue
                target = config.KB_ROOT / rel
                body = text
                for tag in ("## 正文（可直接落库）", "待落库说明"):
                    if tag in body:
                        body = body.split(tag, 1)[-1].strip()
                        break
                if target.exists():
                    cur_t = target.read_text(encoding="utf-8")
                    if body[:60] in cur_t:
                        out.append(f.name + " → " + rel + "（内容已在）")
                        continue
                    with open(target, "a", encoding="utf-8") as fh:
                        fh.write("\n\n" + body + "\n")
                    out.append(f.name + " → 追加 " + rel)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(body + "\n", encoding="utf-8")
                    out.append(f.name + " → 新建 " + rel)
    if ledger:
        lg = config.BATCH_ROOT / ("归档登记-" + today + ".md")
        with open(lg, "a", encoding="utf-8") as fh:
            fh.write("\n".join(["- " + p for p in ledger]) + "\n")
        out.append("无线索文件登记 " + str(len(ledger)) + " 项 → 批阅台/归档登记-" + today + ".md")
    return {"archived": out}


def rn_outputs(no: str = "") -> list:
    """扫描《工作区/》下各角色输出目录的产物（名称工作区/旧 R?-输出 兼容）；no 给出时只保留含该任务编号的产物。"""
    out = []
    for d in _wb_role_dirs():
        files = []
        for p in sorted(d.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            if no and no not in text:
                continue
            files.append({"name": p.name, "rel": p.relative_to(config.ROOT).as_posix(),
                          "mtime": p.stat().st_mtime, "head": text[:200]})
        if files:
            out.append({"dir": d.name, "files": files})
    return out


def task_output(no: str) -> dict:
    """按任务编号聚合输出：回报队列行 + 派发单行 + 角色产物片段 + 调度日志片段。"""
    out = {"no": no, "reports": [], "plan": [], "files": [], "log": ""}
    if config.report_file().exists():
        for ln in config.report_file().read_text(encoding="utf-8").split("\n"):
            if no in ln and ln.startswith("|"):
                out["reports"].append(ln.strip())
    pf = config.dispatch_file()
    if pf.exists():
        for ln in pf.read_text(encoding="utf-8").split("\n"):
            if no in ln and ln.startswith("|"):
                out["plan"].append(ln.strip())
    for d in _wb_role_dirs():
        for p in sorted(d.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            if no in text:
                idx = text.find(no)
                out["files"].append({"name": p.name,
                                     "rel": p.relative_to(config.ROOT).as_posix(),
                                     "head": text[:160],
                                     "seg": text[max(0, idx - 120):idx + 420]})
    lg = config.LOG_FILE
    if lg.exists():
        text = lg.read_text(encoding="utf-8")
        idx = text.rfind(no)
        if idx >= 0:
            out["log"] = text[max(0, idx - 400):idx + 900]
    return out
