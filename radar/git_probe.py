# Git 探针：确认仓库、列出源码文件、批量统计陈旧度与热改次数。
"""通过调用本机 ``git`` 命令采集文件级历史信号。

性能要点：热改与陈旧都尽量「一次 git log 流式解析」，
避免对每个文件单独 ``git log -1``（大仓库会极慢）。
"""

from __future__ import annotations

import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

# 只分析常见源码后缀，跳过资源/二进制，缩小扫描面。
SOURCE_EXTENSIONS: Set[str] = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".swift",
    ".kt",
    ".kts",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".vue",
    ".svelte",
}

# 路径片段或后缀命中则忽略（依赖目录、第三方拷贝、构建/缓存、锁文件、图片等噪音）。
IGNORE_DIR_PARTS: Set[str] = {
    # —— 前端依赖 / 产物 ——
    "node_modules",
    "bower_components",
    "jspm_packages",
    "vendor",
    "vendors",
    "plugin",
    "plugins",
    "dist",
    "build",
    ".next",
    # —— 多语言第三方拷贝 ——
    "third_party",
    "third-party",
    "thirdparty",
    "external",
    "externals",
    "libs",
    # —— Java / 构建 ——
    "target",
    "generated-sources",
    ".gradle",
    # —— Python / 缓存 ——
    "site-packages",
    ".eggs",
    "__pycache__",
    ".tox",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
    ".git",
}

IGNORE_SUFFIXES: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".gz",
    ".lock",
    ".min.js",
    ".min.css",
    ".bundle.js",
    ".bundle.css",
    ".map",
    # Java 二进制 / 编译产物
    ".jar",
    ".war",
    ".ear",
    ".class",
    # Python 分发与字节码
    ".pyc",
    ".pyo",
    ".pyd",
    ".egg",
    ".whl",
}

IGNORE_BASENAMES: Set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
}


@dataclass
class FileHistory:
    """单个文件的 Git 历史摘要。

    Attributes:
        path: 相对仓库根的路径（POSIX 风格字符串）。
        last_commit_ts: 最后一次提交的 Unix 时间戳；未知则为 None。
        churn: 统计窗口内出现在 diff 中的次数（近似「被改过几次」）。
    """

    path: str
    last_commit_ts: Optional[int]
    churn: int


class GitError(RuntimeError):
    """Git 命令失败或目录不是仓库时抛出。"""


