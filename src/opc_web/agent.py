# -*- coding: utf-8 -*-
"""角色派发（delegate）通道：角色卡三通道加载 + subagent 派发规格。

v1.9：角色卡定义由本项目自己维护（agents/，不写入全局 dsh 配置）；
web 引用与工作区创建一律用「角色名称」，R1/R2 仅为编号 Id——
产出目标 = 《工作区/<角色名称>/回报-待落库.md》（v1.10 三目录模型）。
v1.8：headless one-shot（dsh --profile headless）已从调度链路移除——不再由控制台进程 spawn headless。
新的执行方 = 常驻会话主 agent（R1 助理）；向下派活 = DSH subagent 体系。
角色卡三通道加载（必须影响 dsh 本身）：
  1) agent-preset（DSH 正规载体）：~/.dsh/.agent-presets/opc-r?/ —— 会话选择后自动继承给其派出的所有子 agent；
  2) persona（工具配置）：会话/子 agent 的 system persona（可手工或程序注入角色核心）；
  3) prompt 注入（兜底/直达）：本模块 agent_prompt() 把角色卡全文注入任务 prompt。
"""
import datetime
import os
from pathlib import Path

from . import config

# 角色 preset 资产：源（随项目分发）与 DSH 用户级预设根（部署目标/生效处）
PRESET_SRC = config.BASE / "agents" / "presets-src"
PRESET_HOME = Path(os.environ.get("OPC_PRESET_HOME") or Path.home() / ".dsh" / ".agent-presets")


def role_preset(no: str) -> str:
    """角色编号 → DSH preset 名（opc-r?）。"""
    return "opc-" + no.lower()


def preset_meta(no: str) -> dict:
    """读取角色 preset 元数据 {name, description}（源或已部署处，谁存在取谁）。"""
    cands = [PRESET_SRC / role_preset(no) / "preset.yml", PRESET_HOME / role_preset(no) / "preset.yml"]
    for p in cands:
        if p.exists():
            meta = {"name": "", "description": ""}
            for ln in p.read_text(encoding="utf-8").split("\n"):
                if ln.startswith("name:"):
                    meta["name"] = ln.split(":", 1)[1].strip()
                elif ln.startswith("description:"):
                    meta["description"] = ln.split(":", 1)[1].strip()
            return meta
    return {"name": role_preset(no), "description": ""}


def agent_prompt(no: str, task_text: str) -> str:
    """prompt 注入通道（第三通道）：角色卡全文 + 任务 + 工作根 + 回报尾行。"""
    card = config.AGENTS_DIR / (no + ".role.md")
    head = card.read_text(encoding="utf-8") if card.exists() else "OPC 角色 %s" % no
    kb = str(config.ROOT).replace("\\", "/")
    return head + "\n\n【任务】" + task_text + "\n工作根目录：" + kb + "（用 / 分隔路径，知识库唯一权威根）\n回报尾部固定行：回报人：" + no + "｜任务：T-xxx｜状态：完成/部分/阻塞"


def subtask_spec(no: str, task_text: str, expect: str = "") -> dict:
    """subagent 派发规格：角色 / preset / 注入 prompt / 产出路径 / 回报格式。
    主会话 R1 收到后可直接据此调 DSH subagent（prompt=spec['prompt']，desc 含 preset 名）。"""
    return {
        "role": no,
        "preset": role_preset(no),
        "presetName": preset_meta(no)["name"],
        "prompt": agent_prompt(no, task_text),
        "workspaceRoot": str(config.ROOT).replace("\\", "/"),
        "output": "%s/%s/回报-待落库.md" % (config.WORKSPACE_REL, config.role_ws_dir(no)),
        "outputLegacy": "%s/（v1.10 无旧后缀目录，产出固定《工作区/<角色名称>/回报-待落库.md》）" % config.WORKSPACE_REL,
        "reportEnd": "回报人：%s｜任务：T-xxx｜状态：完成/部分/阻塞" % no,
        "expect": expect,
        "discipline": "《知识库/》档案与《批阅台/》公文只读不写；产出先落《%s/<角色名称>/回报-待落库.md》（角色名称，如 需求研究员）再由 R1 归档。" % config.WORKSPACE_REL,
    }


def log_schedule(tag: str, text: str):
    """统一调度日志（追加到 opc-web/运营-调度日志.md）。"""
    with open(str(config.LOG_FILE), "a", encoding="utf-8") as f:
        f.write("\n\n## 【调度指令】%s %s\n\n%s\n" % (tag, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), text))


def headless_removed() -> bool:
    """v1.8 标记：本版本无 headless one-shot 通道（供文档/测试断言）。"""
    return True
