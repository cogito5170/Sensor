"""층 2 -- 관측에서 계산하는 지표. 지표마다 이름 · 실체 종류 · 입력 · 근거 · 계산 함수.

지표는 **값이 없으면 UNKNOWN** 이다. 0 으로 메우지 않는다. 더 이른 호출의 값으로 메우지도 않는다(그것은 낡은 근거다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .model import Basis, EntityType, Metric, Status

ABNORMAL_STOPS = ("max_tokens", "model_context_window_exceeded")   # 한도에 잘린 생성 -- 런타임 신뢰도의 증거


class Ledger:
    """실행 하나의 관측 장부. 엔진이 묶음을 받을 때마다 채운다."""

    def __init__(self, run_id):
        self.run_id = run_id
        self.calls: list = []        # 호출마다 {정준 이름: Observation}
        self.tools: list = []        # 도구 결과마다 {정준 이름: Observation} + "_tool"
        self.run: dict = {}          # 끝 요약 {정준 이름: Observation}
        self.seq = 0
        self.seen: set = set()       # 받은 record_id -- 멱등 받아들이기
        self.last_at = None
        self.time_base = None
        self.source = None


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    entity: EntityType
    inputs: tuple            # 정준 관측 이름 또는 다른 지표 이름
    basis: Basis
    doc: str
    fn: Callable = field(compare=False, repr=False)


def _m(ctx, name, value, inputs, basis=Basis.OBSERVED, status=None, reason=""):
    st = status or (Status.UNKNOWN if value is None else Status.DERIVED)
    return Metric(id=f"{ctx['entity']}/{name}@{ctx['seq']}", entity_id=ctx["entity"], name=name, value=value,
                  status=st, basis=basis, inputs=tuple(inputs), reason=reason, computed_at=ctx["at"])


def _obs(o):
    return None if o is None else o.value


# ---- 맥락 ----
def m_context_tokens(L, ctx, M):
    if not L.calls:
        return _m(ctx, "context_tokens", None, (), reason="모형 호출이 아직 없다")
    c = L.calls[-1]
    parts = [c.get(k) for k in ("tokens.input_uncached", "tokens.cache_read", "tokens.cache_write")]
    if any(p is None or p.value is None for p in parts):
        return _m(ctx, "context_tokens", None, [p.id for p in parts if p],
                  reason="마지막 호출의 입력 토큰 셋 중 못 본 것이 있다 -- 이전 호출 값으로 메우지 않는다")
    return _m(ctx, "context_tokens", sum(p.value for p in parts), [p.id for p in parts])


def m_context_window(L, ctx, M):
    o = L.run.get("run.context_window") or (L.calls[-1].get("call.context_window") if L.calls else None)
    if o is not None and o.value is not None:
        return _m(ctx, "context_window", o.value, [o.id])
    if ctx["config"].context_window_override is not None:
        return _m(ctx, "context_window", ctx["config"].context_window_override, (), Basis.OPERATOR_ASSUMED,
                  reason="런타임이 창을 안 줬다 -- 설정의 context_window_override")
    return _m(ctx, "context_window", None, (), reason="창 크기를 런타임도 설정도 주지 않았다")


def m_compaction_threshold(L, ctx, M):
    o = L.run.get("run.compaction_threshold")
    if o is not None and o.value is not None:
        return _m(ctx, "compaction_threshold", o.value, [o.id], Basis.RUNTIME_DECLARED)
    return _m(ctx, "compaction_threshold", None, (), reason="런타임이 자동 압축 문턱을 선언하지 않았다")


def m_context_utilization(L, ctx, M):
    a, b = M["context_tokens"], M["context_window"]
    v = a.value / b.value if a.value is not None and b.value else None
    return _m(ctx, "context_utilization", v, [a.id, b.id], b.basis if v is not None else Basis.OBSERVED)


def m_context_margin(L, ctx, M):
    a, b = M["context_tokens"], M["context_window"]
    v = b.value - a.value if a.value is not None and b.value is not None else None
    return _m(ctx, "context_margin", v, [a.id, b.id])


def m_compaction_margin(L, ctx, M):
    a, b = M["context_tokens"], M["compaction_threshold"]
    v = b.value - a.value if a.value is not None and b.value is not None else None
    return _m(ctx, "compaction_margin", v, [a.id, b.id], Basis.RUNTIME_DECLARED if v is not None else Basis.OBSERVED)


def m_context_growth(L, ctx, M):
    if len(L.calls) < 2:
        return _m(ctx, "context_growth", None, (), reason="호출이 둘 이상이어야 한다")
    ids, tot = [], []
    for c in L.calls[-2:]:
        parts = [c.get(k) for k in ("tokens.input_uncached", "tokens.cache_read", "tokens.cache_write")]
        if any(p is None or p.value is None for p in parts):
            return _m(ctx, "context_growth", None, [p.id for p in parts if p], reason="입력 토큰을 못 본 호출")
        ids += [p.id for p in parts]
        tot.append(sum(p.value for p in parts))
    return _m(ctx, "context_growth", tot[1] - tot[0], ids)


# ---- 도구 / 실행 ----
def _tool_rows(L, tool=None):
    return [t for t in L.tools if tool is None or t["_tool"] == tool]


def _outcomes(rows):
    """(결과를 본 행, 결과를 못 보는 행) -- is_error 가 관측되었나."""
    seen = [t for t in rows if t.get("tool.is_error") is not None and t["tool.is_error"].value is not None]
    blind = [t for t in rows if t not in seen]
    return seen, blind


def _tool_metrics(prefix, tool):
    def results(L, ctx, M):
        seen, blind = _outcomes(_tool_rows(L, tool))
        return _m(ctx, prefix + "tool_results", len(seen), [t["tool.is_error"].id for t in seen])

    def unobservable(L, ctx, M):
        seen, blind = _outcomes(_tool_rows(L, tool))
        return _m(ctx, prefix + "tool_outcome_unobservable", len(blind),
                  [t["tool.name"].id for t in blind if t.get("tool.name")])

    def errors(L, ctx, M):
        seen, _ = _outcomes(_tool_rows(L, tool))
        bad = [t for t in seen if t["tool.is_error"].value]
        return _m(ctx, prefix + "tool_errors", len(bad), [t["tool.is_error"].id for t in bad])

    def rate(L, ctx, M):
        n, e = M[prefix + "tool_results"], M[prefix + "tool_errors"]
        v = e.value / n.value if n.value else None
        return _m(ctx, prefix + "tool_failure_rate", v, [n.id, e.id],
                  reason="" if v is not None else "결과를 본 도구 호출이 없다")

    def targets(L, ctx, M):
        """겨냥(도구:대상 해시)마다 가장 최근 결과. 미해결 = 마지막이 실패. 회복 = 실패했다가 뒤에 성공."""
        seen, _ = _outcomes(_tool_rows(L, tool))
        last, failed_once = {}, set()
        for t in seen:
            k = t["tool.target"].value if t.get("tool.target") else t["tool.name"].value
            last[k] = t
            if t["tool.is_error"].value:
                failed_once.add(k)
        unresolved = sorted(k for k, t in last.items() if t["tool.is_error"].value)
        recovered = sorted(k for k in failed_once if not last[k]["tool.is_error"].value)
        ids = [last[k]["tool.is_error"].id for k in unresolved + recovered]
        return _m(ctx, prefix + "tool_targets", {"unresolved": unresolved, "recovered": recovered,
                                                 "targets": len(last)}, ids)

    return results, unobservable, errors, rate, targets


A_RES, A_UNOBS, A_ERR, A_RATE, A_TGT = _tool_metrics("", None)


def m_identical_call_max(L, ctx, M):
    c = {}
    ids = {}
    for t in L.tools:
        s = t.get("tool.signature")
        if s is not None:
            c[s.value] = c.get(s.value, 0) + 1
            ids.setdefault(s.value, []).append(s.id)
    if not c:
        return _m(ctx, "identical_call_max", None, (), reason="도구 서명이 없다")
    k = max(sorted(c), key=lambda x: c[x])
    return _m(ctx, "identical_call_max", c[k], ids[k])


# ---- 생각 ----
def m_reasoning_tokens(L, ctx, M):
    obs = [c["tokens.reasoning"] for c in L.calls if c.get("tokens.reasoning") is not None
           and c["tokens.reasoning"].value is not None]
    if not obs:
        return _m(ctx, "reasoning_tokens", None, (), reason="최종 생각 토큰 보고가 없다")
    return _m(ctx, "reasoning_tokens", sum(o.value for o in obs), [o.id for o in obs])


def m_reasoning_estimate(L, ctx, M):
    """생성 도중 런타임 추정 -- 그 호출의 최종값이 오면 INVALID(대체됨)."""
    if not L.calls or L.calls[-1].get("tokens.reasoning_estimate") is None:
        return _m(ctx, "reasoning_estimate", None, (), Basis.ESTIMATE, reason="추정치가 없다")
    c = L.calls[-1]
    est = c["tokens.reasoning_estimate"]
    if c.get("tokens.reasoning") is not None and c["tokens.reasoning"].value is not None:
        return _m(ctx, "reasoning_estimate", est.value, [est.id, c["tokens.reasoning"].id], Basis.ESTIMATE,
                  Status.INVALID, "같은 호출의 최종 생각 토큰이 보고되어 추정은 대체되었다")
    return _m(ctx, "reasoning_estimate", est.value, [est.id], Basis.ESTIMATE)


# ---- 비용 ----
def m_cost(L, ctx, M):
    o = L.run.get("run.cost_usd")
    if o is None or o.value is None:
        return _m(ctx, "cost_usd", None, (), reason="이 런타임들은 비용을 실행 끝에만 보고한다")
    return _m(ctx, "cost_usd", o.value, [o.id])


def m_cost_fraction(L, ctx, M):
    b = ctx["config"].cost_budget_usd
    c = M["cost_usd"]
    if b is None:
        return _m(ctx, "cost_fraction", None, [c.id], Basis.OPERATOR_ASSUMED, Status.NOT_APPLICABLE, "예산 미설정")
    return _m(ctx, "cost_fraction", (c.value / b) if c.value is not None else None, [c.id], Basis.OPERATOR_ASSUMED)


def m_cost_margin(L, ctx, M):
    b = ctx["config"].cost_budget_usd
    c = M["cost_usd"]
    if b is None:
        return _m(ctx, "cost_margin", None, [c.id], Basis.OPERATOR_ASSUMED, Status.NOT_APPLICABLE, "예산 미설정")
    return _m(ctx, "cost_margin", (b - c.value) if c.value is not None else None, [c.id], Basis.OPERATOR_ASSUMED)


# ---- 런타임 ----
def m_stop_reasons(L, ctx, M):
    obs = [c["call.stop_reason"] for c in L.calls if c.get("call.stop_reason") is not None
           and c["call.stop_reason"].value is not None]
    abn = [o for o in obs if o.value in ABNORMAL_STOPS]
    return _m(ctx, "stop_reasons", {"observed": len(obs), "abnormal": [o.value for o in abn]},
              [o.id for o in (abn or obs[-1:])], status=Status.DERIVED if obs else Status.UNKNOWN,
              reason="" if obs else "멈춤 사유를 본 호출이 없다")


def m_api_error(L, ctx, M):
    o = L.run.get("runtime.api_error_status")
    if o is None:
        return _m(ctx, "api_error", None, (), reason="API 오류 상태를 보고받지 못했다(키 없음)")
    return _m(ctx, "api_error", {"reported": not o.reported_null, "value": o.value}, [o.id])


def m_rate_limit(L, ctx, M):
    o = L.run.get("runtime.rate_limit_utilization")
    if o is None or o.value is None:
        return _m(ctx, "rate_limit_utilization", None, (), reason="요금 한도 사건을 못 받았다")
    return _m(ctx, "rate_limit_utilization", o.value, [o.id])


# ---- 과업 ----
def m_termination(L, ctx, M):
    ks = ("run.result_subtype", "run.terminal_reason", "run.is_error")
    obs = [L.run[k] for k in ks if k in L.run]
    if not obs:
        return _m(ctx, "termination", None, (), reason="실행 끝 요약이 아직 없다")
    return _m(ctx, "termination", {k.split(".")[1]: (L.run[k].value if k in L.run else None) for k in ks},
              [o.id for o in obs], Basis.RUNTIME_DECLARED)


def m_activity(L, ctx, M):
    """실행에서 본 사건 수와 마지막 사건 시각 -- 진행이 아니라 '활동' 이다."""
    return _m(ctx, "activity", {"model_calls": len(L.calls), "tool_results": len(L.tools)},
              [o.id for o in (list(L.calls[-1].values()) if L.calls else [])][:1])


AGENT, TASK, RUNTIME, TOOL = EntityType.AGENT, EntityType.TASK, EntityType.RUNTIME, EntityType.TOOL
_TC = ("tool.is_error", "tool.target", "tool.name")

METRICS = [
    MetricDefinition("context_tokens", AGENT, ("tokens.input_uncached", "tokens.cache_read", "tokens.cache_write"),
                     Basis.OBSERVED, "마지막 호출이 본 입력 전체", m_context_tokens),
    MetricDefinition("context_window", AGENT, ("run.context_window", "call.context_window"), Basis.OBSERVED,
                     "맥락 창 크기(없으면 설정 override, 근거 OPERATOR_ASSUMED)", m_context_window),
    MetricDefinition("compaction_threshold", AGENT, ("run.compaction_threshold",), Basis.RUNTIME_DECLARED,
                     "런타임이 선언한 자동 압축 문턱(토큰)", m_compaction_threshold),
    MetricDefinition("context_utilization", AGENT, ("context_tokens", "context_window"), Basis.OBSERVED,
                     "context_tokens / context_window", m_context_utilization),
    MetricDefinition("context_margin", AGENT, ("context_tokens", "context_window"), Basis.OBSERVED,
                     "context_window − context_tokens", m_context_margin),
    MetricDefinition("compaction_margin", AGENT, ("context_tokens", "compaction_threshold"), Basis.RUNTIME_DECLARED,
                     "compaction_threshold − context_tokens", m_compaction_margin),
    MetricDefinition("context_growth", AGENT, ("tokens.input_uncached", "tokens.cache_read", "tokens.cache_write"),
                     Basis.OBSERVED, "마지막 두 호출의 context_tokens 차 (캐시 런타임에서는 ≡ cache_write)",
                     m_context_growth),
    MetricDefinition("tool_results", AGENT, _TC, Basis.OBSERVED, "결과(is_error)를 본 도구 호출 수", A_RES),
    MetricDefinition("tool_outcome_unobservable", AGENT, _TC, Basis.OBSERVED,
                     "결과를 볼 수 없는 도구 호출 수(SWE-agent 추적 등)", A_UNOBS),
    MetricDefinition("tool_errors", AGENT, _TC, Basis.OBSERVED, "is_error=true 인 결과 수", A_ERR),
    MetricDefinition("tool_failure_rate", AGENT, ("tool_results", "tool_errors"), Basis.OBSERVED,
                     "tool_errors / tool_results", A_RATE),
    MetricDefinition("tool_targets", AGENT, _TC, Basis.OBSERVED,
                     "겨냥별 최근 결과: 미해결(마지막이 실패) · 회복(실패 뒤 성공)", A_TGT),
    MetricDefinition("identical_call_max", AGENT, ("tool.signature",), Basis.OBSERVED,
                     "같은 (도구, 인자)의 최대 반복 수", m_identical_call_max),
    MetricDefinition("reasoning_tokens", AGENT, ("tokens.reasoning",), Basis.OBSERVED,
                     "최종 보고된 생각 토큰 합", m_reasoning_tokens),
    MetricDefinition("reasoning_estimate", AGENT, ("tokens.reasoning_estimate", "tokens.reasoning"), Basis.ESTIMATE,
                     "생성 도중 런타임 추정(최종값이 오면 INVALID)", m_reasoning_estimate),
    MetricDefinition("cost_usd", AGENT, ("run.cost_usd",), Basis.OBSERVED, "런타임이 보고한 비용", m_cost),
    MetricDefinition("cost_fraction", AGENT, ("cost_usd",), Basis.OPERATOR_ASSUMED, "cost / 예산(설정)",
                     m_cost_fraction),
    MetricDefinition("cost_margin", AGENT, ("cost_usd",), Basis.OPERATOR_ASSUMED, "예산 − cost", m_cost_margin),
    MetricDefinition("stop_reasons", RUNTIME, ("call.stop_reason",), Basis.OBSERVED,
                     "본 멈춤 사유 수와 한도에 잘린 것(max_tokens · model_context_window_exceeded)", m_stop_reasons),
    MetricDefinition("api_error", RUNTIME, ("runtime.api_error_status",), Basis.OBSERVED,
                     "API 오류 보고 -- 보고된 null 은 '오류 보고 없음'", m_api_error),
    MetricDefinition("rate_limit_utilization", RUNTIME, ("runtime.rate_limit_utilization",), Basis.OBSERVED,
                     "요금 한도 사용률(런타임 사건)", m_rate_limit),
    MetricDefinition("termination", TASK, ("run.result_subtype", "run.terminal_reason", "run.is_error"),
                     Basis.RUNTIME_DECLARED, "런타임이 선언한 종료(성공 여부가 **아니다**)", m_termination),
    MetricDefinition("activity", TASK, ("call.stop_reason",), Basis.OBSERVED, "본 호출 · 도구 결과 수", m_activity),
]


def tool_metric_defs(tool: str) -> "list[MetricDefinition]":
    r, u, e, rate, tg = _tool_metrics("", tool)
    return [MetricDefinition("tool_results", TOOL, _TC, Basis.OBSERVED, "이 도구의 결과 수", r),
            MetricDefinition("tool_outcome_unobservable", TOOL, _TC, Basis.OBSERVED, "결과를 볼 수 없는 호출", u),
            MetricDefinition("tool_errors", TOOL, _TC, Basis.OBSERVED, "이 도구의 오류 결과", e),
            MetricDefinition("tool_failure_rate", TOOL, ("tool_results", "tool_errors"), Basis.OBSERVED, "", rate),
            MetricDefinition("tool_targets", TOOL, _TC, Basis.OBSERVED, "이 도구의 겨냥별 최근 결과", tg)]
