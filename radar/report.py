# 报告输出：Rich 终端危险地图，或 JSON。
"""负责「怎么展示」，不负责采集与打分。

Rich 模式刻意做成「雷达面板」观感：总览一眼扫完，分榜分区着色，
信号用短标签而不是堆砌裸文本。
"""

from __future__ import annotations

import json
import sys
from typing import Callable, Optional, Sequence, TextIO

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from radar.ranker import FileRisk, ScanResult
from radar.todo_scan import TodoHit

# —— 终端色板：青/琥珀为主，高分偏红，避免默认「全红表格」——
_BRAND = "bold cyan"
_MUTED = "dim"
_OK = "green"
_WARN = "yellow"
_HOT = "dark_orange"
_DANGER = "bold red"
_PATH = "bright_white"
_BORDER = "grey37"

# 分榜与危险地图信号标签共用色，建立固定视觉对应。
_SECTION_STALE = "yellow"
_SECTION_CHURN = "dark_orange"
_SECTION_TODO = "magenta"
_SECTION_MISSING = "red"

# 终端不能单独放大某几行字号，用紧凑的块字横幅制造大标题效果。
_RADAR_BANNER = "\n".join(
    (
        "████   ██   ███    ██   ████",
        "█  █  █  █  █  █  █  █  █  █",
        "████  ████  █  █  ████  ████",
        "█ █   █  █  █  █  █  █  █ █ ",
        "█  █  █  █  ███   █  █  █  █",
    )
)


def render_json(result: ScanResult, fp: Optional[TextIO] = None) -> None:
    """把扫描结果以 JSON 写入文件对象（默认 stdout）。"""
    fp = fp or sys.stdout
    json.dump(result.to_dict(), fp, ensure_ascii=False, indent=2)
    fp.write("\n")


def _fmt_stale(days: Optional[int] = None) -> str:
    if days is None:
        return "?"
    return f"{days}天"


def _styled_path(path: str) -> Text:
    """弱化目录层级对比、整体提亮路径，避免被旁侧信号字压过。"""
    parent, separator, name = path.rpartition("/")
    styled = Text()
    if separator:
        styled.append(f"{parent}/", style="bright_cyan")
        styled.append(name, style="bold bright_white")
    else:
        styled.append(path, style="bold bright_white")
    return styled


def _score_style(score: int) -> str:
    """按风险分选色：低分安静，高分醒目。"""
    if score >= 40:
        return _DANGER
    if score >= 20:
        return _HOT
    if score >= 8:
        return _WARN
    return _OK


def _score_bar(score: int, max_score: int, width: int = 6) -> Text:
    """按本榜最高分相对缩放的短进度条，便于同一次扫描内比较高低。"""
    if max_score <= 0 or score <= 0:
        filled = 0
    else:
        filled = max(1, min(width, round(score / max_score * width)))
    bar = Text()
    style = _score_style(score)
    bar.append("█" * filled, style=style)
    bar.append("░" * (width - filled), style=_MUTED)
    return bar


def _signal_tags(risk: FileRisk) -> Text:
    """拼彩色信号标签；色相与分榜标题一致，整体略降亮度以免压过路径。"""
    tags = Text()
    sep = " · "
    # dim + 分区色：保留色相对应，同时让路径成为主视觉。
    stale_style = f"dim {_SECTION_STALE}"
    churn_style = f"dim {_SECTION_CHURN}"
    todo_style = f"dim {_SECTION_TODO}"
    missing_style = f"dim {_SECTION_MISSING}"

    if risk.stale_days is None:
        tags.append("陈旧 ?", style=stale_style)
    else:
        tags.append(f"陈旧 {_fmt_stale(risk.stale_days)}", style=stale_style)

    tags.append(sep, style=_MUTED)
    tags.append(f"热改 {risk.churn}次", style=churn_style)

    tags.append(sep, style=_MUTED)
    label = f"TODO {risk.todo_count}"
    if risk.spicy_todo_count:
        label += f"!{risk.spicy_todo_count}"
    tags.append(label, style=todo_style)

    if risk.missing_test:
        tags.append(sep, style=_MUTED)
        tags.append("缺测", style=missing_style)

    return tags


def _header_panel(result: ScanResult) -> Panel:
    """顶部品牌条：名称 + 仓库路径 + 扫描元信息。"""
    banner = Text(_RADAR_BANNER, style=_BRAND, justify="center")

    title = Text(justify="center")
    title.append("◈  考 古 雷 达", style="bold bright_white")
    title.append("\n")
    title.append("C O D E   R A D A R", style=_BRAND)

    body = Text(justify="center")
    body.append(result.repo, style=_PATH)
    body.append("\n")
    body.append(f"{result.file_count} files", style="cyan")
    body.append(" · ", style=_MUTED)
    body.append(f"{result.since_days}d window", style="cyan")
    body.append(" · ", style=_MUTED)
    body.append(f"top {len(result.risks)}", style="cyan")

    return Panel(
        Group(banner, Text(""), title, Text(""), body),
        box=box.DOUBLE,
        border_style="bright_cyan",
        padding=(1, 2),
    )


