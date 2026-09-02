# -*- coding: utf-8 -*-
"""角色管理自检：角色列表 / 自动编号 / 角色卡组装 / 新增角色(dry)"""
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

    def test_add_role_dry_no_side_effect(self):
        before = len(list(config.AGENTS_DIR.glob("R*.role.md")))
        r = roles.add_role("演示角色", "演示职责", "演示定位", "业务", dry=True)
        self.assertEqual(r["no"], "R10")
        after = len(list(config.AGENTS_DIR.glob("R*.role.md")))
        self.assertEqual(before, after, 'dry 不应落盘角色卡')


class TestConfigFile(unittest.TestCase):
    def test_defaults_from_opc_config_json(self):
        self.assertEqual(config.PIYUETAI_REL, "批阅台/批阅台.md")
        self.assertEqual(config.WORKSPACE_REL, "工作区")
        self.assertEqual(config.PORT, 8901)
        self.assertTrue(config.KB_ROOT.name == "知识库")
        self.assertEqual(config.piyuetai_file().name, "批阅台.md")
        self.assertEqual(config.wb_root().name, "工作区")


if __name__ == "__main__":
    unittest.main(verbosity=2)
