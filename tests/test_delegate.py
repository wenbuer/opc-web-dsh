# -*- coding: utf-8 -*-
"""调度自检：headless one-shot 已移除；角色卡经 prompt 注入装配正确（preset 通道已于 v1.19 删除）。"""
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

    def test_preset_channel_is_gone(self):
        """preset 通道已移除：subagent 工具无 preset 参数，继承方向也反了，留着只会误导。"""
        for gone in ("PRESET_SRC", "PRESET_HOME", "role_preset", "preset_meta"):
            self.assertFalse(hasattr(agent, gone), "agent 不应再有 %s" % gone)

    def test_role_cards_exist(self):
        for n in range(1, 10):
            card = config.AGENTS_DIR / ("R%d.role.md" % n)
            self.assertTrue(card.exists(), "角色卡 R%d.role.md 应存在" % n)


class TestPromptInjection(unittest.TestCase):
    def test_agent_prompt_contains_task_and_tail(self):
        p = agent.agent_prompt("R8", "测试任务：更新 PRD 设计稿",
                               "工作区/产品设计师/T-001-S1.md", "工作区/产品设计师/T-001-S1.meta.json")
        self.assertIn("测试任务：更新 PRD 设计稿", p)
        self.assertIn("T-001-S1.md", p)
        self.assertIn("status 改为", p)
        self.assertIn("工作根目录", p)

    def test_agent_prompt_uses_role_card(self):
        p = agent.agent_prompt("R8", "x")
        self.assertIn("产品设计师", p)


class TestSubtaskSpec(unittest.TestCase):
    def test_spec_shape(self):
        spec = agent.subtask_spec("R2", "挖掘 5 条新用户原声", "期望：原声库增量", sub_no="T-007-S1")
        self.assertEqual(spec["role"], "R2")
        self.assertEqual(spec["roleName"], "需求研究员")
        self.assertNotIn("preset", spec)
        self.assertEqual(spec["output"], "工作区/需求研究员/T-007-S1.md")
        self.assertEqual(spec["meta"], "工作区/需求研究员/T-007-S1.meta.json")
        self.assertIn("挖掘 5 条新用户原声", spec["prompt"])
        self.assertEqual(spec["workspaceRoot"], str(config.ROOT).replace("\\", "/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
