# 命令行入口：解析参数、编排扫描流水线、输出报告。
"""用户面对的唯一入口。

典型用法（在项目根目录）::

    python -m radar /path/to/repo
    python -m radar . --top 10 --json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, Set

from radar.git_probe import GitError, build_file_histories, ensure_git_repo
from radar.ranker import ScanResult, build_scan_result, rank_files
from radar.report import render_json, render_rich
from radar.test_map import missing_tests_for
from radar.todo_scan import rank_todo_hits, scan_todos, todos_by_file


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="radar",
        description="代码考古雷达：扫描本地 Git 仓库，输出危险地图。",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="要扫描的 Git 仓库路径（默认当前目录）",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="危险地图与各榜单展示的条数（默认 15）",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=90,
        dest="since_days",
        help="热改统计窗口天数（默认 90）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出（便于二次处理）",
    )
    parser.add_argument(
        "--detail-top",
        type=int,
        default=5,
        help="Rich 模式下分榜展示条数（默认 5）",
    )
    return parser


def run_scan(
    repo_path: Path,
    since_days: int = 90,
    top: int = 15,
) -> ScanResult:
    """执行完整扫描并返回结构化结果。

    流水线：确认仓库 → Git 历史 → TODO → 缺测 → 打分 → 榜单。
    """
    root = ensure_git_repo(repo_path)
    histories = build_file_histories(root, since_days=since_days)
    paths = [h.path for h in histories]
    tracked_set: Set[str] = set(paths)

    todo_hits = scan_todos(root, paths)
    todo_hits = rank_todo_hits(todo_hits)
    grouped = todos_by_file(todo_hits)

    missing = missing_tests_for(paths, tracked_set)
    risks = rank_files(
        histories=histories,
        todo_totals=grouped["total"],
        todo_spicy=grouped["spicy"],
        missing_test_paths=missing,
    )

    # 展示用路径尽量相对用户传入目录，更友好。
    display_repo = str(repo_path)
    try:
        display_repo = str(Path(repo_path).resolve())
    except OSError:
        pass

    result: ScanResult = build_scan_result(
        repo=display_repo,
        since_days=since_days,
        risks=risks,
        todos=todo_hits,
        top=max(1, top),
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 主函数。

    Returns:
        进程退出码：0 成功，2 参数/仓库错误，1 其它未捕获错误。
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.top < 1:
        parser.error("--top 必须 >= 1")
    if args.since_days < 1:
        parser.error("--since 必须 >= 1")

    try:
        result = run_scan(
            repo_path=Path(args.path),
            since_days=args.since_days,
            top=args.top,
        )
    except GitError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    if args.json:
        render_json(result)
    else:
        render_rich(result, detail_top=max(1, args.detail_top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
