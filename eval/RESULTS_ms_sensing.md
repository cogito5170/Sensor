# 결과 -- MS 센싱 확장 Phase 8 (2026-10-02)

원자료: `results/ms_end_to_end.json` · `results/mutation_ms.json` · 표는 `render_ms_results.py` 가 JSON 에서 만든다.
설계: [`docs/MS_SENSING.md`](../docs/MS_SENSING.md).

**이 평가는 서술이다** -- 사전등록한 가설 검정이 아니다. 데이터는 앞 실험들의 실제 레코드 301 실행(claude -p 12 · 이 세션 1 ·
SWE-agent 288)이고, 새 수집은 없다. 가정: 외부 라벨 = SWE-bench Lite 숨은 시험 판정(`data/`).

> **2026-10-02 고침 (baseline PC-08):** 이 저장소 안의 결정 문맥(`llmsensor/decision/context`)과 참조 정책(`llmsensor/policy`)을
> cogito5170/DC 로 합쳤다. 그래서 2 절(정책 쓸모)과 그 변이는 DC 쪽으로 옮겨 갔다(`DC/eval/policy_impact.py` ·
> `DC/eval/RESULTS_policy_impact.md`). 여기 남은 것은 Sensor 의 일 -- 팩 · 상태별 계산 가능성 · 결정론 · 센싱 변이 -- 뿐이다.
> 옮기기 전의 표는 git 기록(커밋 691c2f3)에 있다.

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

## 2. 정책 쓸모 -- DC 로 옮겼다

같은 레코드를 Sensor 내보내기 계약 -> DC -> 시험 정책으로 다시 쟀다(DC `eval/RESULTS_policy_impact.md`). 결정 변화는 **같다**(483 번, 전부 실행
목적, 맥락 · 공급자 0). 문맥 변화 수(639 -> 3,080)는 DC 가 도구 상태를 도구마다 펼쳐서 늘었다. 옮기는 중에 DC 의 근거 종류 어휘에
`EXTERNAL_LABEL` 이 없어 `quality_state` 가 거절되던 것을 찾아 고쳤다(baseline PC-14).

여기서 적어 둔 재검토 대상(맥락 압력 · 요금 한도가 결정을 한 번도 안 바꿈 -- **쓸모가 없다는 증거가 아니라 시험되지 않은 것**)은 DC 판에서도 같다.

## 3. 결정론과 의도적 고장

결정론: 전체를 두 번 돌려 상태 스냅숏 해시 같음 (41e970b501aa64c6)

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
| 수집기: 스트림의 캐시 쓰기 나눔을 버린다 | RED |

처음 돌렸을 때(PC-08 전) 둘이 살아남았다: (a) 'STALE 을 쓸 수 있다고' 고장은 **같은 뜻의 고장**이었다 -- 실제로 낡음을 허락하는
고장으로 바꿨다(이 고장은 결정 문맥과 함께 DC 로 갔다). (b) 스트림 수집기의 캐시 쓰기 나눔에는 **시험이 없었다** -- 시험을 더했다.

## 4. 공급자 단가 확인 (Cost 센싱)

| 모형 | 무엇과 맞춰 봤나 | 결과 |
|---|---|---|
| claude-haiku-4-5 | claude -p 12 실행의 런타임 `total_cost_usd` | 12/12 상대오차 ≤ 2e-16 |
| claude-opus-5-5 | 이 세션의 Claude Code `cost-state` 스냅숏(앞 27 호출) | $3.337149 = $3.3371494 |

그 과정에서 수집기 결함을 찾았다: Claude Code `cost-state` 는 세션 끝 합계가 아니라 **중간 스냅숏**이었다(`RESULTS_sensor_layer.md` 6).

## 5. 이 결과가 말하지 않는 것

- 정책 쓸모 -- DC 로 옮겼다(2 절).
- 긴 실행 · 요금 한도 거절 · API 오류 · 압축이 있는 상황 -- 이 데이터에 없었다.
- 상태가 **옳은지**(외부 결과를 맞히는지) -- 그것은 앞 SWE-bench 실험 같은 별도 검증의 일이다.
