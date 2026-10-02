"""L1 센서를 **L0 사건**에서 돌린다 -- 원천 -> Telemetry 수집기(L0) -> 꼴 v3 레코드(compat) + L0 묶기(liveness) -> 상태.

    PYTHONPATH=../Telemetry python3 eval/l1_on_l0.py cc_jsonl <세션.jsonl> [cc_stream <캡처.stream.jsonl> ...]

내용은 내지 않는다 -- 사건 수 · 상태 값 · 처분 수만. L0 패키지(cogito5170/Telemetry)가 있어야 돈다(선택 의존).

**덧대기 하나(표시해 둔다):** L0 tool.end 의 `moved_to_background` 는 아직 꼴 v3 레코드(compat)에 실리지 않는다(Telemetry
에 요청). 그동안 이 스크립트가 tool_index 로 L0 사건의 그 칸을 레코드에 이어 붙인다. Telemetry 가 싣게 되면 이 덧대기를 지운다.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.sensing.liveness import batches  # noqa: E402
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402

CARRY = ("moved_to_background",)        # L0 tool.end -> 꼴 v3 tool_call 에 아직 안 실리는 칸(덧대기)


def run(source: str, path: str, run_id: str) -> dict:
    from telemetry import collect
    from telemetry.compat import to_sensor_records
    evs = {"cc_jsonl": collect.from_cc_jsonl, "cc_stream": collect.from_cc_stream,
           "sweagent": collect.from_sweagent}[source](path, run_id)
    recs = to_sensor_records(evs)
    ends = {e["data"]["tool_index"]: e for e in evs if e["type"] == "tool.end"}
    shimmed = 0
    for r in recs:
        if r["kind"] != "tool_call":
            continue
        e = ends.get(r.get("tool_index"))
        for k in CARRY:
            if k not in r and e is not None and e["data"].get(k) is not None:
                r[k] = e["data"][k]
                shimmed += 1
    E = StateEngine()
    E.ingest_all(from_telemetry(recs))
    E.ingest_all(batches(evs))
    want = ("liveness_state", "execution_interruption", "execution_health", "runtime_reliability", "resource_state")
    states = {f"{n}@{ent.split(':')[0]}": (st.status.value, st.value) for (ent, n), st in sorted(E.current.items())
              if n in want and not ent.startswith("tool:")}
    types = collections.Counter(e["type"] for e in evs)
    return {"source": source, "events": len(evs), "records": len(recs), "shimmed_fields": shimmed,
            "event_types": dict(sorted(types.items())), "states": states}


def main(argv=None):
    a = list(argv if argv is not None else sys.argv[1:])
    out = []
    for i in range(0, len(a), 2):
        out.append(run(a[i], a[i + 1], f"{a[i]}:{Path(a[i + 1]).name.split('.')[0]}"))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
