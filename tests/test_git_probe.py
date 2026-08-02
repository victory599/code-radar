# 测试路径忽略规则：第三方与构建产物不进扫描集合。
import unittest

from radar.git_probe import should_ignore_path


class GitProbeIgnoreTests(unittest.TestCase):
    def test_ignores_frontend_third_party_paths_and_bundles(self):
        self.assertTrue(should_ignore_path("web/bower_components/jquery/jquery.js"))
        self.assertTrue(should_ignore_path("assets/jspm_packages/npm/lodash.js"))
        self.assertTrue(
            should_ignore_path(
                "src/main/resources/static/plugin/xndatepicker/moment.js"
            )
        )
        self.assertTrue(
            should_ignore_path(
                "src/main/resources/static/js/vendors.bundle.js"
            )
        )
        self.assertTrue(
            should_ignore_path(
                "src/main/resources/static/js/statistics/chartjs/chartjs.bundle.js"
            )
        )

    def test_ignores_java_and_python_third_party_artifacts(self):
        self.assertTrue(should_ignore_path("libs/guava-sources/com/google/Guava.java"))
        self.assertTrue(should_ignore_path("target/classes/App.class"))
        self.assertTrue(should_ignore_path("third_party/okhttp/OkHttp.java"))
        self.assertTrue(should_ignore_path("vendor_py/site-packages/requests/api.py"))
        self.assertTrue(should_ignore_path("pkg/.eggs/setuptools/pkg.py"))
        self.assertTrue(should_ignore_path("dist_pkg/helper.whl"))

    def test_keeps_business_source_paths(self):
        self.assertFalse(
            should_ignore_path("src/main/java/com/hmatm/okr/services/ObjectiveService.java")
        )
        self.assertFalse(should_ignore_path("radar/todo_scan.py"))
        self.assertFalse(should_ignore_path("src/main/resources/static/js/app.js"))


if __name__ == "__main__":
    unittest.main()
