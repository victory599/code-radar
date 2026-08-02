# 测试 Rich 报告在窄终端中完整换行，不截断内容。
import io
import unittest

from rich.console import Console

from radar.ranker import FileRisk, ScanResult
from radar.report import (
    _danger_table,
    _score_bar,
    _signal_tags,
    _simple_file_table,
    _todo_table,
)
from radar.todo_scan import TodoHit


class ReportTests(unittest.TestCase):
    def _render(self, renderable, width=48):
        output = io.StringIO()
        console = Console(
            file=output,
            width=width,
            color_system=None,
            force_terminal=False,
        )
        console.print(renderable)
        return output.getvalue()

    def test_danger_map_wraps_complete_path_without_ellipsis(self):
        path = "src/very/deep/directory/complete_module_name.py"
        risk = FileRisk(
            path=path,
            score=28,
            stale_days=120,
            churn=6,
            todo_count=2,
            spicy_todo_count=1,
            missing_test=True,
        )
        result = ScanResult(
            repo="repo",
            file_count=1,
            since_days=90,
            risks=[risk],
            todos=[],
            stale_top=[],
            churn_top=[],
            missing_test_hot=[],
        )

        table = _danger_table(result)
        rendered = self._render(table)
        details = next(iter(table.columns[2].cells))

        self.assertNotIn("…", rendered)
        self.assertEqual(table.columns[2].overflow, "fold")
        self.assertIn(path, details.plain)
        self.assertIn("name.py", rendered)

    def test_todo_table_wraps_complete_excerpt_without_ellipsis(self):
        path = "src/very/deep/directory/complete_module_name.py"
        excerpt = "这是一个很长的待办摘录用于确认换行后内容依然完整保留END"
        hit = TodoHit(path, 123, "TODO", excerpt, spicy=False)

        table = _todo_table([hit], limit=1)
        rendered = self._render(table)
        location = next(iter(table.columns[0].cells))
        body = next(iter(table.columns[1].cells))

        self.assertNotIn("…", rendered)
        self.assertEqual(table.columns[0].overflow, "fold")
        self.assertEqual(table.columns[1].overflow, "fold")
        self.assertEqual(location.plain, f"{path}:123")
        self.assertIn(excerpt, body.plain)

    def test_empty_churn_table_explains_the_active_window(self):
        table = _simple_file_table(
            [],
            value_fn=lambda risk: str(risk.churn),
            value_header="提交次数",
            empty_text="近 90 天无源码改动",
        )

        rendered = self._render(table)

        self.assertIn("提交次数", rendered)
        self.assertIn("近 90 天无源码改动", rendered)

    def test_score_bar_scales_against_current_map_max(self):
        high = _score_bar(60, max_score=60, width=6)
        mid = _score_bar(30, max_score=60, width=6)
        low = _score_bar(10, max_score=60, width=6)

        self.assertEqual(high.plain, "██████")
        self.assertEqual(mid.plain, "███░░░")
        self.assertEqual(low.plain, "█░░░░░")

    def test_signal_tags_use_chinese_labels(self):
        risk = FileRisk(
            path="src/app.py",
            score=30,
            stale_days=1810,
            churn=0,
            todo_count=54,
            spicy_todo_count=2,
            missing_test=True,
        )

        styled = _signal_tags(risk)

        self.assertEqual(styled.plain, "陈旧 1810天 · 热改 0次 · TODO 54!2 · 缺测")
        styles = {str(span.style) for span in styled.spans}
        self.assertTrue(any("yellow" in s for s in styles))
        self.assertTrue(any("dark_orange" in s for s in styles))
        self.assertTrue(any("magenta" in s for s in styles))
        self.assertTrue(any("red" in s for s in styles))
        self.assertTrue(any(s.startswith("dim ") for s in styles))


if __name__ == "__main__":
    unittest.main()
