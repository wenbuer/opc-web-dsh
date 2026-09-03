# -*- coding: utf-8 -*-
"""角色管理自检：角色列表 / 自动编号 / 角色卡组装 / 新增角色(dry) / 项目守卫"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opc_web import config, roles  # noqa: E402


class TestRolesCore(unittest.TestCase):
    def test_role_files_has_r1_to_r9(self):
        nos = [no for no, _ in roles.role_files()]
        self.assertEqual(nos, ["R%d" % i for i in range(1, 8)])

    def test_next_no_is_r10(self):
        self.assertEqual(roles.next_no(), "R8")

    def test_role_card_assembly(self):
        card = roles.role_card("R10", "增长实验官", "跑 AB 实验；输出实验简报", "负责增长实验与复盘", "业务")
        self.assertIn("# OPC 角色卡：R10 增长实验官", card)
        self.assertIn("跑 AB 实验；输出实验简报", card)
        self.assertIn("<子任务编号>.md", card)
        self.assertIn("status 改为 完成/部分/阻塞", card)

    def test_add_role_needs_active_project(self):
        """没有激活项目时必须拒绝 —— 否则角色卡会写进 agents-seed 模板库，污染所有新项目。"""
        if config.active_project():
            self.skipTest("当前已有激活项目")
        with self.assertRaises(ValueError):
            roles.add_role("演示角色", "演示职责", "演示定位", "业务", dry=True)

    def test_add_role_dry_no_side_effect(self):
        """dry 预览不落盘（在临时项目里跑，不碰模板库）。"""
        tmp = Path(__file__).resolve().parent.parent / ".testproj"
        shutil.rmtree(tmp, ignore_errors=True)
        keep = (dict(config._CFG), config.ROOT, config.AGENTS_DIR)
        config._CFG = {"projects": [{"name": "t", "root": str(tmp), "schedule": []}], "active": str(tmp)}
        config.ROOT = tmp
        config.AGENTS_DIR = tmp / "agents"
        config.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        for p in config.AGENTS_SEED.glob("R*.role.md"):
            shutil.copy2(p, config.AGENTS_DIR / p.name)
        try:
            before = len(list(config.AGENTS_DIR.glob("R*.role.md")))
            r = roles.add_role("演示角色", "演示职责", "演示定位", "业务", dry=True)
            self.assertEqual(r["no"], "R8")
            self.assertEqual(before, len(list(config.AGENTS_DIR.glob("R*.role.md"))), "dry 不应落盘角色卡")
        finally:
            config._CFG, config.ROOT, config.AGENTS_DIR = keep
            shutil.rmtree(tmp, ignore_errors=True)


class TestConfigFile(unittest.TestCase):
    def test_defaults_from_opc_config_json(self):
        self.assertEqual(config.PIYUETAI_REL, "批阅台/批阅台.md")
        self.assertEqual(config.WORKSPACE_REL, "工作区")
        self.assertEqual(config.PORT, 8901)
        self.assertTrue(config.KB_ROOT.name == "知识库")
        self.assertEqual((config.ROOT / config.PIYUETAI_REL).name, "批阅台.md")
        self.assertEqual(config.wb_root().name, "工作区")


class TestRoleCardSkills(unittest.TestCase):
    """角色卡「## 技能」段：组装 → 解析 往返（含提示行过滤）。"""

    def test_card_skills_roundtrip(self):
        c = roles.role_card("R10", "演示", "演示职责", "演示定位", "业务", skills=["a-guide.md", "b.md"])
        self.assertEqual(roles.card_skills(c), ["a-guide.md", "b.md"])

    def test_empty_skills_renders_hint_and_parses_empty(self):
        c = roles.role_card("R10", "演示", "演示职责", "演示定位")
        self.assertIn("## 技能", c)
        self.assertEqual(roles.card_skills(c), [])     # 提示行（（ 开头）不算装配项

    def test_extract_fields_keeps_skills(self):
        c = roles.role_card("R10", "演示", "演示职责", "演示定位", "业务", skills=["z.md"])
        no, name, type_, position, duties, skills = roles._extract_fields(c)
        self.assertEqual(skills, ["z.md"])



class TestRemoveRoleGuard(unittest.TestCase):
    """删除角色守卫：进行中/待派子任务、工作区未归档产物 → 拒删。"""

    def _tmp(self):
        tmp = Path(__file__).resolve().parent.parent / ".testrm"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        keep = (dict(config._CFG), config.ROOT, config.AGENTS_DIR,
                config.WORKSPACE_ROOT, config.KB_ROOT, config.BATCH_ROOT)
        config._CFG = {"projects": [{"name": "t", "root": str(tmp), "schedule": []}], "active": str(tmp)}
        config.ROOT = tmp
        config.AGENTS_DIR = tmp / "agents"
        config.WORKSPACE_ROOT = tmp / "工作区"
        config.KB_ROOT = tmp / "知识库"
        config.BATCH_ROOT = tmp / "批阅台"
        config.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        for p in config.AGENTS_SEED.glob("R*.role.md"):
            shutil.copy2(p, config.AGENTS_DIR / p.name)
        return tmp, keep

    def _restore(self, keep, tmp):
        config._CFG, config.ROOT, config.AGENTS_DIR, config.WORKSPACE_ROOT, config.KB_ROOT, config.BATCH_ROOT = keep
        shutil.rmtree(tmp, ignore_errors=True)

    def test_remove_role_denied_when_pending_subtask(self):
        """有进行中/待派子任务 → 拒删（避免删除后派发到幽灵角色）。"""
        from opc_web import store
        tmp, keep = self._tmp()
        try:
            no = store.add_task("待删演示")
            store.replace_subtasks(no, [{"sub": "跑实验", "role": "R2", "expect": "x"}])
            with self.assertRaises(ValueError):
                roles.remove_role("R2")
        finally:
            self._restore(keep, tmp)

    def test_remove_role_denied_when_workfiles_present(self):
        """工作区有未归档产物 → 拒删（防止未入库数据被 rmtree 丢弃）。"""
        tmp, keep = self._tmp()
        try:
            ws = tmp / "工作区" / "需求研究员"
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "T-001-S1.md").write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                roles.remove_role("R2")
        finally:
            self._restore(keep, tmp)

    def test_remove_role_ok_when_clean(self):
        """无待办任务、工作区无未归档产物 → 可正常删除。"""
        tmp, keep = self._tmp()
        try:
            r = roles.remove_role("R2")
            self.assertEqual(r["no"], "R2")
            self.assertFalse((config.AGENTS_DIR / "R2.role.md").exists())
        finally:
            self._restore(keep, tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)