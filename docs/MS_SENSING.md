# MS Sensing Expansion -- 설계 (2026-10-02)

검토 · 충돌: [`MS_SENSING_REVIEW.md`](MS_SENSING_REVIEW.md) · 결과: [`../eval/RESULTS_ms_sensing.md`](../eval/RESULTS_ms_sensing.md) ·
선행조사(1 차 자료): [`../paper/선행조사/MS센싱.md`](../paper/선행조사/MS센싱.md) · 상태 규칙 전체(생성):
[`STATE_DERIVATION.md`](STATE_DERIVATION.md)

```
LLM / Tool / Runtime ──► Telemetry (llmsensor/telemetry, 꼴 v3)
                              │
                 ┌────────────┴──────────── Sensing packs (llmsensor/sensing/*) ─────────────┐
                 │ token · execution · latency · provider · cost · quality(외부 라벨만)        │
                 └────────────┬───────────────────────────────────────────────────────────────┘
                              ▼
        Observation(state/normalize) → Metric → State(state/rules, 근거 종류 · 버전) → 이력 · 근거 사슬
                              │
                              ▼
        내보내기 계약 llmsensor.state-export/1 (state/export.py) -- 이 저장소의 끝
                              │
                              ▼
        Decision Context (cogito5170/DC, baseline BD-05) → Policy → … → Arbiter/Guard → Action → Telemetry
```

| 층 | 묻는 것 | 하지 않는 것 |
|---|---|---|
| Sensing | 무슨 일이 관측되었나 | 판정 · 결정 |
| State | 지금 무엇이라고 말할 수 있나 | 행동 선택 |
| Decision Context | 이 결정에 무엇이 필요한가 · 무엇이 **가능한가** | 행동 선택 · 원 텔레메트리 · LLM 프롬프트 |
| Policy | 그 상태에서 무엇을 할까 | 상태를 고치기 · 텔레메트리 읽기 |

## 1. 센싱 팩

| 팩 | 묻는 것 | 새 관측(꼴 v3) | 상태 | 문턱 출처 |
|---|---|---|---|---|
| token (기준선) | 무엇을 읽고 썼나 · 맥락이 런타임 경계의 어느 쪽인가 | -- | `context_pressure` | 런타임(자동 압축 문턱 · 창) |
| execution | 어떻게 끝났나 · 풀리지 않은 도구 실패 · 시간 초과/중단 | `timed_out`(Bash 런타임 문구) | `completion_state` · `execution_health` · `tool_execution_health` · `progress_state` · **`execution_interruption`** | 정의상 · 런타임 · 운영자(정체 문턱) |
| latency | 응답 시간 분포 | (시각 칸을 정준 관측으로) | **`latency_state`** | **운영자 SLO 만**(기본 없음 -> N/A) |
| provider | 공급자가 요청을 받아 주나 | `rate_limit_status` · `rate_limit_threshold` | `runtime_reliability` · **`rate_limit_state` v2** | 런타임(경고 선언) · 공급자(429) · 정의상(사용률 ≥ 1) |
| cost | 청구 기준 얼마인가 | `cache_creation_{5m,1h}` | `resource_state` · `resource_pressure` | 운영자(예산 · 띠, 기본 없음) |
| quality | 외부 평가가 통과로 판정했나 | (외부 라벨 묶음) | **`quality_state`** | 외부 라벨만 |

지표는 38 개(기존 23 + 새 15): 지연 분포 `call_latency` · `first_chunk_latency` · `tool_latency`(백분위는 n ≥ 1/(1−p) 일 때만 --
p95 는 20, p99 는 100), `end_to_end_latency` · `api_time_share` · `api_retry_time`, `tool_timeouts` · `tool_interruptions` ·
`tool_retries` · `turns`, `rate_limit_declared`, `call_cost` · `cost_estimate` · `cost_estimate_error`, `external_outcome`.

