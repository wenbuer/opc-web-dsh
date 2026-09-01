# -*- coding: utf-8 -*-
"""核心逻辑自检（纯标准库 unittest，不依赖真实知识库）：
解析器 / 路径白名单 / 队列读写 / 批阅写入 的最小回归。
运行：python -m unittest tests.test_core -v  （在 opc-web/ 下）。
"""
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opc_web import config, knowledge, parsers, review, runner, store  # noqa: E402


class _TmpKB(unittest.TestCase):
    """把 config 根目录 ROOT 临时指向 tmp（三目录随之），用例间互不污染。"""

    def setUp(self):
        # 普通目录而非 tempfile：受限环境（沙箱/CI）下 mkdtemp 的 0700 目录常不可再写
        root = Path(__file__).resolve().parent.parent / (".testroot-%d-%s" % (os.getpid(), id(self)))
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self._root = root
        self._old_roots = (config.ROOT, config.KB_ROOT, config.BATCH_ROOT, config.WORKSPACE_ROOT)
        config.ROOT = root
        config.KB_ROOT = root / "知识库"
        config.BATCH_ROOT = root / "批阅台"
        config.WORKSPACE_ROOT = root / "工作区"

    def tearDown(self):
        config.ROOT, config.KB_ROOT, config.BATCH_ROOT, config.WORKSPACE_ROOT = self._old_roots
        shutil.rmtree(self._root, ignore_errors=True)


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


class TestStore(_TmpKB):
    def test_task_add_and_update(self):
        no = store.add_task("测试任务 A", "R1 判断")
        self.assertEqual(no, "T-001")
        seen = [t for t in store.tasks() if t["no"] == no]
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["status"], "待派")
        store.set_task(no, "已派", "回报样例")
        seen = [t for t in store.tasks() if t["no"] == no][0]
        self.assertEqual(seen["status"], "已派")
        self.assertEqual(seen["report"], "回报样例")
        self.assertEqual(store.add_task("测试任务 B"), "T-002")

    def test_task_text_with_pipe_survives(self):
        """md 表格时代的死法：任务文本含 | 会把整行切错位。"""
        no = store.add_task("A | B | C", "R1 判断")
        self.assertEqual([t for t in store.tasks() if t["no"] == no][0]["task"], "A | B | C")

    def test_subtasks_replace_is_idempotent(self):
        no = store.add_task("拆解任务")
        rows = [{"sub": "子一", "role": "R8", "expect": "稿"},
                {"sub": "子二", "role": "R2", "expect": "简报"}]
        self.assertEqual(store.replace_subtasks(no, rows), [no + "-S1", no + "-S2"])
        store.replace_subtasks(no, rows)                    # 重复拆解不累积
        self.assertEqual(len(store.subtasks(no)), 2)
        store.set_subtask(no + "-S1", "完成")
        self.assertEqual([s["st"] for s in store.subtasks(no)], ["完成", "待派"])

    def test_report_upsert_by_subtask(self):
        store.put_report("T-001-S1", "T-001", "R8", "完成", "标题", "正文\n第二行", "工作区/x.md")
        store.put_report("T-001-S1", "T-001", "R8", "部分", "标题2", "改过的\n多行正文", "工作区/x.md")
        rs = store.reports("T-001")
        self.assertEqual(len(rs), 1)                        # 主键去重，不再跨天重复入库
        self.assertEqual(rs[0]["status"], "部分")
        self.assertIn("\n", rs[0]["body"])                  # 正文全文入库，不再压平截断


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


class TestChildEnv(unittest.TestCase):
    """dsh 子进程必须拿到 .env 里的密钥。

    此前只有「设置→模型接入」保存那一刻会写 os.environ，手改 .env 或重启后
    界面仍显示「已配置 ✓」而 headless 子进程实际拿不到 key。"""

    def test_env_file_reaches_child_process(self):
        old = config.ENV_FILE
        tmp = Path(__file__).resolve().parent.parent / ".envtest"
        tmp.write_text("# comment\nDEMO_KEY_FROM_FILE=abc\nDEMO_OVERRIDE=from-file\n", encoding="utf-8")
        os.environ["DEMO_OVERRIDE"] = "from-process"
        config.ENV_FILE = tmp
        try:
            env = runner._child_env()
            self.assertEqual(env["DEMO_KEY_FROM_FILE"], "abc")        # 文件里的密钥进得了子进程
            self.assertEqual(env["DEMO_OVERRIDE"], "from-process")    # 环境变量优先于文件
        finally:
            config.ENV_FILE = old
            os.environ.pop("DEMO_OVERRIDE", None)
            tmp.unlink(missing_ok=True)


class TestNamedRoles(unittest.TestCase):
    """点名直派只认任务开头；顺口提及 / R2D2 / 2024 R1 都不该触发直派。"""

    OK = {"R2", "R3", "R8", "R9"}

    def test_head_named_single_and_multi(self):
        from opc_web import chain
        self.assertEqual(chain.named_roles("R8开始设计KeepTalk App的前端界面", self.OK), ["R8"])
        self.assertEqual(chain.named_roles("R2 和 R8 一起做落地页", self.OK), ["R2", "R8"])
        self.assertEqual(chain.named_roles("R3、R9 分头推进", self.OK), ["R3", "R9"])

    def test_mention_is_not_a_call(self):
        from opc_web import chain
        self.assertEqual(chain.named_roles("参考 R8 的设计做个 H5", self.OK), [])
        self.assertEqual(chain.named_roles("整理 2024 R1 季度数据", self.OK), [])
        self.assertEqual(chain.named_roles("做一个 R2D2 玩具页面", self.OK), [])
        self.assertEqual(chain.named_roles("R2D2 玩具页面", self.OK), [])

    def test_unknown_or_excluded_role_ignored(self):
        from opc_web import chain
        self.assertEqual(chain.named_roles("R1 帮我拆一下这个任务", self.OK), [])   # R1 是派发者，不在候选
        self.assertEqual(chain.named_roles("R99 干活", self.OK), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
