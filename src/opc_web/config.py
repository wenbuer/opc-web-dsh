# -*- coding: utf-8 -*-
"""

设置一个「根目录」后自动产生 批阅台/、工作区/、知识库/ 三个文件夹；
工作区按「角色名称」建子文件夹；不再静态预设 决策/运营/营销 等分类目录
（分类内容由对应角色产出时自然形成）。

优先级：环境变量 > 配置文件（opc-config.json，可 OPC_CONFIG 覆盖）> 默认值。
「设置」视图只读写一个根目录字段（root）与端口；保存后 reload()+bootstrap() 立即生效。
v1.9 语义沿用：web 引用与工作区创建一律用「角色名称」，R1/R2 仅为编号 Id。
"""
import datetime
import json
import os
import re
from pathlib import Path

# 应用根：config.py 位于 src/opc_web/，向上三级
BASE = Path(__file__).resolve().parent.parent.parent

CONFIG_FILE = Path(os.environ.get("OPC_CONFIG") or (BASE / "opc-config.json"))


def _load_cfg() -> dict:
    """读取配置文件（不存在/损坏返回 {}）。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_CFG = _load_cfg()

# 根目录：env OPC_KB_ROOT（兼容旧语义，现即总根）> 配置 root（相对 BASE 或绝对）> 默认 BASE
_root_s = os.environ.get("OPC_KB_ROOT") or _CFG.get("root") or "."
ROOT = Path(_root_s).resolve() if os.path.isabs(_root_s) else (BASE / _root_s).resolve()

# 三个自动文件夹（相对根目录）
KB_ROOT = ROOT / "知识库"          # 知识档案（OPC智能体角色架构.md / 知识库索引.md …）
BATCH_ROOT = ROOT / "批阅台"       # R0/R1 公文与日志（批阅台 / 任务队列 / 派发单 / 回报队列 / 调度日志）
WORKSPACE_ROOT = ROOT / "工作区"   # 角色作业区（按角色名称建子文件夹）

# 数据文件位置（相对根目录）
WORKSPACE_REL = "工作区"
PIYUETAI_REL = "批阅台/批阅台.md"
DB_REL = "批阅台/opc.db"               # 状态台账（任务/子任务/回报）—— 唯一真相，见 store.py
LOG_REL = "批阅台/决策日志.md"          # R0 决策记录 + 派发单（parsers 读取）

# 已退役的 md 表格（仅供一次性迁移入库与 legacy 归档定位，程序不再读写）
QUEUE_REL = "批阅台/任务下达队列.md"
REPORT_REL = "批阅台/回报队列.md"
DISPATCH_REL = "批阅台/派发单-动态.md"
SCHED_LOG_REL = "批阅台/调度日志.md"   # R1/控制台运行日志（log_schedule 追加）
ARCH_REL = "知识库/OPC智能体角色架构.md"
INDEX_REL = "知识库/知识库索引.md"

TEMPLATES = BASE / "templates"
STATIC = BASE / "static"
AGENTS_DIR = BASE / "agents"
LOG_FILE = ROOT / SCHED_LOG_REL

HOST = "127.0.0.1"
PORT = int(os.environ.get("OPC_PORT") or _CFG.get("port") or 8901)


def piyuetai_file():
    """批阅台（R0 批阅入口）。"""
    return ROOT / PIYUETAI_REL


def db_file():
    """状态台账 SQLite（跟随 ROOT，测试可猴补丁 config.ROOT）。"""
    return ROOT / DB_REL



def wb_root():
    """角色作业区根（ROOT/工作区/）。"""
    return WORKSPACE_ROOT


def kb_root():
    """知识档案根（ROOT/知识库/）。"""
    return KB_ROOT


# ---------- 配置读写（「设置」视图 /api/settings 使用） ----------

SETTING_KEYS = ("root", "port")          # 设置页可写的字段；其余键只允许手改 opc-config.json

# 运行调参：手改 opc-config.json 即时生效（每次读盘，文件几百字节，代价可忽略）。
# 刻意不进 SETTING_KEYS —— 这些是调优旋钮，不该占设置页的位置。
_TUNABLES = {
    "pollSeconds": 8,           # 调度守护轮询间隔（秒）
    "decomposeTimeout": 480,    # 拆解任务时 headless 的无输出超时（秒）
    "maxSubtasks": 2,           # 单个任务最多拆成几个并行子任务
}


def tune(key: str) -> int:
    """读取运行调参；缺失 / 非法 / 0 一律回退默认值，负数取下限 1。"""
    default = _TUNABLES[key]
    try:
        return max(1, int(_load_cfg().get(key) or default))
    except (TypeError, ValueError):
        return default


def _write_cfg(patch: dict) -> dict:
    """配置写入的唯一出口：读盘 → 合并 patch（值为 None = 删除该键）→ 写盘 → 刷新内存。

    必须读盘再合并，不能基于内存 _CFG 覆写：内存快照可能落后于文件（另一个 save
    刚写过，或用户手改过 opc-config.json），基于它覆写会静默丢段——实测「保存端口」
    会把刚存的 model 段抹掉。"""
    global _CFG
    cur = _load_cfg()
    for k, v in patch.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    _CFG = cur
    return cur


def save_cfg(kv: dict) -> dict:
    """把设置页字段（SETTING_KEYS 白名单）合并写入配置文件（空值=删除该字段）。"""
    patch = {}
    for k, v in kv.items():
        if k not in SETTING_KEYS:
            continue
        blank = v is None or (isinstance(v, str) and not v.strip())
        patch[k] = None if blank else (v.strip() if isinstance(v, str) else v)
    return _write_cfg(patch)


def reload() -> dict:
    """重新读取配置并刷新模块常量（保存后立即生效）。"""
    global _CFG, ROOT, KB_ROOT, BATCH_ROOT, WORKSPACE_ROOT, LOG_FILE, PORT
    _CFG = _load_cfg()
    _root_s = os.environ.get("OPC_KB_ROOT") or _CFG.get("root") or "."
    ROOT = Path(_root_s).resolve() if os.path.isabs(_root_s) else (BASE / _root_s).resolve()
    KB_ROOT = ROOT / "知识库"
    BATCH_ROOT = ROOT / "批阅台"
    WORKSPACE_ROOT = ROOT / "工作区"
    LOG_FILE = ROOT / SCHED_LOG_REL
    PORT = int(os.environ.get("OPC_PORT") or _CFG.get("port") or 8901)
    return settings_info()


def settings_info() -> dict:
    """当前生效配置摘要（根目录与三目录状态/角色与 preset 就绪数）。"""
    preset_home = Path(os.environ.get("OPC_PRESET_HOME") or (Path.home() / ".dsh" / ".agent-presets"))
    presets_ready = sum(1 for d in preset_home.glob("opc-r?") if (d / "preset.yml").exists()) if preset_home.is_dir() else 0
    return {
        "ok": True,
        "config": {k: _CFG.get(k) for k in SETTING_KEYS},
        "root": str(ROOT.resolve()) if ROOT.exists() else str(ROOT),
        "kbRoot": str(KB_ROOT.resolve()) if KB_ROOT.exists() else str(KB_ROOT),
        "kbExists": KB_ROOT.exists(),
        "batchRoot": str(BATCH_ROOT.resolve()) if BATCH_ROOT.exists() else str(BATCH_ROOT),
        "batchExists": BATCH_ROOT.exists(),
        "workspaceRoot": str(WORKSPACE_ROOT.resolve()) if WORKSPACE_ROOT.exists() else str(WORKSPACE_ROOT),
        "workspaceExists": WORKSPACE_ROOT.exists(),
        "presetHome": str(preset_home),
        "presetsReady": presets_ready,
        "model": model_info(),
        "rolesCount": sum(1 for p in AGENTS_DIR.glob("R*.role.md")),
        "envOverride": bool(os.environ.get("OPC_KB_ROOT") or os.environ.get("OPC_CONFIG") or os.environ.get("OPC_PORT")),
    }


def list_dirs(base_path: str = "") -> dict:
    """列出 path 的直接子目录（目录选择器用）；path 空 → 根目录（三个自动文件夹可见）。"""
    try:
        p = Path(base_path).resolve() if base_path else ROOT
        if not p.is_dir():
            return {"ok": False, "msg": "目录不存在或不可读：" + str(p)}
        dirs = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))
        return {"ok": True, "path": str(p), "dirs": dirs}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


# ---------- 角色名称 ↔ 工作区目录（web 引用/工作区创建用角色名称；R1/R2 仅为编号 Id） ----------

_ROLE_NAME_RE = re.compile("名称" + chr(92) + "s*[：:]([^｜|" + chr(92) + "r" + chr(92) + "n]+)")


def sanitize_dir(name: str) -> str:
    """把角色名称转换为安全目录片段（去非法字符，保留中文/括号）。"""
    bad = set(chr(92) + "/:*?<>|\"" + chr(39) + chr(9) + chr(13) + chr(10) + " ")
    s = "".join(c for c in str(name or "") if c not in bad).strip()
    return s or "未命名"


def role_name(no: str) -> str:
    """角色编号 → 角色名称（读本项目 agents/R?.role.md「身份·名称」；缺失时回退编号）。"""
    p = AGENTS_DIR / (no + ".role.md")
    if p.exists():
        m = _ROLE_NAME_RE.search(p.read_text(encoding="utf-8"))
        if m and m.group(1).strip():
            return m.group(1).strip()
    return no


def role_ws_dir(no: str) -> str:
    """角色编号 → 工作区目录名 = 角色名称（不带 -输出 后缀）。"""
    return sanitize_dir(role_name(no))



def role_ws_rel(no: str) -> str:
    """角色编号 → 相对路径「工作区/<角色名称>」。"""
    return "%s/%s" % (WORKSPACE_REL, role_ws_dir(no))


# ---------- 大模型 API（模型接入，参照 dsh 模型 API 接入惯例） ----------
# dsh 惯例：提供方路由 → 凭据引用默认 <ROUTE>_API_KEY（环境变量层）；baseURL/模型可按部署覆盖写进配置段；
# 密钥只写凭据层（环境变量 / 项目根 .env），不落 opc-config.json 明文 —— 模型接入页只读写这些字段。

MODEL_PROVIDERS = (
    ("deepseek",  "DEEPSEEK_API_KEY",  "https://api.deepseek.com",         "deepseek-chat"),
    ("openai",    "OPENAI_API_KEY",    "https://api.openai.com/v1",        "gpt-4o-mini"),
    ("anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1",     "claude-sonnet-4-5"),
    ("custom",    "CUSTOM_API_KEY",    "",                                 ""),
)
ENV_FILE = BASE / ".env"   # 项目根 .env（dsh 环境层文件约定：密钥只写这里）

def model_defaults(provider: str):
    """提供方 → (apiKeyEnv 默认引用名, baseURL 默认, 模型默认)。"""
    for p, env, base, mdl in MODEL_PROVIDERS:
        if p == provider:
            return env, base, mdl
    return "CUSTOM_API_KEY", "", ""


def read_env_file() -> dict:
    """解析项目根 .env（dsh 环境层约定：NAME=value 每行，忽略 # 注释）。"""
    out = {}
    try:
        for ln in ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]          # dotenv 惯例：剥外层引号，否则引号会混进 API Key
            if k:
                out[k.strip()] = v
    except Exception:
        pass
    return out


