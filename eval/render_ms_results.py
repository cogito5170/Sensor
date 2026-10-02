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
u = d["policy_usefulness"]
L += ["", f"평가점 {u['points']:,} (실행 × 묶음 × 목적 3) · 결정 관련 문맥 변화 {u['material_context_changes']:,} · "
          f"결정 변화 {u['decision_changes']:,} (목적별 {u['decision_changes_by_purpose']})", "",
      "| 목적 / 상태 | 상태 변화 | 동시 변화 기준 impact | 정책이 쓴 것만 | 혼자 바뀐 횟수 | 혼자 바뀐 때 impact |",
      "|---|---|---|---|---|---|"]
for k, v in u["by_state"].items():
    L.append(f"| `{k}` | {v['state_changes']} | {f(v['state_impact_rate'])} | {f(v['used_impact_rate'])} | "
             f"{v['alone_changes']} | {f(v['alone_impact_rate'])} |")
L += ["", f"결정론: 전체를 두 번 돌려 결정 · 문맥 해시 {'같음' if d['deterministic'] else '**다름**'} ({d['decision_digest']})", "",
      "| 의도적 고장 | 결과 |", "|---|---|"]
L += [f"| {m['mutation']} | {m['result']} |" for m in mut]
sys.stdout.write("\n".join(L) + "\n")
