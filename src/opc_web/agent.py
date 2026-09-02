# -*- coding: utf-8 -*-
"""角色派发（delegate）通道：角色卡装配 + subagent 派发规格。

角色定义由本项目自己维护（agents/R?.role.md）；web 引用与工作区一律用「角色名称」，
R1/R2 仅为编号 Id。执行方 = 常驻会话主 agent（R1 助理），向下派活 = DSH subagent。

v1.19 移除 DSH preset 通道：原设计想让「会话选择 preset → 派出的子 agent 自动继承
角色 persona」，但方向反了 —— subagent 继承的是父会话（R1 枢纽）的 preset，不是目标
角色的；且 subagent 工具本身没有指定 preset 的参数。角色 persona 实际一直只靠
agent_prompt() 把角色卡全文注入 prompt 生效，preset 资产从未参与自动派发。
"""
import datetime

from . import config


def agent_prompt(no: str, task_text: str, out_rel: str = "", meta_rel: str = "") -> str:
    """角色卡全文 + 任务 + 工作根 + 产出约定 —— 子 agent 的 persona 就来自这里。

    v1.15：不再要求模型复述「回报人｜任务｜状态」尾行——任务号/角色中枢本来就知道，
    让模型复述已知信息只会带来漏写。模型只写正文，外加回填 meta.json 的 status 一个字段。"""
    card = config.AGENTS_DIR / (no + ".role.md")
    head = card.read_text(encoding="utf-8") if card.exists() else "OPC 角色 %s" % no
    kb = str(config.ROOT).replace("\\", "/")
    tail = ""
    if out_rel:
        tail = ("\n产出文件：%s —— 边做边追加进度，可写多次（有输出即视为存活）。"
                "\n回报请在最终写入时用固定小节（便于 R0 决策）："
                "\n## 结论 —— 一两句话说清结果；"
                "\n## 依据与要点 —— 关键信息 / 依据 / 过程；"
                "\n## 需要 R0 拍板 —— 仅在确有需要 R0 拍板的事项时写这一节，且必须把每个决策点写完整：现状背景 → 可选方案 → 你的建议（不要只写一句“请 R0 拍板”，也不要写“任务含决策信号 / 请 R0 裁决 / 驳回将重新派发”这类流程空话——R0 要读到的是一句话能看懂的具体决策点）；没有需要拍板的事项就整节不写。"
                "\n完成后：把 %s 里的 status 改为 完成 / 部分 / 阻塞（只改这一个字段，其余勿动）。"
                % (out_rel, meta_rel))
    return (head + "\n\n【任务】" + task_text +
            "\n工作根目录：" + kb + "（用 / 分隔路径，知识库唯一权威根）" + tail)


def subtask_spec(no: str, task_text: str, expect: str = "", sub_no: str = "") -> dict:
    """subagent 派发规格：角色 / 注入 prompt / 产出路径。
    主会话 R1 收到后据此调一次 DSH subagent（prompt=spec['prompt']）。

    产出按子任务编号命名（T-001-S1.md），不再是全角色共用的「回报-待落库.md」——
    共用固定名会让同角色的多个任务互相覆盖，且归档正则只认得第一条。"""
    if not sub_no:
        raise ValueError("subtask_spec 需要子任务编号：产出按编号命名，共用固定名会让同角色的多任务互相覆盖")
    d = "%s/%s" % (config.WORKSPACE_REL, config.sanitize_dir(config.role_name(no)))
    out_rel = "%s/%s-report.md" % (d, sub_no)      # 完成回报（人读交付物）
    meta_rel = "%s/%s.meta.json" % (d, sub_no)
    return {
        "role": no,
        "roleName": config.role_name(no),
        "prompt": agent_prompt(no, task_text, out_rel, meta_rel),
        "output": out_rel,
        "meta": meta_rel,
        "expect": expect,
    }


def log_schedule(tag: str, text: str):
    """统一调度日志（追加到《批阅台/调度日志.md》）。"""
    with open(str(config.LOG_FILE), "a", encoding="utf-8") as f:
        f.write("\n\n## 【调度指令】%s %s\n\n%s\n" % (tag, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), text))


