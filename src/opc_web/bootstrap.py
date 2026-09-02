# -*- coding: utf-8 -*-
"""部署自举 v1.10：单根目录模型 —— 自动产生 批阅台/、工作区/、知识库/ 三个文件夹，
工作区按「角色名称」建子文件夹（旧结构一次性迁移后不再保留 决策/运营/营销 等静态分类）。
幂等：已存在的目录/种子文件不重建，可重复运行。"""
import shutil

from . import config

BOOT_LOG = []


def init_agents():
    """项目自己的 agents/：为空时从 agents-seed 复制一份。

    角色阵容跟项目走 —— 一个项目要「内容工厂」，另一个要「投研分析师」，
    两边互不干扰。没有激活项目时 AGENTS_DIR 指向模板库本身，不复制。"""
    if not config.active_project():
        return
    d = config.AGENTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    if any(d.glob("R*.role.md")):
        return
    n = 0
    for p in sorted(config.AGENTS_SEED.glob("R*.role.md")):
        shutil.copy2(p, d / p.name)
        n += 1
    if n:
        BOOT_LOG.append("角色卡初始化：从 agents-seed 复制 %d 张 → %s" % (n, d))


def bootstrap():
    BOOT_LOG.clear()          # 只报本次，不累积历史
    init_agents()
    for d in (config.BATCH_ROOT, config.WORKSPACE_ROOT, config.KB_ROOT):
        d.mkdir(parents=True, exist_ok=True)
    # 角色工作区：按「角色名称」建目录（v1.10）
    try:
        from . import roles as _roles
        for _no, _name in _roles.role_files():
            (config.WORKSPACE_ROOT / config.sanitize_dir(_name)).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    h = chr(10)
    seeds = {
        config.ARCH_REL: "| 编号 | 名称 | 职责 | 目标产出 | 状态 |" + h + "|---|---|---|---|---|" + h + "| R0 | 创始人 | 总决策/批阅 | — | 指挥中 |" + h + "| R1 | 老板助理（枢纽） | 任务派发/调度/回报校验 | 调度指令与闭环 | 指挥中 |" + h + "| R2 | 需求研究员 | 用户原声/需求/假设清单维护 | 研究简报 | 就绪 |" + h + "| R3 | 内容工厂 | 内容稿/选题/话术 | 内容资产 | 就绪 |" + h + "| R4 | 增长运营 | 增长实验/落地页 | 实验简报 | 就绪 |" + h + "| R5 | 用户洞察官 | 用户洞察/真实需求 | 用户画像研究 | 就绪 |" + h + "| R6 | 数据分析官 | 指标看板/复盘数据 | 数据报告 | 就绪 |" + h + "| R7 | 财务与合规 | 定价测算/成本/合规审查 | 合规报告 | 就绪 |" + h + "| R8 | 产品设计师 | 产品设计 + 前端实现编码 | 设计稿/前端代码 | 就绪 |" + h + "| R9 | 技术评估与实现 | 技术路径 + 实现编码 | 技术方案/实现代码 | 就绪 |" + h,
        config.INDEX_REL: "# 知识库索引" + h,
        config.LOG_REL: "## 决策日志" + h,
        config.PIYUETAI_REL: "## 待决" + h + "| 编号 | 待决事项 | 提出者 | 日期 | R0 批阅 |" + h + "|---|---|---|---|---|" + h + h + "## 已批阅归档" + h + "| 编号 | 事项 | 批阅 | 日期 |" + h + "|---|---|---|---|" + h,
    }
    for rel, text in seeds.items():
        p = config.ROOT / rel
        if not p.exists():
            p.write_text(text, encoding="utf-8")
            BOOT_LOG.append("创建 " + rel)
    if not config.LOG_FILE.exists():
        config.LOG_FILE.write_text("## R1 调度日志" + h, encoding="utf-8")
        BOOT_LOG.append("创建 " + config.SCHED_LOG_REL)


if __name__ == "__main__":
    bootstrap()
    for ln in BOOT_LOG:
        print(ln)
