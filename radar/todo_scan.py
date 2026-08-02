# TODO 扫描：在源码中查找 TODO/FIXME/HACK/XXX，并挑出更「离谱」的条目。
"""基于正则的轻量注释债务扫描。

不做 AST 解析，因此字符串字面量里的 TODO 也可能被命中——MVP 可接受，
换来的是实现简单、跨语言通用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

# 只把「注释里的债务标记」算进去，避免文档/正则字面量里的 TODO、HACK 等误报。
# 支持 # / // / -- 行注释，以及 *、/* 块注释里的常见写法。
TODO_PATTERN = re.compile(
    r"(?:#|//|--|/\*|\*)\s*(?P<kind>TODO|FIXME|HACK|XXX)\b\s*[:=-]?\s*(?P<body>.*)$",
    re.IGNORECASE,
)

# 命中这些词的 TODO 优先展示（临时方案、口头禅、明显未清理痕迹）。
SPICY_KEYWORDS: Sequence[str] = (
    "临时",
    "删掉",
    "稍后",
    "以后",
    "hack",
    "ugly",
    "workaround",
    "dont commit",
    "don't commit",
    "fixme",
    "shit",
    "fuck",
    "wtf",
)


@dataclass
class TodoHit:
    """单条 TODO 命中。

    Attributes:
        path: 文件相对路径。
        line_no: 1-based 行号。
        kind: TODO/FIXME/HACK/XXX（大写规范化）。
        text: 该行摘录（去首尾空白，截断过长内容）。
        spicy: 是否命中「离谱」关键词。
    """

    path: str
    line_no: int
    kind: str
    text: str
    spicy: bool


def _is_spicy(text: str) -> bool:
    """正文是否包含离谱关键词（大小写不敏感）。"""
    lower = text.lower()
    return any(keyword in lower for keyword in SPICY_KEYWORDS)


def scan_file_todos(repo: Path, rel_path: str, max_line_len: int = 160) -> List[TodoHit]:
    """扫描单个文件中的 TODO 类标记。

    Args:
        repo: 仓库根，用于拼接绝对路径读文件。
        rel_path: 相对路径。
        max_line_len: 摘录最大长度，避免报告被超长行撑爆。

    Returns:
        该文件内的 TodoHit 列表。
    """
    abs_path = repo / rel_path
    hits: List[TodoHit] = []
    try:
        # errors=replace：遇到异常编码不中断整个扫描。
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits

    for idx, line in enumerate(content.splitlines(), start=1):
        match = TODO_PATTERN.search(line)
        if not match:
            continue
        kind = match.group("kind").upper()
        body = match.group("body").strip()
        excerpt = line.strip()
        if len(excerpt) > max_line_len:
            excerpt = excerpt[: max_line_len - 1] + "…"
        hits.append(
            TodoHit(
                path=rel_path,
                line_no=idx,
                kind=kind,
                text=excerpt,
                spicy=_is_spicy(body) or _is_spicy(excerpt),
            )
        )
    return hits


def scan_todos(repo: Path, rel_paths: Iterable[str]) -> List[TodoHit]:
    """批量扫描多个文件的 TODO。"""
    all_hits: List[TodoHit] = []
    for path in rel_paths:
        all_hits.extend(scan_file_todos(repo, path))
    return all_hits


def rank_todo_hits(hits: Sequence[TodoHit]) -> List[TodoHit]:
    """给 TODO 排序：离谱优先，其次同文件条数多的更靠前，再按路径/行号稳定排序。

    同文件条数多，往往意味着这块「欠债堆叠」，比散落单条更值得先看。
    """
    per_file_count: dict = {}
    for hit in hits:
        per_file_count[hit.path] = per_file_count.get(hit.path, 0) + 1

    def sort_key(hit: TodoHit):
        return (
            0 if hit.spicy else 1,
            -per_file_count.get(hit.path, 0),
            hit.path,
            hit.line_no,
        )

    return sorted(hits, key=sort_key)


def todos_by_file(hits: Sequence[TodoHit]) -> dict:
    """按文件聚合 TODO 数量，供风险评分使用。"""
    counts: dict = {}
    spicy_counts: dict = {}
    for hit in hits:
        counts[hit.path] = counts.get(hit.path, 0) + 1
        if hit.spicy:
            spicy_counts[hit.path] = spicy_counts.get(hit.path, 0) + 1
    return {"total": counts, "spicy": spicy_counts}
