# 결과 -- MS 센싱 확장 Phase 8 (2026-10-02)

원자료: `results/ms_end_to_end.json` · `results/mutation_ms.json` · 표는 `render_ms_results.py` 가 JSON 에서 만든다.
설계: [`docs/MS_SENSING.md`](../docs/MS_SENSING.md).

**이 평가는 서술이다** -- 사전등록한 가설 검정이 아니다. 데이터는 앞 실험들의 실제 레코드 301 실행(claude -p 12 · 이 세션 1 ·
SWE-agent 288)이고, 새 수집은 없다. 정책 쓸모는 **참조 정책(MS 아님)에 대한** 쓸모다. 가정: 능력
`{"compaction": True, "providers": 2}`, 외부 라벨 = SWE-bench Lite 숨은 시험 판정(`data/`).

## 1. 팩 · 상태별 계산 가능성

computability = 묶음을 받은 직후마다(평가점) 그 상태가 쓸 수 있는(INFERRED · 낡지 않음) 비율.
UNKNOWN · N/A · STALE · UNTIMED 은 실행 끝 기준, STALE(+1h) 는 마지막 관측 1 시간 뒤 기준.

| 팩 | 상태 / 원천 | computability | UNKNOWN | N/A | STALE(끝) | STALE(+1h) | UNTIMED | provenance | 실체 |
|---|---|---|---|---|---|---|---|---|---|
| token | `context_pressure/cc_stream` | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 12 |
| token | `context_pressure/cc_jsonl_self` | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | - | 1 |
| token | `context_pressure/sweagent` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| execution | `execution_health/cc_stream` | 0.88 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 12 |
| execution | `execution_health/cc_jsonl_self` | 0.99 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 1 |
| execution | `execution_health/sweagent` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| execution | `tool_execution_health/cc_stream` | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 22 |
| execution | `tool_execution_health/cc_jsonl_self` | 0.69 | 0.00 | 0.00 | 0.80 | 1.00 | 0.00 | 1.00 | 5 |
| execution | `tool_execution_health/sweagent` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 2417 |
| execution | `completion_state/cc_stream` | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 12 |
| execution | `completion_state/cc_jsonl_self` | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 1 |
| execution | `completion_state/sweagent` | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 288 |
| execution | `progress_state/cc_stream` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | - | 12 |
| execution | `progress_state/cc_jsonl_self` | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | 0.00 | - | 1 |
| execution | `progress_state/sweagent` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | - | 288 |
| execution | `execution_interruption/cc_stream` | 0.41 | 0.42 | 0.00 | 0.00 | 0.00 | 0.42 | 1.00 | 12 |
| execution | `execution_interruption/cc_jsonl_self` | 0.99 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1 |
| execution | `execution_interruption/sweagent` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| cost | `resource_state/cc_stream` | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | - | 12 |
| cost | `resource_state/cc_jsonl_self` | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | - | 1 |
| cost | `resource_state/sweagent` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| cost | `resource_pressure/cc_stream` | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | - | 12 |
| cost | `resource_pressure/cc_jsonl_self` | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | - | 1 |
| cost | `resource_pressure/sweagent` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| provider | `rate_limit_state/cc_stream` | 0.12 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 12 |
| provider | `rate_limit_state/cc_jsonl_self` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 1 |
| provider | `rate_limit_state/sweagent` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| provider | `runtime_reliability/cc_stream` | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 12 |
| provider | `runtime_reliability/cc_jsonl_self` | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 1.00 | 1 |
| provider | `runtime_reliability/sweagent` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| latency | `latency_state/cc_stream` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | - | 12 |
| latency | `latency_state/cc_jsonl_self` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | - | 1 |
| latency | `latency_state/sweagent` | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 1.00 | - | 288 |
| quality | `quality_state/cc_stream` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 12 |
| quality | `quality_state/cc_jsonl_self` | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | - | 1 |
| quality | `quality_state/sweagent` | 0.01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 288 |

