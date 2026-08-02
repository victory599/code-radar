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
    return f"{days}d"


def _styled_path(path: str) -> Text:
    """弱化目录、突出文件名，让长路径列表更容易逐行扫读。"""
    parent, separator, name = path.rpartition("/")
    styled = Text()
    if separator:
        styled.append(f"{parent}/", style="dim cyan")
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


def _score_bar(score: int, width: int = 6) -> Text:
    """把分数画成短进度条，方便扫一眼相对高低。"""
    # 经验上限：分项封顶约 115，条形按 40 饱和即可区分大部分仓库。
    filled = max(0, min(width, round(score / 40 * width)))
    bar = Text()
    style = _score_style(score)
    bar.append("█" * filled, style=style)
    bar.append("░" * (width - filled), style=_MUTED)
    return bar


def _signal_tags(risk: FileRisk) -> Text:
    """拼彩色信号标签：stale / churn / TODO / no-test。"""
    tags = Text()

    stale = risk.stale_days
    if stale is None:
        tags.append("stale ?", style=_MUTED)
    elif stale >= 180:
        tags.append(f"stale {_fmt_stale(stale)}", style=_HOT)
    elif stale >= 60:
        tags.append(f"stale {_fmt_stale(stale)}", style=_WARN)
    else:
        tags.append(f"stale {_fmt_stale(stale)}", style=_MUTED)

    tags.append("  ")
    if risk.churn >= 8:
        tags.append(f"churn {risk.churn}", style=_HOT)
    elif risk.churn >= 3:
        tags.append(f"churn {risk.churn}", style=_WARN)
    else:
        tags.append(f"churn {risk.churn}", style=_MUTED)

    tags.append("  ")
    if risk.todo_count > 0:
        todo_style = _HOT if risk.spicy_todo_count else _WARN
        label = f"TODO {risk.todo_count}"
        if risk.spicy_todo_count:
            label += f"!{risk.spicy_todo_count}"
        tags.append(label, style=todo_style)
    else:
        tags.append("TODO 0", style=_MUTED)

    if risk.missing_test:
        tags.append("  ")
        tags.append("no-test", style=_DANGER)

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

    for i, risk in enumerate(result.risks, start=1):
        risk_txt = Text()
        risk_txt.append(f"{risk.score:>3} ", style=_score_style(risk.score))
        risk_txt.append_text(_score_bar(risk.score))

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
            "yellow",
            _simple_file_table(
                result.stale_top[:detail_top],
                value_fn=lambda r: _fmt_stale(r.stale_days),
                value_header="天数",
                value_style=_WARN,
            ),
        ),
        _board_panel(
            "热改",
            "dark_orange",
            _simple_file_table(
                result.churn_top[:detail_top],
                value_fn=lambda r: str(r.churn),
                value_header="次数",
                value_style=_HOT,
            ),
        ),
        _board_panel(
            "TODO",
            "magenta",
            _todo_table(result.todos, limit=detail_top),
        ),
        _board_panel(
            "缺测热文件",
            "red",
            _simple_file_table(
                result.missing_test_hot[:detail_top],
                value_fn=lambda r: f"churn {r.churn}",
                value_header="信号",
                value_style=_DANGER,
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
        table.add_row("-", Text("(无)", style=_MUTED))
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

        excerpt = Text()
        kind_style = _HOT if hit.spicy else "magenta"
        excerpt.append(hit.kind, style=f"bold {kind_style}")
        if hit.spicy:
            excerpt.append("!", style=_DANGER)
        excerpt.append("  ", style=_MUTED)
        # 摘录里可能已含 kind 前缀；展示时保留原文，方便对照源码。
        body = hit.text.strip()
        excerpt.append(body, style=_WARN if hit.spicy else "default")
        table.add_row(loc, excerpt)
    return table
