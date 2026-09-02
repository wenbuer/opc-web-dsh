# -*- coding: utf-8 -*-
"""调度中枢 v1.15：subagent 化 + 名称工作区 + SQLite 台账。

执行模型：常驻会话主 agent（R1 助理）是唯一执行方 —— 控制台只负责把
「R0 指令」落成台账（store.py）并把「待执行指令」记入调度日志；
R1 主会话读取台账后用 DSH subagent 体系向下派活，子 agent 产出
《工作区/<角色名称>/T-xxx-Sn.md》，控制台归档时摄取入库。

v1.15：任务/子任务/回报三张表由 SQLite 承载，md 只留正文与公文。
原先「R1 手写 md 表格行 → 程序原样字符串搬运」的 r1_apply 通道已删除。
"""
import datetime
import json
import re
import threading
import time

from . import agent, config, store


def _wb_role_dirs():
    """《工作区/》下所有角色输出目录（按角色名称命名）。"""
    wb = config.wb_root()
    if not wb.is_dir():
        return []
    return sorted(d for d in wb.iterdir() if d.is_dir())


SCHED_LOCK = threading.Lock()
SCHED_STATE = {"busy": False, "tag": "", "at": "", "lastOk": None, "paused": False,
               "issuedTasks": ""}   # 已生成指令的任务编号串（防 auto_pilot 重复刷指令）


def plan_execute() -> dict:
    """按台账里的待派/已派子任务，逐行生成 subagent 派发指令（由主会话 R1 逐个派发）。"""
    rows = [r for r in store.subtasks() if r["st"] in ("", "待派", "已派")]
    if not rows:
        return {"issued": [], "total": len(store.subtasks()), "msg": "无待派子任务"}
    spec_lines = []
    for r in rows:
        spec = agent.subtask_spec(r["role"], "执行子任务：%s。期望产出：%s。" % (r["sub"], r["expect"]),
                                  expect=r["expect"], sub_no=r["no"])
        spec_lines.append("- %s → %s %s：%s" % (r["no"], r["role"], spec["roleName"], spec["output"]))
    agent.log_schedule("派发单执行指令", "【待常驻主会话 R1 按台账逐行 subagent 派发】\n" + "\n".join(spec_lines))
    return {"issued": [r["no"] + "→" + r["role"] for r in rows], "total": len(store.subtasks())}


def scan_once():
    """一轮调度扫描：台账有待派任务 → 立即启动自动执行链。"""
    try:
        if SCHED_STATE.get("paused") or SCHED_STATE.get("busy"):
            return
        for t in store.tasks():
            if t["status"] == "待派":
                from . import chain
                threading.Thread(target=chain.execute, args=(t["no"], t["task"]), daemon=True).start()
                return
    except Exception:
        pass


def schedule_once():
    """定时任务触发检查：到期任务 → 落台账 + 调度日志。"""
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
            no = store.add_task(task, "定时任务（R1 执行）")
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
    """常驻调度守护：轮询台账 + 定时任务触发检查 + 自动归档；
    有待派任务即启动自动执行链，子任务完结后自动归档（无需手动点「归档」）。
    轮询间隔见 opc-config.json 的 pollSeconds（默认 8 秒，手改即时生效）。"""
    while True:
        time.sleep(config.tune("pollSeconds"))
        schedule_once()
        scan_once()
        archive_once()


def _title_of(text: str, fallback: str) -> str:
    m = re.search(r"^#\s*(.+)$", text, re.M)
    return (m.group(1).strip() if m else fallback)[:70]


