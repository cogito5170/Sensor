"""Latency 센싱 -- 응답 시간의 백분위. 상태(latency_state)는 **운영자 SLO 가 있을 때만**.

문턱 출처: F´ Svc::Health 처럼 시간 문턱은 실체마다 **설정**된다(HTH-002/006). 기본 설정에는 없다 -> NOT_APPLICABLE.
시간 초과는 지연 문턱이 아니라 런타임 선언이라 execution 팩의 execution_interruption 이 맡는다(겹치지 않게).

주의(앞 실험): 시간 센서의 뜻은 수집기에 달렸다 -- Claude Code JSONL 의 호출 구간은 블록 줄 시각, stream-json 은 수집기
도착 시각이다. 실행 하나는 한 원천이라 실행 안에서는 일관되지만, **원천이 다른 실행끼리 지연을 비교하지 마라.**
"""
from ...state.config import Band  # noqa: F401
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType, Status
from ...state.rules import Result, Rule, _inf, _unk, band
from .. import SensingPack
from .._base import _m, min_samples, percentile

A, T = EntityType.AGENT, EntityType.TASK
NEW_CANON = {
    "call.t_start": ("model_call", "t_start_ms", A, Basis.OBSERVED),
    "call.t_end": ("model_call", "t_end_ms", A, Basis.OBSERVED),
    "call.first_chunk_ms": ("model_call", "first_chunk_ms", A, Basis.OBSERVED),
    "tool.t_issued": ("tool_call", "t_issued_ms", EntityType.TOOL, Basis.OBSERVED),
    "tool.t_result": ("tool_call", "t_result_ms", EntityType.TOOL, Basis.OBSERVED),
    "run.duration_ms": ("run", "run_duration_ms", T, Basis.OBSERVED),
    "run.api_duration_ms": ("run", "api_duration_ms", T, Basis.OBSERVED),
    "run.api_duration_without_retries_ms": ("run", "api_duration_without_retries_ms", T, Basis.OBSERVED),
    "run.ttft_ms": ("run", "ttft_ms", T, Basis.OBSERVED),
}
PCTS = {"p50": 0.50, "p95": 0.95, "p99": 0.99}


def _dist(ctx, name, samples, ids):
    if not samples:
        return _m(ctx, name, None, (), reason="표본이 없다")
    v = {"n": len(samples)}
    for k, p in PCTS.items():
        v[k] = percentile(samples, p)
    return _m(ctx, name, v, ids)


def m_call_latency(L, ctx, Mx):
    s, ids = [], []
    for c in L.calls:
        a, b = c.get("call.t_start"), c.get("call.t_end")
        if a is not None and b is not None and a.value is not None and b.value is not None:
            s.append(b.value - a.value)
            ids += [a.id, b.id]
    return _dist(ctx, "call_latency", s, ids)


def m_first_chunk(L, ctx, Mx):
    obs = [c["call.first_chunk_ms"] for c in L.calls if c.get("call.first_chunk_ms") is not None
           and c["call.first_chunk_ms"].value is not None]
    return _dist(ctx, "first_chunk_latency", [o.value for o in obs], [o.id for o in obs])


def m_tool_latency(L, ctx, Mx):
    s, ids = [], []
    for t in L.tools:
        a, b = t.get("tool.t_issued"), t.get("tool.t_result")
        if a is not None and b is not None and a.value is not None and b.value is not None:
            s.append(b.value - a.value)
            ids += [a.id, b.id]
    return _dist(ctx, "tool_latency", s, ids)


def _run_obs(L, ctx, name, key):
    o = L.run.get(key)
    if o is None or o.value is None:
        return _m(ctx, name, None, (), reason="실행 요약에 없다")
    return _m(ctx, name, o.value, [o.id])


def m_end_to_end(L, ctx, Mx):
    return _run_obs(L, ctx, "end_to_end_latency", "run.duration_ms")


def m_api_share(L, ctx, Mx):
    a, b = L.run.get("run.api_duration_ms"), L.run.get("run.duration_ms")
    if not a or not b or a.value is None or not b.value:
        return _m(ctx, "api_time_share", None, (), reason="API 시간 또는 전체 시간을 모른다")
    return _m(ctx, "api_time_share", a.value / b.value, [a.id, b.id])


def m_api_retry(L, ctx, Mx):
    a, b = L.run.get("run.api_duration_ms"), L.run.get("run.api_duration_without_retries_ms")
    if not a or not b or a.value is None or b.value is None:
        return _m(ctx, "api_retry_time", None, (), reason="재시도를 뺀 API 시간을 런타임이 주지 않았다")
    return _m(ctx, "api_retry_time", a.value - b.value, [a.id, b.id])


def r_latency(Mx, prev, cfg):
    slo = cfg.latency_slo
    if not slo:
        return Result(None, Status.NOT_APPLICABLE, "지연 SLO 가 설정되지 않았다(문턱을 지어내지 않는다)", ("call_latency",))
    m, pk = Mx[slo["metric"]], slo["percentile"]
    if m.value is None or m.value.get(pk) is None:
        n = m.value["n"] if m.value else 0
        return _unk(f"{slo['metric']} {pk} 에 표본 {min_samples(PCTS[pk])} 개 이상이 필요한데 {n} 개", [slo["metric"]])
    x = m.value[pk]
    return _inf(band(x, slo["bands"], prev, base="NORMAL"),
                f"{slo['metric']} {pk} = {x:.0f} ms, 설정 띠 {[(b.label, b.enter) for b in slo['bands']]}", [slo["metric"]])


NEW_METRICS = (
    MetricDefinition("call_latency", A, ("call.t_start", "call.t_end"), Basis.OBSERVED,
                     "모형 호출 구간(첫 ~ 마지막 관측) 분포 {n, p50, p95, p99} -- 표본이 모자란 백분위는 None", m_call_latency),
    MetricDefinition("first_chunk_latency", A, ("call.first_chunk_ms",), Basis.OBSERVED,
                     "message_start ~ 첫 조각(스트림 수집기에서만) 분포", m_first_chunk),
    MetricDefinition("tool_latency", A, ("tool.t_issued", "tool.t_result"), Basis.OBSERVED,
                     "도구 호출 ~ 결과 분포", m_tool_latency),
    MetricDefinition("end_to_end_latency", T, ("run.duration_ms",), Basis.OBSERVED, "실행 전체 시간", m_end_to_end),
    MetricDefinition("api_time_share", T, ("run.api_duration_ms", "run.duration_ms"), Basis.OBSERVED,
                     "API 시간 / 전체 시간", m_api_share),
    MetricDefinition("api_retry_time", T, ("run.api_duration_ms", "run.api_duration_without_retries_ms"),
                     Basis.OBSERVED, "API 재시도에 쓴 시간", m_api_retry),
)
LATENCY = Rule("latency-state-v1", 1, "latency_state", A, Basis.OPERATOR_ASSUMED,
               ("call_latency", "first_chunk_latency", "tool_latency"), ("NORMAL", "ELEVATED", "DEGRADED"),
               "설정된 SLO 띠로 본 지연(띠 이름 · 문턱은 설정이 정한다). SLO 가 없으면 NOT_APPLICABLE", "더 빠른 경로로 바꿀까",
               r_latency)

PACK = SensingPack("latency", "모형 · 도구 · 실행의 응답 시간이 어떤 분포인가(상태는 운영자 SLO 가 있을 때만)",
                   NEW_CANON, NEW_METRICS, (LATENCY,))