def _danger_table(result: ScanResult) -> Table:
    """主危险地图：风险强度 + 完整路径及信号。"""
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        border_style=_BORDER,
        pad_edge=False,
        expand=True,
        leading=1,
    )
    table.add_column("#", justify="right", style=_MUTED, width=3, overflow="fold")
    table.add_column("风险", width=10, no_wrap=True, overflow="fold")
    table.add_column("文件 / 信号", overflow="fold", ratio=1)

    if not result.risks:
        table.add_row("-", "-", "(无源码文件)")
        return table

    # 以本榜最高分为满格，避免固定阈值导致高分区间全部顶满。
    max_score = max(risk.score for risk in result.risks)
    for i, risk in enumerate(result.risks, start=1):
        risk_txt = Text()
        risk_txt.append(f"{risk.score:>3} ", style=_score_style(risk.score))
        risk_txt.append_text(_score_bar(risk.score, max_score=max_score))

        details = _styled_path(risk.path)
        details.append("\n")
        details.append_text(_signal_tags(risk))
        table.add_row(str(i), risk_txt, details)
    return table


def render_rich(result: ScanResult, detail_top: int = 5) -> None:
    """用 Rich 打印总览危险地图与四个分榜。

    Args:
        result: 扫描结果；``result.risks`` 已是危险地图 Top。
        detail_top: 下方分榜各展示几条。
    """
    console = Console()
    console.print()
    console.print(_header_panel(result))
    console.print()
    danger_subtitle = f"TOP {len(result.risks)}" if result.risks else None
    console.print(
        _board_panel(
            "危险地图",
            "red",
            _danger_table(result),
            subtitle=danger_subtitle,
        )
    )
    console.print()

    # 分榜纵向铺满终端，长路径与 TODO 摘录可以完整换行，不做省略。
    boards = (
        _board_panel(
            "陈旧",
            _SECTION_STALE,
            _simple_file_table(
                result.stale_top[:detail_top],
                value_fn=lambda r: _fmt_stale(r.stale_days),
                value_header="天数",
                value_style=_SECTION_STALE,
            ),
        ),
        _board_panel(
            "热改",
            _SECTION_CHURN,
            _simple_file_table(
                result.churn_top[:detail_top],
                value_fn=lambda r: str(r.churn),
                value_header="提交次数",
                value_style=_SECTION_CHURN,
                empty_text=f"近 {result.since_days} 天无源码改动",
            ),
        ),
        _board_panel(
            "TODO",
            _SECTION_TODO,
            _todo_table(result.todos, limit=detail_top),
        ),
        _board_panel(
            "缺测热文件",
            _SECTION_MISSING,
            _simple_file_table(
                result.missing_test_hot[:detail_top],
                value_fn=lambda r: f"热改 {r.churn}次",
                value_header="信号",
                value_style=_SECTION_MISSING,
            ),
        ),
    )
    for board in boards:
        console.print(board)
        console.print()


def _section_heading(
    title: str,
    color: str,
    subtitle: Optional[str] = None,
) -> Text:
    """构造高对比标题条，以粗体、反色和字间距增强视觉层级。"""
    foreground = "black" if color in {"yellow", "dark_orange"} else "white"
    label = f" ◆  {' '.join(title)} "
    if subtitle:
        label += f"· {subtitle} "

    heading = Text(justify="center")
    heading.append("▰▰ ", style=f"bold {color}")
    heading.append(label, style=f"bold {foreground} on {color}")
    heading.append(" ▰▰", style=f"bold {color}")
    return heading


def _board_panel(
    title: str,
    border_style: str,
    table: Table,
    subtitle: Optional[str] = None,
) -> Panel:
    """分榜外框：粗边框内放置独立标题条。"""
    return Panel(
        Group(
            _section_heading(title, border_style, subtitle=subtitle),
            Text(""),
            table,
        ),
        border_style=border_style,
        box=box.HEAVY,
        padding=(0, 1),
    )


def _simple_file_table(
    risks: Sequence[FileRisk],
    value_fn: Callable[[FileRisk], str],
    value_header: str,
    value_style: str = "bold",
    empty_text: str = "(无)",
) -> Table:
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style=_MUTED,
        show_edge=False,
        pad_edge=False,
        expand=True,
        leading=1,
    )
    table.add_column(
        value_header,
        justify="right",
        style=value_style,
        min_width=8,
        overflow="fold",
    )
    table.add_column("文件", overflow="fold", style=_PATH)
    if not risks:
        table.add_row("-", Text(empty_text, style=_MUTED))
        return table
    for risk in risks:
        table.add_row(value_fn(risk), _styled_path(risk.path))
    return table


def _todo_table(todos: Sequence[TodoHit], limit: int) -> Table:
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style=_MUTED,
        show_edge=False,
        pad_edge=False,
        expand=True,
        leading=1,
    )
    table.add_column("位置", overflow="fold", ratio=2)
    table.add_column("摘录", overflow="fold", ratio=3)
    if not todos:
        table.add_row(
            Text("-", style=_MUTED),
            Text("(未发现 TODO/FIXME/HACK/XXX)", style=_MUTED),
        )
        return table
    for hit in todos[:limit]:
        loc = _styled_path(hit.path)
        loc.append(f":{hit.line_no}", style=_MUTED)

        # 摘录整体降亮：色相仍偏 TODO 分区，避免压过左侧路径。
        excerpt = Text()
        excerpt.append(hit.kind, style=f"dim bold {_SECTION_TODO}")
        if hit.spicy:
            excerpt.append("!", style=f"dim {_SECTION_MISSING}")
        excerpt.append("  ", style=_MUTED)
        # 摘录里可能已含 kind 前缀；展示时保留原文，方便对照源码。
        body = hit.text.strip()
        excerpt.append(body, style="dim")
        table.add_row(loc, excerpt)
    return table
