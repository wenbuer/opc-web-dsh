# -*- coding: utf-8 -*-
"""部署自举 v1.10：单根目录模型 —— 自动产生 批阅台/、工作区/、知识库/ 三个文件夹，
工作区按「角色名称」建子文件夹（旧结构一次性迁移后不再保留 决策/运营/营销 等静态分类）。
幂等：已存在的目录/种子文件不重建，可重复运行。"""
import datetime
import re
import shutil

from . import config, store

BOOT_LOG = []


def _migrate_legacy():
    """一次性迁移 v1.9 旧结构（BASE/knowledge 下 决策/运营/工作区…）→ v1.10 三目录模型。
    幂等：目标 知识库/OPC智能体角色架构.md 已存在则跳过。"""
    old = config.BASE / "knowledge"
    if not old.is_dir():
        return
    if (config.KB_ROOT / "OPC智能体角色架构.md").exists():
        return
    for d in (config.BATCH_ROOT, config.WORKSPACE_ROOT, config.KB_ROOT):
        d.mkdir(parents=True, exist_ok=True)
    # 1) 知识库档案（根目录 md）→ 知识库/
    for p in sorted(old.glob("*.md")):
        try:
            (config.KB_ROOT / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            BOOT_LOG.append("迁移 知识档案 " + p.name + " → 知识库/")
        except Exception:
            pass
    # 2) 决策/运营 等公文 → 批阅台/
    for sub in ("决策", "运营", "行政", "管理"):
        sd = old / sub
        if sd.is_dir():
            for p in sorted(sd.glob("*.md")):
                try:
                    (config.BATCH_ROOT / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                    BOOT_LOG.append("迁移 " + sub + "/" + p.name + " → 批阅台/")
                except Exception:
                    pass
    # 3) 其余分类（营销/需求/证据/战略/验证/财务/技术）md → 知识库/ 平铺
    for sub in ("营销", "需求", "证据", "战略", "验证", "财务", "技术"):
        sd = old / sub
        if sd.is_dir():
            for p in sorted(sd.glob("*.md")):
                try:
                    (config.KB_ROOT / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                    BOOT_LOG.append("迁移 " + sub + "/" + p.name + " → 知识库/")
                except Exception:
                    pass
    # 4) 工作区角色输出 → 工作区/<角色名称>/（去 -输出 后缀、按角色名归位）
    ow = old / "工作区"
    if ow.is_dir():
        for d in sorted(ow.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            if name.endswith("-输出"):
                base_n = name[:-3]
                m = re.match(r"^(R\d+)$", base_n)
                if m:
                    name = config.role_name(m.group(1))
                else:
                    name = base_n
            if not name or name in (".", ".."):
                continue
            target = config.WORKSPACE_ROOT / name
            try:
                if target.exists():
                    for f in d.iterdir():
                        if f.is_file():
                            shutil.copy2(f, target / f.name)
                else:
                    shutil.move(str(d), str(target))
                BOOT_LOG.append("迁移 工作区/" + d.name + " → 工作区/" + name)
            except Exception:
                pass
    # 5) 旧调度日志 → 批阅台/调度日志.md
    lg = config.BASE / "运营-调度日志.md"
    if lg.exists():
        try:
            (config.BATCH_ROOT / "调度日志.md").write_text(lg.read_text(encoding="utf-8"), encoding="utf-8")
            BOOT_LOG.append("迁移 运营-调度日志.md → 批阅台/调度日志.md")
        except Exception:
            pass
    try:
        import shutil as _sh
        _sh.rmtree(old)
        BOOT_LOG.append("已移除旧结构 knowledge/ 目录（内容已并入三目录）")
    except Exception as e:
        BOOT_LOG.append("旧结构 knowledge/ 保留（%s）" % e)
    BOOT_LOG.append("旧结构迁移完成 → 三目录模型（批阅台/工作区/知识库）")


def bootstrap():
    _migrate_legacy()
    for ln in store.migrate_md_tables():      # 退役 md 表格 → SQLite 台账（一次性、幂等）
        BOOT_LOG.append("台账迁移：" + ln)
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