def write_env(name: str, value) -> None:
    """把 name=value 写入项目根 .env（value 为 None → 删除该行）。

    不吞异常：这是凭据路径，写盘失败必须让调用方（/api/settings）报出来，
    否则界面显示「已保存」而 Key 根本没落盘。"""
    cur = read_env_file()
    if value is None:
        cur.pop(name, None)
    else:
        cur[name] = str(value).strip()
    keep = []
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k = ln.split("=", 1)[0].strip() if "=" in ln else ln.strip()
            if k in cur:
                continue
            keep.append(ln)
    rows = ["%s=%s" % (k, v) for k, v in cur.items()]
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(keep + rows) + ("\n" if (keep + rows) else ""), encoding="utf-8")


def save_model(body: dict, dry: bool = False) -> dict:
    """合并写入 model 段：provider / apiKeyEnv(留空按提供方默认) / baseURL / model；
    apiKey 非空 → 只写入项目根 .env 的 <apiKeyEnv>=key 并同步进程环境（密钥不进 opc-config.json）。"""
    provider = str(body.get("provider") or "deepseek").strip()
    env, base, mdl = model_defaults(provider)
    api_key_env = str(body.get("apiKeyEnv") or env).strip()
    base_url = str(body.get("baseURL") or "").strip()
    model = str(body.get("model") or "").strip()
    api_key = str(body.get("apiKey") or "").strip()

    section = {"provider": provider}
    if api_key_env != env:
        section["apiKeyEnv"] = api_key_env
    if base_url:
        section["baseURL"] = base_url
    if model:
        section["model"] = model

    result = {
        "provider": provider,
        "apiKeyEnv": api_key_env,
        "baseURL": base_url or base,
        "model": model or mdl,
        "keySet": bool(api_key),
        "envFile": str(ENV_FILE),
    }
    if dry:
        return result
    _write_cfg({"model": section})
    if api_key:
        write_env(api_key_env, api_key)
        os.environ[api_key_env] = api_key
    return result


