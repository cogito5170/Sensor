"""사전등록 eval/PREREG_swe_lite.md 의 분석. **한 번만 돌린다.**

    python3 eval/swe_lite.py <fetch_swe_lite.sh 로 받은 곳> [--out eval/results/swe_lite.json]

라벨 = SWE-bench 의 숨은 시험으로 판정한 resolved(외부 결과). 외부 결과 센서는 라벨 그 자체이므로 끈다(UNKNOWN).
남은 네 센서(실행 · 제약 · 일관성 · 행동)와 융합 Q 가 라벨을 얼마나 맞히나, 그리고 그것이 사소한 기준선보다 나은가.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor import OutcomeModel, PerformanceModel, Reading, Verifier, sense, telemetry  # noqa: E402
from llmsensor.adapters.sweagent import from_sweagent  # noqa: E402

SENSORS = ("execution", "constraint", "consistency", "behavior", "outcome")


def split_of(iid: str) -> str:
    return "fit" if int(hashlib.sha256(iid.encode()).hexdigest(), 16) % 2 == 0 else "test"


def auroc_rank(s, y) -> float:
    """Mann-Whitney U / (n+ n-), 동점은 평균 순위."""
    order = sorted(range(len(s)), key=lambda i: s[i])
    ranks = [0.0] * len(s)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and s[order[j + 1]] == s[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    npos = sum(y)
    nneg = len(y) - npos
    return (sum(r for r, t in zip(ranks, y) if t) - npos * (npos + 1) / 2) / (npos * nneg)


def auroc_trap(s, y) -> float:
    """독립 대조: ROC 곡선을 문턱마다 그려 사다리꼴 넓이."""
    P, N = sum(y), len(y) - sum(y)
    pts, tp, fp = [(0.0, 0.0)], 0, 0
    for th in sorted(set(s), reverse=True):
        tp += sum(1 for a, b in zip(s, y) if a == th and b)
        fp += sum(1 for a, b in zip(s, y) if a == th and not b)
        pts.append((fp / N, tp / P))
    return sum((x2 - x1) * (y1 + y2) / 2 for (x1, y1), (x2, y2) in zip(pts, pts[1:]))


def boot_diff(a, b, y, n=2000, seed=0):
    rng = random.Random(seed)
    idx = range(len(y))
    out = []
    for _ in range(n):
        smp = [rng.choice(idx) for _ in idx]
        yy = [y[i] for i in smp]
        if 0 < sum(yy) < len(yy):
            out.append(auroc_rank([a[i] for i in smp], yy) - auroc_rank([b[i] for i in smp], yy))
    out.sort()
    return out[int(.025 * len(out))], out[int(.975 * len(out))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--out", default="eval/results/swe_lite.json")
    a = ap.parse_args(argv)
    D = Path(a.data)
    res = json.loads((D / "results.json").read_text())
    resolved, no_logs = set(res["resolved"]), set(res.get("no_logs", []))
    tasks, y, sp = [], [], []
    for p in sorted((D / "trajs").glob("*.traj.gz")):
        iid = p.name.split(".")[0]
        if iid in no_logs:
            continue
        tasks.append(from_sweagent(p, iid))
        y.append(iid in resolved)
        sp.append(split_of(iid))
    fit = [i for i, s in enumerate(sp) if s == "fit"]
    test = [i for i, s in enumerate(sp) if s == "test"]
    M = PerformanceModel(min_n=5).fit_tasks([tasks[i] for i in fit], [y[i] for i in fit])
    reps = [sense(t, model=M) for t in tasks]
    R = [[Reading(**r) for r in rep["readings"]] for rep in reps]
    priors = [rep["fusion"]["prior"] for rep in reps]

    omB = OutcomeModel().calibrate([(R[i], y[i]) for i in fit])
    v = Verifier()
    qA = [rep["fusion"]["Q"] for rep in reps]
    qA0 = [OutcomeModel().q(r, 0.5)["Q"] for r in R]                    # 사전 없이 -- 센서만
    qB = [omB.q(r, p)["Q"] for r, p in zip(R, priors)]
    qB0 = [omB.q(r, 0.5)["Q"] for r in R]
    verdA = [rep["verdict"]["action"] for rep in reps]
    verdB = [v.decide(r, q, 0, telemetry(t), M.expect(t.cls)).action for r, q, t in zip(R, qB, tasks)]

    tel = [telemetry(t) for t in tasks]
    base = {
        "neg_log_tokens": [-math.log(max(1, x["T"])) for x in tel],
        "neg_api_calls": [-(t.meta["api_calls"] or 0) for t in tasks],
        "neg_steps": [-x["L"] for x in tel],
        "exit_submitted": [1.0 if t.meta["exit_status"] == "submitted" else 0.0 for t in tasks],
        "patch_nonempty": [1.0 if t.meta["patch_chars"] > 0 else 0.0 for t in tasks],
        "repo_prior": priors,
    }
    scores = {"Q_A_default": qA, "Q_A_default_noprior": qA0, "Q_B_calibrated": qB, "Q_B_calibrated_noprior": qB0}
    yt = [y[i] for i in test]

    def on_test(s):
        return [s[i] for i in test]

    out = {"n": len(tasks), "resolved": sum(y), "fit": {"n": len(fit), "resolved": sum(y[i] for i in fit)},
           "test": {"n": len(test), "resolved": sum(yt)}, "auroc": {}, "auroc_check_maxdiff": 0.0}
    for k, s in {**scores, **base}.items():
        st = on_test(s)
        r1, r2 = auroc_rank(st, yt), auroc_trap(st, yt)
        out["auroc"][k] = r1
        out["auroc_check_maxdiff"] = max(out["auroc_check_maxdiff"], abs(r1 - r2))
    best = max(base, key=lambda k: out["auroc"][k])
    out["best_baseline"] = best
    out["diff_vs_best"] = {k: {"diff": out["auroc"][k] - out["auroc"][best],
                               "ci95": boot_diff(on_test(scores[k]), on_test(base[best]), yt)}
                           for k in scores}
    for nm, vv in (("A", verdA), ("B", verdB)):
        tab = {}
        for i in test:
            tab.setdefault(vv[i], [0, 0])[0 if y[i] else 1] += 1
        out[f"verdict_{nm}"] = {k: {"resolved": r, "unresolved": u} for k, (r, u) in sorted(tab.items())}
    per = {}
    for s_i, s in enumerate(SENSORS):
        tab = {}
        for i in test:
            st = R[i][s_i].status
            tab.setdefault(st, [0, 0])[0 if y[i] else 1] += 1
        per[s] = {k: {"resolved": r, "unresolved": u} for k, (r, u) in sorted(tab.items())}
    out["per_sensor_test"] = per
    out["unknown_share_all"] = {s: sum(R[i][j].status == "UNKNOWN" for i in range(len(R))) / len(R)
                                for j, s in enumerate(SENSORS)}
    out["fault_share_all"] = {s: sum(R[i][j].status == "FAULT" for i in range(len(R))) / len(R)
                              for j, s in enumerate(SENSORS)}
    out["Q_std_test"] = {k: (lambda xs: (sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)) ** .5)(on_test(s))
                         for k, s in scores.items()}
    out["lr_calibrated"] = omB.lr
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