def _run_git(repo: Path, args: List[str], check: bool = True) -> str:
    """在仓库目录执行 git 子命令，返回 stdout 文本。

    Args:
        repo: 仓库根路径。
        args: 传给 git 的参数列表（不含 ``git`` 本身）。
        check: 为 True 时非零退出码抛出 GitError。

    Returns:
        标准输出（去掉末尾空白）。
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("未找到 git 命令，请先安装 Git 并确保在 PATH 中。") from exc

    if check and completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise GitError(err or f"git {' '.join(args)} 失败（退出码 {completed.returncode}）")
    return completed.stdout


def ensure_git_repo(repo: Path) -> Path:
    """确认 path 位于 Git 工作树内，并返回仓库根目录。

    Args:
        repo: 用户指定的路径（可以是子目录）。

    Returns:
        ``git rev-parse --show-toplevel`` 解析出的绝对路径。
    """
    repo = repo.resolve()
    if not repo.exists():
        raise GitError(f"路径不存在: {repo}")
    if not repo.is_dir():
        raise GitError(f"不是目录: {repo}")

    try:
        inside = _run_git(repo, ["rev-parse", "--is-inside-work-tree"]).strip()
    except GitError as exc:
        raise GitError(f"不是 Git 仓库: {repo}") from exc
    if inside != "true":
        raise GitError(f"不是 Git 仓库: {repo}")

    root = _run_git(repo, ["rev-parse", "--show-toplevel"]).strip()
    return Path(root).resolve()


def should_ignore_path(rel_path: str) -> bool:
    """判断相对路径是否应被排除出分析集合。"""
    parts = Path(rel_path).parts
    if any(part in IGNORE_DIR_PARTS for part in parts):
        return True
    name = Path(rel_path).name
    if name in IGNORE_BASENAMES:
        return True
    lower = rel_path.lower()
    for suffix in IGNORE_SUFFIXES:
        if lower.endswith(suffix):
            return True
    return False


def is_source_file(rel_path: str) -> bool:
    """是否属于默认关注的源码后缀。"""
    return Path(rel_path).suffix.lower() in SOURCE_EXTENSIONS


def list_tracked_source_files(repo: Path) -> List[str]:
    """列出仓库中已 tracked、且通过后缀/忽略过滤的源码文件。

    使用 ``git ls-files``，不扫描未跟踪文件，避免把本地垃圾算进雷达。
    """
    raw = _run_git(repo, ["ls-files", "-z"])
    if not raw:
        return []
    files: List[str] = []
    for item in raw.split("\0"):
        if not item:
            continue
        # git 在 Windows 可能用反斜杠；统一成 POSIX 便于后续匹配。
        rel = item.replace("\\", "/")
        if should_ignore_path(rel):
            continue
        if not is_source_file(rel):
            continue
        files.append(rel)
    return files


def collect_churn(repo: Path, since_days: int = 90) -> Counter:
    """统计窗口内每个文件出现在提交 diff 中的次数。

    实现：一次 ``git log --since --name-only``，空 pretty 格式只留下文件名行，
    再 Counter 计数。同一 commit 改多个文件会分别 +1。

    Args:
        repo: 仓库根。
        since_days: 回溯天数，默认 90。

    Returns:
        文件相对路径 -> 出现次数。
    """
    # --pretty=format: 让 commit 头变成空行，输出里只剩文件名，便于聚合。
    out = _run_git(
        repo,
        [
            "log",
            f"--since={since_days}.days",
            "--name-only",
            "--pretty=format:",
            "--diff-filter=ACMR",
        ],
        check=False,
    )
    counter: Counter = Counter()
    for line in out.splitlines():
        path = line.strip().replace("\\", "/")
        if not path or should_ignore_path(path) or not is_source_file(path):
            continue
        counter[path] += 1
    return counter


def collect_last_commit_times(repo: Path, interested: Optional[Iterable[str]] = None) -> Dict[str, int]:
    """批量解析每个文件最近一次提交的时间戳。

    策略：从新到旧遍历 ``git log --name-only``；某个文件**第一次**出现时，
    当前 commit 的时间就是它的 last_commit_ts。无需对每个文件再开进程。

    Args:
        repo: 仓库根。
        interested: 若给定，只记录这些路径（加速大仓库：解析完即可早停）。

    Returns:
        文件路径 -> Unix 时间戳。
    """
    want: Optional[Set[str]] = set(interested) if interested is not None else None
    # %ct = committer 时间戳；下一行起是该 commit 改动的文件列表。
    out = _run_git(
        repo,
        ["log", "--name-only", "--pretty=format:COMMIT %ct", "--diff-filter=ACMR"],
        check=False,
    )

    last_ts: Dict[str, int] = {}
    current_ts: Optional[int] = None
    for line in out.splitlines():
        if line.startswith("COMMIT "):
            try:
                current_ts = int(line.split(" ", 1)[1].strip())
            except ValueError:
                current_ts = None
            continue
        path = line.strip().replace("\\", "/")
        if not path or current_ts is None:
            continue
        if want is not None and path not in want:
            continue
        # 只保留第一次见到的时间 = 最近提交。
        if path not in last_ts:
            last_ts[path] = current_ts
            # 已收集齐感兴趣集合时可提前结束，少读历史尾部。
            if want is not None and len(last_ts) >= len(want):
                break
    return last_ts


def build_file_histories(
    repo: Path,
    since_days: int = 90,
) -> List[FileHistory]:
    """汇总 tracked 源码文件的陈旧与热改信息。

    Args:
        repo: 仓库根（调用前应已经 ensure_git_repo）。
        since_days: 热改统计窗口。

    Returns:
        FileHistory 列表（含 churn=0 且很久未改的文件）。
    """
    files = list_tracked_source_files(repo)
    churn_map = collect_churn(repo, since_days=since_days)
    last_map = collect_last_commit_times(repo, interested=files)

    histories: List[FileHistory] = []
    for path in files:
        histories.append(
            FileHistory(
                path=path,
                last_commit_ts=last_map.get(path),
                churn=int(churn_map.get(path, 0)),
            )
        )
    return histories


def days_since(ts: Optional[int], now: Optional[float] = None) -> Optional[int]:
    """把 Unix 时间戳换成「距今天数」；未知返回 None。"""
    if ts is None:
        return None
    now_ts = time.time() if now is None else now
    return max(0, int((now_ts - ts) / 86400))