**공급자 차이는 위로 새지 않는다.** usage 는 `state/normalize.canonical_usage`, 오류는 `llmsensor/providers/{anthropic,gemini,openai}`
가 정준 꼴(`ErrorKind` · `retry_after_ms`)로 바꾼다. 대응표마다 출처가 있고, 출처 없는 대응은 UNKNOWN 으로 둔다(OpenAI 는
429 만).

## 2. 과제의 상태 이름 -> 이 구현에서 답하는 곳

| 과제의 값 | 답하는 상태 = 값 | 비고 |
|---|---|---|
| execution_state RUNNING / ENDED_NORMALLY | `completion_state` = RUNNING / ENDED_NORMALLY | ENDED_NORMALLY ≠ 과업 성공 -> `quality_state` 가 따로 |
| FAILED | `completion_state` = ENDED_WITH_ERROR · ENDED_BY_LIMIT | 한도 종료를 실패와 갈랐다 |
| TIMEOUT · CANCELLED | `execution_interruption` = TIMEOUT_OBSERVED · INTERRUPTED_OBSERVED | **도구** 단위. 실행 단위의 시간 초과 · 취소는 관측 못 함(UNKNOWN) |
| RATE_LIMITED | `rate_limit_state` = LIMITED · EXHAUSTED | |
| TOOL_FAILURE | `execution_health` = UNRESOLVED_FAILURES | |
| latency_state NORMAL/ELEVATED/DEGRADED | `latency_state` | 운영자 SLO 가 있을 때만 |
| latency_state TIMEOUT | `execution_interruption` | 지연 문턱이 아니라 런타임 선언이라 |
| provider_health HEALTHY/DEGRADED/UNAVAILABLE | `runtime_reliability` = NO_FAILURE_OBSERVED / FAILURE_OBSERVED | HEALTHY 는 쓰지 않는다. 단계는 Circuit Breaker 처럼 설정 문턱이 필요 |
| rate_limit_state NORMAL/LIMITED/EXHAUSTED | `rate_limit_state` = AVAILABLE · WARNING · LIMITED · EXHAUSTED | WARNING 은 런타임 선언 |
| resource_state NORMAL/NEAR_BUDGET/EXHAUSTED | `resource_state` = WITHIN_BUDGET · BUDGET_EXHAUSTED, `resource_pressure`(설정 띠) | 예산 없으면 N/A(**결정 필요 -- 아래**) |
| quality_state | `quality_state` = PASSED · FAILED · UNKNOWN | 외부 라벨만 |

## 3. Decision Context · 4. 참조 정책 -- DC 저장소로 합쳤다 (2026-10-02, baseline PC-08)

이 저장소에 있던 결정 문맥(`llmsensor/decision/context` -- 목적 넷 · 얼림 · explain)과 참조 정책(`llmsensor/policy`)은
cogito5170/DC 로 합쳤다. baseline 이 DC 저장소를 결정 문맥의 기준 구현으로 정했다(BD-05 · DUP-04 · BV-11).

| 옮겨 간 것 | DC 에서 |
|---|---|
| `allow_stale`(낡은 값은 정책이 명시해야만) | `DecisionContext.value(key, allow_stale=True)` -- STALE 만 풀고 UNKNOWN · INVALID 는 그대로 |
| `ContextStore`(id 로 다시 꺼냄) | `dc.ContextStore` -- 근거 사슬은 복사하지 않고 `evidence_refs` 참조로(BD-06) |
| 목적 `manage_context` · `select_provider` · `continue_or_stop` | DC 이름(BD-30): `context_policy` · `provider_selection`(+`WAIT`) · `execution_control`(+`execution_interruption` · `quality_state`) |
| 참조 정책 셋 | `DC/refpolicy/` -- DC 기반 시험 정책(MS 아님, `dc` 패키지 밖) |
| Phase 8 의 정책 쓸모 측정 | `DC/eval/policy_impact.py` -- 같은 레코드에서 결정 변화 483 번으로 같다 |

