# 상태 모형 (State Model) -- 2026-10-01

```
Telemetry = 무엇을 보았나        (llmsensor/telemetry -- 앞 단계)
State     = 지금 무엇이 참이라고 믿나  (llmsensor/state/engine.py 의 current)
Model     = 그 상태가 무엇을 뜻하나    (llmsensor/state/registry.py)
Policy    = 무엇을 할까              (여기 없다)
```

규칙 · 지표 · 그래프의 세부: [`STATE_DERIVATION.md`](STATE_DERIVATION.md) (코드에서 생성).
시간 · 유효성 · 전이: [`STATE_LIFECYCLE.md`](STATE_LIFECYCLE.md). 선행조사: [`paper/선행조사/STATE층.md`](../paper/선행조사/STATE층.md).

## 1. 상태의 정의

> 상태 = 어떤 **실체**에 대해 시스템이 **지금** 참이라고 믿는 것의, 시간적으로 유효한 의미 표현. 하나 이상의 관측에서
> 명시된 규칙으로 도출된다.

상태 하나(`model.State`)가 늘 가진 것:

| 성질 | 칸 | 예 |
|---|---|---|
| 뜻 | `name` + registry 의 `meaning` · `decision` | `execution_health`: "도구 실행 결과에 풀리지 않은 실패가 있나" |
| 값 | `value` · `status` | `UNRESOLVED_FAILURES` · `INFERRED` |
| 시간 | `observed_at`(근거의 최신 관측) · `updated_at` · `since`(이 값의 시작) | 질의 때 나이 · 신선도로 바뀐다 |
| 근거 | `evidence`(지표 id) · `rule_id` · `rule_version` · `config_version` · `basis` | `explain()` 이 관측 id 까지 펼친다 |
| 유효성 | `status` ∈ OBSERVED · DERIVED · INFERRED · UNKNOWN · STALE · INVALID · NOT_APPLICABLE | |

## 2. 세 층 -- 형으로 갈랐다

| 층 | 형 | 무엇에 답하나 | 예 |
|---|---|---|---|
| 1 관측 | `Observation` | 런타임이 무엇을 보고했나(값, 또는 **보고된 null**) | `tokens.cache_read = 130000` |
| 2 지표 | `Metric` | 관측에서 무엇을 계산할 수 있나 | `context_utilization = 0.761` |
| 3 상태 | `State` | 근거가 시스템에 대해 무엇을 뜻하나 | `context_pressure = BELOW_COMPACTION_THRESHOLD` |

층을 건너뛰지 않는다: 상태 규칙의 입력은 **지표만**이다(`registry.check()` 와 시험이 지킨다). 정규화
(`normalize.py`)가 공급자 꼴을 정준 이름으로 바꾼다 -- OpenAI · Gemini 는 입력에 캐시가 들어가고 Gemini 출력에는 생각이
빠지므로 여기서 맞춘다(SDK 소스 근거, 실제 응답으로는 미확인). 그래서 `anthropic_reasoning_*` 같은 공급자별 상태는 없다.

## 3. 실체와 관계

실체는 실행(run) 안에 둔다: `agent:<run>` · `task:<run>` · `runtime:<run>` · `tool:<run>:<도구 이름>`.
관계는 상태가 아니고 따로 남는다(`engine.relationships`, 처음 · 마지막 관측 시각과 근거 레코드):

```
task --executed_by--> agent --uses--> tool (도구마다)
                       agent --runs_on--> runtime
```

## 4. 분류 -- 후보 열 무리를 실제 텔레메트리에 대 보았다

넣을지 정하는 일곱 질문(돕는 결정 · 근거 · 독립 · 안정 · 관측/추론 · 형식적 정의 · 근거 복원) 중 하나라도 못 넘으면
넣지 않았다. 아래 "실측" 은 `eval/state_on_records.py` 를 앞 실험의 실제 레코드 301 실행에 돌린 결과다.

