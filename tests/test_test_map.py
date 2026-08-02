# 测试「缺测」启发式匹配。
import unittest

from radar.test_map import (
    candidate_test_paths,
    has_matching_test,
    is_test_path,
    missing_tests_for,
)


class TestMapTests(unittest.TestCase):
    def test_python_candidates_include_common_layouts(self):
        cands = candidate_test_paths("pkg/foo.py")
        self.assertIn("pkg/test_foo.py", cands)
        self.assertIn("tests/test_foo.py", cands)
        self.assertIn("pkg/foo_test.py", cands)

    def test_ts_candidates(self):
        cands = candidate_test_paths("src/foo.ts")
        self.assertIn("src/foo.test.ts", cands)
        self.assertIn("src/foo.spec.ts", cands)

    def test_has_matching_test(self):
        tracked = {"src/foo.ts", "src/foo.test.ts", "src/bar.ts"}
        self.assertTrue(has_matching_test("src/foo.ts", tracked))
        self.assertFalse(has_matching_test("src/bar.ts", tracked))

    def test_is_test_path_and_missing(self):
        self.assertTrue(is_test_path("tests/test_foo.py"))
        self.assertTrue(is_test_path("src/foo.test.ts"))
        tracked = {"a.py", "tests/test_a.py", "b.py"}
        missing = missing_tests_for(["a.py", "b.py", "tests/test_a.py"], tracked)
        self.assertEqual(missing, {"b.py"})


if __name__ == "__main__":
    unittest.main()
