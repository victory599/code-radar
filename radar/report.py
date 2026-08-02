# 报告输出：Rich 终端危险地图，或 JSON。
"""负责「怎么展示」，不负责采集与打分。"""

from __future__ import annotations

import json
import sys
from typing import Callable, Optional, Sequence, TextIO

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from radar.ranker import FileRisk, ScanResult
from radar.todo_scan import TodoHit


def render_json(result: ScanResult, fp: Optional[TextIO] = None) -> None:
    """把扫描结果以 JSON 写入文件对象（默认 stdout）。"""
    fp = fp or sys.stdout
    json.dump(result.to_dict(), fp, ensure_ascii=False, indent=2)
    fp.write("\n")


def _fmt_stale(days: Optional[int] = None) -> str:
    if days is None:
        return "?"
    return f"{days}d"


def _risk_row_label(risk: FileRisk) -> str:
    """拼一行紧凑标签：stale / churn / TODO / no-test。"""
    parts = [
        f"stale {_fmt_stale(risk.stale_days)}",
        f"churn {risk.churn}",
        f"TODO {risk.todo_count}",
    ]
    if risk.missing_test:
        parts.append("no-test")
    return "  ".join(parts)


def render_rich(result: ScanResult, detail_top: int = 5) -> None:
    """用 Rich 打印总览危险地图与四个分榜。

    Args:
        result: 扫描结果；``result.risks`` 已是危险地图 Top。
        detail_top: 下方分榜各展示几条。
    """
    console = Console()
    header = Text()
    header.append("考古雷达  ", style="bold cyan")
    header.append(result.repo, style="bold")
    header.append(f"          files={result.file_count}  window={result.since_days}d")

    map_title = (
        "危险地图"
        if not result.risks
        else f"危险地图 (Top {len(result.risks)})"
    )
    danger = Table(title=map_title, show_header=True, header_style="bold")
    danger.add_column("分", justify="right", style="red", width=4)
    danger.add_column("文件", overflow="fold")
    danger.add_column("信号", overflow="fold")

    if not result.risks:
        danger.add_row("-", "(无源码文件)", "-")
    else:
        for risk in result.risks:
            danger.add_row(str(risk.score), risk.path, _risk_row_label(risk))

    stale_tbl = _simple_file_table(
        "陈旧 Top",
        result.stale_top[:detail_top],
        value_fn=lambda r: _fmt_stale(r.stale_days),
        value_header="天数",
    )
    churn_tbl = _simple_file_table(
        "热改 Top",
        result.churn_top[:detail_top],
        value_fn=lambda r: str(r.churn),
        value_header="次数",
    )
    missing_tbl = _simple_file_table(
        "缺测热文件",
        result.missing_test_hot[:detail_top],
        value_fn=lambda r: f"churn {r.churn}",
        value_header="信号",
    )
    todo_tbl = _todo_table(result.todos, limit=detail_top)

    console.print(Panel(header, expand=False))
    console.print(danger)
    console.print()
    console.print(Group(stale_tbl, churn_tbl, todo_tbl, missing_tbl))


def _simple_file_table(
    title: str,
    risks: Sequence[FileRisk],
    value_fn: Callable[[FileRisk], str],
    value_header: str,
) -> Table:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column(value_header, justify="right", width=8)
    table.add_column("文件", overflow="fold")
    if not risks:
        table.add_row("-", "(无)")
        return table
    for risk in risks:
        table.add_row(value_fn(risk), risk.path)
    return table


def _todo_table(todos: Sequence[TodoHit], limit: int) -> Table:
    table = Table(title="TODO 精选", show_header=True, header_style="bold")
    table.add_column("位置", overflow="fold")
    table.add_column("摘录", overflow="fold")
    if not todos:
        table.add_row("-", "(未发现 TODO/FIXME/HACK/XXX)")
        return table
    for hit in todos[:limit]:
        # 离谱条目加前缀，避免依赖 emoji 字体。
        mark = "[!] " if hit.spicy else ""
        loc = f"{hit.path}:{hit.line_no}"
        table.add_row(loc, f"{mark}{hit.text}")
    return table
