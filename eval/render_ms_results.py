"""eval/results/ms_end_to_end.json · mutation_ms.json -> eval/RESULTS_ms_sensing.md 의 표 부분(수를 옮겨 적지 않게)."""
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent / "results"
d = json.loads((R / "ms_end_to_end.json").read_text())
mut = json.loads((R / "mutation_ms.json").read_text())
f = lambda x: "-" if x is None else f"{x:.2f}"
L = ["| 팩 | 상태 / 원천 | computability | UNKNOWN | N/A | STALE(끝) | STALE(+1h) | UNTIMED | provenance | 실체 |",
     "|---|---|---|---|---|---|---|---|---|---|"]
for pk, v in d["packs"].items():
    for k, x in v.items():
        L.append(f"| {pk} | `{k}` | {f(x['computability'])} | {f(x['unknown_rate'])} | {f(x['not_applicable_rate'])} | "
                 f"{f(x['stale_rate_at_end'])} | {f(x['stale_rate_after_1h'])} | {f(x['untimed_rate'])} | "
                 f"{f(x['provenance_coverage'])} | {x['entities']} |")
L += ["", "정책 쓸모(상태 -> 문맥 -> 결정)는 cogito5170/DC `eval/policy_impact.py` 로 옮겼다(baseline PC-08).", "",
      f"결정론: 전체를 두 번 돌려 상태 스냅숏 해시 {'같음' if d['deterministic'] else '**다름**'} ({d['state_digest']})", "",
      "| 의도적 고장 | 결과 |", "|---|---|"]
L += [f"| {m['mutation']} | {m['result']} |" for m in mut]
sys.stdout.write("\n".join(L) + "\n")
