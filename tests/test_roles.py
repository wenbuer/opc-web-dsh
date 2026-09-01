# -*- coding: utf-8 -*-
"""角色管理自检：角色列表/自动编号/角色卡组装/persona 提取/preset 资产/新增角色(dry)"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opc_web import agent, config, roles  # noqa: E402


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

    def test_extract_persona(self):
        card = roles.role_card("R10", "增长实验官", "跑实验", "定位", "业务")
        p = roles.extract_persona(card, "R10")
        self.assertIn("你是 OPC", p)
        self.assertIn("工作纪律", p)
        self.assertIn("工作区/增长实验官/<子任务编号>.md", p)
        self.assertIn(".meta.json", p)

    def test_preset_files(self):
        p = roles.preset_files("R10", "增长实验官", "persona 正文\n回报人：R10｜任务：T-xxx｜状态：完成")
        self.assertIn("name: OPC 增长实验官", p["preset.yml"])
        self.assertIn("order: 10", p["preset.yml"])
        self.assertIn("@deepseek-ai/dsh-persona", p["agent.cordis.yml"])
        self.assertIn("persona 正文", p["agent.cordis.yml"])

    def test_generate_all_idempotent(self):
        # 部署目标指向临时目录：测试不该往用户真实的 ~/.dsh/.agent-presets 写
        old_home = agent.PRESET_HOME
        tmp = Path(__file__).resolve().parent.parent / ".testpresets"
        shutil.rmtree(tmp, ignore_errors=True)
        agent.PRESET_HOME = tmp
        try:
            r = roles.generate_all(force=True)
            self.assertGreater(r["count"], 0)
            self.assertIn("R1", r["roles"])
            self.assertTrue((agent.PRESET_SRC / "opc-r1" / "preset.yml").exists())
            self.assertTrue((tmp / "opc-r1" / "preset.yml").exists())
        finally:
            agent.PRESET_HOME = old_home
            shutil.rmtree(tmp, ignore_errors=True)

    def test_add_role_dry_no_side_effect(self):
        before = len(list(config.AGENTS_DIR.glob("R*.role.md")))
        r = roles.add_role("演示角色", "演示职责", "演示定位", "业务", dry=True)
        self.assertEqual(r["no"], "R10")
        self.assertIn("preset", r)
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
