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


def _piyue_next_no(text: str) -> int:
    # 工作条目与待决条目共用递增编号，避免跨区重号
    nums = [int(m) for m in re.findall(r"^###\s+(?:待决|工作)\s+(\d+)", text, re.M)]
    return (max(nums) + 1) if nums else 1


_DECIDE_WORDS = ("拍板", "决策", "决定", "取舍", "是否", "要不要", "可不可以", "选哪个", "方案选择",
                "定价", "预算", "批准", "驳回", "上线", "启动", "方向", "首包", "双包", "放大", "止损",
                "请 R0", "需要 R0", "请R0", "需要R0")


def _field_lines(key: str, value: str) -> list:
    """条目字段 → 行列表：首行 `- **key**：首段`，其余段以两空格缩进续行（md 人读清晰、解析可还原换行）。"""
    parts = str(value or "").split("\n")
    first = parts[0].strip()
    out = ["- **" + key + "**：" + first] if first else ["- **" + key + "**："]
    for ln in parts[1:]:
        s = ln.strip()
        if s:
            out.append("  " + s)
    return out


def _needs_decision(task_text: str, brief: str) -> bool:
    """启发式：任务/回报含明确决策信号（拍板/定价/是否…/请 R0 等）→ 进「决策裁决」，否则进「工作内容」。"""
    hay = "%s %s" % ((task_text or ""), (brief or "")[:2000])
    return any(w in hay for w in _DECIDE_WORDS)


def _tree_text(root, max_depth=3):
    """文本目录树（剔除运行数据/依赖目录），用于代码类工作汇总展示当前目录结构。"""
    skip = {".git", "node_modules", "__pycache__", ".dsh-tmp", "已归档"}
    out = []
    def walk(p, pre, dep):
        if dep > max_depth:
            return
        try:
            ents = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except OSError:
            return
        files = [e for e in ents if not e.is_dir() and e.name not in skip and not e.name.endswith((".pyc", ".db", ".db-journal"))]
        dirs = [e for e in ents if e.is_dir() and e.name not in skip]
        for i, d in enumerate(dirs):
            last = (i == len(dirs) - 1) and not files
            out.append(pre + ("└── " if last else "├── ") + d.name + "/")
            walk(d, pre + ("    " if last else "│   "), dep + 1)
        for j, f in enumerate(files):
            out.append(pre + ("└── " if j == len(files) - 1 else "├── ") + f.name)
    root = config.ROOT
    out.append(root.name + "/")
    walk(root, "", 1)
    return "\n".join(out[:160])