def model_info() -> dict:
    """大模型 API 配置摘要（凭据脱敏：仅返回是否已配置 + 引用名 + 掩码）。"""
    section = _CFG.get("model") or {}
    provider = str(section.get("provider") or "deepseek")
    env, base, mdl = model_defaults(provider)
    api_key_env = str(section.get("apiKeyEnv") or env)
    base_url = str(section.get("baseURL") or base)
    model = str(section.get("model") or mdl)
    key = os.environ.get(api_key_env) or read_env_file().get(api_key_env) or ""
    masked = ""
    if key:
        masked = (key[:4] + "…" + key[-2:]) if len(key) > 6 else "****"
    return {
        "provider": provider,
        "apiKeyEnv": api_key_env,
        "configured": bool(key),
        "keyMasked": masked,
        "baseURL": base_url,
        "model": model,
        "envFile": str(ENV_FILE),
    }




# ---------- 定时任务（在 opc-config.json 的 \"schedule\" 段；到点生成调度指令，由常驻主会话 R1 执行） ----------
# 每个任务：{id, task(下达指令文本), mode: daily|weekly|interval, time:"HH:MM"(daily/weekly),
#            weekday:0-6(weekly,0=周一), intervalMin(interval), enabled, lastRun}
# 执行语义同 README：控制台只把到期任务写入《任务下达队列.md》并记调度日志（生成调度指令），
# 实际执行方 = 常驻主会话 R1（读取队列后拆解派发）。

