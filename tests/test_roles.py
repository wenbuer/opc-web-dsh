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
        self.assertEqual(nos, ["R%d" % i for i in range(1, 10)])

    def test_next_no_is_r10(self):
        self.assertEqual(roles.next_no(), "R10")

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
            self.assertEqual(r["no"], "R10")
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



if __name__ == "__main__":
    unittest.main(verbosity=2)