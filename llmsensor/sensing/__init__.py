"""센싱 팩 -- 관측 영역마다 '무엇을 보나' 를 묶는다. 팩은 정책을 정하지 않는다(상태까지만).

    token      얼마나 썼나 · 맥락이 경계의 어느 쪽인가           (기존 Token 센싱, 기준선)
    execution  실행이 어떻게 끝났나 · 도구 결과 · 시간 초과/중단  (기존 실행 상태 + 새 관측)
    latency    응답 시간 -- 백분위, 운영자 SLO 가 있을 때만 상태
    provider   공급자 · 요금 한도 · 오류                           (기존 신뢰 상태 + 런타임 선언 경고)
    cost       청구 기준 비용 -- 공급자 단가표로 호출마다 계산
    quality    외부 평가 라벨이 있을 때만(지금은 SWE-bench 판정 뿐)
    liveness   지금 움직이나 -- 끝남 · 입력 대기 · 차례 중(멈춤은 운영자 무음 문턱이 있을 때만)
    actions    런타임이 스스로 한 행동 -- 압축 · 백그라운드 이동 · 입력 빼기 · 권한 거부(지표만)

팩은 기존 지표 · 규칙 정의를 **그대로 재사용**하고 새 것을 덧붙인다(뜻 불변 -- 실제 레코드 301 실행 스냅숏으로 확인).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SensingPack:
    name: str
    question: str
    canonical: dict = field(default_factory=dict)     # 이 팩이 책임지는 정준 관측
    metrics: tuple = ()
    rules: tuple = ()


# 기존 규칙의 평가 순서 -- 생애 사건 순서가 바뀌지 않게 이것을 먼저, 새 규칙은 뒤에
BASELINE_ORDER = ("context_pressure", "execution_health", "tool_execution_health", "completion_state",
                  "progress_state", "resource_state", "resource_pressure", "rate_limit_state", "runtime_reliability")


def packs() -> tuple:
    from .token import PACK as token
    from .execution import PACK as execution
    from .latency import PACK as latency
    from .provider import PACK as provider
    from .cost import PACK as cost
    from .quality import PACK as quality
    from .liveness import PACK as liveness
    from .actions import PACK as actions
    return (token, execution, latency, provider, cost, quality, liveness, actions)


def canonical_all() -> dict:
    out = {}
    for p in packs():
        for k, v in p.canonical.items():
            if k in out and out[k] != v:
                raise ValueError(f"정준 관측 {k} 의 정의가 팩끼리 다르다")
            out[k] = v
    return out


def owner(name: str) -> "str | None":
    for p in packs():
        if any(r.state == name for r in p.rules):
            return p.name
    return None


# 팩 하나를 바로 import 해도(`from llmsensor.sensing.token.events import …`) 돌게 -- 팩 → _base → state → registry → packs()
# 의 고리에서 이 패키지가 먼저 다 서 있어야 한다. state 를 여기서 올려 그 순서를 고정한다.
from .. import state as _state  # noqa: E402,F401
