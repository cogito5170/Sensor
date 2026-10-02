"""Phase 8 -- 끝에서 끝까지: 실제 레코드를 한 묶음씩 다시 흘리며, 묶음마다 결정 문맥을 만들고 참조 정책을 돌린다.

    python3 eval/ms_end_to_end.py [--out eval/results/ms_end_to_end.json]

재는 것(과제 §18 · §19):
  팩 · 상태마다   computability = 쓸 수 있는 평가점 / 전체 평가점 (평가점 = 묶음 하나를 받은 직후)
                 unknown_rate · stale_rate (실행 끝, now = 마지막 관측 / 마지막 관측 + 1 시간)
                 provenance_coverage = 근거 사슬이 관측 id 까지 닿는 쓸 수 있는 상태 / 쓸 수 있는 상태
  결정론          전체를 두 번 돌려 결정 · 문맥 id 의 해시가 같은가
  정책 쓸모       상태가 바뀐 평가점 -> 문맥이 바뀌었나 -> 결정이 바뀌었나, state_impact_rate = 둘 다 / 상태 바뀜

가정(결과에 적는다): 능력 = {"compaction": True, "providers": 2}. 외부 라벨 = SWE-bench Lite 판정(eval/data).
참조 정책은 MS 정책이 아니다 -- 쓸모 지표는 '이 참조 정책에 대한' 쓸모다.
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
from llmsensor.decision.context import ContextBuilder  # noqa: E402
from llmsensor.policy import context as cpol, execution as epol, provider as ppol  # noqa: E402
from llmsensor.sensing.quality import external_label_batch  # noqa: E402
from llmsensor.state import REGISTRY, StateEngine, from_telemetry  # noqa: E402
from llmsensor.state.model import Freshness, Status  # noqa: E402

HERE = Path(__file__).resolve().parent
REC = HERE / "results" / "sensor_layer_records.jsonl.gz"
LABELS = HERE / "data" / "swe_lite_20240620_sweagent_claude35sonnet_results.json"
CAP = {"compaction": True, "providers": 2}
POLICIES = (("manage_context", cpol), ("select_provider", ppol), ("continue_or_stop", epol))


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
    B = ContextBuilder(E, capture_provenance=False)
    comp = collections.Counter()           # (source, state) -> [usable points]
    total = collections.Counter()
    seqs = collections.defaultdict(list)   # (run, purpose) -> [(views, ctx_id, action)]
    digest = hashlib.sha256()
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
            for purpose, pol in POLICIES:
                c = B.build(run, purpose, capabilities=CAP)
                d = pol.decide(c)
                views = tuple((s.name, s.value, s.status, s.usable) for s in c.states)
                material = (views, c.available_actions, c.validity)     # 나이 · as_of 는 뺀 결정 관련 내용
                seqs[(run, purpose)].append((views, material, d.action, d.used))
                digest.update(f"{run}|{purpose}|{c.context_id}|{d.action}".encode())
    return E, comp, total, seqs, digest.hexdigest()


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


def impact(seqs):
    """상태 바뀜 -> 문맥 바뀜 -> 결정 바뀜. 사소한 설명 둘을 갈라 센다:
       (1) 동시 변화: 실행 끝에는 여러 상태가 한꺼번에 바뀐다 -> 그 상태 '혼자' 바뀐 점만 따로 센다
       (2) 쓰이지 않는 상태: 결정이 바뀌었어도 정책이 그 상태를 안 썼으면 그 상태 덕이 아니다 -> 'used' 로 귀속"""
    C = collections.Counter
    ch, co, alone, alone_hit, used_hit = C(), C(), C(), C(), C()
    ctx_changes = dec_changes = points = 0
    by_purpose = C()
    for (run, purpose), seq in seqs.items():
        for prev, cur in zip(seq, seq[1:]):
            points += 1
            pv, cv = dict((x[0], x[1:]) for x in prev[0]), dict((x[0], x[1:]) for x in cur[0])
            ctx_changed = prev[1] != cur[1]
            dec_changed = prev[2] != cur[2]
            ctx_changes += ctx_changed
            dec_changes += dec_changed
            by_purpose[purpose] += dec_changed
            changed = [n for n in set(pv) | set(cv) if pv.get(n) != cv.get(n)]
            for n in changed:
                ch[(purpose, n)] += 1
                co[(purpose, n)] += dec_changed
                used_hit[(purpose, n)] += dec_changed and (n in prev[3] or n in cur[3])
                if len(changed) == 1:
                    alone[(purpose, n)] += 1
                    alone_hit[(purpose, n)] += dec_changed
    rates = {f"{p}/{n}": {"state_changes": ch[(p, n)], "with_decision_change": co[(p, n)],
                          "state_impact_rate": co[(p, n)] / ch[(p, n)],
                          "used_impact_rate": used_hit[(p, n)] / ch[(p, n)],
                          "alone_changes": alone[(p, n)],
                          "alone_impact_rate": (alone_hit[(p, n)] / alone[(p, n)]) if alone[(p, n)] else None}
             for (p, n) in sorted(ch)}
    return {"points": points, "material_context_changes": ctx_changes, "decision_changes": dec_changes,
            "by_state": rates, "decision_changes_by_purpose": dict(by_purpose)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/results/ms_end_to_end.json")
    a = ap.parse_args(argv)
    recs = load()
    E, comp, total, seqs, dg = replay(recs)
    _, _, _, _, dg2 = replay(recs)
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
    out = {"runs": len(E.ledgers), "deterministic": dg == dg2, "decision_digest": dg[:16],
           "assumptions": {"capabilities": CAP, "external_labels": LABELS.name,
                           "policies": "reference-*-v1 (not MS)"},
           "packs": packs, "policy_usefulness": impact(seqs)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("runs", "deterministic", "decision_digest")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
