# llmsensor -- LLM 전용 센서

LLM 을 하나의 자율 시스템으로 보고 센서를 단다. **성공률을 직접 재는 센서는 없다.** 성공을 가리키는 증거를
여러 센서에서 모아 잠재 상태 `P(success | 증거)` 를 추정하고, LLM 이 아니라 결정론적 판정기가 받을지를 정한다.
NASA 식 analytical redundancy(Chow & Willsky 1984)의 *잔차 생성 → 결정* 두 단계를 그대로 빌렸다.
새 방법이 아니라 묶음이다 -- [`paper/선행조사/LLM센서.md`](paper/선행조사/LLM센서.md).

```
과업 추적 ─► 센서 다섯 ─► Reading(OK · SUSPECT · FAULT · UNKNOWN)
                │
   성능모형 M_P ─┼─► 잔차 r_T · r_R · r_E · r_V ─► R_sys
                │
                └─► 성과모형 M_O(로그 오즈 융합) ─► Q ─► 판정기 ─► ACCEPT · REJECT · RETRY · DEGRADE + 정책 제안
```

표준 라이브러리만 쓴다.

**센서 층(텔레메트리) 설계: [`docs/SENSOR_LAYER.md`](docs/SENSOR_LAYER.md)** -- 후보 71 개의 원천별 가용성 근거,
레코드 꼴(`schema/telemetry.schema.json`), 수집기(`llmsensor/telemetry/`), 파생, 의존 그래프, 최소 비중복 관측 16 개,
UNKNOWN 목록. 측정: [`eval/RESULTS_sensor_layer.md`](eval/RESULTS_sensor_layer.md).

**상태 층(State): [`docs/STATE_MODEL.md`](docs/STATE_MODEL.md)** -- 텔레메트리를 받아 실체(agent · task · runtime ·
tool)의 의미 상태 9 개를 결정론적으로 만든다(`llmsensor/state/`). 규칙마다 근거 종류(정의상 · 런타임 선언 · 운영자 가정)가
붙고, 경험적 근거가 없는 문턱은 기본 설정에 없다. 질의 · 설명(상태 → 규칙 → 지표 → 관측) · 최소 결정 문맥 ·
신선도(STALE) · UNKNOWN 을 일급으로. 도출: [`docs/STATE_DERIVATION.md`](docs/STATE_DERIVATION.md) ·
생애: [`docs/STATE_LIFECYCLE.md`](docs/STATE_LIFECYCLE.md) · 시연: `python3 eval/state_demo.py`.

**MS 센싱 확장 · 결정 문맥: [`docs/MS_SENSING.md`](docs/MS_SENSING.md)** -- 센싱 팩 여섯(`llmsensor/sensing/`: token ·
execution · latency · provider · cost · quality), 공급자 어댑터(`llmsensor/providers/`), Decision Context(`llmsensor/decision/context/`,
목적별 투영 · 얼림 · explain), 참조 정책(`llmsensor/policy/`, MS 정책 아님). 결과: [`eval/RESULTS_ms_sensing.md`](eval/RESULTS_ms_sensing.md).
건강 차원 센서 설계(설계만 · 텔레메트리와 분리된 입력 계약): [`docs/SENSOR_HEALTH_DESIGN.md`](docs/SENSOR_HEALTH_DESIGN.md).

## 센서 다섯 (진실에 가까운 순)

| 센서 | 무엇을 보나 | FAULT 가 되는 때 | 못 보는 것 |
|---|---|---|---|
| `ExternalOutcomeSensor` | 단위 시험 · 컴파일러 · 시뮬 · DB -- 명령의 종료 코드 또는 `fn(task)` | 종료 ≠ 0 / False | 시험 자체가 틀린 것 |
| `ExecutionSensor` | 도구 호출 결과. 겨냥(명령 첫 낱말 · 파일 경로)마다 **마지막** 호출 | 마지막이 실패로 남은 겨냥 · (선택) 썼다는데 없는 파일 | exit 0 인데 아무것도 안 한 도구. 실패해도 되는 호출(탐색용 grep 등은 뺀다) |
| `ConstraintSensor` | 최종 답의 JSON 스키마(부분집합) · 정규식 · 길이 · 술어 | 위반 하나라도 | `$ref` · `oneOf` · `format` -- 만나면 UNKNOWN |
| `ConsistencySensor` | 답 ↔ 도구 출력 · 답 ↔ 질문 · 답 ↔ 다른 모형의 답 | **완료를 말하는데 마지막 검증 호출이 실패**(false success) | 정규식 주장 탐지라 말 바꾸기에 약하다. 근거 없는 수는 SUSPECT 까지만 |
| `BehaviorSensor` | 토큰 팽창 · 붕괴 · 재시도 · 도구 고리(같은 호출 + 같은 출력) · ABAB 진동 · 지연 · 예산 | 고리 · z > 3.5 팽창 · 재시도 5+ · 예산 초과 | **성공 여부.** 평소처럼 행동하는지만 본다 |

**UNKNOWN 은 OK 가 아니다.** 센서가 평가를 못 했으면(도구 호출 없음 · 제약 안 걸림 · 성능모형 없음 · 명령이 없음 ·
시간 초과) UNKNOWN 이고, 융합에서는 증거 0(LR=1), 판정에서는 '근거 없음' 이다.

