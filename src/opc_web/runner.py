# -*- coding: utf-8 -*-
"""执行事件流：自动执行链把阶段事件写进内存缓冲，工作台详情面板轮询显示。

v1.16 精简：控制台不再自己 spawn 观测进程（原「直跑观测」），也不再读主会话遥测
JSONL——两条通道都从未产生过数据（《批阅台/运行监控/》与 ~/.dsh/opc-telemetry.jsonl
均不存在），UI 入口随「agent 执行监听」面板一并下线。本模块现在只做两件事：
接收 chain 写入的阶段事件，以及为任务拆解同步直跑一次 dsh headless。
"""
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


def state() -> dict:
    with _LOCK:
        return {"seq": _ACTIVE["seq"]}


def events(since: int = 0) -> dict:
    """自 since 之后的新事件（前端用返回的 state.seq 作为下次游标）。"""
    with _LOCK:
        return {"ok": True, "state": {"seq": _ACTIVE["seq"]},
                "events": [e for e in _ACTIVE["events"] if e["seq"] > since]}


def run_headless_sync(task_text: str, timeout: float = 600) -> str:
    """同步直跑 dsh headless（最终文本模式），返回 stdout。

    超时语义（v1.14，来自实测）：headless 只在 turn 结束后一次性打印 final 文本，
    因此一旦监控到任何输出行即视为任务存活、放弃强杀、等待自然结束；
    仅当全程无输出且超时才强杀（防 headless 静默挂死泄漏进程树）。"""
    exe = shutil.which("dsh") or "dsh"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    si = subprocess.STARTUPINFO() if hasattr(subprocess, "STARTUPINFO") else None
    if si is not None:
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    try:
        p = subprocess.Popen([exe, "--profile", "headless", task_text],
                             cwd=str(config.ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=flags, startupinfo=si, env=_child_env())
    except Exception:
        return ""
    out = []

    def _drain():
        try:
            for ln in p.stdout:
                out.append(ln)
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True).start()
    t0 = time.monotonic()
    alive = False
    while True:
        if p.poll() is not None:
            break                       # 自然结束
        if out:
            alive = True                # 有输出 → 任务在推进，不再按超时强杀
        if alive:
            try:
                p.wait()                # 等自然结束（不设超时上限）
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
    return "".join(out).strip()