def load_schedules() -> list:
    """读取 opc-config.json 的 schedule 段（任务列表）。"""
    s = _CFG.get("schedule")
    return s if isinstance(s, list) else []


def save_schedules(jobs: list) -> None:
    """把任务列表写回 opc-config.json（不触发 reload，避免重扫目录）。"""
    _write_cfg({"schedule": jobs or []})


def schedule_next(job: dict, now=None) -> object:
    """计算任务下一次触发时刻（datetime 或 None）。interval 模式从 lastRun/now 滚动计算。"""
    now = now or datetime.datetime.now()
    mode = str(job.get("mode") or "daily")
    enabled = job.get("enabled", True)
    if not enabled:
        return None
    if mode == "interval":
        mins = 0
        try:
            mins = max(1, int(job.get("intervalMin") or 0))
        except Exception:
            mins = 30
        base = None
        if job.get("lastRun"):
            try:
                base = datetime.datetime.strptime(str(job["lastRun"])[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                base = None
        base = base or now
        return base + datetime.timedelta(minutes=mins)
    hh = mm = 0
    try:
        hp = str(job.get("time") or "09:00").strip().split(":")
        hh, mm = int(hp[0]), int(hp[1])
    except Exception:
        hh, mm = 9, 0
    if mode == "weekly":
        try:
            wd = int(job.get("weekday") or 0)
        except Exception:
            wd = 0
        days = (wd - now.weekday()) % 7
        nxt = (now + datetime.timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= now:
            nxt = (now + datetime.timedelta(days=days + 7)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        return nxt
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt = nxt + datetime.timedelta(days=1)
    return nxt


def schedule_status(jobs: list = None) -> list:
    """任务列表摘要（供 /api/schedule 与设置页展示：含下次触发时间/状态）。"""
    jobs = jobs if jobs is not None else load_schedules()
    now = datetime.datetime.now()
    out = []
    for i, j in enumerate(jobs):
        nxt = schedule_next(j, now)
        out.append({
            "id": j.get("id") or ("sched-%d" % (i + 1)),
            "task": j.get("task") or "",
            "mode": j.get("mode") or "daily",
            "time": j.get("time") or "",
            "weekday": j.get("weekday"),
            "intervalMin": j.get("intervalMin"),
            "enabled": bool(j.get("enabled", True)),
            "lastRun": j.get("lastRun") or "",
            "nextRun": nxt.strftime("%Y-%m-%d %H:%M") if nxt else "",
        })
    return out

def test_model(body: dict, timeout: int = 15) -> dict:
    """真实连通测试（1 token 最小请求）：按提供方协议调用 chat 端点。
    返回 {ok, msg, provider, model, baseURL, latencyMs, status}。"""
    import time
    import urllib.error
    import urllib.request

    provider = str(body.get("provider") or "deepseek").strip()
    env, base, mdl = model_defaults(provider)
    api_key_env = str(body.get("apiKeyEnv") or env)
    base_url = str(body.get("baseURL") or base or "").strip()
    model = str(body.get("model") or mdl or "").strip()
    api_key = str(body.get("apiKey") or "").strip()
    if not api_key:
        api_key = os.environ.get(api_key_env) or read_env_file().get(api_key_env) or ""
    if not base_url:
        return {"ok": False, "msg": "缺少 baseURL（自定义提供方需填写端点）"}
    if not model:
        return {"ok": False, "msg": "缺少模型 Id（或选择提供方默认）"}
    if not api_key:
        return {"ok": False, "msg": "缺少 API Key：请先保存密钥或本次测试输入"}

    anthropic = provider == "anthropic"
    if anthropic:
        endpoint = base_url.rstrip("/") + "/messages"
        payload = json.dumps({"model": model, "max_tokens": 1,
                              "messages": [{"role": "user", "content": "ping"}]}).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
    else:
        endpoint = base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps({"model": model, "max_tokens": 1,
                              "messages": [{"role": "user", "content": "ping"}]}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key}
    t0 = time.time()
    base_result = {"provider": provider, "model": model, "baseURL": endpoint, "apiKeyEnv": api_key_env}
    try:
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            code = resp.status
        latency = int((time.time() - t0) * 1000)
        if code == 200:
            return {"ok": True, "msg": "连通正常", "latencyMs": latency, "status": code, **base_result}
        err = ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                err = parsed.get("error") or parsed.get("message") or ""
                if isinstance(err, dict):
                    err = err.get("message") or ""
        except Exception:
            err = raw
        return {"ok": False, "msg": "HTTP %s %s" % (code, str(err)[:200]), "latencyMs": latency, "status": code, **base_result}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        latency = int((time.time() - t0) * 1000)
        return {"ok": False, "msg": "HTTP %s %s" % (e.code, raw[:200]), "latencyMs": latency, "status": e.code, **base_result}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:200], **base_result}
