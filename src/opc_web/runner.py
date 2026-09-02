# -*- coding: utf-8 -*-
"""执行事件流：自动执行链把阶段事件写进内存缓冲，工作台详情面板轮询显示。

v1.16 精简：控制台不再自己 spawn 观测进程（原「直跑观测」），也不再读主会话遥测
JSONL——两条通道都从未产生过数据（《批阅台/运行监控/》与 ~/.dsh/opc-telemetry.jsonl
均不存在），UI 入口随「agent 执行监听」面板一并下线。本模块现在只做两件事：
接收 chain 写入的阶段事件，以及为任务拆解同步直跑一次 dsh headless。
"""
import json
import os
import shutil
import subprocess
import threading
import time

from . import config

_LOCK = threading.RLock()
_ACTIVE = {"events": [], "seq": 0}


def _child_env() -> dict:
    """dsh 子进程的环境：项目根 .env 打底 + 当前进程环境覆盖（环境变量优先于文件）。

    dsh 自己不读项目 .env，子进程只继承父进程环境；而控制台启动时并不加载 .env
    （只有「设置→模型接入」保存那一刻会往 os.environ 塞一次）。结果是手改 .env 或
    重启之后，界面显示「已配置 ✓」而 headless 实际拿不到密钥。这里每次 spawn 现读，
    顺带让改完 .env 无需重启。"""
    return {**config.read_env_file(), **os.environ}


def _append(ev: dict) -> int:
    with _LOCK:
        _ACTIVE["seq"] += 1
        _ACTIVE["events"].append({"seq": _ACTIVE["seq"], **ev})
        if len(_ACTIVE["events"]) > 6000:
            _ACTIVE["events"] = _ACTIVE["events"][-4000:]
        return _ACTIVE["seq"]


def emit(ev: dict) -> int:
    """公开事件入口：自动执行链把阶段事件写进来，前端详情面板增量轮询。"""
    return _append(ev)


def events(since: int = 0) -> dict:
    """自 since 之后的新事件（前端用返回的 state.seq 作为下次游标）。"""
    with _LOCK:
        return {"ok": True, "state": {"seq": _ACTIVE["seq"]},
                "events": [e for e in _ACTIVE["events"] if e["seq"] > since]}


def _spawn_headless(argv: list, timeout: float) -> bytes:
    """启动 dsh headless 子进程并收尾，返回其原始 stdout（stderr 合并）字节。

    超时语义（v1.14，来自实测）：headless 只在 turn 结束后一次性打印 final 文本，
    因此一旦收到任何输出即视为任务存活、放弃强杀、等待自然结束；
    仅当全程无输出且超时才强杀（防 headless 静默挂死泄漏进程树）。
    spawn 失败返回 b""。"""
    exe = shutil.which("dsh") or "dsh"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    si = subprocess.STARTUPINFO() if hasattr(subprocess, "STARTUPINFO") else None
    if si is not None:
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    try:
        p = subprocess.Popen([exe, "--profile", "headless"] + argv,
                             cwd=str(config.ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=flags, startupinfo=si, env=_child_env())
    except Exception:
        return b""
    chunks = []

    def _drain():
        try:
            for blk in iter(lambda: p.stdout.read(65536), b""):
                chunks.append(blk)
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True).start()
    t0 = time.monotonic()
    while True:
        if p.poll() is not None:
            break                       # 自然结束
        if chunks:
            # 有输出 → 任务在推进：等自然结束（不设超时上限）
            try:
                p.wait()
            except Exception:
                pass
            break
        if time.monotonic() - t0 > timeout:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True, text=True)
            try:
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
            break
        time.sleep(0.5)
    try:
        p.stdout.close()
    except Exception:
        pass
    return b"".join(chunks)


def run_headless_sync(task_text: str, timeout: float = 600) -> str:
    """同步直跑 dsh headless（最终文本模式），返回 stdout。"""
    return _spawn_headless([task_text], timeout).decode("utf-8", "replace").strip()


def _decode_stdout(data: bytes) -> str:
    """dsh 在 Windows 下把 --events-jsonl 写成了 UTF-16LE（带 BOM）；按 BOM 解，否则 UTF-8。"""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16-le" if data[:2] == b"\xff\xfe" else "utf-16-be", errors="replace")
    return data.decode("utf-8", errors="replace")


def run_headless_task(task_text: str, timeout: float = 600):
    """headless + --events-jsonl：返回 (最终文本, 用量 dict|None)。

    用量来自事件流 assistant/chunk 的 data.usage（inputTokens/outputTokens 等），
    供 chain 写回子任务 meta.json；最终文本取 run/end.text（无则拼 chunk）。"""
    text = _decode_stdout(_spawn_headless([task_text, "--events-jsonl"], timeout))
    usage = None
    final = ""
    for ln in text.splitlines():
        line = ln.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        d = ev.get("data") or {}
        if ev.get("type") == "assistant/chunk" and isinstance(d.get("usage"), dict):
            u = d["usage"]
            if u.get("inputTokens") is not None or u.get("outputTokens") is not None:
                usage = {"inputTokens": int(u.get("inputTokens") or 0),
                         "outputTokens": int(u.get("outputTokens") or 0),
                         "cacheReadTokens": int(u.get("cacheReadTokens") or 0),
                         "reasoningTokens": int(u.get("reasoningTokens") or 0)}
        elif ev.get("type") == "run/end" and ev.get("text"):
            final = ev["text"]
    if not final:
        final = text
    return final.strip(), usage
