"""Cost 센싱 -- 그 사용이 청구 기준으로 얼마인가. Token 센싱(얼마나 썼나)과 갈라 둔다.

- 호출마다 토큰 × 공급자 단가표(pricing.py, PROVIDER_DECLARED, 두 모형 모두 런타임 보고값과 정확히 같음을 확인)
- 실행 누적 추정 · 런타임 보고값과의 차(보고 시각까지의 호출만 -- Claude Code cost-state 는 중간 스냅숏이다)
- 상태: resource_state **v2**(baseline BD-39) · resource_pressure(v1, 뜻 그대로). **예산 문턱을 기본값으로 넣지 않는다.**

resource-state-v2 (BD-39, baseline#3 CMD-S3):
    예산 없음                         -> NOT_APPLICABLE (v1 과 같다. UNKNOWN 이 아니다 -- 예산은 상태를 정의하는 문턱이다)
    하한 ≥ 예산                       -> BUDGET_EXHAUSTED, permanent(비용은 줄지 않는다)
        하한 = max(런타임 보고 비용, 단가가 있는 호출의 합) -- 단가 ≥ 0 이라 부분 합도 하한이다
               (보고가 모든 호출을 덮으면 하한 = 보고. 추정과 어긋나면 그 차는 cost_estimate_error 가 말한다)
    합을 안다 그리고 합 < 예산         -> WITHIN_BUDGET
        합 = 보고 비용(보고가 모든 호출을 덮을 때 -- 보고가 이긴다) 또는 추정(모든 호출에 단가가 있을 때)
    그 밖                             -> UNKNOWN (단가 없는 호출이 있어 합을 모른다)
    단가 없는 호출: 단가표에 없는 모형 · 토큰 칸을 못 본 호출 · 런타임이 합성한 오류 메시지(`<synthetic>`, 재고 D3)
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType, Status
from ...state.rules import Result, Rule, _inf, _unk
from .. import SensingPack
from .._base import M, R, _m, canon
from . import pricing

A = EntityType.AGENT
NEW_CANON = {
    "tokens.cache_write_5m": ("model_call", "cache_creation_5m_input_tokens", A, Basis.OBSERVED),
    "tokens.cache_write_1h": ("model_call", "cache_creation_1h_input_tokens", A, Basis.OBSERVED),
    "call.model": ("model_call", "model", A, Basis.OBSERVED),
    # 꼴 v3: 실행 요약이 실행 끝이 아니라 **중간 스냅숏**일 때만 그 시각이 붙는다(Claude Code cost-state). 없으면 실행 끝 요약이다
    "run.snapshot_at_ms": ("run", "snapshot_at_ms", A, Basis.OBSERVED),
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


def _t(c):
    t = c.get("tokens.output") or c.get("tokens.input_uncached")
    return None if t is None else t.observed_at


def m_cost_bounds(L, ctx, Mx):
    """비용의 하한과(알면) 합. 하한 = max(보고, 단가 있는 호출의 합). 합 = 모든 호출을 덮는 보고 > 모든 호출의 추정.

    보고가 모든 호출을 덮나:
        실행 끝 요약(스냅숏 표시 없음)      -> 덮는다(BD-39 "실행 끝의 보고 비용이 이긴다"). 단 보고보다 늦은 호출이 보이면 안 덮는다
        중간 스냅숏(snapshot_at_ms 있음)   -> 모든 호출 시각을 알고 전부 스냅숏 이전일 때만 덮는다. 시각을 모르면 짐작하지 않는다
    """
    priced, unpriced, est, ids = 0, 0, 0.0, []
    for c in L.calls:
        v, i = _cost_of(c)
        if v is None:
            unpriced += 1
            continue
        priced += 1
        est += v["total"]
        ids += i
    rep = L.run.get("run.cost_usd")
    rv = None if rep is None else rep.value
    if rv is None and not L.calls:
        return _m(ctx, "cost_bounds", None, (), reason="호출도 보고 비용도 아직 없다")
    covers, snap = None, L.run.get("run.snapshot_at_ms")
    if rv is not None:
        ts = [_t(c) for c in L.calls]
        if snap is not None and snap.value is not None:
            covers = all(t is not None and t <= snap.value for t in ts)
        else:
            covers = not (rep.observed_at is not None and any(t is not None and t > rep.observed_at for t in ts))
    total, source = None, None
    if covers:
        total, source = rv, "reported"                 # 보고가 이긴다(계산값은 대체됨 -- 차는 cost_estimate_error)
    elif L.calls and unpriced == 0:
        total, source = est, "estimate"
    if covers:
        lower = rv            # 덮는 보고가 이긴다 -- 추정이 더 커도(단가표가 틀린 것) 그것으로 소진을 내지 않는다
    else:
        lower = max(x for x in (rv, est if priced else None, 0.0) if x is not None)
    v = {"lower": lower, "total": total, "source": source, "reported": rv, "reported_covers_all": covers,
         "priced_calls": priced, "unpriced_calls": unpriced, "pricing": pricing.VERSION}
    refs = [o.id for o in (rep, snap) if o is not None] + ids
    return _m(ctx, "cost_bounds", v, refs, Basis.PROVIDER_DECLARED)


def r_resource_state_v2(Mx, prev, cfg):
    b = cfg.cost_budget_usd
    if b is None:
        return Result(None, Status.NOT_APPLICABLE, "예산이 설정되지 않았다", ("cost_bounds",))
    cb = Mx["cost_bounds"]
    if cb.value is None:
        return _unk("비용을 아직 못 봤다: " + cb.reason, ["cost_bounds"])
    v = cb.value
    if v["lower"] >= b:
        return _inf("BUDGET_EXHAUSTED", f"비용 하한 ${v['lower']:.6f} ≥ 예산 ${b} -- 비용은 줄지 않으므로 이후에도 참"
                    f" (단가표 {v['pricing']})", ["cost_bounds"], final=True)
    if v["total"] is not None:
        return _inf("WITHIN_BUDGET", f"비용 ${v['total']:.6f}({v['source']}) < 예산 ${b}", ["cost_bounds"])
    why = (f"단가 없는 호출 {v['unpriced_calls']} 개" if v["unpriced_calls"] else "보고 비용이 모든 호출을 덮는지 모른다")
    return _unk(f"{why} -- 합을 모른다. 하한 ${v['lower']:.6f} < 예산 ${b} 이라 소진도 증명되지 않는다", ["cost_bounds"])


RESOURCE_V2 = Rule("resource-state-v2", 2, "resource_state", A, Basis.DEFINITIONAL, ("cost_bounds",),
                   ("WITHIN_BUDGET", "BUDGET_EXHAUSTED"),
                   "비용이 설정 예산 안인가 -- 실행 중에도(공급자 단가 × 토큰). 하한 ≥ 예산이면 소진(영구), 합을 알 때만 예산 안. "
                   "예산이 없으면 NOT_APPLICABLE (BD-39)", "멈출까", r_resource_state_v2)
RESOURCE_V1 = R["resource_state"]       # 회귀 시험용으로 남긴다

NEW_METRICS = (
    MetricDefinition("call_cost", A, KEYS, Basis.PROVIDER_DECLARED, "마지막 호출의 비용 성분($) -- 토큰 × 공급자 단가",
                     m_call_cost),
    MetricDefinition("cost_estimate", A, KEYS, Basis.PROVIDER_DECLARED, "실행 누적 비용 추정($)", m_cost_estimate),
    MetricDefinition("cost_estimate_error", A, KEYS + ("run.cost_usd",), Basis.VALIDATED_EXPERIMENT,
                     "(추정 − 런타임 보고) / 보고 -- 보고 시각까지의 호출만", m_cost_estimate_error),
    MetricDefinition("cost_bounds", A, KEYS + ("run.cost_usd", "run.snapshot_at_ms"), Basis.PROVIDER_DECLARED,
                     "비용 하한(보고 · 단가 있는 호출의 합 중 큰 것)과, 알면 합(덮는 보고 > 완전한 추정) · 단가표 판본", m_cost_bounds),
)

PACK = SensingPack(
    "cost", "그 사용이 청구 기준으로 얼마인가(공급자 단가표) · 설정 예산에 대해 어디인가",
    {**canon("run.cost_usd"), **NEW_CANON},
    tuple(M[n] for n in ("cost_usd", "cost_fraction", "cost_margin")) + NEW_METRICS,
    (RESOURCE_V2, R["resource_pressure"]))
