"""catalog.py -> docs/sensor_catalog.md (문서와 코드가 어긋나지 않게 코드에서 만든다)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.telemetry.catalog import CATALOG, GROUPS, NOT_SENSORS, SOURCES, IDENTITIES  # noqa: E402

L = ["# 센서 목록 (catalog.py 에서 생성 -- 손으로 고치지 말 것)", "",
     "가용성: **O** 이 세션의 실제 추적에서 봄 · **D** 이 세션에서 읽은 문서/SDK 소스에 있음 · **A** 그 추적 꼴에 없음 · "
     "**U** 모름 · **-** 해당 없음(파생은 입력의 가용성을 따른다)", "",
     "원천: " + " · ".join(SOURCES), ""]
for g in GROUPS:
    rows = [s for s in CATALOG if s["group"] == g]
    if not rows:
        continue
    L += [f"## {g}", "", "| 센서 | 형 | " + " | ".join(SOURCES) + " | 측정 시점 | 무엇 | 한계 | 파생 입력 |",
          "|---|---|" + "---|" * len(SOURCES) + "---|---|---|---|"]
    for s in rows:
        L.append(f"| `{s['name']}` | {s['type']} | " + " | ".join(s["availability"][k] for k in SOURCES)
                 + f" | {s['sampling']} | {s['meaning']} | {s['limitation']} | "
                 + ", ".join(f"`{d}`" for d in s["derived_from"]) + " |")
    L.append("")
L += ["## 근거 (형 1)", ""]
L += [f"- `{s['name']}`: {s['evidence']}" for s in CATALOG if s["type"] == 1 and s["evidence"]]
L += ["", "## 센서가 아닌 것 (형 3 -- State 해석)", ""]
L += [f"- `{n}` -- {w}" for n, w in NOT_SENSORS]
L += ["", "## 정의상 같은 것 (상관이 나와도 발견이 아니다)", ""]
L += [f"- `{a}` ~ {b}: {w}" for a, b, w in IDENTITIES]
L += ["", "## 비용 · 지속성", "",
      "모든 형 1 센서는 **추가 토큰 · API 호출이 0** 이다 -- 응답 · 런타임 출력에 이미 들어 있다. 예외: Models API 로 "
      "창 크기를 묻는 것(호출 1 회, 토큰 0), `count_tokens`(호출 1 회). 파생은 계산만 든다. "
      "실행 안에서는 모두 누적할 수 있다. 실행을 넘는 지속성은 수집기가 레코드를 저장할 때만 생긴다."]
Path("docs").mkdir(exist_ok=True)
Path("docs/sensor_catalog.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(len(CATALOG), "sensors ->", "docs/sensor_catalog.md")
