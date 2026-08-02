# 支持 ``python -m radar`` 从项目根目录启动 CLI。
"""包入口：把控制权交给 cli.main。"""

from radar.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
