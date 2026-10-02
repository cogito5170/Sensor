"""정규화 -- 원천마다 다른 꼴을 **정준 관측**으로. 공급자 이름이 상태 이름에 새지 않게 여기서 끊는다.

정준 토큰(Anthropic 식으로 셋을 갈라 둔다 -- 가장 잘게 쪼개진 꼴이라 다른 꼴을 여기로 옮길 수 있다):

    tokens.input_uncached   캐시 밖에서 새로 읽은 입력
    tokens.cache_read       캐시에서 읽은 입력
    tokens.cache_write      캐시에 새로 쓴 입력
    tokens.output           출력 전체(생각 **포함**)
    tokens.reasoning        생각 · 추론 출력(최종 보고값)
    tokens.reasoning_estimate  생성 도중 런타임 추정(ESTIMATE -- 권위 없음. 앞 실험: 최종값의 중앙 1.68 배)

공급자 차이(앞 실험의 SDK 소스 확인, 확인수준 D):
    OpenAI   prompt_tokens 는 캐시 **포함** -> input_uncached = prompt − cached
    Gemini   prompt_token_count 는 캐시 **포함**, candidates 는 생각 **제외**, 도구 결과 입력은 따로
             -> input_uncached = prompt − cached + tool_use_prompt, output = candidates + thoughts
"""
from __future__ import annotations

from .model import Basis, EntityType, Observation

# 정준 이름 -> (레코드 종류, 레코드 칸, 실체 종류, 근거)
CANONICAL = {
    # model_call -> agent
    "tokens.input_uncached": ("model_call", "input_tokens", EntityType.AGENT, Basis.OBSERVED),
    "tokens.cache_read": ("model_call", "cache_read_input_tokens", EntityType.AGENT, Basis.OBSERVED),
    "tokens.cache_write": ("model_call", "cache_creation_input_tokens", EntityType.AGENT, Basis.OBSERVED),
    "tokens.output": ("model_call", "output_tokens", EntityType.AGENT, Basis.OBSERVED),
    "tokens.reasoning": ("model_call", "thinking_tokens", EntityType.AGENT, Basis.OBSERVED),
    "tokens.reasoning_estimate": ("model_call", "stream_thinking_estimate", EntityType.AGENT, Basis.ESTIMATE),
    "call.stop_reason": ("model_call", "stop_reason", EntityType.AGENT, Basis.OBSERVED),
    "call.tool_uses": ("model_call", "tool_calls_per_message", EntityType.AGENT, Basis.OBSERVED),
    "call.context_window": ("model_call", "context_window", EntityType.AGENT, Basis.OBSERVED),
    # tool_call -> tool
    "tool.name": ("tool_call", "tool_name", EntityType.TOOL, Basis.OBSERVED),
    "tool.target": ("tool_call", "tool_head", EntityType.TOOL, Basis.OBSERVED),
    "tool.signature": ("tool_call", "tool_sig", EntityType.TOOL, Basis.OBSERVED),
    "tool.is_error": ("tool_call", "is_error", EntityType.TOOL, Basis.OBSERVED),
    "tool.output_chars": ("tool_call", "tool_output_chars", EntityType.TOOL, Basis.OBSERVED),
    # run -> task / runtime / agent
    "run.terminal_reason": ("run", "terminal_reason", EntityType.TASK, Basis.OBSERVED),
    "run.result_subtype": ("run", "result_subtype", EntityType.TASK, Basis.OBSERVED),
    "run.is_error": ("run", "is_error", EntityType.TASK, Basis.OBSERVED),
    "run.cost_usd": ("run", "cost_usd", EntityType.AGENT, Basis.OBSERVED),
    "run.context_window": ("run", "context_window", EntityType.AGENT, Basis.OBSERVED),
    "run.compaction_threshold": ("run", "autocompact_threshold", EntityType.AGENT, Basis.OBSERVED),
    "runtime.api_error_status": ("run", "api_error_status", EntityType.RUNTIME, Basis.OBSERVED),
    "runtime.rate_limit_utilization": ("run", "rate_limit_utilization", EntityType.RUNTIME, Basis.OBSERVED),
    "runtime.model": ("run", "model", EntityType.RUNTIME, Basis.OBSERVED),
}


def entity_id(kind: EntityType, run_id: str, tool: "str | None" = None) -> str:
    return f"{kind.value}:{run_id}" + (f":{tool}" if kind is EntityType.TOOL else "")


def _time(rec):
    if rec["kind"] == "model_call":
        return rec.get("t_end_ms")
    if rec["kind"] == "tool_call":
        return rec.get("t_result_ms") if rec.get("t_result_ms") is not None else rec.get("t_issued_ms")
    return None


class Batch:
    """한 레코드에서 나온 관측 묶음 -- 엔진이 한 번에 받아들이는 단위."""

    def __init__(self, record_id, run_id, kind, at, time_base, source, observations, call_index=None, tool=None):
        self.record_id, self.run_id, self.kind, self.at = record_id, run_id, kind, at
        self.time_base, self.source, self.observations = time_base, source, observations
        self.call_index, self.tool = call_index, tool


