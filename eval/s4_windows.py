"""S4 창 (baseline#3 CMD-S21) 을 실기록에서 -- 값이 선 수, 여유를 정한 창, v1(1 − 런타임 사용률)과의 차이.

    PYTHONPATH=../Telemetry python3 eval/s4_windows.py cc_stream <a.stream.jsonl> ... [-- cc_jsonl <b.jsonl> ...]

원천 -> L0 -> compat 레코드 + L0 묶기 -> 지표 (eval/l1_on_l0.py 와 같은 길). 내용은 내지 않는다 -- 창 이름 · 수만.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.sensing.liveness import batches  # noqa: E402
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402


def _last(E, ent, name):
    ms = [m for i, m in E.metrics.items() if i.startswith(f"{ent}/{name}@")]
    return max(ms, key=lambda m: int(str(m.id.rsplit("@", 1)[1]).split("+")[0])) if ms else None


def one(source, path):
    from telemetry import collect
    from telemetry.compat import to_sensor_records
    run_id = f"{source}:{Path(path).name.split('.')[0]}"
    evs = {"cc_jsonl": collect.from_cc_jsonl, "cc_stream": collect.from_cc_stream}[source](path, run_id)
    recs = to_sensor_records(evs)
    E = StateEngine()
    E.ingest_all(from_telemetry(recs))
    E.ingest_all(batches(evs))
    ent = f"runtime:{run_id}"
    h, t, w, ra = (_last(E, ent, n) for n in ("quota_headroom", "quota_time_to_reset_ms", "quota_windows", "quota_resets_at_ms"))
    u = [r.get("rate_limit_utilization") for r in recs if r["kind"] == "run" and r.get("rate_limit_utilization") is not None]
    deciding = re.findall(r"(\w+)\(사용률", h.reason) if h is not None and h.value is not None else []
    return {"window_events": sum(e["type"] == "provider.rate_limit_window" for e in evs),
            "windows": sorted(w.value) if w is not None and w.value else [],
            "headroom": h.value if h else None, "deciding": deciding,
            "v1_headroom": round(1 - u[-1], 6) if u else None,
            "time_to_reset": t.value if t else None,
            "resets_at": ra.value if ra else None,
            "resets_at_agrees": (ra is not None and w is not None and bool(w.value) and bool(deciding)
                                 and ra.value == max(w.value[n]["resets_at_ms"] for n in deciding)),
            "time_to_reset_why": (t.reason.split(" -- ")[0] if t is not None and t.value is None else None),
            "resets_declared": sum(x["resets_at_ms"] is not None for x in (w.value or {}).values()) if w is not None else 0}


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
        rows = {Path(p).name.split(".")[0]: one(source, p) for p in paths}
        out[source] = {
            "runs": len(rows),
            "with_windows": sum(bool(r["windows"]) for r in rows.values()),
            "window_sets": dict(collections.Counter(",".join(r["windows"]) for r in rows.values())),
            "headroom_valued": sum(r["headroom"] is not None for r in rows.values()),
            "deciding_window": dict(collections.Counter(",".join(r["deciding"]) or "-" for r in rows.values())),
            "headroom_differs_from_v1": sum(r["headroom"] != r["v1_headroom"] for r in rows.values()),
            "time_to_reset_valued": sum(r["time_to_reset"] is not None for r in rows.values()),
            "resets_at_valued": sum(r["resets_at"] is not None for r in rows.values()),
            "resets_at_agrees_with_window_event": sum(r["resets_at_agrees"] for r in rows.values()),
            "time_to_reset_none_why": dict(collections.Counter(r["time_to_reset_why"] for r in rows.values()
                                                               if r["time_to_reset"] is None)),
            "declared_resets_carried": sum(r["resets_declared"] for r in rows.values()),
            "per_run": rows,
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
