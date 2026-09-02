# -*- coding: utf-8 -*-
"""角色管理（v1.9+）：角色卡由本项目自己维护（agents/，不写入全局 dsh 配置）；
新增角色 agent（自动编号 / 角色卡 / 工作区 / 架构登记）。

v1.9 语义：web 引用与工作区创建一律使用「角色名称」，R1/R2 仅为编号 Id——
工作区目录 = 《工作区/<角色名称>/》（v1.10 三目录模型，无 -输出 后缀）。
"""
import datetime
import re

from . import config

CARD_TPL = """# OPC 角色卡：%(no)s %(name)s
## 身份
- 编号：%(no)s｜名称：%(name)s｜类型：%(type_)s
- 一句话定位：%(position)s
- 上级：R1 枢纽（接受派发、回报确认）

## 职责
%(duties)s

## 不做的事
- 不拍板、不花钱、不发布（总决策在 R0）
- 不越权修改他人职责范围；冲突提交 R1 仲裁、R0 裁决

## 读写权限
- 读：知识库全库（%(kb)s/）；个人作业区《%(ws)s/%(wsname)s/》
- 写：仅《%(ws)s/%(wsname)s/》及其产出/回报文件
- 禁止：修改知识库档案与批阅台（只读）

## 激活触发器
- 派发单出现 %(no)s 行 / R1 注入本卡全文的任务 prompt

## 协议与输出格式
- 任务以文件形式接收（本卡全文 + 【任务】段）
- 工作根目录 = 根目录（用 / 分隔路径）
- 产出先写《%(ws)s/%(wsname)s/<子任务编号>.md》（编号由中枢派发时给定，如 T-001-S1；边做边追加进度）
- 完成后把同名 .meta.json 的 status 改为 完成/部分/阻塞（只改这一个字段）；任务号与角色无需复述

## 当前上下文（最近更新）
- %(today)s：控制台「设置 → 角色创建」创建本角色（编号 %(no)s）
"""


def role_files():
    """列出已有角色 [(no, 名称)]（名称取自角色卡「身份·名称」，web 引用用名称）。"""
    out = []
    for p in sorted(config.AGENTS_DIR.glob("R*.role.md")):
        m = re.match(r"R(\d+)\.role\.md", p.name)
        if not m:
            continue
        no = "R" + m.group(1)
        name = config.role_name(no)
        if name == no:                       # 旧卡无「名称」字段 → 用首行标题兜底
            head = p.read_text(encoding="utf-8").split("\n", 1)[0]
            nm = re.match(r"#\s*OPC 角色卡：R\d+\s+(.+)$", head)
            name = nm.group(1).strip() if nm else no
        out.append((no, name))
    out.sort(key=lambda x: int(x[0][1:]))
    return out


def next_no():
    return "R%d" % (max([int(no[1:]) for no, _ in role_files()] or [0]) + 1)


def _card_name(text: str) -> str:
    """从角色卡文本提取「名称」字段（不依赖落盘，dry 预览也能取）。"""
    m = re.search(r"名称\s*[：:]\s*([^｜|\r\n]+)", text)
    return m.group(1).strip() if m else ""


def role_digest(exclude=("R0", "R1")):
    """角色摘要 [(编号, 名称, 一句话职责)] —— 给任务拆解器认人用。

    只给编号+名称时模型只能靠名字猜（「本周产品动态提纲」该给 R3 内容工厂还是
    R6 数据分析官？），带上首条职责就能判准。整卡 5000+ 字塞进 prompt 只会稀释
    注意力，取「## 职责」段首条即可。默认剔除 R0/R1：派发者不能是被派发对象。"""
    out = []
    for no, name in role_files():
        if no in exclude:
            continue
        p = config.AGENTS_DIR / (no + ".role.md")
        duty = ""
        if p.exists():
            m = re.search(r"##\s*职责[^\n]*\n+\s*-\s*([^\n]+)", p.read_text(encoding="utf-8"))
            if m:
                duty = m.group(1).strip()
        out.append((no, name, duty))
    return out


def role_card(no, name, duty, position, type_="业务"):
    """组装新角色卡（CARD_TPL + 运行时变量）。"""
    today = datetime.date.today().isoformat()
    duties = "\n".join("- " + s.strip() for s in duty.replace(chr(13), "").split("\n") if s.strip())
    kb = str(config.ROOT).replace("\\", "/")
    ws = config.WORKSPACE_REL
    return CARD_TPL % {
        "no": no, "name": name, "today": today,
        "type_": type_, "position": position,
        "duties": duties, "kb": kb, "ws": ws, "wsname": name,
    }