## 판정기 규칙

1. 외부 결과 FAULT 또는 제약 FAULT → RETRY (한도 넘으면 REJECT)
2. 외부 결과 OK 이고 Q ≥ 0.8 → ACCEPT (행동 FAULT 는 비용 경고로)
3. false success → RETRY / REJECT
4. 행동 FAULT → DEGRADE (`route: escalate`)
5. Q ≥ 0.8 이고 결과 근거(외부 OK · 제약 OK · 마지막 검증 성공과 맞는 주장) → ACCEPT
6. Q ≥ 0.8 인데 결과 근거 없음 → DEGRADE -- **토큰 · 실행 성공만으로는 받지 않는다**
7. Q ≤ 0.2 → RETRY / REJECT
8. 나머지 → DEGRADE (`route: verify`)

판정에는 다음 실행을 위한 정책 제안이 붙는다(`token_budget` = 부류 기대 토큰 × 3, `retry_limit`,
`terminate_on_repeat`, `route`). 가중치가 아니라 정책을 먼저 바꾼다.

## 쓰기

```bash
python3 -m llmsensor read ~/.claude/projects/<프로젝트>/<세션>.jsonl          # 과업마다 판독 · Q · 판정
python3 -m llmsensor fit  ~/.claude/projects/<프로젝트>/*.jsonl -o m.json     # 성능모형 M_P
python3 -m llmsensor read <세션>.jsonl --model m.json --json                  # 토큰 센서까지
python3 -m llmsensor check -- pytest -q                                       # 외부 결과 센서 하나 (종료 0/1/2 = OK/FAULT/UNKNOWN)
```

`read` 는 집계와 판독만 낸다 -- 질문 · 답 · 명령의 글은 안 낸다.

```python
from llmsensor import Recorder, sense, ConstraintSensor, ExternalOutcomeSensor, PerformanceModel

rec = Recorder("CSV 를 JSON 으로", cls="convert")
rec.turn(input_tokens=1200, output_tokens=300)
rec.call("Bash", {"command": "python3 conv.py"}, ok=True, output="wrote out.json")
rec.answer('{"rows": 42}')
rep = sense(rec.done(),
            model=PerformanceModel.load("m.json"),
            constraint=ConstraintSensor({"type": "object", "required": ["rows"]}),
            external=ExternalOutcomeSensor(["python3", "-m", "pytest", "-q", "tests/test_conv.py"]),
            others=["다른 모형이 같은 과업에 낸 답"])   # 교차 모형 일치 (선택)
rep["verdict"]   # {"action": "ACCEPT", "rule": 2, "reasons": [...], "policy": {...}}
```

## 알고 쓸 것

- **기본 우도비(LR)는 잰 값이 아니다.** 우선순위를 따르게 손으로 둔 사전값이다. 라벨 붙은 이력으로
  `OutcomeModel().calibrate([(readings, success), ...])` 하기 전의 Q 는 **확률이 아니라 순서 점수**다
  (`fusion.calibrated` 가 그것을 말한다). 그 상태에서는 외부 결과 센서 없이 추적 안의 검증 하나만으로는
  Q ≈ 0.78 이라 받지 않는다(DEGRADE). 보정은 m-추정이다 -- 한 번도 안 나온 상태는 LR 1.
- 융합은 naive Bayes 다. 실행 센서와 외부 결과 센서가 같은 시험을 보면 증거를 두 번 세어 과신한다.
- `R_sys` 는 단위가 다른 잔차를 무게로 더한 **순위 점수**다. 문턱은 재서 정한 것이 아니다.
- 성능모형은 부류마다 표본이 `min_n`(5) 이상이어야 기대값을 낸다. 모자라면 전체로 물러나고, 그것도 모자라면
  토큰 센서는 UNKNOWN 이다.
- **잰 것 (SWE-bench Lite, 사전등록 · 한 번, [`eval/RESULTS_swe_lite.md`](eval/RESULTS_swe_lite.md)):**
  SWE-agent + Claude 3.5 Sonnet 추적 287 개, 라벨은 숨은 시험. 외부 결과 센서를 끄고 잰 test AUROC:
  보정한 Q **0.73** vs 토큰 수 하나 **0.71** -- 차 +0.025, 95% 구간 [−0.09, +0.14]. **사소한 기준선보다 낫다는
  증거가 없다.** 신호는 행동 센서(토큰 팽창)에서만 나왔고, 실행 센서는 종료 코드 없는 추적에서 정보가 없었다.
- **기본 LR 로 쓰지 마라.** 같은 데이터에서 보정 전 Q 는 AUROC 0.54 로 토큰 수 하나보다 **확실히 나빴다**
  (차 −0.16, 구간 [−0.28, −0.04]). 기본 LR 의 RETRY 는 우연보다 못했다. 라벨 수십 개로라도 `calibrate()` 하고 쓴다.
- 그 측정은 Claude Code 세션이 아니다. Claude Code 추적(`is_error` 가 있다)에서는 아직 안 쟀다.
- 시험(45개)은 배선과 규칙을 붙든다. 의도적 고장 7 가지를 전부 빨갛게 잡는 것을 확인했다.

```bash
python3 -m unittest discover -s tests -t .
```