읽는 법:
- **SWE-agent 는 대부분 UNKNOWN 이다** -- 그 추적에 호출별 토큰 · 시각 · 도구 오류 깃발이 없다(앞 실험). 원천의 한계이고,
  관측이 없는 것을 건강으로 바꾸지 않았다. 계산되는 것은 `completion_state`(종료 선언)와 `quality_state`(외부 라벨, 끝에만 와서
  computability 0.01).
- `execution_interruption/cc_stream` 0.41 -- 12 실행 중 5 실행에 Bash 결과가 없어 판정할 수 없었다(UNKNOWN 0.42).
- `rate_limit_state/cc_stream` 0.12 -- 요금 한도 사건이 실행 끝 요약에 담겨 있어 마지막 평가점에만 계산된다(꼴의 한계).
- `latency_state` · `resource_*` 는 전부 N/A -- **운영자 문턱(SLO · 예산)을 기본에 두지 않았기 때문**이다.
- STALE(+1h): 시간이 있는 원천에서는 낡음이 실제로 판정된다. `completion_state` 는 끝난 일이라 낡지 않는다(PERMANENT).
- provenance: 쓸 수 있는 상태는 **전부**(1.00) 관측 id 까지 근거가 닿는다.

## 2. 정책 쓸모 -- 상태가 바뀌면 결정이 바뀌나

평가점 57,873 (실행 × 묶음 × 목적 3) · 결정 관련 문맥 변화 639 · 결정 변화 483 (목적별 {'manage_context': 0, 'select_provider': 0, 'continue_or_stop': 483})

| 목적 / 상태 | 상태 변화 | 동시 변화 기준 impact | 정책이 쓴 것만 | 혼자 바뀐 횟수 | 혼자 바뀐 때 impact |
|---|---|---|---|---|---|
| `continue_or_stop/completion_state` | 300 | 1.00 | 1.00 | 0 | - |
| `continue_or_stop/execution_health` | 17 | 0.35 | 0.35 | 12 | 0.25 |
| `continue_or_stop/execution_interruption` | 8 | 0.38 | 0.38 | 3 | 0.00 |
| `continue_or_stop/progress_state` | 300 | 1.00 | 0.00 | 0 | - |
| `continue_or_stop/quality_state` | 287 | 0.62 | 0.62 | 287 | 0.62 |
| `manage_context/context_pressure` | 12 | 0.00 | 0.00 | 12 | 0.00 |
| `manage_context/execution_interruption` | 8 | 0.00 | 0.00 | 8 | 0.00 |
| `select_provider/rate_limit_state` | 12 | 0.00 | 0.00 | 12 | 0.00 |


**사소한 설명 둘을 잡았다**(처음 판의 수가 그대로였으면 과장이었다):
1. 처음 판은 "문맥이 57,873 평가점 중 57,873 번 바뀌었다" 였다. 문맥 id 에 나이 · as_of 가 들어 있어 **매번 바뀔 수밖에 없었다.**
   결정 관련 내용(상태 값 · 유효성 · 가능한 행동)만 비교하도록 고쳤다 -> 639.
2. `progress_state` 의 impact 1.00 은 **실행 끝에 completion_state 와 함께 바뀌어서**다. 정책은 그 상태를 쓰지 않는다 ->
   '정책이 쓴 것만' 으로 세면 0.00. 그래서 세 가지(동시 변화 · 정책이 쓴 것 · 혼자 바뀐 때)를 함께 낸다.

재검토 대상(과제 §19 -- 결정을 한 번도 안 바꾼 상태):
- `context_pressure` (manage_context) -- 이 데이터에서 맥락이 압축 문턱 근처에 간 적이 없다(claude -p 최대 64,301 -- t09 큰 파일 읽기 -- / 문턱 144,000. 처음 적은 "약 33k" 는 기억으로 쓴 틀린 수였다).
  **쓸모가 없다는 증거가 아니라 시험되지 않은 것이다.** 긴 실행의 레코드가 있어야 잴 수 있다.