def r1_archive() -> dict:
    """归档：扫各角色工作区的 .meta.json → 已完成的子任务入库 → 正文移入 已归档/。

    幂等由主键（子任务编号）保证：重复归档即覆盖同一行，不再靠整行字符串比对去重。
    文件在=待处理、文件移走=已处理，文件系统本身就是状态机。"""
    done, skipped, ledger = [], [], []
    for d in _wb_role_dirs():
        for meta_p in sorted(d.glob("*.meta.json")):
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
            except Exception as e:
                ledger.append("%s（元数据损坏：%s）" % (meta_p.name, str(e)[:40]))
                continue
            sub_no = str(meta.get("subNo") or meta_p.stem.replace(".meta", ""))
            status = str(meta.get("status") or "待执行").strip()
            body_p = d / (sub_no + ".md")
            if status in ("待执行", "执行中") or not body_p.exists():
                skipped.append("%s（%s）" % (sub_no, status if body_p.exists() else "正文未产出"))
                continue
            text = body_p.read_text(encoding="utf-8")
            store.put_report(sub_no, str(meta.get("taskNo") or ""), str(meta.get("role") or ""),
                             status, _title_of(text, sub_no), text,
                             body_p.relative_to(config.ROOT).as_posix())
            store.set_subtask(sub_no, status)
            store.settle_execution(sub_no, status)
            arc = d / "已归档"
            arc.mkdir(exist_ok=True)
            body_p.replace(arc / body_p.name)
            meta_p.replace(arc / meta_p.name)
            done.append("%s → 回报入库（%s）" % (sub_no, status))
        # 内容类交付物（非子任务产出）：不猜落库路径，登记待 R1/R0 指定
        for f in sorted(d.glob("*.md")):
            if (d / (f.stem + ".meta.json")).exists():
                continue
            ledger.append(f.relative_to(config.wb_root()).as_posix())
    # 任务级回填：子任务全部完成 → 任务完成
    by_task = {}
    for s in store.subtasks():
        by_task.setdefault(s["taskNo"], []).append(s["st"])
    for task_no, sts in by_task.items():
        if sts and all(x == "完成" for x in sts):
            store.set_task(task_no, "完成", "%d/%d 子任务完成" % (len(sts), len(sts)))
            done.append("%s → 任务完成" % task_no)
    out = {"archived": done, "skipped": skipped, "ledger": ledger}
    if done:
        agent.log_schedule("R1 自动归档",
                           "子任务已全部/部分完结，自动归档入库 %d 项：%s" % (len(done), "；".join(done)))
    if ledger:
        lg = config.BATCH_ROOT / ("归档登记-" + datetime.date.today().isoformat() + ".md")
        lg.parent.mkdir(parents=True, exist_ok=True)
        with open(lg, "a", encoding="utf-8") as fh:
            fh.write("\n".join("- " + p for p in ledger) + "\n")
    return out


def archive_once():
    """自动归档（R1 中枢守护）：扫描工作区，出现已完结（完成/部分/阻塞）子任务即归档一次。
    幂等由 r1_archive 保证：重复扫描/重复调用不会重复入库；执行中的子任务跳过。"""
    try:
        for d in _wb_role_dirs():
            for meta_p in d.glob("*.meta.json"):
                try:
                    st = str(json.loads(meta_p.read_text(encoding="utf-8")).get("status") or "").strip()
                except Exception:
                    continue
                if st in ("完成", "部分", "阻塞"):
                    r1_archive()
                    return
    except Exception:
        pass


def rn_outputs(no: str = "") -> list:
    """扫描《工作区/》各角色目录的产出（跳过 已归档/）；no 给出时只保留该任务编号的产出。"""
    out = []
    for d in _wb_role_dirs():
        files = []
        for p in sorted(d.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            if no and no not in text and no not in p.name:
                continue
            meta_p = d / (p.stem + ".meta.json")
            st = ""
            if meta_p.exists():
                try:
                    st = str(json.loads(meta_p.read_text(encoding="utf-8")).get("status") or "")
                except Exception:
                    st = "元数据损坏"
            files.append({"name": p.name, "rel": p.relative_to(config.ROOT).as_posix(),
                          "mtime": p.stat().st_mtime, "status": st, "head": text[:200]})
        if files:
            out.append({"dir": d.name, "files": files})
    return out


def task_output(no: str) -> dict:
    """按任务编号聚合输出：回报（DB）+ 子任务（DB）+ 工作区产物 + 调度日志片段。"""
    out = {"no": no,
           "reports": store.reports(no),
           "plan": store.subtasks(no),
           "executions": store.executions(no),
           "files": [], "log": ""}
    for d in _wb_role_dirs():
        for p in sorted(d.glob("*.md")) + sorted((d / "已归档").glob("*.md")):
            text = p.read_text(encoding="utf-8")
            if no in text or no in p.name:
                idx = max(text.find(no), 0)
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
