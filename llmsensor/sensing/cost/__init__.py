"""Cost 센싱 -- 그 사용이 청구 기준으로 얼마인가. Token 센싱(얼마나 썼나)과 갈라 둔다.

- 호출마다 토큰 × 공급자 단가표(pricing.py, PROVIDER_DECLARED, 두 모형 모두 런타임 보고값과 정확히 같음을 확인)
- 실행 누적 추정 · 런타임 보고값과의 차(보고 시각까지의 호출만 -- Claude Code cost-state 는 중간 스냅숏이다)
- 상태: 기존 resource_state · resource_pressure(v1, 뜻 그대로). **예산 문턱을 기본값으로 넣지 않는다.**
  추정 비용으로 실행 중 resource_state 를 내는 것(v2)은 리뷰 C1 의 결정과 함께 사용자에게 묻는다.
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType
from .. import SensingPack
from .._base import M, R, _m, canon
from . import pricing

A = EntityType.AGENT
NEW_CANON = {
    "tokens.cache_write_5m": ("model_call", "cache_creation_5m_input_tokens", A, Basis.OBSERVED),
    "tokens.cache_write_1h": ("model_call", "cache_creation_1h_input_tokens", A, Basis.OBSERVED),
    "call.model": ("model_call", "model", A, Basis.OBSERVED),
}
KEYS = ("call.model", "tokens.input_uncached", "tokens.output", "tokens.cache_read", "tokens.cache_write_5m",
        "tokens.cache_write_1h")


def _cost_of(c):
    o = [c.get(k) for k in KEYS]
    if any(x is None for x in o):
        return None, [x.id for x in o if x is not None]
    return pricing.call_cost(*(x.value for x in o)), [x.id for x in o]


def m_call_cost(L, ctx, Mx):
    if not L.calls:
        return _m(ctx, "call_cost", None, (), reason="호출이 없다")
    v, ids = _cost_of(L.calls[-1])
    if v is None:
        return _m(ctx, "call_cost", None, ids, Basis.PROVIDER_DECLARED,
                  reason="마지막 호출의 모형이 단가표에 없거나 토큰 칸(캐시 쓰기 5m/1h 포함)을 못 봤다")
    return _m(ctx, "call_cost", v, ids, Basis.PROVIDER_DECLARED)


def m_cost_estimate(L, ctx, Mx):
    tot, ids = 0.0, []
    for c in L.calls:
        v, i = _cost_of(c)
        if v is None:
            return _m(ctx, "cost_estimate", None, i, Basis.PROVIDER_DECLARED,
                      reason="계산할 수 없는 호출이 있다 -- 부분 합을 내지 않는다")
        tot += v["total"]
        ids += i
    if not L.calls:
        return _m(ctx, "cost_estimate", None, (), reason="호출이 없다")
    return _m(ctx, "cost_estimate", tot, ids, Basis.PROVIDER_DECLARED)


def m_cost_estimate_error(L, ctx, Mx):
    """런타임 보고 비용과의 상대차. 보고 시각(스냅숏) 이후의 호출은 빼고 센다."""
    rep = L.run.get("run.cost_usd")
    if rep is None or rep.value is None:
        return _m(ctx, "cost_estimate_error", None, (), reason="보고된 비용이 없다")
    tot, ids = 0.0, [rep.id]
    for c in L.calls:
        t = c.get("tokens.output")
        if rep.observed_at is not None and t is not None and t.observed_at is not None and t.observed_at > rep.observed_at:
            continue
        v, i = _cost_of(c)
        if v is None:
            return _m(ctx, "cost_estimate_error", None, ids + i, reason="계산할 수 없는 호출이 있다")
        tot += v["total"]
        ids += i
    return _m(ctx, "cost_estimate_error", (tot - rep.value) / rep.value if rep.value else None, ids,
              Basis.VALIDATED_EXPERIMENT)


NEW_METRICS = (
    MetricDefinition("call_cost", A, KEYS, Basis.PROVIDER_DECLARED, "마지막 호출의 비용 성분($) -- 토큰 × 공급자 단가",
                     m_call_cost),
    MetricDefinition("cost_estimate", A, KEYS, Basis.PROVIDER_DECLARED, "실행 누적 비용 추정($)", m_cost_estimate),
    MetricDefinition("cost_estimate_error", A, KEYS + ("run.cost_usd",), Basis.VALIDATED_EXPERIMENT,
                     "(추정 − 런타임 보고) / 보고 -- 보고 시각까지의 호출만", m_cost_estimate_error),
)

PACK = SensingPack(
    "cost", "그 사용이 청구 기준으로 얼마인가(공급자 단가표) · 설정 예산에 대해 어디인가",
    {**canon("run.cost_usd"), **NEW_CANON},
    tuple(M[n] for n in ("cost_usd", "cost_fraction", "cost_margin")) + NEW_METRICS,
    (R["resource_state"], R["resource_pressure"]))