- `rate_limit_state` (select_provider) -- 바뀐 것은 UNKNOWN -> WARNING 뿐이고, 참조 정책은 WARNING 에서 공급자를 바꾸지 않는다.
  LIMITED · EXHAUSTED 가 한 번도 관측되지 않았다.
- `execution_interruption` -- 참조 정책은 이유 문자열에만 쓴다. 혼자 바뀐 3 번 모두 결정은 그대로였다. 시간 초과를 다르게
  다루는 정책이 없으면 이 상태는 정책 쪽에서 쓸모가 없다 -- **정책이 생기기 전까지는 보류.**

## 3. 결정론과 의도적 고장

결정론: 전체를 두 번 돌려 결정 · 문맥 해시 같음 (d806c73bc600b3bc)

| 의도적 고장 | 결과 |
|---|---|
| latency: 표본이 모자라도 백분위를 낸다 | RED |
| latency: SLO 없이 NORMAL 을 지어낸다 | RED |
| provider: 모르는 런타임 상태를 WARNING 으로 짐작 | RED |
| provider: 429 를 무시 | RED |
| provider 어댑터: 출처 없는 OpenAI 503 대응 | RED |
| cost: 표에 없는 모형을 haiku 값으로 짐작 | RED |
| cost: 계산 못 하는 호출을 건너뛰고 부분 합 | RED |
| quality: 라벨 없음을 FAILED 로 | RED |
| execution: 판정 근거 없이 NONE_OBSERVED | RED |
| DC: N/A 선택 상태를 거르지 않는다 | RED |
| DC: STALE 을 쓸 수 있다고 한다 | RED |
| DC: 전제 조건 없이 모든 행동을 가능하다고 | RED |
| DC: 목표를 제약으로 받는다 | RED |
| DC: 이유 문자열(원 수치)을 넣는다 | RED |
| DC: 얼린 뒤 저장소를 따라 바뀐다(상태를 살아 있는 참조로) | RED |
| 정책: 모르는 맥락 압력으로 맥락을 줄인다 | RED |
| 정책: 가능하지 않은 행동을 고른다 | RED |
| 수집기: 스트림의 캐시 쓰기 나눔을 버린다 | RED |

처음 돌렸을 때 둘이 살아남았다: (a) 'STALE 을 쓸 수 있다고' 고장은 **같은 뜻의 고장**이었다(질의가 이미 STALE 을 쓸 수 없는
유효성으로 바꾼다) -- 실제로 낡음을 허락하는 고장으로 바꿨다. (b) 스트림 수집기의 캐시 쓰기 나눔에는 **시험이 없었다** -- 시험을 더했다.

## 4. 공급자 단가 확인 (Cost 센싱)

| 모형 | 무엇과 맞춰 봤나 | 결과 |
|---|---|---|
| claude-haiku-4-5 | claude -p 12 실행의 런타임 `total_cost_usd` | 12/12 상대오차 ≤ 2e-16 |
| claude-opus-5-5 | 이 세션의 Claude Code `cost-state` 스냅숏(앞 27 호출) | $3.337149 = $3.3371494 |

그 과정에서 수집기 결함을 찾았다: Claude Code `cost-state` 는 세션 끝 합계가 아니라 **중간 스냅숏**이었다(`RESULTS_sensor_layer.md` 6).

## 5. 이 결과가 말하지 않는 것

- MS 정책에 대한 쓸모. MS 정책 런타임을 찾지 못해 참조 정책으로 쟀다.
- 긴 실행 · 요금 한도 거절 · API 오류 · 압축이 있는 상황 -- 이 데이터에 없었다.
- 상태가 **옳은지**(외부 결과를 맞히는지) -- 그것은 앞 SWE-bench 실험 같은 별도 검증의 일이다.
