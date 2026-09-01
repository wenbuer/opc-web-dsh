# -*- coding: utf-8 -*-
"""状态台账（SQLite）：任务 / 子任务（派发单）/ 回报索引 —— 状态的唯一真相。

替代原先的三个 md 表格（任务下达队列.md / 派发单-动态.md / 回报队列.md）。
那套写法的实测毛病：表头 6 列实写 5 列、split("|") 按位置改写整行、
无主键靠整行字符串去重（跨天必重复）、read-all→write-all 无锁并发丢写。

纪律：只有控制台进程写本库（单写者）；agent 只写自己工作区里的 md 正文。
md 仍然承载正文与公文（回报正文 / 批阅台 / 决策日志 / 知识库），不承载状态。
"""
import datetime
import re
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS task(
  no      TEXT PRIMARY KEY,
  date    TEXT NOT NULL,
  task    TEXT NOT NULL,
  expect  TEXT NOT NULL DEFAULT '',
  status  TEXT NOT NULL DEFAULT '待派',
  report  TEXT NOT NULL DEFAULT '—'
);
CREATE TABLE IF NOT EXISTS subtask(
  no      TEXT PRIMARY KEY,
  task_no TEXT NOT NULL,
  sub     TEXT NOT NULL,
  role    TEXT NOT NULL,
  expect  TEXT NOT NULL DEFAULT '',
  status  TEXT NOT NULL DEFAULT '待派'
);
CREATE TABLE IF NOT EXISTS report(
  sub_no  TEXT PRIMARY KEY,
  date    TEXT NOT NULL,
  task_no TEXT NOT NULL,
  role    TEXT NOT NULL,
  title   TEXT NOT NULL DEFAULT '',
  status  TEXT NOT NULL DEFAULT '',
  body    TEXT NOT NULL DEFAULT '',
  src     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS execution(
  id         TEXT PRIMARY KEY,
  sub_no     TEXT NOT NULL,
  task_no    TEXT NOT NULL,
  role       TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at   TEXT,
  result     TEXT,
  error      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_execution_sub ON execution(sub_no);
CREATE INDEX IF NOT EXISTS ix_execution_task ON execution(task_no);
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@contextmanager
def _db():
    """一次操作一个连接：SQLite 自带文件锁，不需要连接池。

    ponytail: 每次都跑一遍 CREATE TABLE IF NOT EXISTS（微秒级、永远正确）；
    等真的成为热点再缓存。"""
    p = config.db_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ---------- 任务 ----------
def add_task(text: str, expect: str = "R1 判断") -> str:
    """下达任务 → 返回任务编号 T-00N。"""
    with _db() as c:
        n = c.execute("SELECT COALESCE(MAX(CAST(SUBSTR(no, 3) AS INTEGER)), 0) FROM task").fetchone()[0]
        no = "T-%03d" % (n + 1)
        c.execute("INSERT INTO task(no, date, task, expect) VALUES(?, ?, ?, ?)",
                  (no, datetime.date.today().isoformat(), text, expect))
        return no


def tasks() -> list:
    """全部任务（键名沿用前端契约：no/time/task/expect/status/report）。"""
    with _db() as c:
        return [{"no": r["no"], "time": r["date"], "task": r["task"], "expect": r["expect"],
                 "status": r["status"], "report": r["report"]}
                for r in c.execute("SELECT * FROM task ORDER BY no")]


def set_task(no: str, status: str, report: str = None) -> bool:
    """回填任务状态（report 为 None 时不动原摘要）。"""
    with _db() as c:
        if report is None:
            cur = c.execute("UPDATE task SET status = ? WHERE no = ?", (status, no))
        else:
            cur = c.execute("UPDATE task SET status = ?, report = ? WHERE no = ?", (status, report, no))
        return cur.rowcount > 0


# ---------- 子任务（派发单） ----------
def replace_subtasks(task_no: str, rows: list) -> list:
    """整体替换某任务的子任务 → 返回子任务编号列表 [T-001-S1, ...]。

    幂等由主键保证：重复拆解直接覆盖，不再需要「删掉旧 ### 节」那种字符串手术。"""
    with _db() as c:
        c.execute("DELETE FROM subtask WHERE task_no = ?", (task_no,))
        out = []
        for i, r in enumerate(rows, 1):
            no = "%s-S%d" % (task_no, i)
            c.execute("INSERT INTO subtask(no, task_no, sub, role, expect, status) VALUES(?, ?, ?, ?, ?, ?)",
                      (no, task_no, r["sub"], r["role"], r.get("expect", ""), r.get("status", "待派")))
            out.append(no)
        return out


def subtasks(task_no: str = "") -> list:
    """子任务清单（键名沿用前端 /api/plan-rows 契约：no/sub/role/expect/st）+ 执行摘要。"""
    q = ("SELECT s.*,"
         " (SELECT COUNT(*) FROM execution e WHERE e.sub_no = s.no) AS tries,"
         " (SELECT e.result FROM execution e WHERE e.sub_no = s.no"
         "  ORDER BY e.started_at DESC, e.id DESC LIMIT 1) AS last_result,"
         " (SELECT e.started_at FROM execution e WHERE e.sub_no = s.no"
         "  ORDER BY e.started_at DESC, e.id DESC LIMIT 1) AS last_started"
         " FROM subtask s")
    args = ()
    if task_no:
        q += " WHERE s.task_no = ?"
        args = (task_no,)
    with _db() as c:
        return [{"no": r["no"], "taskNo": r["task_no"], "sub": r["sub"], "role": r["role"],
                 "expect": r["expect"], "st": r["status"],
                 "tries": r["tries"], "lastResult": r["last_result"], "lastStarted": r["last_started"]}
                for r in c.execute(q + " ORDER BY s.no", args)]


def set_subtask(no: str, status: str) -> bool:
    with _db() as c:
        return c.execute("UPDATE subtask SET status = ? WHERE no = ?", (status, no)).rowcount > 0


# ---------- 回报 ----------
def put_report(sub_no: str, task_no: str, role: str, status: str,
               title: str = "", body: str = "", src: str = "") -> None:
    """落库一条回报（主键 = 子任务编号，重复摄取即覆盖，天然幂等）。"""
    with _db() as c:
        c.execute("""INSERT INTO report(sub_no, date, task_no, role, title, status, body, src)
                     VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(sub_no) DO UPDATE SET
                       date = excluded.date, title = excluded.title, status = excluded.status,
                       body = excluded.body, src = excluded.src""",
                  (sub_no, datetime.date.today().isoformat(), task_no, role, title, status, body, src))


def reports(task_no: str = "") -> list:
    """回报索引；body 为回报正文全文（正文文件已归档，DB 为权威副本）。"""
    q = "SELECT * FROM report"
    args = ()
    if task_no:
        q += " WHERE task_no = ?"
        args = (task_no,)
    with _db() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY date, sub_no", args)]

# ---------- 执行记录（一次派发 = 一条；重试开新条，不覆盖历史） ----------
def open_execution(sub_no: str, task_no: str, role: str) -> str:
    """开一次执行尝试，返回执行 id（<子任务号>#<第几次>）。

    重试不覆盖上一次 —— 原先「回报队列.md」里同一个 T-001 出现四条互相矛盾的行，
    根因就是每次重跑都往同一处写，没有「第几次尝试」这个维度。"""
    with _db() as c:
        n = c.execute("SELECT COUNT(*) FROM execution WHERE sub_no = ?", (sub_no,)).fetchone()[0]
        eid = "%s#%d" % (sub_no, n + 1)
        c.execute("INSERT INTO execution(id, sub_no, task_no, role, started_at) VALUES(?, ?, ?, ?, ?)",
                  (eid, sub_no, task_no, role, _now()))
        return eid


def settle_execution(sub_no: str, result: str, error: str = "") -> bool:
    """结算该子任务最近一次未结算的执行；没有在跑的执行则返回 False。"""
    with _db() as c:
        row = c.execute("SELECT id FROM execution WHERE sub_no = ? AND ended_at IS NULL "
                        "ORDER BY started_at DESC, id DESC LIMIT 1", (sub_no,)).fetchone()
        if row is None:
            return False
        c.execute("UPDATE execution SET ended_at = ?, result = ?, error = ? WHERE id = ?",
                  (_now(), result, error, row["id"]))
        return True


def executions(task_no: str = "", sub_no: str = "") -> list:
    """执行历史（最近的在后）。给定 sub_no 时只看该子任务。"""
    q, args = "SELECT * FROM execution", []
    where = []
    if task_no:
        where.append("task_no = ?")
        args.append(task_no)
    if sub_no:
        where.append("sub_no = ?")
        args.append(sub_no)
    if where:
        q += " WHERE " + " AND ".join(where)
    with _db() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY started_at, id", args)]


# ---------- 一次性迁移：退役的 md 表格 → 本库 ----------
_ROW = re.compile(r"^\|(.+)\|\s*$")


def _cells(line: str) -> list:
    """md 表格行 → 单元格列表；非表行或 |---|---| 分隔行返回 []。"""
    m = _ROW.match(line.strip())
    if not m:
        return []
    cells = [c.strip() for c in m.group(1).split("|")]
    return [] if all(set(c) <= set("-: ") for c in cells) else cells


def migrate_md_tables() -> list:
    """把退役的三个 md 表格导入本库，原文件移入《批阅台/legacy/》。

    幂等：靠主键 INSERT OR IGNORE；文件移走后不再重复执行。"""
    out = []
    files = {rel: config.ROOT / rel for rel in
             (config.QUEUE_REL, config.DISPATCH_REL, config.REPORT_REL)}
    if not any(p.exists() for p in files.values()):
        return out
    with _db() as c:
        q = files[config.QUEUE_REL]
        if q.exists():
            n = 0
            for ln in q.read_text(encoding="utf-8").split("\n"):
                cs = _cells(ln)
                if len(cs) < 5 or not cs[0].startswith("T-"):
                    continue
                c.execute("INSERT OR IGNORE INTO task(no, date, task, expect, status, report) "
                          "VALUES(?, ?, ?, ?, ?, ?)",
                          (cs[0], cs[1], cs[2], cs[3], cs[4], cs[5] if len(cs) > 5 else "—"))
                n += 1
            out.append("任务下达队列.md → task %d 行" % n)
        d = files[config.DISPATCH_REL]
        if d.exists():
            seq, n = {}, 0
            for ln in d.read_text(encoding="utf-8").split("\n"):
                cs = _cells(ln)
                if len(cs) < 4 or not cs[0].startswith("T-") or not re.match(r"^R\d+", cs[2]):
                    continue
                seq[cs[0]] = seq.get(cs[0], 0) + 1
                c.execute("INSERT OR IGNORE INTO subtask(no, task_no, sub, role, expect, status) "
                          "VALUES(?, ?, ?, ?, ?, ?)",
                          ("%s-S%d" % (cs[0], seq[cs[0]]), cs[0], cs[1], cs[2].split()[0],
                           cs[3], cs[4] if len(cs) > 4 else "待派"))
                n += 1
            out.append("派发单-动态.md → subtask %d 行" % n)
        r = files[config.REPORT_REL]
        if r.exists():
            seq, n = {}, 0
            for ln in r.read_text(encoding="utf-8").split("\n"):
                cs = _cells(ln)
                if len(cs) < 5 or not re.match(r"^\d{4}-\d{2}-\d{2}$", cs[0]):
                    continue
                key = cs[1] or "历史"
                seq[key] = seq.get(key, 0) + 1
                c.execute("INSERT OR IGNORE INTO report(sub_no, date, task_no, role, title, status, body, src) "
                          "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                          ("%s-legacy%d" % (key, seq[key]), cs[0], cs[1], cs[2], cs[3], cs[4],
                           cs[5] if len(cs) > 5 else "", "legacy/回报队列.md"))
                n += 1
            out.append("回报队列.md → report %d 行（历史行正文当年已被截断，无法还原）" % n)
    legacy = config.BATCH_ROOT / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    for p in files.values():
        if p.exists():
            p.replace(legacy / p.name)
    out.append("原 md 表格已移入 批阅台/legacy/")
    return out

