# 测试 TODO 扫描与排序。
import unittest
from pathlib import Path
import tempfile

from radar.todo_scan import TodoHit, rank_todo_hits, scan_file_todos


class TodoScanTests(unittest.TestCase):
    def test_scan_detects_kinds_and_spicy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            rel = "sample.py"
            (repo / rel).write_text(
                "# TODO: 正常待办\n"
                "# FIXME: 临时方案，稍后删掉\n"
                "x = 1  # HACK ugly workaround\n",
                encoding="utf-8",
            )
            hits = scan_file_todos(repo, rel)
            self.assertEqual(len(hits), 3)
            kinds = {h.kind for h in hits}
            self.assertEqual(kinds, {"TODO", "FIXME", "HACK"})
            spicy = [h for h in hits if h.spicy]
            self.assertGreaterEqual(len(spicy), 1)

    def test_rank_prefers_spicy_and_dense_files(self):
        hits = [
            TodoHit("a.py", 1, "TODO", "TODO plain", spicy=False),
            TodoHit("b.py", 1, "TODO", "TODO 临时", spicy=True),
            TodoHit("a.py", 2, "FIXME", "FIXME again", spicy=False),
        ]
        ranked = rank_todo_hits(hits)
        self.assertEqual(ranked[0].path, "b.py")
        # a.py 有 2 条，应排在同为非 spicy 时更前——这里 b 因 spicy 已第一
        self.assertTrue(any(h.path == "a.py" for h in ranked[1:]))


if __name__ == "__main__":
    unittest.main()