_TRIPLE_BT = chr(96) * 3      # ```（源码避免反引号字面）
_CODE_HINT = (".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".htm", ".vue", ".sql", ".json")


def _looks_code(text: str, src: str) -> bool:
    """启发式：产出正文含代码块/程序特征，或产出文件为代码文件 → 代码类工作。"""
    if src and src.lower().endswith(_CODE_HINT):
        return True
    if _TRIPLE_BT in (text or ""):
        return True
    head = (text or "")[:3000]
    for pat in ("def ", "function ", "class ", "import ", "const ", "let ", "interface ", "CREATE TABLE", "<!DOCTYPE", "#include"):
        if pat in head:
            return True
    return False


def _digest_body(text: str, limit: int = 600) -> str:
    """抽取产出要点：去掉控制台预置模板头，保留原始 md（标题/加粗/换行），超长截断。"""
    t = (text or "").strip()
    idx = t.find("\n---\n")                 # 预置模板头以 --- 分隔线结束
    if 0 < idx < 1200:
        t = t[idx + 6:].lstrip("\n")
    t = t.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return ""
    t = re.sub(r"\n{3,}", "\n\n", t)       # 压缩多余空行，保留段落换行
    if len(t) > limit:
        t = t[:limit].rstrip() + "\n\n……（过长截断，完整见「查看角色产物」）"
    return t


def _one_line_digest(text: str, limit: int = 120) -> str:
    """把产出压成「一段话」摘要（剥掉 md 标记），给任务信息里的「回报摘要」字段用。"""
    t = _digest_body(text, limit=3000)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"\[[xX]\]\s*", "", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", "\1", t)
    t = t.replace("**", " ").replace("`", " ").replace("#", " ").replace("*", " ")
    t = re.sub(r"^[\s>|-]+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    return (t[:limit] + "…") if len(t) > limit else t


def work_summary(task_no: str) -> str:
    """R1 汇总任务全部 subagent 产出 →《工作区/老板助理（枢纽）/T-xxx-工作汇总.md》。

    内容：各角色工作与产出全文；代码类工作附「改动/产出文件 + 当前目录结构」。
    返回 rel（供工作内容条目挂载，UI 直接查看）；失败返回 None。"""
    try:
        reps = store.reports(task_no)
        if not reps:
            return None
        task_row = None
        for t in store.tasks():
            if t["no"] == task_no:
                task_row = t
                break
        subs = {}
        try:
            for s in store.subtasks(task_no):
                subs[s["no"]] = s["sub"]
        except Exception:
            pass
        today = datetime.date.today().isoformat()
        lines = ["# %s 工作汇总（R1） · %s" % (task_no, today), ""]
        lines.append("> 任务：" + ((task_row or {}).get("task") or "").replace("\n", " ")[:300])
        lines.append("> 本文件由 R1 汇总 %d 个 subagent 的回报与产出，供 R0 直接查看。" % len(reps))
        has_code = False
        code_files = []
        for r in reps:
            role = str(r.get("role") or "?")
            st = str(r.get("status") or "")
            sub = subs.get(str(r.get("sub_no") or ""), "")
            src = str(r.get("src") or "")
            body = str(r.get("body") or "")
            lines.append("")
            lines.append("## " + role + "（" + st + "）")
            if sub:
                lines.append("> 子任务：" + sub.replace("\n", " ")[:200])
            full = _digest_body(body, limit=30000)   # R1 汇总报告 = 完整产出（去模板头、不截断）
            if full:
                lines.append("")
                lines.append(full)
            if src:
                lines.append("")
                lines.append("> 产出文件：" + src)
            if _looks_code(body, src):
                has_code = True
                code_files.append(src)
        if has_code:
            lines.append("")
            lines.append("## 代码工作：改动与当前目录结构")
            lines.append("**改动/产出文件**：" + ("；".join(f for f in code_files if f) or "见各子任务产出"))
            lines.append("")
            lines.append("**当前目录结构**（项目根，" + config.ROOT.name + "）：")
            lines.append("")
            lines.append(_TRIPLE_BT)
            lines.append(_tree_text(config.ROOT))
            lines.append(_TRIPLE_BT)
        out_p = config.WORKSPACE_ROOT / config.sanitize_dir(config.role_name("R1")) / (task_no + "-工作汇总.md")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text("\n".join(lines), encoding="utf-8")
        return out_p.relative_to(config.ROOT).as_posix()
    except Exception:
        return None



def piyue_report(task_no: str, task_text: str, ok_cnt: int, total: int, fail: list) -> int:
    """任务自动执行完成后：R1 整理回报呈报 R0。

    - 例行进展（默认）→ 追加「### 工作 N」到「## 工作内容」（查看即可，R0 可一键归档）；
    - 命中决策信号（定价/拍板/是否…/请 R0）→ 追加「### 待决 N」到「## 决策裁决」（需 R0 拍板）。
    段落格式与 parsers.parse_piyuetai / review.write_piyue 兼容。返回编号（失败返回 None）。"""
    try:
        rel = config.PIYUETAI_REL
        p = config.ROOT / rel
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        n = _piyue_next_no(text)          # 现有条目最大编号 +1（无则从 1 起）
        brief = "无回报正文"
        brief_hay = ""          # 决策信号检测用全文
        try:
            reps = store.reports(task_no)
            if reps:
                last = reps[-1]
                raw = str(last.get("body") or "")
                brief_hay = _digest_body(raw, limit=3000)
                one = _one_line_digest(raw, limit=130)   # 回报摘要 = 一段话
                brief = "%s（%s）：%s" % (last.get("role") or "?", last.get("status") or "?", one or "无正文内容")
        except Exception:
            pass
        task_s = (task_text or "").replace(chr(10), " ").replace("|", "／")
        # 条目 schema：标题只到任务号；长内容字段（回报摘要 / R 建议）保留原始 md 换行与标记，UI 按 markdown 渲染
        prog = "%d/%d 子任务完成%s，回报与产物已归档入库" % (ok_cnt, total, "" if not fail else "；阻塞 " + ",".join(fail))
        if _needs_decision(task_text, brief_hay or brief):
            lines_b = ["### 待决 %d｜任务 %s" % (n, task_no)]
            lines_b += _field_lines("任务", task_s[:160])
            lines_b += _field_lines("进展", prog)
            lines_b += _field_lines("R 建议（R1）", brief)
            lines_b += _field_lines("需要 R0 拍板什么", "任务含决策信号（定价 / 方向 / 是否推进等），请 R0 裁决；驳回 / 修改意见将触发重新派发。")
            lines_b += ["- **R0 批阅**：待填"]
            blk = chr(10) + chr(10).join(lines_b) + chr(10)
            section = "## 决策裁决"
        else:
            head = "### 工作 %d｜任务 %s" % (n, task_no)
            sum_rel = ""
            try:
                sum_rel = work_summary(task_no)      # R1 汇总全部 subagent 产出（代码类附变更与目录树）
            except Exception:
                sum_rel = ""
            lines_b = [head]
            lines_b += _field_lines("任务", task_s[:160])
            lines_b += _field_lines("进展", prog)
            lines_b += _field_lines("回报摘要", brief)
            if sum_rel:
                lines_b += ["- **汇总文件**：" + sum_rel]
            blk = chr(10) + chr(10).join(lines_b) + chr(10)
            section = "## 工作内容"
        idx = text.find(section)
        if idx >= 0:
            nxt = text.find("## ", idx + len(section))     # 插到该区段末尾（下一个 ## 之前）
            if nxt < 0:
                text = text.rstrip() + "\n" + blk
            else:
                text = text[:nxt] + blk + "\n" + text[nxt:]
        else:
            text = text.rstrip() + "\n\n" + section + "\n" + blk if text.strip() else section + "\n" + blk
        p.write_text(text, encoding="utf-8")
        return n
    except Exception:
        return None


def clean_task_files(no: str) -> int:
    """删除某任务在工作区的产出文件（子任务正文 / .meta.json，含已归档/），返回删除数。

    只按 no + "-S" 前缀匹配（T-001-S1.md），不会误伤 T-0010 等其他任务。"""
    removed = 0
    for d in _wb_role_dirs():
        for p in list(d.glob(no + "-S*.md")) + list(d.glob(no + "-S*.json")):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        arc = d / "已归档"
        if arc.is_dir():
            for p in list(arc.glob(no + "-S*.md")) + list(arc.glob(no + "-S*.json")):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


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