DC 는 이 저장소를 **내보내기 계약으로만** 읽는다(`docs/STATE_MODEL.md` 6.1). 남은 차이: 런타임 압축(`COMPACT_CONTEXT`)에 해당하는
행동이 DC 어휘에 없다 -- baseline 에 물었다.

## 5. 설계 결정과 근거

| 결정 | 근거(1 차 자료) |
|---|---|
| 감지(State)와 대응(Policy)을 다른 단계로 | NASA cFS Limit Checker: 문턱 넘음 -> **event**, 대응 RTS 는 "may be initiated" |
| 문턱은 미리 정의된 것만 -- 출처를 규칙마다 | NASA LC "predefined threshold limits", F´ Health: 포트마다 설정된 timeout(HTH-002/006) |
| 지연 상태는 운영자 SLO 가 있을 때만 | F´ Health(설정 timeout) · Microsoft Circuit Breaker(설정 failure threshold) |
| 공급자 단계(DEGRADED/UNAVAILABLE)를 기본으로 만들지 않음 | Microsoft Circuit Breaker: 전이가 설정 문턱에 달렸다 |
| 시간 초과를 실패로 동일시하지 않음 | Google `code.proto` DEADLINE_EXCEEDED: "may be returned even if the operation has completed successfully" |
| 429 = 요금 한도, retry-after 는 공급자 선언 | Google `code.proto` RESOURCE_EXHAUSTED(HTTP 429) · `RetryInfo`, Anthropic error-codes.md |
| 상태를 주기적으로 재서 캐시하고 노출, 낡음 표시 | Microsoft Health Endpoint Monitoring("cache the status") |
| UNKNOWN 일급, 상위 요약 조건 | Kubernetes Conditions(앞 단계) |
| 비용 = 토큰 × 공급자 단가(캐시 쓰기 5m/1h 따로) | claude-api 스킬 prompt-caching.md -- **두 모형 모두 런타임 보고 비용과 정확히 같음을 확인** |

못 읽은 1 차 자료(Google SRE Book, learn.microsoft.com, NASA 핸드북)는 근거로 쓰지 않았다.

## 6. 사용자가 정할 것

1. **예산 미설정 시 `resource_state`**: 과제는 UNKNOWN, 기존 v1 은 NOT_APPLICABLE. 지금은 기존을 유지했다(새 상태 latency_state 도 같은 규약).
   UNKNOWN 으로 바꾸려면 규칙 버전을 올린다 -- 정책 쪽에서는 `not_applicable` 목록이 `uncertain` 목록으로 옮겨 간다.
2. **실행 중 비용으로 `resource_state` 를 낼까**: 공급자 단가로 계산한 비용이 런타임 보고값과 정확히 같으므로(두 모형), 실행 끝을
   기다리지 않고 예산 상태를 낼 수 있다. 규칙 v2 가 된다 -- 1 과 함께 정하면 좋다.
3. **"MS" 가 무엇인가 · walp 와 연결할까**: walp 의 P4(출력 예산)가 Context Policy, `llmfront` 가 Provider Policy 에 가깝다.
   다른 저장소를 고치는 일이라 이번에 하지 않았다.

## 7. 한계

- 계산 가능성은 원천에 크게 달렸다 -- SWE-agent 추적에서는 종료 선언과 외부 라벨 말고는 거의 UNKNOWN 이다.
- 요금 한도 · 압축 문턱이 꼴에서 실행 끝 요약에 들어 있어 실행 중에는 늦게 알게 된다(런타임은 시작 때 알려 준다).
- 시간 초과는 **Bash 의 런타임 문구**로만 안다. 다른 도구 · 실행 단위의 시간 초과와 취소는 관측하지 못한다.
- OpenAI · Gemini 는 실제 응답으로 확인하지 않았다(SDK 소스 · Google API 정의만). 단가표도 Anthropic 두 모형뿐이다.
- 정책 쓸모는 참조 정책 기준이고, 이 데이터에는 긴 실행 · 요금 한도 거절 · API 오류가 없어 상태 몇은 시험되지 않았다.
