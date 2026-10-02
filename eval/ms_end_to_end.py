"""Phase 8 -- 끝에서 끝까지: 실제 레코드를 한 묶음씩 다시 흘리며, 묶음마다 상태가 쓸 수 있는지 잰다.

    python3 eval/ms_end_to_end.py [--out eval/results/ms_end_to_end.json]

재는 것(과제 §18 · §19):
  팩 · 상태마다   computability = 쓸 수 있는 평가점 / 전체 평가점 (평가점 = 묶음 하나를 받은 직후)
                 unknown_rate · stale_rate (실행 끝, now = 마지막 관측 / 마지막 관측 + 1 시간)
                 provenance_coverage = 근거 사슬이 관측 id 까지 닿는 쓸 수 있는 상태 / 쓸 수 있는 상태
  결정론          전체를 두 번 돌려 상태 스냅숏의 해시가 같은가

가정(결과에 적는다): 외부 라벨 = SWE-bench Lite 판정(eval/data).

**정책 쓸모(상태 바뀜 -> 문맥 바뀜 -> 결정 바뀜)는 여기서 뺐다.** 결정 문맥과 참조 정책을 DC 저장소로 합치면서(baseline PC-08)
그 측정도 옮겼다: cogito5170/DC `eval/policy_impact.py` (Sensor 내보내기 계약으로 같은 레코드를 읽는다).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.sensing.quality import external_label_batch  # noqa: E402
from llmsensor.state import REGISTRY, StateEngine, from_telemetry  # noqa: E402
from llmsensor.state.model import Freshness, Status  # noqa: E402

HERE = Path(__file__).resolve().parent
REC = HERE / "results" / "sensor_layer_records.jsonl.gz"
LABELS = HERE / "data" / "swe_lite_20240620_sweagent_claude35sonnet_results.json"


def load():
    with gzip.open(REC, "rt", encoding="utf-8") as f:
        recs = [json.loads(x) for x in f]
    return [r for r in recs if not r["run_id"].startswith("cc_jsonl_child:")]


def labels():
    d = json.loads(LABELS.read_text())
    return set(d["resolved"]), set(d.get("no_logs", []))


def replay(recs):
    resolved, nolog = labels()
    batches = from_telemetry(recs)
    byrun = collections.defaultdict(list)
    for b in batches:
        byrun[b.run_id].append(b)
    E = StateEngine()
    comp = collections.Counter()           # (source, state) -> [usable points]
    total = collections.Counter()
    for run in sorted(byrun):
        src = run.split(":")[0]
        extra = []
        if src == "sweagent":
            iid = run.split(":", 1)[1]
            if iid not in nolog:
                extra.append(external_label_batch(run, iid in resolved, "swe-bench-lite hidden tests", iid))
        for b in byrun[run] + extra:
            E.ingest(b)
            for key in sorted(E.by_run.get(run, ())):
                st, name = E.current[key], key[1]
                total[(src, name)] += 1
                v = E.view(st)
                comp[(src, name)] += v.status.usable and v.freshness is not Freshness.STALE
    digest = hashlib.sha256(json.dumps(E.snapshot(), sort_keys=True, ensure_ascii=False, default=str).encode())
    return E, comp, total, digest.hexdigest()


def end_rates(E):
    out = collections.defaultdict(lambda: collections.Counter())
    known = set(E.observations)
    for run, keys in E.by_run.items():
        src = run.split(":")[0]
        last = E.ledgers[run].last_at
        for ent, name in sorted(keys):
            st = E.current[(ent, name)]
            v0 = E.view(st)
            v1 = E.view(st, None if last is None else last + 3_600_000)
            c = out[(src, name)]
            c["n"] += 1
            c["unknown"] += v0.status is Status.UNKNOWN
            c["na"] += v0.status is Status.NOT_APPLICABLE
            c["usable"] += v0.status.usable and v0.freshness is not Freshness.STALE
            c["stale_at_end"] += v0.freshness is Freshness.STALE
            c["stale_after_1h"] += v1.freshness is Freshness.STALE
            c["untimed"] += v0.freshness is Freshness.UNTIMED
            if v0.status.usable:
                c["usable_any"] += 1
                ids = E.observation_ids(ent, name)
                c["prov_ok"] += bool(ids) and ids <= known
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/results/ms_end_to_end.json")
    a = ap.parse_args(argv)
    recs = load()
    E, comp, total, dg = replay(recs)
    _, _, _, dg2 = replay(recs)
    er = end_rates(E)
    packs = {}
    for name in REGISTRY.rules:
        pk = REGISTRY.pack_of(name)
        for src in ("cc_stream", "cc_jsonl_self", "sweagent"):
            n = total[(src, name)]
            if not n:
                continue
            e = er[(src, name)]
            packs.setdefault(pk, {})[f"{name}/{src}"] = {
                "computability": comp[(src, name)] / n, "eval_points": n, "entities": e["n"],
                "unknown_rate": e["unknown"] / e["n"], "not_applicable_rate": e["na"] / e["n"],
                "stale_rate_at_end": e["stale_at_end"] / e["n"], "stale_rate_after_1h": e["stale_after_1h"] / e["n"],
                "untimed_rate": e["untimed"] / e["n"],
                "provenance_coverage": (e["prov_ok"] / e["usable_any"]) if e["usable_any"] else None}
    out = {"runs": len(E.ledgers), "deterministic": dg == dg2, "state_digest": dg[:16],
           "assumptions": {"external_labels": LABELS.name},
           "packs": packs,
           "policy_usefulness": "moved to cogito5170/DC eval/policy_impact.py (baseline PC-08)"}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("runs", "deterministic", "state_digest")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
