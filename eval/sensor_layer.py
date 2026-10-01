"""사전등록 eval/PREREG_sensor_layer.md 의 분석. 레코드(JSONL)만 읽는다.

    python3 eval/sensor_layer.py <records.jsonl> [--out eval/results/sensor_layer.json]

하는 일(정해 둔 그대로):
  1. 가용성: 원천 × 칸마다 null 이 아닌 비율(실측 신뢰도)
  2. 독립 대조: 같은 모형 호출을 두 수집기(cc_stream · 자식 cc_jsonl)가 본 값이 같은가 + 런타임 합계와의 차
  3. 호출 단위 중복: Spearman ρ · 정규화 상호정보(5 분위) -- 원천별로도 따로
  4. 걸음 번호(시계)와의 ρ, 실행 안 1 차 차분의 ρ
  5. 실행 단위 중복(SWE-agent 287)
  6. 중복 무리와 대표(형 1 > 형 2 > 원천 가용성 > 이름)
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.telemetry.catalog import CALL_VARS, CATALOG, RUN_VARS  # noqa: E402
from llmsensor.telemetry.derive import by_run, calls, run_summary  # noqa: E402
from llmsensor.telemetry.schema import FIELDS  # noqa: E402

RHO_RED, RHO_CLOCK, MIN_N, BINS = 0.9, 0.9, 30, 5
ANALYSIS_SOURCES = {"cc_jsonl_self", "cc_stream"}       # 자식 cc_jsonl 은 대조에만(같은 호출을 두 번 세지 않는다)


def ranks(x):
    o = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def pairs(rows, a, b):
    return [(r[a], r[b]) for r in rows if r.get(a) is not None and r.get(b) is not None]


def spearman(rows, a, b):
    p = pairs(rows, a, b)
    if len(p) < MIN_N:
        return None, len(p)
    return pearson(ranks([x for x, _ in p]), ranks([y for _, y in p])), len(p)


def nmi(rows, a, b):
    p = pairs(rows, a, b)
    if len(p) < MIN_N:
        return None

    def binned(xs):
        r = ranks(xs)
        n = len(xs)
        return [min(BINS - 1, int(v * BINS / n)) for v in r]
    xa, xb = binned([x for x, _ in p]), binned([y for _, y in p])
    n = len(p)
    ca, cb, cab = collections.Counter(xa), collections.Counter(xb), collections.Counter(zip(xa, xb))
    ha = -sum(c / n * math.log(c / n) for c in ca.values())
    hb = -sum(c / n * math.log(c / n) for c in cb.values())
    if ha == 0 or hb == 0:
        return None
    mi = sum(c / n * math.log((c / n) / (ca[i] / n * cb[j] / n)) for (i, j), c in cab.items())
    return mi / math.sqrt(ha * hb)


def matrix(rows, names):
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            r, n = spearman(rows, a, b)
            out[f"{a}|{b}"] = {"rho": r, "n": n, "nmi": nmi(rows, a, b)}
    return out


def diffs(rows, names):
    """실행 안 1 차 차분 -- 실행마다 자라는 추세(시계)를 지운 뒤의 ρ 를 보려고."""
    byrun = collections.defaultdict(list)
    for r in rows:
        byrun[r["run_id"]].append(r)
    out = []
    for rs in byrun.values():
        rs.sort(key=lambda r: r["step_index"])
        for p, q in zip(rs, rs[1:]):
            out.append({k: (q[k] - p[k] if q.get(k) is not None and p.get(k) is not None else None) for k in names})
    return out


def clusters(names, mat, stable):
    adj = collections.defaultdict(set)
    for k, v in mat.items():
        a, b = k.split("|")
        if v["rho"] is not None and abs(v["rho"]) >= RHO_RED and stable.get(k, True):
            adj[a].add(b)
            adj[b].add(a)
    seen, out = set(), []
    for n in names:
        if n in seen:
            continue
        st, comp = [n], []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            st += list(adj[x])
        out.append(sorted(comp))
    return out


CAT = {s["name"]: s for s in CATALOG}


def rank_key(name):
    s = CAT.get(name)
    typ = s["type"] if s else 2
    if s and s["type"] == 1:
        av = sum(v in ("O", "D") for v in s["availability"].values())
    elif s:
        ins = [CAT.get(d) for d in s["derived_from"] if CAT.get(d)]
        av = min((sum(v in ("O", "D") for v in d["availability"].values()) for d in ins), default=0)
    else:
        av = 0
    return (typ, -av, name)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--out", default="eval/results/sensor_layer.json")
    a = ap.parse_args(argv)
    recs = [json.loads(x) for x in open(a.records, encoding="utf-8") if x.strip()]
    res: dict = {"n_records": len(recs)}

    # 1. 가용성
    av = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in recs:
        tag = r["run_id"].split(":")[0]
        for k in FIELDS[r["kind"]]:
            c = av[f"{tag}/{r['kind']}"][k]
            c[1] += 1
            c[0] += r[k] is not None
    res["availability"] = {g: {k: round(o / t, 3) for k, (o, t) in sorted(d.items())} for g, d in sorted(av.items())}
    res["record_counts"] = dict(collections.Counter(f"{r['run_id'].split(':')[0]}/{r['kind']}" for r in recs))

    runs = by_run(recs)
    # 2. 독립 대조 -- 같은 과업을 cc_stream 과 자식 cc_jsonl 이 본 것
    cross = []
    for rid, run in runs.items():
        if not rid.startswith("cc_stream:"):
            continue
        twin = runs.get("cc_jsonl_child:" + rid.split(":", 1)[1])
        row = {"run": rid}
        keys = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]
        s = {k: sum(m[k] or 0 for m in run["model_call"]) for k in keys}
        if twin:
            j = {k: sum(m[k] or 0 for m in twin["model_call"]) for k in keys}
            row["calls"] = [len(run["model_call"]), len(twin["model_call"])]
            row["stream_vs_jsonl_equal"] = {k: s[k] == j[k] for k in keys}
            row["per_call_equal"] = sum(
                all(p[k] == q[k] for k in keys) for p, q in zip(run["model_call"], twin["model_call"]))
        rr = run["run"][0] if run["run"] else {}
        row["vs_result_usage"] = {k: (s[k], rr.get("reported_" + k)) for k in keys}
        cross.append(row)
    res["cross_check"] = cross

    # 3-4. 호출 단위
    rows = [c for rid, run in runs.items() if rid.split(":")[0] in ANALYSIS_SOURCES for c in calls(run)]
    for c in rows:
        c["_src"] = c["run_id"].split(":")[0]
    res["call_rows"] = dict(collections.Counter(c["_src"] for c in rows))
    names = list(CALL_VARS)
    mat = matrix(rows, names)
    per_src = {s: matrix([c for c in rows if c["_src"] == s], names) for s in sorted(ANALYSIS_SOURCES)}
    stable = {}
    for k, v in mat.items():
        hs = [per_src[s][k]["rho"] for s in per_src if per_src[s][k]["rho"] is not None]
        stable[k] = (len(hs) < 2) or all(abs(h) >= RHO_RED for h in hs)
    res["call_matrix"] = mat
    res["call_matrix_by_source"] = per_src
    res["call_source_dependent"] = sorted(k for k, v in mat.items()
                                          if v["rho"] is not None and abs(v["rho"]) >= RHO_RED and not stable[k])
    res["clock"] = {n: mat.get(f"step_index|{n}", {}).get("rho") for n in names if n != "step_index"}
    dif = diffs(rows, names)
    res["call_matrix_diff"] = matrix(dif, [n for n in names if n != "step_index"])
    res["call_clusters"] = clusters(names, mat, stable)
    res["call_nonmonotone"] = sorted(k for k, v in mat.items() if v["nmi"] is not None and v["nmi"] >= .5
                                     and v["rho"] is not None and abs(v["rho"]) < .5)

    # 5. 실행 단위 (SWE-agent)
    rsum = [run_summary(run) for rid, run in runs.items() if rid.startswith("sweagent:")]
    res["run_rows"] = len(rsum)
    rmat = matrix(rsum, list(RUN_VARS))
    res["run_matrix"] = rmat
    res["run_clusters"] = clusters(list(RUN_VARS), rmat, {})
    res["run_summaries_claude"] = [run_summary(run) for rid, run in runs.items() if rid.split(":")[0] in ANALYSIS_SOURCES]

    # 6. 대표
    def reps(cl, mat_):
        out = []
        for comp in cl:
            measured = [n for n in comp if any(v["rho"] is not None for k, v in mat_.items() if n in k.split("|"))]
            if not measured:
                out.append({"members": comp, "representative": None, "note": "n<30 -- 안 잼"})
                continue
            out.append({"members": comp, "representative": sorted(comp, key=rank_key)[0]})
        return out
    res["call_representatives"] = reps(res["call_clusters"], mat)
    res["run_representatives"] = reps(res["run_clusters"], rmat)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in ("n_records", "record_counts", "call_rows", "run_rows", "call_clusters",
                                          "run_clusters", "call_source_dependent", "clock", "cross_check")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