| 무리 | 넣은 상태 | 실측: 실행 끝에 판정된 비율 | 넣지 않은 것과 까닭 |
|---|---|---|---|
| A 맥락 | `agent.context_pressure` (RUNTIME_DECLARED) | cc_stream 12/12, Claude Code JSONL 0/1(창이 없다 -- `context_window_override` 로 채울 수 있다), SWE-agent 0/288 | growth_rate("빠르다" 문턱 없음) · compaction_risk · budget_state(같은 것) |
| B 추론 | -- | -- | `reasoning_load`: 문턱 근거가 없다. 지표 `reasoning_tokens` · `reasoning_estimate`(ESTIMATE) 로만 |
| C 실행 | `agent.execution_health` (DEFINITIONAL) | cc_stream 12/12, JSONL 1/1, SWE-agent 0/288(is_error 없음) | latency · stability(문턱 없음, 시간 센서는 수집기에 달림) |
| D 도구 | `tool.tool_execution_health` (도구마다) | cc_stream 22/22, JSONL 5/5(4 는 STALE -- 10 분 넘게 안 씀), SWE-agent 0/2417 | availability(실패와 못 씀을 못 가른다) · recent_failure(중복) |
| E 진행 | `task.progress_state` (OPERATOR_ASSUMED) | 기본 설정: 진행 중 실행 1/1 이 UNKNOWN, 끝난 300 은 NOT_APPLICABLE | ACTIVE/SLOW(활동 ≠ 진행) |
| F 자원 | `agent.resource_state` (DEFINITIONAL) · `agent.resource_pressure` (OPERATOR_ASSUMED) | 기본 설정에 예산이 없어 301/301 NOT_APPLICABLE | token_budget_state(예산 설정 없음) |
| F 자원 | `runtime.rate_limit_state` (DEFINITIONAL) | cc_stream 12/12, JSONL 0/1, SWE-agent 0/288 | -- |
| G 신뢰 | `runtime.runtime_reliability` (DEFINITIONAL) | cc_stream 12/12, JSONL 1/1, SWE-agent 0/288 | timeout_state(전용 관측 없음) |
| H 과업 | `task.completion_state` (RUNTIME_DECLARED) | 301/301 (SWE-agent 도: 243 정상 · 45 한도) | -- |
| I 상호작용 | -- | -- | 사람 말 · 턴 관측이 텔레메트리 꼴에 없다 |
| J 불확실 | -- (저장 안 함) | -- | 결정 문맥이 투영한다: cogito5170/DC 의 `validity.uncertain` |

상태는 **9 개**다(71 개 텔레메트리 후보에서). 중복을 상태로 옮기지 않았다: cache_read · 걸음 번호(ρ 0.99)와
cache_write ≡ context_growth 는 상태가 아니라 `context_tokens` · `context_growth` 지표의 근거로만 남는다.

### 문턱을 지어내지 않은 결과

과제 예시는 `context_utilization = 0.761 → context_pressure = HIGH` 였다. 이 층의 답은
`BELOW_COMPACTION_THRESHOLD` 다 -- 런타임(Claude Code)이 선언한 자동 압축 문턱이 144,000/180,000 = 0.8 이고 0.761 은
그 밑이기 때문이다. "0.7 이면 HIGH" 의 근거는 우리에게 없다. 운영자가 띠를 원하면 설정(`resource_bands` 처럼)으로 주고,
그 상태는 `OPERATOR_ASSUMED` 로 표시된다.

## 5. 모형 · 상태 · 관계 · 정책을 섞지 않는다

| 무엇 | 어디 | 담는 것 |
|---|---|---|
| 모형 | `registry.py` · `rules.py` | 상태 이름, 값 집합, 뜻, 입력, 규칙(버전) |
| 상태 | `engine.current` · `engine.history` | 현재 값, 유효성, 근거, 시각 |
| 관계 | `engine.relationships` | 실체 사이 간선 |
| 정책 | **없음** | -- 상태는 "무엇이 참인가" 만 말한다. `decision` 칸은 *어떤 결정을 돕나* 의 설명이지 결정이 아니다 |
| LLM 의견 | `engine.proposals` | 보관만. 상태 · 전이 · 생애 사건에 손대지 않는다(시험이 붙든다) |

## 6. 질의 인터페이스

```python
from llmsensor.state import StateEngine, from_telemetry
E = StateEngine(config).ingest_all(from_telemetry(records))     # 같은 레코드를 다시 넣어도 멱등

E.query("agent:<run>", ["execution_health", "context_pressure"], now=None)  # -> [StateView]
E.explain("agent:<run>", "execution_health")      # 상태 -> 규칙 -> 지표 -> 관측 id
E.tick({"<run>": now})                            # TTL 넘긴 상태를 STALE 생애 사건으로
E.invalidate(entity, name, reason, at)            # 명시적 무효화
E.propose(entity, name, value, author, rationale) # 권위 없는 제안
E.snapshot()                                      # 결정성 비교용
```

`StateView` 는 값만 주지 않는다: `status`(STALE 판정 포함) · `freshness` · `age_ms` · `basis` · `rule` · `reason` ·
근거 지표 id · `since`. 정의는 있는데 아직 계산되지 않은 상태를 물으면 `UNKNOWN` 으로 답한다(K8s: 없음 = Unknown).
내부 표현은 dataclass 이고 JSON 은 `to_dict()` 의 출력일 뿐이다.

결정 문맥(정책에 줄 최소 의미 표현)은 이 저장소에 없다 -- cogito5170/DC 가 아래 내보내기 계약으로 읽어 짓는다(baseline PC-08).
원 텔레메트리 · 지표 값이 그쪽으로 넘어가지 않는다는 것은 계약 시험(`tests/test_state_export.py`)이 본다.

### 6.1 내보내기 계약 -- 상태 층 밖이 읽는 유일한 길 (`llmsensor/state/export.py`)

```python
E.EXPORT_CONTRACT                          # "llmsensor.state-export/1"
E.state_catalog()                          # 상태 정의: 실체 · 값 집합 · 근거 종류 · 규칙 id/판본 · TTL · 뜻 · 돕는 결정
E.export_state(entity, name, now=None)     # 상태 하나 -- 기본 값의 새 사본(JSON 가능). 없으면 UNKNOWN
E.subjects(run_id)                         # 역할 -> 실체(agent · task · runtime · tool 들)
E.as_of(run_id)                            # 그 실행에서 본 가장 늦은 관측 시각 + 시각 기준
```

