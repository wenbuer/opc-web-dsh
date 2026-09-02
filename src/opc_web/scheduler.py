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
            body_p = d / (sub_no + "-report.md")          # 新命名：完成回报
            if not body_p.exists():
                body_p = d / (sub_no + ".md")             # 兼容历史旧命名
            if status in ("待执行", "执行中") or not body_p.exists():
                skipped.append("%s（%s）" % (sub_no, status if body_p.exists() else "正文未产出"))
                continue
            text = config.read_text(body_p)
            # 产出生命周期（模型 A）：工作中 = -report（完成回报）；归档时改名为 -output.md 移入 已归档/
            arc = d / "已归档"
            arc.mkdir(exist_ok=True)
            stem = body_p.stem
            if stem.endswith("-report"):
                stem = stem[: -len("-report")]
            out_name = stem + "-output.md"
            arc_rel = (arc / out_name).relative_to(config.ROOT).as_posix()
            store.put_report(sub_no, str(meta.get("taskNo") or ""), str(meta.get("role") or ""),
                             status, _title_of(text, sub_no), text, arc_rel)
            store.set_subtask(sub_no, status)
            store.settle_execution(sub_no, status)
            body_p.replace(arc / out_name)
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


# 「需要 R0 拍板」小节里常见的流程/机制套话（本身不含任何具体待决内容），抽取时剔除：
# 例：“任务含决策信号（定价 / 方向 / 是否推进等），请 R0 裁决；驳回 / 修改意见将触发重新派发。”
# 这类话等于没写 —— R0 要看到的是“现状背景 → 可选方案 → 建议 → 具体请拍板什么”。
_DECISION_NOISE = ("决策信号", "请 R0 裁决", "请R0裁决", "R0 裁决", "请 R0 拍板", "请R0拍板",
                   "驳回", "重新派发", "修改意见", "回报未列出", "请展开本条目", "请直接批复",
                   "完整产出后再给出意见", "读完完整产出后再给出意见")
_DECISION_CONCRETE = ("方案", "还是", "或", "建议", "选择", "采用", "预算", "上限", "金额", "？", "?")


def _clean_decision_seg(role: str, seg: str) -> str:
    """把某角色「需要 R0 拍板」原文里的机制套话句剔除，只留具体待决内容（过短视为没写）。"""
    t = (seg or "").strip()
    t = re.sub(r"^[#\-*\s]*" +
               r"(?:需要\s*R0\s*拍板|需要R0拍板|需要拍板|待拍板|请\s*R0\s*拍板|请R0拍板|需\s*R0\s*决策|请求\s*R0\s*决策)" +
               r"[\s:：]*", "", t)
    frags = [f.strip(" \t·-*#") for f in re.split(r"(?<=[。！？!?；;])|[\n\r]", t)]
    keep = []
    for f in frags:
        if not f:
            continue
        noise = any(w in f for w in _DECISION_NOISE)
        concrete = any(w in f for w in _DECISION_CONCRETE) or bool(re.search(r"(?<![A-Za-zRr])[0-9０-９]", f))
        if noise and not concrete:
            continue          # 纯机制套话，不等于要拍板的具体内容
        keep.append(f)
    cleaned = "\n".join(keep).strip()
    return cleaned if len(cleaned) >= 20 else ""


