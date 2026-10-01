"""텔레메트리 레코드 꼴 -- 세 종류. 못 본 값은 null 이고 그 이름을 `unobserved` 에 **반드시** 적는다.

0 과 '안 보임' 을 섞지 않으려는 것이다. 예: SWE-agent 추적의 호출별 토큰은 null + unobserved 에 이름.

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
COMMON = {"kind": {"type": "string"}, "run_id": {"type": "string", "minLength": 1},
          "source": {"enum": SOURCES}, "unobserved": {"type": "array", "items": {"type": "string"}}}

MODEL_CALL_FIELDS = {
    "call_index": {"type": "integer", "minimum": 0},
    "model": STR,
    "t_start_ms": NUM, "t_end_ms": NUM,           # 첫/마지막 관측(유닉스 ms 또는 수집기 단조 ms -- time_base)
    "time_base": {"enum": ["unix_ms", "monotonic_ms", None]},
    "input_tokens": INT, "cache_read_input_tokens": INT, "cache_creation_input_tokens": INT,
    "output_tokens": INT, "thinking_tokens": INT, "server_tool_requests": INT, "iterations": INT,
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
}
RUN_FIELDS = {
    "model": STR, "run_duration_ms": NUM, "api_duration_ms": NUM, "api_duration_without_retries_ms": NUM,
    "ttft_ms": NUM, "num_turns": INT, "cost_usd": NUM, "terminal_reason": STR, "result_subtype": STR,
    "is_error": BOOL, "api_error_status": STR, "permission_denials": INT, "context_window": INT,
    "max_output_tokens": INT, "autocompact_threshold": INT, "rate_limit_utilization": NUM,
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


def record(kind: str, run_id: str, source: str, **vals) -> dict:
    """빈 칸은 null 로 채우고 unobserved 에 이름을 적는다."""
    r = {"kind": kind, "run_id": run_id, "source": source}
    miss = []
    for k in FIELDS[kind]:
        v = vals.get(k)
        r[k] = v
        if v is None:
            miss.append(k)
    extra = set(vals) - set(FIELDS[kind])
    if extra:
        raise KeyError(f"{kind}: 꼴에 없는 칸 {sorted(extra)}")
    r["unobserved"] = miss
    return r


def check(rec: dict) -> "list[str]":
    from ..sensors.constraint import validate
    errs, unk = validate(rec, SCHEMAS[rec.get("kind", "?")]) if rec.get("kind") in SCHEMAS else (["kind?"], [])
    errs += [f"unobserved 불일치: {k}" for k in FIELDS[rec["kind"]] if (rec[k] is None) != (k in rec["unobserved"])] \
        if rec.get("kind") in FIELDS else []
    return errs + [f"검사 못 함: {u}" for u in unk if not u.endswith(":$schema")]


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "schema/telemetry.schema.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"$id": "llm-telemetry", "description": __doc__.strip().splitlines()[0],
                               "oneOf": list(SCHEMAS.values())}, ensure_ascii=False, indent=1))
    print(out)
