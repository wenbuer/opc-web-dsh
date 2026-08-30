# -*- coding: utf-8 -*-
"""核心逻辑自检（纯标准库 unittest，不依赖真实知识库）：
解析器 / 路径白名单 / 队列读写 / 批阅写入 的最小回归。
运行：python -m unittest tests.test_core -v  （在 opc-web/ 下）。
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opc_web import config, knowledge, parsers, queue, review  # noqa: E402


class _TmpKB(unittest.TestCase):
    """把 config 根目录 ROOT 临时指向 tmp（三目录随之），用例间互不污染。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._old_roots = (config.ROOT, config.KB_ROOT, config.BATCH_ROOT, config.WORKSPACE_ROOT)
        config.ROOT = root
        config.KB_ROOT = root / "知识库"
        config.BATCH_ROOT = root / "批阅台"
        config.WORKSPACE_ROOT = root / "工作区"

    def tearDown(self):
        config.ROOT, config.KB_ROOT, config.BATCH_ROOT, config.WORKSPACE_ROOT = self._old_roots
        self._tmp.cleanup()


class TestReadMdGuard(_TmpKB):
    def test_escape_denied(self):
        config.BATCH_ROOT.mkdir(parents=True, exist_ok=True)
        (config.BATCH_ROOT / "note.md").write_text("ok", encoding="utf-8")
        with self.assertRaises(ValueError):
            knowledge.read_md("../批阅台/note.md")

    def test_non_md_denied(self):
        config.BATCH_ROOT.mkdir(parents=True, exist_ok=True)
        (config.BATCH_ROOT / "x.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            knowledge.read_md("x.txt")


class TestQueue(_TmpKB):
    def _seed(self, rows):
        config.BATCH_ROOT.mkdir(parents=True, exist_ok=True)
        config.queue_file().write_text(
            "| 编号 | 下达时间 | 任务内容 | 期望执行 | 状态 | 回报 |\n| --- | --- | --- | --- | --- | --- |\n" + "".join(rows),
            encoding="utf-8")

    def test_append_and_update(self):
        self._seed("")
        no = queue.append_queue("测试任务 A", "R1 判断")
        self.assertEqual(no, "T-001")
        seen = [t for t in queue.parse_queue() if t["no"] == no]
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["status"], "待派")
        queue.update_queue(no, "已派", "回报样例")
        seen = [t for t in queue.parse_queue() if t["no"] == no][0]
        self.assertEqual(seen["status"], "已派")
        self.assertEqual(seen["report"], "回报样例")
        no2 = queue.append_queue("测试任务 B")
        self.assertEqual(no2, "T-002")


class TestParsers(_TmpKB):
    def test_parse_piyuetai_pending_vs_archive(self):
        text = (
            "## 一、当前待决清单\n"
            "### 待决 16｜测试待决项\n"
            "- **背景**：内容\n"
            "- **R0 批阅**：待填\n"
            "### 待决 17｜已批阅项\n"
            "- **背景**：内容\n"
            "- **R0 批阅**：✅ 2026-08-27：批准。意见：通过。\n"
            "## 二、已批阅归档\n"
        )
        data = parsers.parse_piyuetai(text)
        self.assertEqual([it["n"] for it in data["pending"]], [16])
        self.assertEqual([it["n"] for it in data["archive"]], [17])

    def test_write_piyue(self):
        config.BATCH_ROOT.mkdir(parents=True, exist_ok=True)
        (config.BATCH_ROOT / "批阅台.md").write_text(
            "## 待决\n| 编号 | 待决事项 | 提出者 | 日期 | R0 批阅 |\n|---|---|---|---|---|\n"
            "### 待决 20｜写批阅测试\n- **R0 批阅**：待填\n", encoding="utf-8")
        line = review.write_piyue("20", "✅", "同意试点")
        self.assertIn("✅", line)
        self.assertIn("同意试点", line)
        text = knowledge.read_md(config.PIYUETAI_REL)
        self.assertNotIn("待填", text)
        self.assertIn("同意试点", text)

    def test_parse_roles_and_dispatch(self):
        config.BATCH_ROOT.mkdir(parents=True, exist_ok=True)
        (config.BATCH_ROOT / "决策日志.md").write_text(
            "## 派发单\n| 角色 | 任务 | 期望产出 | 状态 |\n|---|---|---|---|\n"
            "| R3 内容工厂 | 选题 3 篇（暂不激活的除外） | 《营销/选题库.md》 | 执行中 |\n", encoding="utf-8")
        config.KB_ROOT.mkdir(parents=True, exist_ok=True)
        (config.KB_ROOT / "OPC智能体角色架构.md").write_text(
            "| 编号 | 名称 | 职责 | 目标产出 | 状态 |\n|---|---|---|---|---|\n"
            "| R4 | 增长运营 | 投放执行 | 投放周报 | 暂不激活 |\n\n"
            "### R4 增长运营\n- **职责**：投放执行、数据监控、私域运维\n", encoding="utf-8")
        roles = parsers.parse_roles()
        r4 = [r for r in roles if r["code"] == "R4"][0]
        self.assertEqual(r4["name"], "增长运营")
        self.assertIn("投放执行", r4["desc"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