def _decision_items(reps: list) -> str:
    """从各角色回报正文抽取「需要 R0 拍板」具体内容 → 拼接为待决条目字段值（无则空串）。

    子 agent 按约定写「## 需要 R0 拍板」小节（或内联“需要 R0 拍板：…”）；
    这里取首个命中位置起 700 字内、到下一个二级标题前的原文，剔除“请 R0 裁决 / 驳回将
    重新派发”这类机制空话后，R0 拍板看的就是它。"""
    out = []
    marks = ("需要 R0 拍板", "需要R0拍板", "需要拍板", "待拍板",
             "请 R0 拍板", "请R0拍板", "需 R0 决策", "请求 R0 决策")
    for role, body in (reps or []):
        t = str(body or "")
        pos = min([i for mk in marks if (i := t.find(mk)) >= 0] or [-1])
        if pos < 0:
            continue
        seg = t[pos:pos + 700]
        cut = seg.find("\n## ")
        if cut > 0:
            seg = seg[:cut]
        seg = _clean_decision_seg(role, seg)
        if seg:
            out.append(("【%s】\n" % (role or "")) + seg)
    return "\n\n".join(out)


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
        out_p = config.WORKSPACE_ROOT / config.sanitize_dir(config.role_name("R1")) / (task_no + "-summary.md")
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
        text = config.read_text(p) if p.exists() else ""
        n = _piyue_next_no(text)          # 现有条目最大编号 +1（无则从 1 起）
        brief = "无回报正文"
        brief_hay = ""          # 决策信号检测用全文
        decisions = ""         # 回报里抽出的「需要 R0 拍板」原文（决策项）
        reps = []
        try:
            reps = store.reports(task_no)
        except Exception:
            reps = []
        try:
            if reps:
                raw_last = str(reps[-1].get("body") or "")
                brief_hay = _digest_body(raw_last, limit=3000)
                # R 建议：逐角色给一段摘要（每人一行续行），不再是只取最后一份的 130 字压缩
                parts = []
                for rp in reps:
                    rb = str(rp.get("body") or "")
                    one = _one_line_digest(rb, limit=170) or "无正文内容"
                    parts.append("%s（%s）：%s" % (rp.get("role") or "?", rp.get("status") or "?", one))
                brief = "\n".join(parts)
                decisions = _decision_items([(rp.get("role"), rp.get("body")) for rp in reps])
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
            # “需要 R0 拍板什么”必须落具体内容：角色回报里写明就用回报原文；
            # 回报没写明时回退到任务原话（R0 自己下达时的决策请求）。
            # 绝不把“任务含决策信号…请 R0 裁决；驳回将触发重新派发”这类机制空话写进待决。
            ask = decisions or task_s
            lines_b += _field_lines("需要 R0 拍板什么", ask)
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
            text = config.read_text(p)
            if no and no not in text and no not in p.name:
                continue
            stem = p.stem
            for suf in ("-report", "-output"):
                if stem.endswith(suf):
                    stem = stem[: -len(suf)]
                    break
            meta_p = d / (stem + ".meta.json")
            st = ""
            if meta_p.exists():
                try:
                    st = str(json.loads(config.read_text(meta_p)).get("status") or "")
                except Exception:
                    st = "元数据损坏"
            files.append({"name": p.name, "rel": p.relative_to(config.ROOT).as_posix(),
                          "mtime": p.stat().st_mtime, "status": st, "head": text[:200]})
        if files:
            out.append({"dir": d.name, "files": files})
    return out


# ================= 04 项目文件：各角色工作区浏览器（按角色/任务筛选，可读文件才放行预览） =================
_WS_BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".psd", ".ai",
                  ".zip", ".rar", ".7z", ".gz", ".tar", ".exe", ".dll", ".so", ".pyc",
                  ".db", ".sqlite", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".mp3", ".mp4", ".wav", ".avi", ".mov", ".woff", ".woff2", ".ttf", ".otf",
                  ".class", ".o", ".obj", ".bin", ".dat", ".wasm", ".jar"}
_WS_SKIP_PARTS = {"node_modules", ".git", "__pycache__", ".dsh-tmp"}
_WS_MAX_BYTES = 3 * 1024 * 1024        # 在线预览上限 3 MB


