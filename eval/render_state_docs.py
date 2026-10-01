"""registry -> docs/STATE_DERIVATION.md (규칙 · 지표 · 그래프는 코드에서 만든다 -- 손으로 고치지 말 것)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.state import DEFAULT_CONFIG, REGISTRY  # noqa: E402
from llmsensor.state.metrics import ABNORMAL_STOPS  # noqa: E402
from llmsensor.state.normalize import CANONICAL  # noqa: E402
from llmsensor.state.rules import TERMINATION_MAP  # noqa: E402

L = ["# 상태 도출 (registry 에서 생성 -- 손으로 고치지 말 것)", "",
     "`python3 eval/render_state_docs.py` 로 다시 만든다. 뜻 · 생애 · 질의는 [`STATE_MODEL.md`](STATE_MODEL.md) · "
     "[`STATE_LIFECYCLE.md`](STATE_LIFECYCLE.md).", "",
     "## 근거 종류(Basis) -- 문턱이 어디서 왔나", "",
     "| 근거 | 뜻 | 기본 설정에서 |", "|---|---|---|",
     "| `OBSERVED` | 관측값을 그대로 | 동작 |",
     "| `DEFINITIONAL` | 정의에서 따라 나온다(마지막 결과가 실패 = 미해결, 비용 ≥ 예산 = 소진, 사용률 ≥ 1 = 소진) | 동작 |",
     "| `RUNTIME_DECLARED` | 경계를 런타임이 선언(자동 압축 문턱 · 창 · 종료 사유) | 동작 -- 런타임이 안 주면 UNKNOWN |",
     "| `OPERATOR_ASSUMED` | 운영자가 설정에 준 문턱 -- **잰 값이 아니다** | 문턱이 없어 NOT_APPLICABLE · UNKNOWN |",
     "| `ESTIMATE` | 런타임 추정 -- 권위 없음 | 지표로만, 최종값이 오면 INVALID |", "",
     "**경험적 문턱(EMPIRICAL)인 규칙은 없다.** 앞 실험들로 정당화되는 문턱이 없기 때문이다.", "",
     "## 상태 규칙", ""]
for name, r in REGISTRY.rules.items():
    d = REGISTRY.state_definition(name, DEFAULT_CONFIG)
    L += [f"### `{r.entity.value}.{name}` -- `{r.id}` (v{r.version}, {r.basis.value})", "",
          f"- **뜻**: {r.meaning}", f"- **돕는 결정**: {r.decision}",
          f"- **값**: {' · '.join(f'`{v}`' for v in d['allowed_values'])}",
          f"- **입력 지표**: {', '.join(f'`{i}`' for i in r.inputs)}",
          f"- **기본 TTL**: {d['ttl_ms']} ms (OPERATOR_ASSUMED)", "",
          "```", (r.fn.__doc__ or "").strip() or "(규칙 본문: llmsensor/state/rules.py)", "```", ""]
L += ["### 종료 선언 표 (`completion-state-v1`) -- 표에 없는 문자열은 추측하지 않고 UNKNOWN", "",
      "| 칸 | 런타임 값 | 상태 |", "|---|---|---|"]
L += [f"| {k} | `{v}` | `{s}` |" for (k, v), s in TERMINATION_MAP.items()]
L += ["", f"한도에 잘린 생성으로 보는 멈춤 사유(`runtime-reliability-v1`): {', '.join(f'`{x}`' for x in ABNORMAL_STOPS)}", "",
      "## 지표 (층 2)", "", "| 지표 | 실체 | 근거 | 입력 | 정의 |", "|---|---|---|---|---|"]
L += [f"| `{m.name}` | {m.entity.value} | {m.basis.value} | {', '.join(f'`{i}`' for i in m.inputs)} | {m.doc} |"
      for m in REGISTRY.metrics.values()]
L += ["", "## 정준 관측 (층 1)", "", "| 정준 이름 | 텔레메트리 칸 | 실체 | 근거 |", "|---|---|---|---|"]
L += [f"| `{k}` | {kind}.`{fld}` | {et.value} | {b.value} |" for k, (kind, fld, et, b) in CANONICAL.items()]
L += ["", "## 의존 그래프", "", "```", REGISTRY.render_graph(), "```", "",
      "## 넣지 않은 후보 상태와 까닭", "", "| 후보 | 까닭 |", "|---|---|"]
L += [f"| `{n}` | {w} |" for n, w in REGISTRY.candidates]
Path("docs/STATE_DERIVATION.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("docs/STATE_DERIVATION.md", len(L), "lines")
