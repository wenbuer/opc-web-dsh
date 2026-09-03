# -*- coding: utf-8 -*-
"""调度自检：headless one-shot 已移除；角色卡经 prompt 注入装配正确（preset 通道已于 v1.19 删除）。
技能装配：共享库 agents/skills/ + 角色卡「## 技能」段登记。"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opc_web import agent, config  # noqa: E402


class TestNoHeadless(unittest.TestCase):
    def test_no_headless_channel(self):
        self.assertFalse(hasattr(agent, "run_headless"), "agent 模块不应再有 run_headless")
        self.assertFalse(hasattr(agent, "bash_exe"), "agent 模块不应再有 bash_exe")

    def test_preset_channel_is_gone(self):
        """preset 通道已移除：subagent 工具无 preset 参数，继承方向也反了，留着只会误导。"""
        for gone in ("PRESET_SRC", "PRESET_HOME", "role_preset", "preset_meta"):
            self.assertFalse(hasattr(agent, gone), "agent 不应再有 %s" % gone)

    def test_role_cards_exist(self):
        for n in range(1, 8):
            card = config.AGENTS_DIR / ("R%d.role.md" % n)
            self.assertTrue(card.exists(), "角色卡 R%d.role.md 应存在" % n)


class TestPromptInjection(unittest.TestCase):
    def test_agent_prompt_contains_task_and_tail(self):
        p = agent.agent_prompt("R6", "测试任务：更新 PRD 设计稿",
                               "工作区/产品设计师/T-001-S1.md", "工作区/产品设计师/T-001-S1.meta.json")
        self.assertIn("测试任务：更新 PRD 设计稿", p)
        self.assertIn("T-001-S1.md", p)
        self.assertIn("status 改为", p)
        self.assertIn("工作根目录", p)

    def test_agent_prompt_uses_role_card(self):
        p = agent.agent_prompt("R6", "x")
        self.assertIn("产品设计师", p)


class TestSubtaskSpec(unittest.TestCase):
    def test_spec_shape(self):
        spec = agent.subtask_spec("R2", "挖掘 5 条新用户原声", "期望：原声库增量", sub_no="T-007-S1")
        self.assertEqual(spec["role"], "R2")
        self.assertEqual(spec["roleName"], "需求研究员")
        self.assertNotIn("preset", spec)
        self.assertEqual(spec["output"], "工作区/需求研究员/T-007-S1-report.md")
        self.assertEqual(spec["meta"], "工作区/需求研究员/T-007-S1.meta.json")
        self.assertIn("挖掘 5 条新用户原声", spec["prompt"])


class TestRoleSkills(unittest.TestCase):
    """C 路线技能装配：技能 md 平铺共享在 agents/skills/，角色卡「## 技能」段登记即装配。"""

    def _env(self, suffix):
        from pathlib import Path
        import shutil
        tmp = Path(__file__).resolve().parent.parent / (".skilltest-" + suffix)
        shutil.rmtree(tmp, ignore_errors=True)
        agents = tmp / "agents"
        (agents / "skills").mkdir(parents=True)
        old = config.AGENTS_DIR
        config.AGENTS_DIR = agents
        return tmp, agents, old

    def test_skills_from_shared_library_by_card_list(self):
        tmp, agents, old = self._env("shared")
        try:
            # 共享技能库：平铺，多角色可复用
            (agents / "skills" / "design-guide.md").write_text("## 设计规范\n- 主色用品牌蓝 #2563EB", encoding="utf-8")
            (agents / "skills" / "copy-guide.md").write_text("只属于内容岗的文案技能", encoding="utf-8")
            (agents / "R6.role.md").write_text(
                "# OPC 角色卡：R6 产品设计师\n\n## 职责\n- 设计\n\n## 技能\n- design-guide.md", encoding="utf-8")
            (agents / "R3.role.md").write_text(
                "# OPC 角色卡：R3 内容工厂\n\n## 职责\n- 内容\n\n## 技能\n- copy-guide.md", encoding="utf-8")
            p = agent.agent_prompt("R6", "做一版首页", "工作区/产品设计师/T-1-S1.md", "工作区/产品设计师/T-1-S1.meta.json")
            self.assertIn("【装配技能】", p)
            self.assertIn("设计规范", p)
            self.assertNotIn("只属于内容岗", p)       # 卡上没登记就不装
            p2 = agent.agent_prompt("R3", "写一条推文")  # R3 装自己的
            self.assertIn("只属于内容岗", p2)
            self.assertNotIn("品牌蓝", p2)
        finally:
            config.AGENTS_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_skill_file_and_empty_card_are_noops(self):
        tmp, agents, old = self._env("empty")
        try:
            (agents / "R2.role.md").write_text("# OPC 角色卡：R2\n\n## 职责\n- 调研", encoding="utf-8")   # 无技能段
            (agents / "R3.role.md").write_text(
                "# OPC 角色卡：R3\n\n## 职责\n- 内容\n\n## 技能\n- 不存在.md\n- （未装配提示行不算）", encoding="utf-8")
            self.assertNotIn("【装配技能】", agent.agent_prompt("R2", "普通任务"))
            p3 = agent.agent_prompt("R3", "普通任务")   # 登记了但库文件不存在 / 提示行 → 不注入
            self.assertNotIn("【装配技能】", p3)
        finally:
            config.AGENTS_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)



if __name__ == "__main__":
    unittest.main(verbosity=2)