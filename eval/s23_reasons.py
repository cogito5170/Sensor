"""S23 (baseline#3 CMD-S23): 결과를 못 본 도구 호출의 UNKNOWN 이유를 실기록에서 센다 -- 기다리는 중 · 원천이 안 줌 · 모른다.

    PYTHONPATH=../Telemetry python3 eval/s23_reasons.py cc_jsonl <a.jsonl> ... -- cc_stream <b> ... -- sweagent <c.traj.gz> ...

세 자리에서 잰다:
    end        실행 전체(eval/l1_on_l0.py 의 길) 뒤 -- 실행 실체의 execution_health 와 도구 실체마다의 tool_execution_health
    at_start   L0 를 사건 순서로 흘려 넣어 첫 tool.start 를 받은 순간(앞 사건만으로 지은 엔진)
    at_end     같은 도구의 tool.end 를 받은 순간
내용은 내지 않는다 -- 이유의 갈래와 수만.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_eval import _events  # noqa: E402
from llmsensor.sensing.liveness import batches  # noqa: E402
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402

KINDS = (("기다리는 호출", "mixed"), ("기다리는 중", "waiting"), ("원천이 주지 않는다", "source_gives_none"),
         ("모른다", "cannot_tell"))


def kind(st):
    if st is None:
        return "none"
    if st.status.value != "UNKNOWN":
        return f"value:{st.value}"
    return next((k for s, k in KINDS if s in st.reason), "unknown_other")


def _engine(evs):
    from telemetry.compat import to_sensor_records
    E = StateEngine()
    E.ingest_all(from_telemetry(to_sensor_records(evs)))
    E.ingest_all(batches(evs))
    return E


def one(source, path):
    evs = sorted(_events(source, path, f"{source}:{Path(path).name.split('.')[0]}"), key=lambda e: e["seq"])
    E = _engine(evs)
    agent = next((s for (e, n), s in E.current.items() if n == "execution_health" and e.startswith("agent:")), None)
    tools = [kind(s) for (e, n), s in E.current.items() if n == "tool_execution_health"]
    k = next((i for i, e in enumerate(evs) if e["type"] == "tool.start"), None)
    out = {"end_agent": kind(agent), "end_tools": tools}
    if k is not None:
        idx = evs[k]["data"].get("tool_index")
        j = next((i for i, e in enumerate(evs) if e["type"] == "tool.end" and e["data"].get("tool_index") == idx), None)
        for name, n in (("at_start", k + 1), ("at_end", None if j is None else j + 1)):
            if n is not None:
                En = _engine(evs[:n])
                out[name] = kind(next((s for (e, m), s in En.current.items()
                                       if m == "execution_health" and e.startswith("agent:")), None))
    return out


def main(argv=None):
    a = list(argv if argv is not None else sys.argv[1:])
    groups, cur = [], None
    for x in a:
        if x == "--":
            cur = None
        elif cur is None:
            cur = (x, [])
            groups.append(cur)
        else:
            cur[1].append(x)
    out = {}
    for source, paths in groups:
        rows = [one(source, p) for p in paths]
        out[source] = {"runs": len(rows),
                       "end_agent": dict(collections.Counter(r["end_agent"] for r in rows).most_common()),
                       "end_tool_entities": dict(collections.Counter(t for r in rows for t in r["end_tools"]).most_common()),
                       "at_first_tool_start": dict(collections.Counter(r.get("at_start", "-") for r in rows).most_common()),
                       "at_its_tool_end": dict(collections.Counter(r.get("at_end", "-") for r in rows).most_common())}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
