# -*- coding: utf-8 -*-
"""v1.8 调度改造自检：headless one-shot 已移除；角色卡三通道（preset / persona / prompt 注入）装配正确。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opc_web import agent, config  # noqa: E402


class TestNoHeadless(unittest.TestCase):
    def test_headless_removed(self):
        self.assertFalse(hasattr(agent, "run_headless"), "agent 模块不应再有 run_headless")
        self.assertFalse(hasattr(agent, "bash_exe"), "agent 模块不应再有 bash_exe")
        self.assertTrue(agent.headless_removed())

    def test_preset_assets_exist(self):
        for n in range(1, 10):
            name = "opc-r%d" % n
            src = agent.PRESET_SRC / name / "preset.yml"
            home = agent.PRESET_HOME / name / "preset.yml"
            self.assertTrue(src.exists() or home.exists(), "%s 的 preset 资产应存在（源或 ~/.dsh/.agent-presets）" % name)
        for n in range(1, 10):
            card = config.AGENTS_DIR / ("R%d.role.md" % n)
            self.assertTrue(card.exists(), "角色卡 R%d.role.md 应存在" % n)


class TestPromptInjection(unittest.TestCase):
    def test_agent_prompt_contains_task_and_tail(self):
        p = agent.agent_prompt("R8", "测试任务：更新 PRD 设计稿")
        self.assertIn("测试任务：更新 PRD 设计稿", p)
        self.assertIn("回报人：R8", p)
        self.assertIn("工作根目录", p)

    def test_agent_prompt_uses_role_card(self):
        p = agent.agent_prompt("R8", "x")
        self.assertIn("产品设计师", p)

    def test_role_preset_mapping(self):
        self.assertEqual(agent.role_preset("R3"), "opc-r3")
        meta = agent.preset_meta("R3")
        self.assertTrue(meta["name"], "preset 名称应非空")
        self.assertIn("内容工厂", meta["name"])


class TestSubtaskSpec(unittest.TestCase):
    def test_spec_shape(self):
        spec = agent.subtask_spec("R2", "挖掘 5 条新用户原声", "期望：原声库增量")
        self.assertEqual(spec["role"], "R2")
        self.assertEqual(spec["preset"], "opc-r2")
        self.assertIn("需求研究员", spec["presetName"])
        self.assertIn("工作区/需求研究员/回报-待落库.md", spec["output"])
        self.assertIn("回报人：R2", spec["reportEnd"])
        self.assertIn("挖掘 5 条新用户原声", spec["prompt"])
        self.assertEqual(spec["workspaceRoot"], str(config.ROOT).replace("\\", "/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
