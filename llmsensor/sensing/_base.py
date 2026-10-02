"""팩들이 함께 쓰는 것 -- 기존 정의 사전, 백분위."""
from __future__ import annotations

import math

from ..state.metrics import METRICS, _m  # noqa: F401  (팩들이 지표를 만들 때 같은 꼴을 쓴다)
from ..state.normalize import CANONICAL as BASE_CANONICAL
from ..state.rules import RULES

M = {m.name: m for m in METRICS}
R = {r.state: r for r in RULES}


def canon(*names) -> dict:
    return {n: BASE_CANONICAL[n] for n in names}


def min_samples(p: float) -> int:
    """p 백분위가 '최댓값이 아닌 값' 으로 정의되려면 n ≥ 1/(1−p) 개가 있어야 한다(정의상: p95 -> 20, p99 -> 100)."""
    return math.ceil(1 / (1 - p) - 1e-9)


def percentile(xs, p: float):
    """가장 가까운 순위(nearest-rank). 표본이 min_samples(p) 보다 적으면 None -- 지어내지 않는다."""
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < min_samples(p):
        return None
    return xs[max(0, math.ceil(p * len(xs)) - 1)]
