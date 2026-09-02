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


def decode_bytes(data: bytes) -> str:
    """宽容解码文本字节：纯 UTF-8 直读；首个坏字节处切分 = 前半 UTF-8 + 后半 GBK。

    旧版程序/外部工具可能用 Windows 默认 GBK 追加写过 md/日志，形成
    「UTF-8 头 + GBK 尾」的混合文件；这里兜底，避免读取端抛 UnicodeDecodeError。
    注意：不能整段按 GBK 试解 —— GBK 对 UTF-8 字节常能“解成功”但产出乱码。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        head = data[:e.start].decode("utf-8", errors="replace")
        try:
            tail = data[e.start:].decode("gbk")
        except UnicodeDecodeError:
            tail = data[e.start:].decode("gbk", errors="replace")
        return head + tail


def read_text(p: Path) -> str:
    """按 UTF-8 读文件；遇非 UTF-8（如 GBK 旧文件）自动兜底。"""
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return decode_bytes(p.read_bytes())


def _load_cfg() -> dict:
    """读取配置文件（不存在/损坏返回 {}）。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_CFG = _load_cfg()

# ---------- 项目：一个 opc-web 对应多个 OPC 项目 ----------
# BASE = 程序目录（代码 + opc-config.json + .env + agents-seed/）
# ROOT = 当前激活项目的根（agents/ + 批阅台/ + 工作区/ + 知识库/），每个项目完全自包含。
# 项目以 root 路径为唯一键 —— 项目就是一个目录，不再另造 slug/id 这层概念。
AGENTS_SEED = BASE / "agents-seed"      # 角色卡模板库：新建项目时复制一份进项目自己的 agents/


def projects() -> list:
    """已登记的项目 [{name, root, schedule}]。"""
    ps = _CFG.get("projects")
    return ps if isinstance(ps, list) else []


def active_project() -> dict:
    """当前激活项目；active 指不到就退到第一个，都没有则空 dict。"""
    ps = projects()
    want = str(_CFG.get("active") or "")
    for p in ps:
        if str(p.get("root") or "") == want:
            return p
    return ps[0] if ps else {}


# 默认数据目录：无激活项目时数据落在程序目录旁（opc-data/），绝不混进代码目录。
# 建项目后 ROOT = 项目目录，运行数据（批阅台/工作区/知识库/台账）全部随项目走。
DATA_DIR = BASE.parent / "opc-data"


def _resolve_root() -> Path:
    """优先级：env OPC_KB_ROOT > 激活项目 root > 旧字段 root > 默认数据目录。"""
    s = (os.environ.get("OPC_KB_ROOT")
         or str(active_project().get("root") or "")
         or str(_CFG.get("root") or "")
         or "")
    if not s:
        return DATA_DIR
    return Path(s).resolve() if os.path.isabs(s) else (BASE / s).resolve()


ROOT = _resolve_root()

# 三个自动文件夹（相对根目录）
KB_ROOT = ROOT / "知识库"          # 知识档案（OPC智能体角色架构.md / 知识库索引.md …）
BATCH_ROOT = ROOT / "批阅台"       # R0/R1 公文与日志（批阅台 / 任务队列 / 派发单 / 回报队列 / 调度日志）
WORKSPACE_ROOT = ROOT / "工作区"   # 角色作业区（按角色名称建子文件夹）

# 数据文件位置（相对根目录）
WORKSPACE_REL = "工作区"
PIYUETAI_REL = "批阅台/批阅台.md"
DB_REL = "批阅台/opc.db"               # 状态台账（任务/子任务/回报）—— 唯一真相，见 store.py
LOG_REL = "批阅台/决策日志.md"          # R0 决策记录 + 派发单（parsers 读取）

SCHED_LOG_REL = "批阅台/调度日志.md"   # R1/控制台运行日志（log_schedule 追加）
ARCH_REL = "知识库/OPC智能体角色架构.md"
INDEX_REL = "知识库/知识库索引.md"

TEMPLATES = BASE / "templates"
STATIC = BASE / "static"
# 角色阵容跟项目走；还没建项目时退回模板库，作战面板不至于空着（此时只读）
AGENTS_DIR = (ROOT / "agents") if active_project() else AGENTS_SEED
LOG_FILE = ROOT / SCHED_LOG_REL

HOST = "127.0.0.1"
PORT = int(os.environ.get("OPC_PORT") or _CFG.get("port") or 8901)


def wb_root():
    """角色作业区根（ROOT/工作区/）。"""
    return WORKSPACE_ROOT


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
    global _CFG, ROOT, KB_ROOT, BATCH_ROOT, WORKSPACE_ROOT, AGENTS_DIR, LOG_FILE, PORT
    _CFG = _load_cfg()
    ROOT = _resolve_root()
    KB_ROOT = ROOT / "知识库"
    BATCH_ROOT = ROOT / "批阅台"
    WORKSPACE_ROOT = ROOT / "工作区"
    AGENTS_DIR = (ROOT / "agents") if active_project() else AGENTS_SEED
    LOG_FILE = ROOT / SCHED_LOG_REL
    PORT = int(os.environ.get("OPC_PORT") or _CFG.get("port") or 8901)
    return settings_info()


