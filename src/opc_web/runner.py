# -*- coding: utf-8 -*-
"""agent 执行遥测（方案 A）：控制台直跑 dsh headless，捕获完整 prompt、
大模型流式输出、工具调用，供工作台「执行监控」面板实时查看。"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config


_LOCK = threading.RLock()  # events() 嵌套调 state()，需可重入
_ACTIVE = {"proc": None, "run_id": "", "task": "", "started": 0.0, "events": [], "seq": 0, "log_path": None}


def _append(ev: dict) -> int:
    with _LOCK:
        _ACTIVE["seq"] += 1
        _ACTIVE["events"].append({"seq": _ACTIVE["seq"], **ev})
        if len(_ACTIVE["events"]) > 6000:
            _ACTIVE["events"] = _ACTIVE["events"][-4000:]
        return _ACTIVE["seq"]


def _assemble(task: str) -> str:
    """若任务以 R? 开头，自动注入对应角色卡全文作为 persona 上下文。"""
    m = re.match(r"^R(\d+)\b", task.strip())
    if m:
        card = config.AGENTS_DIR / (m.group(1) + ".role.md")
        if card.is_file():
            text = card.read_text(encoding="utf-8")
            return "（控制台观测执行 · 角色卡注入）\n" + text + "\n\n任务：" + task.strip()
    return task.strip()


def start(task_text: str) -> str:
    t = (task_text or "").strip()
    if not t:
        raise ValueError("任务内容不能为空")
    with _LOCK:
        p = _ACTIVE["proc"]
        if p is not None and p.poll() is None:
            raise ValueError("已有运行中的观测任务，请先停止")
    run_id = time.strftime("run-%Y%m%d-%H%M%S")
    task = _assemble(t)
    with _LOCK:
        _ACTIVE.update(run_id=run_id, task=t, started=time.time(), events=[], seq=0,
                       log_path=(config.ROOT / "批阅台" / "运行监控" / (run_id + ".jsonl")))
        _ACTIVE["log_path"].parent.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("dsh") or "dsh"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startup = subprocess.STARTUPINFO() if hasattr(subprocess, "STARTUPINFO") else None
    if startup is not None:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    proc = subprocess.Popen([exe, "--profile", "headless", "--events-jsonl", task],
                            cwd=str(config.ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=dict(os.environ),
                            creationflags=flags, startupinfo=startup)
    with _LOCK:
        _ACTIVE["proc"] = proc

    def _reader():
        log = _ACTIVE["log_path"]
        with open(log, "w", encoding="utf-8") as lf:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                seq = _append(ev)
                lf.write(json.dumps({"seq": seq, **ev}, ensure_ascii=False) + "\n")
                lf.flush()
        code = proc.wait()
        _append({"type": "run/exited", "code": code})

    threading.Thread(target=_reader, daemon=True, name="opc-telemetry-reader").start()
    return run_id


def stop() -> str:
    with _LOCK:
        proc = _ACTIVE["proc"]
        if proc is None or proc.poll() is not None:
            return "当前无运行中的观测任务"
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
    except Exception:
        pass
    return "已停止"


def state() -> dict:
    with _LOCK:
        proc = _ACTIVE["proc"]
        running = proc is not None and proc.poll() is None
        return {
            "running": running,
            "runId": _ACTIVE["run_id"],
            "task": _ACTIVE["task"],
            "started": _ACTIVE["started"],
            "seq": _ACTIVE["seq"],
            "logPath": str(_ACTIVE["log_path"]) if _ACTIVE["log_path"] else "",
        }


def events(since: int = 0) -> dict:
    with _LOCK:
        st = state()
        evs = [e for e in _ACTIVE["events"] if e["seq"] > since]
        return {"ok": True, "state": st, "events": evs}


def latest_log() -> str:
    d = config.ROOT / "批阅台" / "运行监控"
    if not d.is_dir():
        return ""
    files = sorted(d.glob("run-*.jsonl"), reverse=True)
    return str(files[0]) if files else ""
# ---- 主会话遥测（方案 B）：读 ~/.dsh/opc-telemetry.jsonl（dsh-session 实时落盘）----
def _telemetry_path() -> Path:
    home = os.environ.get("DSH_HOME") or str(Path.home() / ".dsh")
    p = Path(home)
    if p.name == ".dsh":
        return p / "opc-telemetry.jsonl"
    return p / ".dsh" / "opc-telemetry.jsonl"


def main_telemetry(since_off: int = 0) -> dict:
    """增量读主会话遥测 JSONL（自 since_off 字节偏移）。"""
    path = _telemetry_path()
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return {"events": [], "nextOffset": 0, "size": 0, "path": str(path),
                "error": "遥测文件尚未生成（需重启 DSH 主会话后产生）"}
    if since_off >= size:
        return {"events": [], "nextOffset": size, "size": size, "path": str(path)}
    try:
        with path.open("r", encoding="utf-8") as fh:
            fh.seek(since_off)
            chunk = fh.read()
    except Exception:
        return {"events": [], "nextOffset": since_off, "size": size, "path": str(path)}
    events = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
def run_headless_sync(task_text: str, timeout: float = 600) -> str:
    """同步直跑 dsh headless（最终文本模式），返回 stdout。
    超时用 taskkill /T /F 强杀整棵进程树（Windows 下 subprocess.run 的 timeout
    对 dsh 的孙进程无效，会卡在管道读取）。"""
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
                             creationflags=flags, startupinfo=si, env=dict(os.environ))
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
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       capture_output=True, text=True)
        try:
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    try:
        p.stdout.close()
    except Exception:
        pass
    return "".join(out).strip()