def ws_files() -> list:
    """扫描《工作区/<角色>/》文件 → 产物清单（供按 角色/任务 筛选）。

    只收人读产物：md 交付物（-report / -output / -summary / 其它 .md）与普通文本；
    .meta.json 是机器状态文件不进产物列表。同角色同名文件同时存在于当前与 已归档/ 时只留当前副本。"""
    raw = []
    ws = config.WORKSPACE_ROOT
    if not ws.is_dir():
        return []
    for d in sorted(ws.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file() or any(seg in _WS_SKIP_PARTS for seg in p.relative_to(ws).parts):
                continue
            if p.suffix.lower() == ".json":            # meta.json = 元数据，不展示
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            m = re.search(r"T-\d+", p.name)
            rel = p.relative_to(config.ROOT).as_posix()
            raw.append({"role": d.name, "name": p.name, "rel": rel,
                        "ext": p.suffix.lower(), "task": m.group(0) if m else "",
                        "archived": "已归档" in p.relative_to(d).parts,
                        "size": st.st_size, "mtime": int(st.st_mtime)})
    seen = {}
    for f in raw:
        key = (f["role"], f["name"])
        cur = seen.get(key)
        if cur is None or (cur["archived"] and not f["archived"]):
            seen[key] = f
    return sorted(seen.values(), key=lambda f: (f["role"], f["name"], f["rel"]))


def rename_legacy_ws_files() -> list:
    """历史旧命名 → 新命名格式（就地改名，含 已归档/）：
       T-xxx-Sn.md        → T-xxx-Sn-report.md
       T-xxx-工作汇总.md    → T-xxx-summary.md
       已是新命名 / meta.json / 其它文件不动；目标已存在则跳过。"""
    renamed = []
    ws = config.WORKSPACE_ROOT
    if not ws.is_dir():
        return renamed
    for p in sorted(ws.rglob("*")):
        if not p.is_file():
            continue
        name = p.name
        if not name.endswith(".md") or name.endswith(("-report.md", "-output.md", "-summary.md")):
            continue
        base = name[:-3]
        new = None
        if re.fullmatch(r"T-\d+-S\d+", base):
            new = base + "-report.md"
        elif re.fullmatch(r"T-\d+-工作汇总", base):
            new = re.sub(r"-工作汇总$", "", base) + "-summary.md"
        if not new:
            continue
        target = p.with_name(new)
        if target.exists():
            continue
        try:
            p.rename(target)
            renamed.append("%s -> %s" % (p.relative_to(config.ROOT).as_posix(),
                                         target.relative_to(config.ROOT).as_posix()))
        except OSError:
            pass
    return renamed


def token_rows() -> list:
    """从各角色工作区 meta.json（当前 + 已归档）读 token 统计行（meta 里 tokensIn/tokensOut）。"""
    rows = []
    ws = config.WORKSPACE_ROOT
    if not ws.is_dir():
        return rows
    for d in sorted(ws.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        for base in (d, d / "已归档"):
            if not base.is_dir():
                continue
            for meta_p in sorted(base.glob("*.meta.json")):
                try:
                    m = json.loads(meta_p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if m.get("tokensIn") is None and m.get("tokensOut") is None:
                    continue
                sub = str(m.get("subNo") or "")
                if not sub:
                    continue
                rows.append({"sub": sub, "task": str(m.get("taskNo") or ""),
                             "role": str(m.get("role") or ""), "roleName": str(m.get("roleName") or ""),
                             "date": str(m.get("createdAt") or "")[:10],
                             "tokensIn": int(m.get("tokensIn") or 0),
                             "tokensOut": int(m.get("tokensOut") or 0),
                             "archived": base.name == "已归档"})
    seen = {}
    for r in rows:
        key = (r["task"], r["sub"])
        cur = seen.get(key)
        if cur is None or (cur["archived"] and not r["archived"]):
            seen[key] = r
    return sorted(seen.values(), key=lambda r: (r["task"], r["sub"]))


def ws_read(rel: str) -> dict:
    """读取《工作区/》文件内容供预览：md 原样返回（前端渲染）；其余可解码文本以 txt 预览；
    二进制 / 不可读 / 过大一律不放行（只允许工作区根内，防路径逃逸）。"""
    root = config.ROOT.resolve()
    p = (root / rel).resolve()
    if not str(p).startswith(str(root)) or not p.is_file():
        raise ValueError("文件不存在或路径越界")
    try:
        size = p.stat().st_size
    except OSError:
        raise ValueError("文件不可读")
    if size > _WS_MAX_BYTES:
        raise ValueError("文件过大（超过 %d MB），不提供在线预览" % (_WS_MAX_BYTES // (1024 * 1024)))
    data = p.read_bytes()
    if p.suffix.lower() in _WS_BINARY_EXT or b"\x00" in data[:4096]:
        raise ValueError("二进制 / 不可读文件，已禁止查看")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("gbk")
        except UnicodeDecodeError:
            raise ValueError("无法按 UTF-8 / GBK 解码的文本文件，已禁止查看")
    return {"name": p.name, "kind": "md" if p.suffix.lower() == ".md" else "txt",
            "text": text, "rel": rel}


def task_output(no: str) -> dict:
    """按任务编号聚合输出：回报（DB）+ 子任务（DB）+ 工作区产物 + 调度日志片段。"""
    out = {"no": no,
           "reports": store.reports(no),
           "plan": store.subtasks(no),
           "executions": store.executions(no),
           "files": [], "log": ""}
    for d in _wb_role_dirs():
        for p in sorted(d.glob("*.md")) + sorted((d / "已归档").glob("*.md")):
            if p.name.endswith("-summary.md"):
                continue
            text = config.read_text(p)
            if no in text or no in p.name:
                idx = max(text.find(no), 0)
                out["files"].append({"name": p.name,
                                     "rel": p.relative_to(config.ROOT).as_posix(),
                                     "head": text[:160],
                                     "seg": text[max(0, idx - 120):idx + 420]})
    lg = config.LOG_FILE
    if lg.exists():
        text = config.read_text(lg)
        idx = text.rfind(no)
        if idx >= 0:
            out["log"] = text[max(0, idx - 400):idx + 900]
    return out


def sub_output(sub_no: str) -> dict:
    """单个子任务的产出全文（工作区或已归档下的 {sub_no}.md），供工作台点击子任务查看。"""
    sub_no = (sub_no or "").strip()
    if not sub_no:
        return {}
    for d in _wb_role_dirs():
        for base in (d, d / "已归档"):
            p = base / (sub_no + "-report.md")
            if not p.exists():
                p = base / (sub_no + ".md")
            if not p.exists():
                continue
            meta = {}
            meta_p = base / (sub_no + ".meta.json")
            if meta_p.exists():
                try:
                    meta = json.loads(config.read_text(meta_p))
                except Exception:
                    meta = {}
            return {"rel": p.relative_to(config.ROOT).as_posix(),
                    "text": config.read_text(p),
                    "meta": meta}
    return {}
