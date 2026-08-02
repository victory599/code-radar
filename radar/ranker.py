# 风险排序：把陈旧 / 热改 / TODO / 缺测合成可解释的风险分。
"""风险分刻意保持线性、可解释，方便在终端一眼看出「为什么高」。

权重不是科学公式，而是 MVP 默认值；后续若要调参，改本模块常量即可。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from radar.git_probe import FileHistory, days_since
from radar.todo_scan import TodoHit


# —— 权重上限：避免单一信号把总分完全拉爆 ——
MAX_STALE = 40
MAX_CHURN = 40
MAX_TODO = 20
MISSING_TEST_BONUS = 15

# 热改多少次才认真看待「缺测」（避免 churn=1 的文件也被标红）。
CHURN_HOT_THRESHOLD = 3


@dataclass
class FileRisk:
    """单个文件的风险画像，供报告与 JSON 输出。"""

    path: str
    score: int
    stale_days: Optional[int]
    churn: int
    todo_count: int
    spicy_todo_count: int
    missing_test: bool
    components: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的字典。"""
        return asdict(self)


def _stale_weight(stale_days: Optional[int]) -> int:
    """陈旧分：大约每 20 天 +1，封顶 MAX_STALE。

    很久没人碰的文件不一定坏，但和热改/TODO 叠在一起时往往是「无人认领的坑」。
    """
    if stale_days is None:
        return 0
    return min(MAX_STALE, stale_days // 20)


def _churn_weight(churn: int) -> int:
    """热改分：每次提交约 +2，封顶 MAX_CHURN。"""
    if churn <= 0:
        return 0
    return min(MAX_CHURN, churn * 2)


def _todo_weight(todo_count: int, spicy_count: int) -> int:
    """TODO 分：每条 +3，离谱条目额外 +2，封顶 MAX_TODO。"""
    if todo_count <= 0:
        return 0
    raw = todo_count * 3 + spicy_count * 2
    return min(MAX_TODO, raw)


def score_file(
    history: FileHistory,
    todo_count: int = 0,
    spicy_todo_count: int = 0,
    missing_test: bool = False,
    now: Optional[float] = None,
) -> FileRisk:
    """计算单个文件的风险分与分项。

    Args:
        history: Git 历史摘要。
        todo_count: 该文件 TODO 条数。
        spicy_todo_count: 其中离谱条数。
        missing_test: 是否判定缺测。
        now: 可注入的当前时间（测试用）。

    Returns:
        FileRisk。
    """
    stale_days = days_since(history.last_commit_ts, now=now)
    w_stale = _stale_weight(stale_days)
    w_churn = _churn_weight(history.churn)
    w_todo = _todo_weight(todo_count, spicy_todo_count)

    # 缺测加分只给「够热」的文件，否则陈旧冷文件会大面积假阳性。
    w_missing = 0
    effective_missing = False
    if missing_test and history.churn >= CHURN_HOT_THRESHOLD and not _path_looks_like_test(history.path):
        w_missing = MISSING_TEST_BONUS
        effective_missing = True

    score = w_stale + w_churn + w_todo + w_missing
    return FileRisk(
        path=history.path,
        score=score,
        stale_days=stale_days,
        churn=history.churn,
        todo_count=todo_count,
        spicy_todo_count=spicy_todo_count,
        missing_test=effective_missing,
        components={
            "stale": w_stale,
            "churn": w_churn,
            "todo": w_todo,
            "missing_test": w_missing,
        },
    )


def _path_looks_like_test(path: str) -> bool:
    """避免循环导入 test_map 时的轻量判断（ranker 内联一份）。"""
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return (
        "/tests/" in f"/{lower}"
        or "/test/" in f"/{lower}"
        or "/__tests__/" in f"/{lower}"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def rank_files(
    histories: Sequence[FileHistory],
    todo_totals: Dict[str, int],
    todo_spicy: Dict[str, int],
    missing_test_paths: Set[str],
    now: Optional[float] = None,
) -> List[FileRisk]:
    """对全部文件打分并按分数降序排列。"""
    risks = [
        score_file(
            history=h,
            todo_count=todo_totals.get(h.path, 0),
            spicy_todo_count=todo_spicy.get(h.path, 0),
            missing_test=h.path in missing_test_paths,
            now=now,
        )
        for h in histories
    ]
    risks.sort(key=lambda r: (-r.score, r.path))
    return risks


@dataclass
class ScanResult:
    """一次完整扫描的结构化结果。"""

    repo: str
    file_count: int
    since_days: int
    risks: List[FileRisk]
    todos: List[TodoHit]
    stale_top: List[FileRisk]
    churn_top: List[FileRisk]
    missing_test_hot: List[FileRisk]

    def to_dict(self) -> dict:
        """JSON 友好结构。"""
        return {
            "repo": self.repo,
            "file_count": self.file_count,
            "since_days": self.since_days,
            "danger_map": [r.to_dict() for r in self.risks],
            "todos": [
                {
                    "path": t.path,
                    "line_no": t.line_no,
                    "kind": t.kind,
                    "text": t.text,
                    "spicy": t.spicy,
                }
                for t in self.todos
            ],
            "stale_top": [r.to_dict() for r in self.stale_top],
            "churn_top": [r.to_dict() for r in self.churn_top],
            "missing_test_hot": [r.to_dict() for r in self.missing_test_hot],
        }


def build_scan_result(
    repo: str,
    since_days: int,
    risks: List[FileRisk],
    todos: List[TodoHit],
    top: int,
) -> ScanResult:
    """从已打分列表派生各榜单 Top N。"""
    # 陈旧榜：按 stale_days 降序（越久越靠前）；未知天数排最后。
    stale_sorted = sorted(
        risks,
        key=lambda r: (-(r.stale_days or -1), r.path),
    )
    churn_sorted = sorted(risks, key=lambda r: (-r.churn, r.path))
    missing_hot = [r for r in risks if r.missing_test]
    missing_hot.sort(key=lambda r: (-r.churn, -r.score, r.path))

    return ScanResult(
        repo=repo,
        file_count=len(risks),
        since_days=since_days,
        risks=risks[:top],
        todos=todos,
        stale_top=stale_sorted[:top],
        churn_top=churn_sorted[:top],
        missing_test_hot=missing_hot[:top],
    )