def add_project(name: str, root: str) -> dict:
    """登记一个项目（目录初始化交给 bootstrap.init_project）；root 已存在则返回原条目。"""
    root_s = _norm_root(root)
    for p in projects():
        if str(p.get("root") or "") == root_s:
            return p
    item = {"name": (name or "").strip() or Path(root_s).name, "root": root_s, "schedule": []}
    _write_cfg({"projects": projects() + [item], "active": root_s})
    reload()
    return item


def _norm_root(root: str) -> str:
    """把调用方给的路径归一化成与 projects[] 里一致的形态（resolve + 原生分隔符）。"""
    r = str(root or "").strip()
    if not r:
        raise ValueError("项目路径不能为空")
    return str(Path(r).resolve() if os.path.isabs(r) else (BASE / r).resolve())


def switch_project(root: str) -> dict:
    """切换激活项目并刷新全部路径常量（ROOT / 三目录 / AGENTS_DIR / LOG_FILE）。"""
    root_s = _norm_root(root)
    if not any(str(p.get("root") or "") == root_s for p in projects()):
        raise ValueError("项目未登记：" + root_s)
    _write_cfg({"active": root_s})
    reload()
    return active_project()


def remove_project(root: str) -> dict:
    """把项目移出登记 —— 只删配置里的条目，项目目录与其中数据一律不动。"""
    root_s = _norm_root(root)
    left = [p for p in projects() if str(p.get("root") or "") != root_s]
    if len(left) == len(projects()):
        raise ValueError("项目未登记：" + root_s)
    patch = {"projects": left}
    if str(_CFG.get("active") or "") == root_s:
        patch["active"] = str(left[0].get("root")) if left else None
    _write_cfg(patch)
    reload()
    return {"removed": root_s, "left": len(left)}


def settings_info() -> dict:
    """当前生效配置摘要（根目录与三目录状态 / 角色数）。"""
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
        "model": model_info(),
        "projects": projects(),
        "activeProject": active_project(),
        "agentsDir": str(AGENTS_DIR),
        "seedRoles": sum(1 for p in AGENTS_SEED.glob("R*.role.md")),
        "rolesCount": sum(1 for p in AGENTS_DIR.glob("R*.role.md")),
        "envOverride": bool(os.environ.get("OPC_KB_ROOT") or os.environ.get("OPC_CONFIG") or os.environ.get("OPC_PORT")),
    }


def list_dirs(base_path: str = "") -> dict:
    """目录选择器：列出 path 的直接子目录（不含隐藏项），返回 parent 供「上级」导航。
    path 为空 → Windows 盘符列表 / 其他系统根目录。"""
    try:
        if not base_path:
            if os.name == "nt":
                drives = []
                for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    p = Path(d + ":\\")
                    if p.exists():
                        drives.append(p.as_posix())
                return {"ok": True, "path": "", "parent": "", "dirs": drives}
            root = Path("/")
            return {"ok": True, "path": "/", "parent": "",
                    "dirs": sorted(d.name for d in root.iterdir() if d.is_dir())}
        p = Path(base_path).resolve()
        if not p.is_dir():
            return {"ok": False, "msg": "目录不存在或不可读：" + str(p)}
        dirs = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))
        parent = "" if p.parent == p else str(p.parent)
        return {"ok": True, "path": str(p), "parent": parent, "dirs": dirs}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


# ---------- 角色名称 ↔ 工作区目录（web 引用/工作区创建用角色名称；R1/R2 仅为编号 Id） ----------

_ROLE_NAME_RE = re.compile(r"名称\s*[：:]([^｜|\r\n]+)")


def sanitize_dir(name: str) -> str:
    """把角色名称转换为安全目录片段（去非法字符，保留中文/括号）。"""
    bad = set("\\/:*?<>|\"'\t\r\n ")
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
    """当前项目的定时任务（存在 projects[i].schedule —— 不同项目节奏不同）。"""
    s = active_project().get("schedule")
    if isinstance(s, list):
        return s
    s = _CFG.get("schedule")            # 兼容尚未建项目时的旧顶层字段
    return s if isinstance(s, list) else []


def save_schedules(jobs: list) -> None:
    """写回当前项目的定时任务（没有项目时退回顶层字段）。"""
    cur = active_project()
    if not cur:
        _write_cfg({"schedule": jobs or []})
        return
    ps = [dict(p) for p in projects()]
    for p in ps:
        if str(p.get("root") or "") == str(cur.get("root") or ""):
            p["schedule"] = jobs or []
    _write_cfg({"projects": ps})


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
