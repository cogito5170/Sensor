# Phase 1 -- 기존 구조 검토와 과제 지시와의 충돌 (2026-10-02)

과제(MS Sensing Expansion)를 짓기 전에 저장소를 읽고 충돌을 적는다. **기존 Token/State 의 뜻은 바꾸지 않는다** --
충돌은 아래처럼 풀거나 사용자에게 묻는다.

## 지금 있는 것

| 층 | 위치 | 상태 |
|---|---|---|
| 텔레메트리(수집 · 꼴 v2) | `llmsensor/telemetry/` · `schema/telemetry.schema.json` | 원천 3 곳, 레코드 19,406, 꼴 위반 0 |
| 정규화 · 지표 · 규칙 · 레지스트리 · 엔진 | `llmsensor/state/` | 상태 9, 지표 23, 규칙마다 근거 종류, 멱등 · 결정론 |
| 최소 결정 문맥 | `StateEngine.decision_context()` | 목적이 없다(한 가지 투영뿐), 얼려지지 않는다 |
| 정책 | 없음 | -- |

## "MS" 와 "기존 MS 정책" -- 찾지 못했다

이 세션의 네 저장소(Sensor · walp · se_new · sub_brain)에서 `MS` 런타임 · 정책 코드를 찾지 못했다(se_new 의 "MS" 는
학위 과정 표기, 나머지는 무관). 가장 가까운 것은 **walp 의 실행 정책층**(`walp/execpolicy.py`: P1 상태 재사용 · P2 발행
매크로 · P3 기다리기 · P4 출력 예산 -- P4 가 사실상 Context Policy)과 `walp/llmfront.py`(잡담은 WALP, 나머지는
gemini/claude 로 -- 사실상 Provider Policy)다. 그래서 **Phase 7 은 "기존 MS 정책 연결" 이 아니라 "결정 문맥을 소비하는
참조 정책" 으로 짓고, 그것이 MS 가 아님을 이름에 적는다**(`llmsensor/policy/reference_*`). walp 와의 실제 연결은 다른
저장소를 고치는 일이라 이번 범위에서 뺀다.

## 과제 지시와 기존 설계의 충돌

| # | 과제 | 기존 | 결정 |
|---|---|---|---|
| C1 | 예산 미설정이면 `resource_state = UNKNOWN` | `resource-state-v1` 은 `NOT_APPLICABLE`(질문 자체가 정의되지 않음) | **기존 유지, 사용자에게 묻는다.** 새 상태들도 운영자 문턱이 없으면 같은 규약(NOT_APPLICABLE)을 따른다. 바꾸려면 설정 한 줄로 갈 수 있게 해 둔다 |
| C2 | `execution_state` 한 열거(RUNNING · ENDED_NORMALLY · FAILED · TIMEOUT · CANCELLED · RATE_LIMITED · TOOL_FAILURE) | `completion_state`(실행 종료) · `execution_health`(도구 결과) 로 갈라져 있다 | **합성 열거를 만들지 않는다.** 실행 끝 사유 · 도구 실패 · 시간 초과 · 요금 한도는 서로 다른 시점 · 실체의 일이라 한 값으로 접으면 정보가 사라진다(t11: 도구는 시간 초과, 실행은 정상 종료). 과제의 값마다 어느 상태의 어느 값이 답하는지 표로 준다(`MS_SENSING.md`). 새로 관측할 수 있게 된 것(시간 초과 · 중단)만 새 상태로 |
| C3 | `rate_limit_state = NORMAL · LIMITED · EXHAUSTED` | `rate-limit-state-v1 = AVAILABLE · EXHAUSTED` | **v2 로 넓힌다**: 런타임이 선언한 경고(`allowed_warning`) -> WARNING, 429 -> LIMITED. 앞 꼴(v2)의 레코드에서는 v1 과 출력이 **같음을 회귀 시험으로** 붙든다 |
| C4 | `provider_health = HEALTHY · DEGRADED · UNAVAILABLE` | `runtime_reliability = NO_FAILURE_OBSERVED · FAILURE_OBSERVED` | 같은 개념이다 -- 새 상태를 만들지 않는다. **HEALTHY 를 쓰지 않는다**(과제 §13 "No observation ≠ Healthy" 와 같은 까닭). DEGRADED/UNAVAILABLE 를 가를 문턱은 Circuit Breaker 처럼 설정이 필요하고, 기본에 없다 |
| C5 | `latency_state = NORMAL · ELEVATED · DEGRADED · TIMEOUT` | 없음 | NORMAL/ELEVATED/DEGRADED 는 **운영자 SLO 가 있을 때만**(F´ Health: 포트마다 설정된 timeout). TIMEOUT 은 지연이 아니라 런타임이 선언한 사건이라 실행 센싱의 상태로 둔다(C2 와 같은 까닭으로 겹치지 않게) |
| C6 | `sensing/token/` 등 디렉터리 | 한 덩어리 `state/metrics.py` · `rules.py` | 규칙 · 지표 정의는 **그대로 두고**(뜻 불변) 센싱 팩이 그것을 묶는다. 레지스트리는 팩을 조립한다. 바뀐 것이 없음을 실제 레코드 301 실행의 **스냅숏 동일성**으로 확인한다 |
| C7 | 저장소 나무(`sensing/ state/ decision/ policy/ providers/ walp/`) | `llmsensor/` 아래 | `llmsensor/sensing/*` · `llmsensor/decision/context/` · `llmsensor/policy/` · `llmsensor/providers/` 를 만든다. `state/` 는 이미 observation(normalize) · metric · derivation(rules) · registry · provenance(explain) 를 갖고 있어 옮기지 않는다. `walp/` 는 다른 저장소다 |
| C8 | Quality 는 ground truth 없이 만들지 말 것 | -- | 인터페이스만 + 외부 라벨이 있으면 그대로 옮긴다. **SWE-bench 의 숨은 시험 판정이 실제 외부 라벨로 있다** -- 그 287 실행에 한해 quality_state 가 계산된다 |

## 텔레메트리에 더해야 하는 관측 (꼴 v3, 덧붙이기만)

과제의 관측 후보 중 **원천에 이미 있는데 꼴에 안 담은 것**만 더한다. 새 수집은 하지 않는다.

| 칸 | 원천 | 왜 |
|---|---|---|
| `tool_call.timed_out` | 도구 결과 글의 런타임 선언 "Command timed out after" (Bash) | 시간 초과의 유일한 직접 관측(앞 실험 t11). 다른 도구의 문구는 모르므로 Bash 외에는 null |
| `model_call.cache_creation_5m_input_tokens` · `_1h_` | `usage.cache_creation` | 캐시 쓰기 값이 5분/1시간에 따라 다르다 -- 비용 계산에 필요 |
| `run.rate_limit_status` · `run.rate_limit_threshold` | `rate_limit_event.rate_limit_info.status` · `surpassedThreshold` | 런타임이 선언한 경고 문턱 -- 문턱을 우리가 만들 필요가 없다 |
