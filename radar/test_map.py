# 测试文件启发式：判断源文件是否「看起来」有对应测试。
"""不解析覆盖率，只按常见命名约定做存在性检查。

这是启发式，会有漏报/误报（例如测试写在别的名字里）；
目标是标出「常改却连约定测试文件都找不到」的高风险点，而不是精确覆盖率。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Set


def is_test_path(rel_path: str) -> bool:
    """路径本身是否已经是测试文件/测试目录下的文件。

    这类文件不再要求「再有一套测试的测试」，缺测标记应跳过。
    """
    path = Path(rel_path)
    parts_lower = {p.lower() for p in path.parts}
    name = path.name.lower()
    stem = path.stem.lower()

    if "tests" in parts_lower or "test" in parts_lower or "__tests__" in parts_lower:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if stem.endswith(".test") or stem.endswith(".spec"):
        return True
    if name.endswith(".test.js") or name.endswith(".test.ts"):
        return True
    if name.endswith(".spec.js") or name.endswith(".spec.ts"):
        return True
    if name.endswith(".test.tsx") or name.endswith(".spec.tsx"):
        return True
    if name.endswith(".test.jsx") or name.endswith(".spec.jsx"):
        return True
    return False


def candidate_test_paths(rel_path: str) -> Set[str]:
    """根据源文件路径生成可能的测试文件相对路径集合。

    约定示例：
    - ``foo.py`` → ``test_foo.py`` / ``tests/test_foo.py`` / ``foo_test.py``
    - ``foo.ts`` → ``foo.test.ts`` / ``foo.spec.ts``
    - 同目录与 ``tests/``、``__tests__/`` 下的变体都会尝试。
    """
    path = Path(rel_path)
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    # 处理 ``foo.tests`` 这类少见 stem 时仍用原始 stem。
    candidates: Set[str] = set()

    def add(p: Path) -> None:
        candidates.add(p.as_posix())

    # Python 风格
    if suffix == ".py":
        add(parent / f"test_{stem}.py")
        add(parent / f"{stem}_test.py")
        add(Path("tests") / f"test_{stem}.py")
        add(Path("test") / f"test_{stem}.py")
        if parent != Path("."):
            add(parent / "tests" / f"test_{stem}.py")
            add(parent.parent / "tests" / f"test_{stem}.py")

    # JS/TS 风格：同目录或 __tests__
    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        add(parent / f"{stem}.test{suffix}")
        add(parent / f"{stem}.spec{suffix}")
        add(parent / "__tests__" / f"{stem}{suffix}")
        add(parent / "__tests__" / f"{stem}.test{suffix}")
        add(Path("tests") / f"{stem}.test{suffix}")
        add(Path("__tests__") / f"{stem}.test{suffix}")

    # 通用：tests 目录下同名文件
    add(Path("tests") / path.name)
    add(Path("test") / path.name)

    return candidates


def has_matching_test(rel_path: str, tracked_files: Set[str]) -> bool:
    """源文件是否在 tracked 集合中存在任一约定测试路径。

    Args:
        rel_path: 源文件相对路径。
        tracked_files: 仓库全部相关文件路径集合（建议含全部 tracked 源码）。

    Returns:
        True 表示找到了至少一个候选测试文件。
    """
    if is_test_path(rel_path):
        return True
    for candidate in candidate_test_paths(rel_path):
        if candidate in tracked_files:
            return True
    return False


def missing_tests_for(
    rel_paths: Iterable[str],
    tracked_files: Set[str],
) -> Set[str]:
    """返回「不是测试文件、且找不到约定测试」的源路径集合。"""
    missing: Set[str] = set()
    for path in rel_paths:
        if is_test_path(path):
            continue
        if not has_matching_test(path, tracked_files):
            missing.add(path)
    return missing


def explain_candidates(rel_path: str) -> Optional[str]:
    """调试用：返回候选测试路径的简短说明（当前报告未直接展示）。"""
    cands = sorted(candidate_test_paths(rel_path))
    if not cands:
        return None
    return ", ".join(cands[:5])