def add_role(name, duty, position, type_="业务", dry=False):
    """新增角色 agent：编号 → 角色卡 → 工作区目录《<角色名称>》→ 角色架构登记。
    dry 只返回预览。角色卡只写本项目 agents/，不写入全局 dsh 配置。"""
    if not config.active_project():
        raise ValueError("还没有激活的项目：请先在「设置 → 项目」新建或选择一个项目，再新增角色")
    no = next_no()
    card = role_card(no, name, duty, position, type_)
    wsname = config.sanitize_dir(name)
    result = {
        "no": no, "name": name, "card": card,
        "cardPath": str(config.AGENTS_DIR / (no + ".role.md")),
        "wsRel": "%s/%s" % (config.WORKSPACE_REL, wsname),
        "sbRoot": (config.wb_root() / wsname).as_posix(),
    }
    if dry:
        return result
    (config.AGENTS_DIR / (no + ".role.md")).write_text(card, encoding="utf-8")
    (config.wb_root() / wsname).mkdir(parents=True, exist_ok=True)
    arch = config.ROOT / config.ARCH_REL
    if arch.exists():
        head = arch.read_text(encoding="utf-8")
        if no not in head:
            lines = head.split("\n")
            at = 0
            for i, ln in enumerate(lines):
                if ln.startswith("| R") and not ln.startswith("| 编号"):
                    at = i + 1
                    break
            lines.insert(at, "| %s | %s | %s | 待激活 | %s |" % (no, name, position, type_))
            arch.write_text("\n".join(lines), encoding="utf-8")
            result["archLine"] = "| %s | %s | %s | 待激活 | %s |" % (no, name, position, type_)
    return result



def remove_role(no: str) -> dict:
    """删除角色 agent：角色卡 + 工作区《名称/》 + 架构登记行。
    安全：R0（创始人）/R1（枢纽）不可删除，其余 R2+ 可删。返回 {no, name, removed, roleLeft}。"""
    no = (no or "").strip().upper()
    if no in ("R0", "R1"):
        raise ValueError("角色 %s（创始人/枢纽）受保护，不可删除" % no)
    p = config.AGENTS_DIR / (no + ".role.md")
    if not p.exists():
        raise ValueError("角色卡 %s 不存在" % no)
    name = config.role_name(no)
    wsname = config.sanitize_dir(name if name != no else no)
    removed = []
    # 1) 角色卡（本项目 agents/）
    p.unlink()
    removed.append(str(p))
    # 3) 工作区《工作区/<名称>/》（v1.10 名称工作区；旧 R?-输出 目录不在本次删除范围内）
    ws = config.wb_root() / wsname
    if ws.exists():
        import shutil
        shutil.rmtree(ws, ignore_errors=True)
        removed.append(str(ws))
    # 4) 知识库《OPC智能体角色架构.md》中的登记行（| R? | …）
    arch = config.ROOT / config.ARCH_REL
    if arch.exists():
        lines = arch.read_text(encoding="utf-8").split("\n")
        keep = [ln for ln in lines if not ln.startswith("| " + no + " |")]
        if len(keep) != len(lines):
            arch.write_text("\n".join(keep), encoding="utf-8")
            removed.append(str(arch) + "（登记行已移除）")
    return {"no": no, "name": name, "removed": removed, "roleLeft": len(role_files())}


def _card_sections(text):
    """把角色卡按 ## 段切成 {段名: [行,...]}。"""
    seg = {}
    cur = None
    for ln in text.split("\n"):
        if ln.startswith("## "):
            cur = ln[3:].strip()
            seg[cur] = []
            continue
        if cur:
            seg[cur].append(ln)
    return seg


def _extract_fields(text):
    """从现角色卡提取 (no, name, type_, position, duties)。"""
    seg = _card_sections(text)
    ident = [ln for ln in seg.get("身份", [])]
    no = name = type_ = ""
    for ln in ident:
        s = ln.strip()
        if s.startswith("- 编号："):
            for part in s[4:].split("｜"):
                k, _, v = part.partition("：")
                if k == "编号": no = v
                elif k == "名称": name = v
                elif k == "类型": type_ = v
        if s.startswith("- 一句话定位："):
            position = s.split("：", 1)[1].strip()
    if "position" not in locals():
        position = "一句话定位"
    duties = "\n".join(ln.strip()[2:].strip() for ln in seg.get("职责", []) if ln.strip().startswith("- "))
    return no or "R?", name, type_, position, duties


def edit_role(no, name=None, duty=None, position=None, type_=None, dry=False):
    """编辑角色卡：缺省字段取自现卡；重生成并覆写角色卡。dry 只返回预览。"""
    p = config.AGENTS_DIR / (no + ".role.md")
    if not p.exists():
        raise ValueError("角色 %s 不存在" % no)
    text = p.read_text(encoding="utf-8")
    c_no, c_name, c_type, c_pos, c_duties = _extract_fields(text)
    name = name or c_name or "未命名"
    type_ = type_ or c_type or "业务"
    position = position or c_pos or "一句话定位"
    duty = duty or c_duties or "待补充职责"
    card = role_card(no, name, duty, position, type_)
    result = {"no": no, "name": name, "card": card, "cardPath": str(p)}
    if dry:
        return result
    p.write_text(card, encoding="utf-8")
    return result


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1:] if len(sys.argv) > 1 else []
    if cmd and cmd[0] == "add":
        kv = {}
        for i in range(1, len(cmd), 2):
            kv[cmd[i].lstrip("-")] = cmd[i + 1] if i + 1 < len(cmd) else ""
        r = add_role(kv.get("name", "新角色"), kv.get("duty", "待补充职责"), kv.get("position", "一句话定位"), kv.get("type", "业务"), dry="--dry" in cmd)
        print("新增角色 %s %s" % (r["no"], r["name"]))
        print("  卡: %s" % r["cardPath"])
        print("  作业区: %s" % r["sbRoot"])
        if r.get("archLine"):
            print("  架构登记: " + r["archLine"])
    else:
        for no, name in role_files():
            print("%s %s" % (no, name))
