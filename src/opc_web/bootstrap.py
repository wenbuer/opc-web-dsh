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
    # 角色工作区：按「角色名称」建目录（v1.10）；角色技能共享库 agents/skills/（平铺，卡上登记即装配）
    try:
        from . import roles as _roles
        active = bool(config.active_project())
        for _no, _name in _roles.role_files():
            (config.WORKSPACE_ROOT / config.sanitize_dir(_name)).mkdir(parents=True, exist_ok=True)
        if active:
            (config.AGENTS_DIR / config.SKILLS_REL).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    h = chr(10)
    seeds = {
        config.INDEX_REL: "# 知识库索引" + h,
        config.LOG_REL: "## 决策日志" + h,
        # 批阅台：空骨架 = 工作内容（例行进展）/ 决策裁决（需 R0 拍板）/ 已批阅归档 三区
        config.PIYUETAI_REL: "## 工作内容" + h + h + "## 决策裁决" + h + h + "## 已批阅归档" + h,
    }
    for rel, text in seeds.items():
        p = config.ROOT / rel
        if not p.exists():
            p.write_text(text, encoding="utf-8")
            BOOT_LOG.append("创建 " + rel)
    # 架构表速览：从当前角色卡动态生成（人读；功能权威=角色卡），启动时生成/校验
    try:
        from . import roles as _roles
        _ap = config.ROOT / config.ARCH_REL
        if not _ap.exists():
            _ap.write_text(_roles.build_arch_table(), encoding="utf-8")
            BOOT_LOG.append("创建 " + config.ARCH_REL)
    except Exception:
        pass
    if not config.LOG_FILE.exists():
        config.LOG_FILE.write_text("## R1 调度日志" + h, encoding="utf-8")
        BOOT_LOG.append("创建 " + config.SCHED_LOG_REL)


if __name__ == "__main__":
    bootstrap()
    for ln in BOOT_LOG:
        print(ln)