엔진 안(`current` · `view` · `reg` · `cfg` · `metrics`)은 바뀔 수 있고, 밖은 이 넷만 본다. 원 텔레메트리 · 지표 값은 없고(근거는
지표 **id**), 판정기 · 참조 정책 · 결정 문맥(`llmsensor/decision`)의 출력도, LLM 제안도 없다. 칸을 빼거나 뜻을 바꾸면 판본을 올린다
(`tests/test_state_export.py` 가 칸 · 판본을 붙든다).

읽는 쪽: [cogito5170/DC](https://github.com/cogito5170/DC) 의 `SensorSource` 가 이 계약**만** 읽는다(엔진 안을 감추고 계약 넷만
남겨도 같은 결정 문맥이 나오는지 DC 쪽 시험이 본다). Sensor 는 DC 를 import 하지 않는다. DC 는 아직 바뀌는 중이라, 두 저장소가
맞물리는 자리를 이 계약 하나로 좁혀 두었다.

**합쳤다(2026-10-02, baseline PC-08):** 이 저장소에 있던 결정 문맥(`llmsensor/decision/context`)과 참조 정책(`llmsensor/policy`)은
DC 로 옮겼다. `StateEngine.decision_context()` 도 없앴다. 결정 문맥은 DC 하나뿐이다(BD-05).

## 7. 예 -- 과제 §40 의 수로

[`eval/results/state_demo.txt`](../eval/results/state_demo.txt) 전체. 줄이면:

```
RAW      context 137,000 (input 10 + cache_read 130,000 + cache_write 6,990) · window 180,000
         tool 11 회 · 오류 2 (pytest 1 회 실패 뒤 성공, WebFetch 실패) · cost 0.07(끝에) · 예산 0.10(설정)
DERIVED  context_utilization 0.761 · context_margin 43,000 · tool_failure_rate 0.1818 · cost_margin 0.03
STATE    실행 중:  context_pressure = BELOW_CONTEXT_LIMIT (압축 문턱이 아직 선언 안 됨)
                   execution_health = UNRESOLVED_FAILURES (겨냥 1/8 의 마지막 결과가 실패)
                   resource_state = UNKNOWN (비용은 실행 끝에만 보고된다)
                   progress_state = UNKNOWN (검증된 진행 근거 없음)
         끝난 뒤:  context_pressure = BELOW_COMPACTION_THRESHOLD (137,000 < 144,000)
                   resource_state = WITHIN_BUDGET · resource_pressure = MEDIUM (설정 띠, OPERATOR_ASSUMED)
                   completion_state = ENDED_NORMALLY (성공이라는 뜻이 아니다)
QUERY    "지금 실행 상태는?" -> execution_health · context_pressure · resource_pressure (+ 유효성 · 신선도 · 근거)
45분 뒤  같은 값이 STALE 로 -- 지금 값으로 쓰면 안 된다
```

## 8. 알려진 한계

- **경험적으로 검증된 상태는 하나도 없다.** 상태들은 정의 · 런타임 선언 · 운영자 가정에서 나온다. "이 상태가 실패를
  잘 가리키나" 는 앞 SWE-bench 실험 같은 외부 라벨로 따로 재야 한다.
- 비용은 이 런타임들에서 **실행 끝에만** 보고된다 -- 실행 중 자원 상태는 늘 UNKNOWN 이다(단가표 추정은 안 지었다).
- 압축 문턱 · 요금 한도도 텔레메트리 꼴에서는 실행 끝 요약에 들어 있다(런타임은 시작 때 알려 준다). 그래서 실행 중
  `context_pressure` 는 창만으로 `BELOW_CONTEXT_LIMIT` 까지만 말한다. 꼴에 시작 사건을 따로 담으면 풀린다.
- 실행 끝 요약에는 자기 시각이 없어, 그 실행에서 본 가장 늦은 시각을 하한으로 쓴다.
- `context_window` 는 cc_stream 수집기가 실행 끝 값을 모든 호출 레코드에 채워 넣은 것이다(앞 단계 수집기의 일).
- 탐색용 명령(grep 이 못 찾음)의 실패도 `UNRESOLVED_FAILURES` 로 센다 -- 정의상 실패이고, 중요한지는 정책이 정한다.
  실측: 이 세션 자신의 `execution_health` 가 미해결인 까닭은 **막힌 문서 가져오기 두 번**(OpenAI · Gemini, WebFetch)이었다.
- 요금 한도 사건의 런타임 경고 문턱(`surpassedThreshold`)은 꼴 v2 에 없다 -- `rate_limit_state` 는 소진 여부만 말한다.
- 흔들림 억제(`min_consecutive` · 띠의 enter/exit)는 시험으로만 확인했다. 실제 레코드에서는 상태당 전이가 최대 2 회라
  흔들림이 나타나지 않았다(실행이 짧다).
- TTL 기본값(10 분 · 요금 한도 5 분)은 잰 값이 아니다.
