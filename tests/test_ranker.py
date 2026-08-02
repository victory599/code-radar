# 测试风险分计算与排序。
import unittest

from radar.git_probe import FileHistory
from radar.ranker import CHURN_HOT_THRESHOLD, MISSING_TEST_BONUS, rank_files, score_file


class RankerTests(unittest.TestCase):
    def test_score_components_increase(self):
        # last_commit_ts 设为「很久以前」，确保 stale 分 > 0
        old_ts = 1_000_000_000  # 约 2001 年
        now = 1_700_000_000  # 约 2023 年
        history = FileHistory(path="old.py", last_commit_ts=old_ts, churn=5)
        risk = score_file(
            history,
            todo_count=2,
            spicy_todo_count=1,
            missing_test=True,
            now=now,
        )
        self.assertGreater(risk.components["stale"], 0)
        self.assertGreater(risk.components["churn"], 0)
        self.assertGreater(risk.components["todo"], 0)
        self.assertEqual(risk.components["missing_test"], MISSING_TEST_BONUS)
        self.assertEqual(
            risk.score,
            sum(risk.components.values()),
        )

    def test_missing_test_requires_hot_churn(self):
        history = FileHistory(path="cold.py", last_commit_ts=None, churn=1)
        risk = score_file(history, missing_test=True)
        self.assertFalse(risk.missing_test)
        self.assertEqual(risk.components["missing_test"], 0)

        hot = FileHistory(path="hot.py", last_commit_ts=None, churn=CHURN_HOT_THRESHOLD)
        risk_hot = score_file(hot, missing_test=True)
        self.assertTrue(risk_hot.missing_test)
        self.assertEqual(risk_hot.components["missing_test"], MISSING_TEST_BONUS)

    def test_rank_files_sorts_by_score_desc(self):
        histories = [
            FileHistory("low.py", None, 0),
            FileHistory("high.py", None, 20),
        ]
        ranked = rank_files(
            histories,
            todo_totals={"low.py": 0, "high.py": 0},
            todo_spicy={},
            missing_test_paths=set(),
        )
        self.assertEqual(ranked[0].path, "high.py")
        self.assertGreaterEqual(ranked[0].score, ranked[1].score)


if __name__ == "__main__":
    unittest.main()
