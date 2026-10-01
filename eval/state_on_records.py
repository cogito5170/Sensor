"""상태 층을 앞 실험의 실제 레코드 전부에 돌려, 상태마다 **원천별로 얼마나 판정되나**를 센다(서술 -- 예측 평가 아님).

    python3 eval/state_on_records.py [--out eval/results/state_on_records.json]

세는 것: 실행 끝의 상태 값 · 유효성 분포(원천별), 실행당 전이 수(흔들림), 결정성(두 번 돌려 같은가),
되돌림(쓸 수 있는 상태마다 explain 사슬이 실제 관측 id 에 닿는가).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402

REC = Path(__file__).resolve().parent / "results" / "sensor_layer_records.jsonl.gz"


def run(records):
    return StateEngine().ingest_all(from_telemetry(records))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/results/state_on_records.json")
    a = ap.parse_args(argv)
    with gzip.open(REC, "rt", encoding="utf-8") as f:
        recs = [json.loads(x) for x in f]
    recs = [r for r in recs if not r["run_id"].startswith("cc_jsonl_child:")]     # 같은 실행을 두 번 세지 않는다
    E = run(recs)
    E2 = run(recs)
    out = {"runs": len(E.ledgers), "deterministic": E.snapshot() == E2.snapshot()}
    dist = collections.defaultdict(lambda: collections.Counter())
    for (ent, name), st in E.current.items():
        src = ent.split(":")[1]
        v = E.view(st)
        dist[f"{name}/{src}"][f"{v.status.value}:{v.value}"] += 1
    out["final_state_distribution"] = {k: dict(sorted(c.items())) for k, c in sorted(dist.items())}
    tr = collections.Counter()
    for t in E.transitions:
        tr[(t.entity_id, t.name)] += 1
    per = collections.defaultdict(list)
    for (ent, name), st in E.current.items():
        per[f"{name}/{ent.split(':')[1]}"].append(tr.get((ent, name), 0))
    out["transitions_per_entity"] = {k: {"median": statistics.median(v), "max": max(v), "n": len(v)}
                                     for k, v in sorted(per.items())}
    bad = []
    usable = 0
    for (ent, name), st in E.current.items():
        if st.status.usable:
            usable += 1
            ids = E.observation_ids(ent, name)
            if not ids or not ids <= set(E.observations):
                bad.append(f"{ent}|{name}")
    out["provenance"] = {"usable_states": usable, "without_observation_chain": len(bad), "examples": bad[:5]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