def _batch(rec, idx, at) -> Batch:
    run = rec["run_id"]
    rid = f"{run}/{rec['kind']}/{idx}"
    tool = rec.get("tool_name") if rec["kind"] == "tool_call" else None
    rn = set(rec.get("reported_null", ()))
    obs = []
    for name, (kind, fld, et, basis) in CANONICAL.items():
        if kind != rec["kind"] or fld not in rec:
            continue
        v = rec[fld]
        if v is None and fld not in rn:
            continue                          # 못 봤다 -- 관측을 만들지 않는다(없음 = UNKNOWN)
        obs.append(Observation(id=f"{rid}#{name}", entity_id=entity_id(et, run, tool), field=name, value=v,
                               reported_null=v is None, observed_at=at, time_base=rec.get("time_base"),
                               source=rec["source"], basis=basis))
    return Batch(rid, run, rec["kind"], at, rec.get("time_base"), rec["source"], obs,
                 rec.get("call_index"), tool)


def from_telemetry(records) -> "list[Batch]":
    """텔레메트리 레코드(꼴 v2) -> 인과 순서의 관측 묶음. 실행마다: 호출 i, 그 호출의 도구 결과들, ..., 끝 요약.
    시각이 없어도(SWE-agent) 순서는 인과로 정해진다. 실행 끝 요약의 시각 = 그 실행에서 본 가장 늦은 시각."""
    runs: dict = {}
    for r in records:
        runs.setdefault(r["run_id"], []).append(r)
    out = []
    for run in sorted(runs):
        rs = runs[run]
        mcs = sorted((r for r in rs if r["kind"] == "model_call"), key=lambda r: r["call_index"])
        tcs = sorted((r for r in rs if r["kind"] == "tool_call"), key=lambda r: r["tool_index"])
        last = None
        for m in mcs:
            t = _time(m)
            last = max(last, t) if (t is not None and last is not None) else (t if t is not None else last)
            out.append(_batch(m, m["call_index"], t))
            for tc in (x for x in tcs if x["call_index"] == m["call_index"]):
                t2 = _time(tc)
                last = max(last, t2) if (t2 is not None and last is not None) else (t2 if t2 is not None else last)
                out.append(_batch(tc, tc["tool_index"], t2))
        for i, rr in enumerate(r for r in rs if r["kind"] == "run"):
            # 중간 스냅숏(snapshot_at_ms)이면 그 시각, 아니면 그 실행에서 본 가장 늦은 시각(하한)
            out.append(_batch(rr, i, rr.get("snapshot_at_ms") if rr.get("snapshot_at_ms") is not None else last))
    return out


def canonical_usage(provider: str, usage: dict) -> "tuple[dict, list]":
    """공급자 usage -> (정준 토큰 dict, 주석). 못 본 칸은 dict 에 넣지 않는다.
    OpenAI · Gemini 는 SDK 소스(D)로만 확인한 꼴이다 -- 실제 응답으로 확인하지 않았다."""
    notes = []
    if provider == "anthropic":
        m = {"tokens.input_uncached": "input_tokens", "tokens.cache_read": "cache_read_input_tokens",
             "tokens.cache_write": "cache_creation_input_tokens", "tokens.output": "output_tokens"}
        out = {k: usage[v] for k, v in m.items() if usage.get(v) is not None}
        th = (usage.get("output_tokens_details") or {}).get("thinking_tokens")
        if th is not None:
            out["tokens.reasoning"] = th
        return out, notes
    if provider == "openai":
        pt = usage.get("prompt_tokens", usage.get("input_tokens"))
        det = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        cd = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
        out = {}
        cached = det.get("cached_tokens")
        if pt is not None and cached is not None:
            out["tokens.input_uncached"] = pt - cached
            out["tokens.cache_read"] = cached
            notes.append("openai: prompt_tokens 는 캐시 포함 -> input_uncached = prompt − cached")
        if det.get("cache_write_tokens") is not None:
            out["tokens.cache_write"] = det["cache_write_tokens"]
        ct = usage.get("completion_tokens", usage.get("output_tokens"))
        if ct is not None:
            out["tokens.output"] = ct
        if cd.get("reasoning_tokens") is not None:
            out["tokens.reasoning"] = cd["reasoning_tokens"]
        return out, notes
    if provider == "gemini":
        g = {k: usage.get(k) for k in ("prompt_token_count", "cached_content_token_count", "candidates_token_count",
                                       "thoughts_token_count", "tool_use_prompt_token_count")}
        out = {}
        if g["prompt_token_count"] is not None and g["cached_content_token_count"] is not None:
            out["tokens.input_uncached"] = (g["prompt_token_count"] - g["cached_content_token_count"]
                                            + (g["tool_use_prompt_token_count"] or 0))
            out["tokens.cache_read"] = g["cached_content_token_count"]
            notes.append("gemini: prompt 는 캐시 포함, 도구 결과 입력은 따로 -> input_uncached = prompt − cached + tool_use")
        if g["candidates_token_count"] is not None:
            out["tokens.output"] = g["candidates_token_count"] + (g["thoughts_token_count"] or 0)
            notes.append("gemini: candidates 는 생각 제외 -> output = candidates + thoughts")
        if g["thoughts_token_count"] is not None:
            out["tokens.reasoning"] = g["thoughts_token_count"]
        return out, notes
    raise ValueError(f"모르는 공급자 {provider!r}")
