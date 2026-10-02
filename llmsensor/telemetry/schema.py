"""텔레메트리 레코드 꼴 (v2) -- 세 종류. null 인 칸은 그 이름이 **정확히 한 목록**에 있어야 한다.

    unobserved     원천이 그 값을 주지 않았다(칸이 없다) -- 못 봤다
    reported_null  원천이 그 칸을 **null 로 주었다** -- 봤고, 값이 null 이다
                   (예: claude -p result 의 api_error_status: null = 오류가 보고되지 않았다)

0 과 '안 보임' 을 섞지 않고, '보고된 null' 과 '안 보임' 도 섞지 않으려는 것이다.
v1 은 둘을 다 unobserved 로 적어서 "오류 없음" 과 "못 봄" 을 못 갈랐다(2026-10-01 결과 문서의 한계 1).

    model_call   모형 호출 하나(응답 하나)
    tool_call    도구 호출 하나와 그 결과
    run          실행(과업) 하나의 끝 요약 -- 런타임이 준 값만. 합계를 우리가 내지 않는다(그것은 derive)

`python3 -m llmsensor.telemetry.schema` 가 schema/telemetry.schema.json 을 쓴다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SOURCES = ["cc_jsonl", "cc_stream", "sweagent"]
INT = {"type": ["integer", "null"], "minimum": 0}
NUM = {"type": ["number", "null"]}
STR = {"type": ["string", "null"]}
BOOL = {"type": ["boolean", "null"]}
SCHEMA_VERSION = 3   # v3: 덧붙이기만 -- timed_out · 캐시 쓰기 5m/1h · 요금 한도 상태/문턱
COMMON = {"kind": {"type": "string"}, "run_id": {"type": "string", "minLength": 1},
          "source": {"enum": SOURCES}, "unobserved": {"type": "array", "items": {"type": "string"}},
          "reported_null": {"type": "array", "items": {"type": "string"}}}

MODEL_CALL_FIELDS = {
    "call_index": {"type": "integer", "minimum": 0},
    "model": STR,
    "t_start_ms": NUM, "t_end_ms": NUM,           # 첫/마지막 관측(유닉스 ms 또는 수집기 단조 ms -- time_base)
    "time_base": {"enum": ["unix_ms", "monotonic_ms", None]},
    "input_tokens": INT, "cache_read_input_tokens": INT, "cache_creation_input_tokens": INT,
    "output_tokens": INT, "thinking_tokens": INT, "server_tool_requests": INT, "iterations": INT,
    "cache_creation_5m_input_tokens": INT, "cache_creation_1h_input_tokens": INT,     # v3 -- 쓰기 값이 다르다
    "stop_reason": STR, "tool_calls_per_message": INT, "output_text_chars": INT,
    "thinking_duration_ms": NUM, "first_chunk_ms": NUM, "stream_chunks": INT, "stream_thinking_estimate": INT,
    "context_window": INT,
}
TOOL_CALL_FIELDS = {
    "call_index": {"type": "integer", "minimum": 0},  # 그 도구를 부른 모형 호출
    "tool_index": {"type": "integer", "minimum": 0},  # 실행 안 도구 순번
    "tool_name": {"type": "string"}, "tool_head": {"type": "string"}, "tool_sig": {"type": "string"},
    "tool_input_chars": INT, "t_issued_ms": NUM, "t_result_ms": NUM, "time_base": {"enum": ["unix_ms",
                                                                                              "monotonic_ms", None]},
    "reported_duration_ms": NUM, "is_error": BOOL, "interrupted": BOOL, "tool_output_chars": INT,
    "timed_out": BOOL,   # v3 -- 런타임 선언 문구("Command timed out after", Bash). 다른 도구의 문구는 몰라 null
}
RUN_FIELDS = {
    "model": STR, "run_duration_ms": NUM, "api_duration_ms": NUM, "api_duration_without_retries_ms": NUM,
    "ttft_ms": NUM, "num_turns": INT, "cost_usd": NUM, "terminal_reason": STR, "result_subtype": STR,
    "is_error": BOOL, "api_error_status": STR, "permission_denials": INT, "context_window": INT,
    "max_output_tokens": INT, "autocompact_threshold": INT, "rate_limit_utilization": NUM,
    "rate_limit_status": STR, "rate_limit_threshold": NUM,     # v3 -- 런타임 선언(allowed_warning · surpassedThreshold)
    "snapshot_at_ms": NUM,   # v3 -- 이 요약이 실행 끝이 아니라 중간 스냅숏일 때 그 시각(Claude Code cost-state)
    "tokens_sent": INT, "tokens_received": INT, "api_calls": INT,       # 런타임이 준 실행 합계(있으면)
    "reported_input_tokens": INT, "reported_output_tokens": INT, "reported_cache_read_input_tokens": INT,
    "reported_cache_creation_input_tokens": INT,
}


def _schema(kind, fields):
    props = dict(COMMON, **fields)
    props["kind"] = {"const": kind}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": f"llm-telemetry/{kind}",
            "type": "object", "required": list(props), "additionalProperties": False, "properties": props}


SCHEMAS = {"model_call": _schema("model_call", MODEL_CALL_FIELDS),
           "tool_call": _schema("tool_call", TOOL_CALL_FIELDS),
           "run": _schema("run", RUN_FIELDS)}
FIELDS = {"model_call": MODEL_CALL_FIELDS, "tool_call": TOOL_CALL_FIELDS, "run": RUN_FIELDS}


def record(kind: str, run_id: str, source: str, reported_null=(), **vals) -> dict:
    """빈 칸은 null. reported_null 에 든 이름은 '원천이 null 로 줬다', 나머지 null 은 unobserved."""
    r = {"kind": kind, "run_id": run_id, "source": source}
    extra = (set(vals) | set(reported_null)) - set(FIELDS[kind])
    if extra:
        raise KeyError(f"{kind}: 꼴에 없는 칸 {sorted(extra)}")
    rn = set(reported_null)
    for k in FIELDS[kind]:
        r[k] = vals.get(k)
        if k in rn and r[k] is not None:
            raise ValueError(f"{kind}.{k}: reported_null 인데 값이 있다 ({r[k]!r})")
    r["unobserved"] = [k for k in FIELDS[kind] if r[k] is None and k not in rn]
    r["reported_null"] = [k for k in FIELDS[kind] if r[k] is None and k in rn]
    return r


def observed(rec: dict, k: str) -> bool:
    """그 칸을 봤나 -- 값이 있거나, 원천이 null 로 보고했으면 봤다."""
    return rec.get(k) is not None or k in rec.get("reported_null", ())


def check(rec: dict) -> "list[str]":
    from ..sensors.constraint import validate
    if rec.get("kind") not in SCHEMAS:
        return ["kind?"]
    errs, unk = validate(rec, SCHEMAS[rec["kind"]])
    for k in FIELDS[rec["kind"]]:
        lists = (k in rec.get("unobserved", [])) + (k in rec.get("reported_null", []))
        if rec.get(k) is None and lists != 1:
            errs.append(f"null 인 {k} 가 unobserved/reported_null 중 정확히 하나에 있어야 한다 ({lists})")
        if rec.get(k) is not None and lists:
            errs.append(f"값이 있는 {k} 가 null 목록에 있다")
    return errs + [f"검사 못 함: {u}" for u in unk if not u.endswith(":$schema")]


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "schema/telemetry.schema.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"$id": f"llm-telemetry/v{SCHEMA_VERSION}", "description": __doc__.strip().splitlines()[0],
                               "oneOf": list(SCHEMAS.values())}, ensure_ascii=False, indent=1))
    print(out)
