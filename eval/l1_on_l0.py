"""L1 센서를 **L0 사건**에서 돌린다 -- 원천 -> Telemetry 수집기(L0) -> 꼴 v3 레코드(compat) + L0 묶기(liveness) -> 상태.

    PYTHONPATH=../Telemetry python3 eval/l1_on_l0.py cc_jsonl <세션.jsonl> [cc_stream <캡처.stream.jsonl> ...]

내용은 내지 않는다 -- 사건 수 · 상태 값 · 처분 수만. L0 패키지(cogito5170/Telemetry)가 있어야 돈다(선택 의존).

S2 의 처분(tool.end.moved_to_background)과 S4 의 리셋 시각(provider.rate_limit.resets_at_ms)은 L0 묶기가 사건에서 **직접**
읽는다(BD-80 · CMD-S16). 예전의 tool_index 덧대기는 걷었다.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.sensing.liveness import batches  # noqa: E402
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402



def run(source: str, path: str, run_id: str) -> dict:
    from telemetry import collect
    from telemetry.compat import to_sensor_records
    evs = {"cc_jsonl": collect.from_cc_jsonl, "cc_stream": collect.from_cc_stream,
           "sweagent": collect.from_sweagent}[source](path, run_id)
    recs = to_sensor_records(evs)
    E = StateEngine()
    E.ingest_all(from_telemetry(recs))
    E.ingest_all(batches(evs))
    want = ("liveness_state", "execution_interruption", "execution_health", "runtime_reliability", "resource_state",
            "rate_limit_state", "dependency_fault")
    states = {}
    for (ent, n), st in sorted(E.current.items()):
        if n not in want or ent.startswith("tool:"):
            continue
        kind = ent.split(":", 1)[0]
        label = f"{kind}:{ent.rsplit(':', 1)[1]}" if kind == "dependency" else kind      # 의존 대상은 이름까지
        states[f"{n}@{label}"] = (st.status.value, st.value)
    types = collections.Counter(e["type"] for e in evs)
    return {"source": source, "events": len(evs), "records": len(recs),
            "event_types": dict(sorted(types.items())), "states": states}


def main(argv=None):
    a = list(argv if argv is not None else sys.argv[1:])
    out = []
    for i in range(0, len(a), 2):
        out.append(run(a[i], a[i + 1], f"{a[i]}:{Path(a[i + 1]).name.split('.')[0]}"))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
