# 상태 도출 (registry 에서 생성 -- 손으로 고치지 말 것)

`python3 eval/render_state_docs.py` 로 다시 만든다. 뜻 · 생애 · 질의는 [`STATE_MODEL.md`](STATE_MODEL.md) · [`STATE_LIFECYCLE.md`](STATE_LIFECYCLE.md).

## 근거 종류(Basis) -- 문턱이 어디서 왔나

| 근거 | 뜻 | 기본 설정에서 |
|---|---|---|
| `OBSERVED` | 관측값을 그대로 | 동작 |
| `DEFINITIONAL` | 정의에서 따라 나온다(마지막 결과가 실패 = 미해결, 비용 ≥ 예산 = 소진, 사용률 ≥ 1 = 소진) | 동작 |
| `RUNTIME_DECLARED` | 경계를 런타임이 선언(자동 압축 문턱 · 창 · 종료 사유) | 동작 -- 런타임이 안 주면 UNKNOWN |
| `OPERATOR_ASSUMED` | 운영자가 설정에 준 문턱 -- **잰 값이 아니다** | 문턱이 없어 NOT_APPLICABLE · UNKNOWN |
| `ESTIMATE` | 런타임 추정 -- 권위 없음 | 지표로만, 최종값이 오면 INVALID |

**경험적 문턱(EMPIRICAL)인 규칙은 없다.** 앞 실험들로 정당화되는 문턱이 없기 때문이다.

## 상태 규칙

### `agent.context_pressure` -- `context-pressure-v1` (v1, RUNTIME_DECLARED)

- **뜻**: 맥락이 런타임이 선언한 경계(자동 압축 문턱 · 창)의 어느 쪽에 있나. 경계는 런타임 것이지 우리 것이 아니다
- **돕는 결정**: 다음 호출 전에 맥락을 줄일까
- **값**: `BELOW_CONTEXT_LIMIT` · `BELOW_COMPACTION_THRESHOLD` · `ABOVE_COMPACTION_THRESHOLD` · `AT_CONTEXT_LIMIT` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `context_tokens`, `context_window`, `compaction_threshold`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `agent.execution_health` -- `execution-health-v1` (v1, DEFINITIONAL)

- **뜻**: 도구 실행 결과에 풀리지 않은 실패가 있나. 겨냥마다 마지막 결과로 본다(실패율 문턱이 아니다)
- **돕는 결정**: 다시 시도할까 · 사람에게 올릴까
- **값**: `NO_FAILURE_OBSERVED` · `RECOVERED_FAILURES` · `UNRESOLVED_FAILURES` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `tool_results`, `tool_outcome_unobservable`, `tool_targets`, `tool_failure_rate`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `tool.tool_execution_health` -- `tool-execution-health-v1` (v1, DEFINITIONAL)

- **뜻**: 도구 하나에 대한 execution_health -- 도구마다 따로
- **돕는 결정**: 이 도구를 계속 쓸까
- **값**: `NO_FAILURE_OBSERVED` · `RECOVERED_FAILURES` · `UNRESOLVED_FAILURES` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `tool_results`, `tool_outcome_unobservable`, `tool_targets`, `tool_failure_rate`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `task.completion_state` -- `completion-state-v1` (v1, RUNTIME_DECLARED)

- **뜻**: 런타임이 실행을 어떻게 끝냈다고 선언했나. **과업 성공이 아니다**(SWE-bench: 정상 제출 243 중 해결 69 이하)
- **돕는 결정**: 결과를 검증으로 넘길까 · 한도를 올릴까
- **값**: `RUNNING` · `ENDED_NORMALLY` · `ENDED_BY_LIMIT` · `ENDED_WITH_ERROR` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `termination`, `activity`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `task.progress_state` -- `progress-state-v1` (v1, OPERATOR_ASSUMED)

- **뜻**: 같은 호출 반복으로 본 정체. 문턱은 운영자 가정 -- 기본 설정에서는 UNKNOWN
- **돕는 결정**: 끊을까
- **값**: `STALLED` · `NO_STALL_DETECTED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `identical_call_max`, `termination`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `agent.resource_state` -- `resource-state-v1` (v1, DEFINITIONAL)

- **뜻**: 보고된 비용이 설정 예산 안인가
- **돕는 결정**: 멈출까
- **값**: `WITHIN_BUDGET` · `BUDGET_EXHAUSTED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `cost_fraction`, `cost_margin`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `agent.resource_pressure` -- `resource-pressure-v1` (v1, OPERATOR_ASSUMED)

- **뜻**: 설정 띠로 본 비용 압력(띠 이름은 설정이 정한다). 띠가 없으면 NOT_APPLICABLE
- **돕는 결정**: 싼 경로로 바꿀까
- **값**: `LOW` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `cost_fraction`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `runtime.rate_limit_state` -- `rate-limit-state-v2` (v2, RUNTIME_DECLARED)

- **뜻**: 요금 한도: 429 로 거절됨(LIMITED) · 사용률 ≥ 1(EXHAUSTED) · 런타임이 경고를 선언(WARNING) · 그 밖(AVAILABLE). v1(AVAILABLE · EXHAUSTED)의 확장 -- 새 관측이 없으면 v1 과 같다
- **돕는 결정**: 늦출까 · 공급자를 바꿀까
- **값**: `AVAILABLE` · `WARNING` · `LIMITED` · `EXHAUSTED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `rate_limit_utilization`, `rate_limit_declared`, `api_error`
- **기본 TTL**: 300000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `runtime.runtime_reliability` -- `runtime-reliability-v1` (v1, DEFINITIONAL)

- **뜻**: API 오류 보고 · 한도에 잘린 생성이 있었나. '실패를 못 봤다' 와 '건강하다' 를 가른다
- **돕는 결정**: 다른 공급자로 돌릴까
- **값**: `NO_FAILURE_OBSERVED` · `FAILURE_OBSERVED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `api_error`, `stop_reasons`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `agent.execution_interruption` -- `execution-interruption-v1` (v1, RUNTIME_DECLARED)

- **뜻**: 런타임이 도구의 시간 초과(문구) · 중단(깃발)을 선언했나. 지연 문턱이 아니라 런타임의 선언이다
- **돕는 결정**: 시간 제한을 늘릴까 · 배경으로 돌릴까
- **값**: `TIMEOUT_OBSERVED` · `INTERRUPTED_OBSERVED` · `NONE_OBSERVED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `tool_timeouts`, `tool_interruptions`
- **기본 TTL**: None ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `agent.latency_state` -- `latency-state-v1` (v1, OPERATOR_ASSUMED)

- **뜻**: 설정된 SLO 띠로 본 지연(띠 이름 · 문턱은 설정이 정한다). SLO 가 없으면 NOT_APPLICABLE
- **돕는 결정**: 더 빠른 경로로 바꿀까
- **값**: `NORMAL` · `ELEVATED` · `DEGRADED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `call_latency`, `first_chunk_latency`, `tool_latency`
- **기본 TTL**: None ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `task.quality_state` -- `quality-state-v1` (v1, EXTERNAL_LABEL)

- **뜻**: 외부 평가가 과업을 통과로 판정했나. 라벨이 없으면 UNKNOWN -- 점수를 지어내지 않는다
- **돕는 결정**: 결과를 받아들일까 · 사람에게 올릴까
- **값**: `PASSED` · `FAILED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `external_outcome`
- **기본 TTL**: None ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### `task.liveness_state` -- `liveness-state-v1` (v1, DEFINITIONAL)

- **뜻**: 대상이 아직 움직이나. 끝남 · 끝 신호 없이 닫힘 · 입력 대기 · 차례 중은 문턱 없이, ACTIVE · STALLED 는 운영자 무음 문턱이 있을 때만(값마다 근거가 따로 남는다). DEAD 는 내지 않는다
- **돕는 결정**: 기다릴까 · 끊고 다시 띄울까
- **값**: `ENDED` · `ENDED_WITHOUT_TERMINAL` · `AWAITING_INPUT` · `IN_TURN` · `ACTIVE` · `STALLED` · `UNKNOWN` · `NOT_APPLICABLE`
- **입력 지표**: `stream_end`, `termination`, `turn_open`, `silence_ms`
- **기본 TTL**: 600000 ms (OPERATOR_ASSUMED)

```
(규칙 본문: llmsensor/state/rules.py)
```

### 종료 선언 표 (`completion-state-v1`) -- 표에 없는 문자열은 추측하지 않고 UNKNOWN

| 칸 | 런타임 값 | 상태 |
|---|---|---|
| result_subtype | `success` | `ENDED_NORMALLY` |
| result_subtype | `error_max_turns` | `ENDED_BY_LIMIT` |
| result_subtype | `error_during_execution` | `ENDED_WITH_ERROR` |
| terminal_reason | `completed` | `ENDED_NORMALLY` |
| terminal_reason | `max_turns` | `ENDED_BY_LIMIT` |
| terminal_reason | `submitted` | `ENDED_NORMALLY` |
| terminal_reason | `submitted (exit_cost)` | `ENDED_BY_LIMIT` |

한도에 잘린 생성으로 보는 멈춤 사유(`runtime-reliability-v1`): `max_tokens`, `model_context_window_exceeded`

## 지표 (층 2)

| 지표 | 실체 | 근거 | 입력 | 정의 |
|---|---|---|---|---|
| `context_tokens` | agent | OBSERVED | `tokens.input_uncached`, `tokens.cache_read`, `tokens.cache_write` | 마지막 호출이 본 입력 전체 |
| `context_window` | agent | OBSERVED | `run.context_window`, `call.context_window` | 맥락 창 크기(없으면 설정 override, 근거 OPERATOR_ASSUMED) |
| `compaction_threshold` | agent | RUNTIME_DECLARED | `run.compaction_threshold` | 런타임이 선언한 자동 압축 문턱(토큰) |
| `context_utilization` | agent | OBSERVED | `context_tokens`, `context_window` | context_tokens / context_window |
| `context_margin` | agent | OBSERVED | `context_tokens`, `context_window` | context_window − context_tokens |
| `compaction_margin` | agent | RUNTIME_DECLARED | `context_tokens`, `compaction_threshold` | compaction_threshold − context_tokens |
| `context_growth` | agent | OBSERVED | `tokens.input_uncached`, `tokens.cache_read`, `tokens.cache_write` | 마지막 두 호출의 context_tokens 차 (캐시 런타임에서는 ≡ cache_write) |
| `tool_results` | agent | OBSERVED | `tool.is_error`, `tool.target`, `tool.name` | 결과(is_error)를 본 도구 호출 수 |
| `tool_outcome_unobservable` | agent | OBSERVED | `tool.is_error`, `tool.target`, `tool.name` | 결과를 볼 수 없는 도구 호출 수(SWE-agent 추적 등) |
| `tool_errors` | agent | OBSERVED | `tool.is_error`, `tool.target`, `tool.name` | is_error=true 인 결과 수 |
| `tool_failure_rate` | agent | OBSERVED | `tool_results`, `tool_errors` | tool_errors / tool_results |
| `tool_targets` | agent | OBSERVED | `tool.is_error`, `tool.target`, `tool.name` | 겨냥별 최근 결과: 미해결(마지막이 실패) · 회복(실패 뒤 성공) |
| `identical_call_max` | agent | OBSERVED | `tool.signature` | 같은 (도구, 인자)의 최대 반복 수 |
| `reasoning_tokens` | agent | OBSERVED | `tokens.reasoning` | 최종 보고된 생각 토큰 합 |
| `reasoning_estimate` | agent | ESTIMATE | `tokens.reasoning_estimate`, `tokens.reasoning` | 생성 도중 런타임 추정(최종값이 오면 INVALID) |
| `cost_usd` | agent | OBSERVED | `run.cost_usd` | 런타임이 보고한 비용 |
| `cost_fraction` | agent | OPERATOR_ASSUMED | `cost_usd` | cost / 예산(설정) |
| `cost_margin` | agent | OPERATOR_ASSUMED | `cost_usd` | 예산 − cost |
| `stop_reasons` | runtime | OBSERVED | `call.stop_reason` | 본 멈춤 사유 수와 한도에 잘린 것(max_tokens · model_context_window_exceeded) |
| `api_error` | runtime | OBSERVED | `runtime.api_error_status` | API 오류 보고 -- 보고된 null 은 '오류 보고 없음' |
| `rate_limit_utilization` | runtime | OBSERVED | `runtime.rate_limit_utilization` | 요금 한도 사용률(런타임 사건) |
| `termination` | task | RUNTIME_DECLARED | `run.result_subtype`, `run.terminal_reason`, `run.is_error` | 런타임이 선언한 종료(성공 여부가 **아니다**) |
| `activity` | task | OBSERVED | `call.stop_reason` | 본 호출 · 도구 결과 수 |
| `tool_timeouts` | agent | RUNTIME_DECLARED | `tool.timed_out` | 런타임이 시간 초과를 선언한 도구 결과 수 / 판정 가능한 결과 수 |
| `tool_interruptions` | agent | OBSERVED | `tool.interrupted` | 중단 깃발이 선 도구 결과 수 / 깃발을 본 결과 수 |
| `tool_retries` | agent | OBSERVED | `tool.is_error`, `tool.target`, `tool.name` | 오류 뒤 같은 겨냥 재호출 수 |
| `turns` | task | OBSERVED | `run.num_turns` | 런타임이 보고한 회전 수 |
| `call_latency` | agent | OBSERVED | `call.t_start`, `call.t_end` | 모형 호출 구간(첫 ~ 마지막 관측) 분포 {n, p50, p95, p99} -- 표본이 모자란 백분위는 None |
| `first_chunk_latency` | agent | OBSERVED | `call.first_chunk_ms` | message_start ~ 첫 조각(스트림 수집기에서만) 분포 |
| `tool_latency` | agent | OBSERVED | `tool.t_issued`, `tool.t_result` | 도구 호출 ~ 결과 분포 |
| `end_to_end_latency` | task | OBSERVED | `run.duration_ms` | 실행 전체 시간 |
| `api_time_share` | task | OBSERVED | `run.api_duration_ms`, `run.duration_ms` | API 시간 / 전체 시간 |
| `api_retry_time` | task | OBSERVED | `run.api_duration_ms`, `run.api_duration_without_retries_ms` | API 재시도에 쓴 시간 |
| `rate_limit_declared` | runtime | RUNTIME_DECLARED | `runtime.rate_limit_status`, `runtime.rate_limit_threshold` | 런타임이 선언한 요금 한도 상태와 그 문턱 |
| `call_cost` | agent | PROVIDER_DECLARED | `call.model`, `tokens.input_uncached`, `tokens.output`, `tokens.cache_read`, `tokens.cache_write_5m`, `tokens.cache_write_1h` | 마지막 호출의 비용 성분($) -- 토큰 × 공급자 단가 |
| `cost_estimate` | agent | PROVIDER_DECLARED | `call.model`, `tokens.input_uncached`, `tokens.output`, `tokens.cache_read`, `tokens.cache_write_5m`, `tokens.cache_write_1h` | 실행 누적 비용 추정($) |
| `cost_estimate_error` | agent | VALIDATED_EXPERIMENT | `call.model`, `tokens.input_uncached`, `tokens.output`, `tokens.cache_read`, `tokens.cache_write_5m`, `tokens.cache_write_1h`, `run.cost_usd` | (추정 − 런타임 보고) / 보고 -- 보고 시각까지의 호출만 |
| `external_outcome` | task | EXTERNAL_LABEL | `task.external_outcome` | 외부 평가 라벨(그대로) |
| `stream_end` | task | OBSERVED | `run.terminal_seen`, `run.transport_closed` | 종료 사건을 받았나 · 흐름이 닫혔나 |
| `turn_open` | task | OBSERVED | `run.turn_open` | 차례가 열려 있나(입력 수신 ~ 차례 끝) |
| `silence_ms` | task | OBSERVED | `run.activity_at_ms`, `run.heartbeat_at_ms` | 평가 시각 − 마지막 활동(사건 또는 런타임 heartbeat) |

## 정준 관측 (층 1)

| 정준 이름 | 텔레메트리 칸 | 실체 | 근거 |
|---|---|---|---|
| `tokens.input_uncached` | model_call.`input_tokens` | agent | OBSERVED |
| `tokens.cache_read` | model_call.`cache_read_input_tokens` | agent | OBSERVED |
| `tokens.cache_write` | model_call.`cache_creation_input_tokens` | agent | OBSERVED |
| `tokens.output` | model_call.`output_tokens` | agent | OBSERVED |
| `tokens.reasoning` | model_call.`thinking_tokens` | agent | OBSERVED |
| `tokens.reasoning_estimate` | model_call.`stream_thinking_estimate` | agent | ESTIMATE |
| `call.stop_reason` | model_call.`stop_reason` | agent | OBSERVED |
| `call.tool_uses` | model_call.`tool_calls_per_message` | agent | OBSERVED |
| `call.context_window` | model_call.`context_window` | agent | OBSERVED |
| `tool.name` | tool_call.`tool_name` | tool | OBSERVED |
| `tool.target` | tool_call.`tool_head` | tool | OBSERVED |
| `tool.signature` | tool_call.`tool_sig` | tool | OBSERVED |
| `tool.is_error` | tool_call.`is_error` | tool | OBSERVED |
| `tool.output_chars` | tool_call.`tool_output_chars` | tool | OBSERVED |
| `run.terminal_reason` | run.`terminal_reason` | task | OBSERVED |
| `run.result_subtype` | run.`result_subtype` | task | OBSERVED |
| `run.is_error` | run.`is_error` | task | OBSERVED |
| `run.cost_usd` | run.`cost_usd` | agent | OBSERVED |
| `run.context_window` | run.`context_window` | agent | OBSERVED |
| `run.compaction_threshold` | run.`autocompact_threshold` | agent | OBSERVED |
| `runtime.api_error_status` | run.`api_error_status` | runtime | OBSERVED |
| `runtime.rate_limit_utilization` | run.`rate_limit_utilization` | runtime | OBSERVED |
| `runtime.model` | run.`model` | runtime | OBSERVED |

## 의존 그래프

```
state:context_pressure  [context-pressure-v1, RUNTIME_DECLARED]
  <- metric:context_tokens  [OBSERVED]
       <- obs:tokens.input_uncached
       <- obs:tokens.cache_read
       <- obs:tokens.cache_write
  <- metric:context_window  [OBSERVED]
       <- obs:run.context_window
       <- obs:call.context_window
  <- metric:compaction_threshold  [RUNTIME_DECLARED]
       <- obs:run.compaction_threshold
state:execution_health  [execution-health-v1, DEFINITIONAL]
  <- metric:tool_results  [OBSERVED]
       <- obs:tool.is_error
       <- obs:tool.target
       <- obs:tool.name
  <- metric:tool_outcome_unobservable  [OBSERVED]
       <- obs:tool.is_error
       <- obs:tool.target
       <- obs:tool.name
  <- metric:tool_targets  [OBSERVED]
       <- obs:tool.is_error
       <- obs:tool.target
       <- obs:tool.name
  <- metric:tool_failure_rate  [OBSERVED]
       <- metric:tool_results
       <- metric:tool_errors
state:tool_execution_health  [tool-execution-health-v1, DEFINITIONAL]
  <- metric:tool_results  [OBSERVED]
       <- obs:tool.is_error
       <- obs:tool.target
       <- obs:tool.name
  <- metric:tool_outcome_unobservable  [OBSERVED]
       <- obs:tool.is_error
       <- obs:tool.target
       <- obs:tool.name
  <- metric:tool_targets  [OBSERVED]
       <- obs:tool.is_error
       <- obs:tool.target
       <- obs:tool.name
  <- metric:tool_failure_rate  [OBSERVED]
       <- metric:tool_results
       <- metric:tool_errors
state:completion_state  [completion-state-v1, RUNTIME_DECLARED]
  <- metric:termination  [RUNTIME_DECLARED]
       <- obs:run.result_subtype
       <- obs:run.terminal_reason
       <- obs:run.is_error
  <- metric:activity  [OBSERVED]
       <- obs:call.stop_reason
state:progress_state  [progress-state-v1, OPERATOR_ASSUMED]
  <- metric:identical_call_max  [OBSERVED]
       <- obs:tool.signature
  <- metric:termination  [RUNTIME_DECLARED]
       <- obs:run.result_subtype
       <- obs:run.terminal_reason
       <- obs:run.is_error
state:resource_state  [resource-state-v1, DEFINITIONAL]
  <- metric:cost_fraction  [OPERATOR_ASSUMED]
       <- metric:cost_usd
  <- metric:cost_margin  [OPERATOR_ASSUMED]
       <- metric:cost_usd
state:resource_pressure  [resource-pressure-v1, OPERATOR_ASSUMED]
  <- metric:cost_fraction  [OPERATOR_ASSUMED]
       <- metric:cost_usd
state:rate_limit_state  [rate-limit-state-v2, RUNTIME_DECLARED]
  <- metric:rate_limit_utilization  [OBSERVED]
       <- obs:runtime.rate_limit_utilization
  <- metric:rate_limit_declared  [RUNTIME_DECLARED]
       <- obs:runtime.rate_limit_status
       <- obs:runtime.rate_limit_threshold
  <- metric:api_error  [OBSERVED]
       <- obs:runtime.api_error_status
state:runtime_reliability  [runtime-reliability-v1, DEFINITIONAL]
  <- metric:api_error  [OBSERVED]
       <- obs:runtime.api_error_status
  <- metric:stop_reasons  [OBSERVED]
       <- obs:call.stop_reason
state:execution_interruption  [execution-interruption-v1, RUNTIME_DECLARED]
  <- metric:tool_timeouts  [RUNTIME_DECLARED]
       <- obs:tool.timed_out
  <- metric:tool_interruptions  [OBSERVED]
       <- obs:tool.interrupted
state:latency_state  [latency-state-v1, OPERATOR_ASSUMED]
  <- metric:call_latency  [OBSERVED]
       <- obs:call.t_start
       <- obs:call.t_end
  <- metric:first_chunk_latency  [OBSERVED]
       <- obs:call.first_chunk_ms
  <- metric:tool_latency  [OBSERVED]
       <- obs:tool.t_issued
       <- obs:tool.t_result
state:quality_state  [quality-state-v1, EXTERNAL_LABEL]
  <- metric:external_outcome  [EXTERNAL_LABEL]
       <- obs:task.external_outcome
state:liveness_state  [liveness-state-v1, DEFINITIONAL]
  <- metric:stream_end  [OBSERVED]
       <- obs:run.terminal_seen
       <- obs:run.transport_closed
  <- metric:termination  [RUNTIME_DECLARED]
       <- obs:run.result_subtype
       <- obs:run.terminal_reason
       <- obs:run.is_error
  <- metric:turn_open  [OBSERVED]
       <- obs:run.turn_open
  <- metric:silence_ms  [OBSERVED]
       <- obs:run.activity_at_ms
       <- obs:run.heartbeat_at_ms
```

## 넣지 않은 후보 상태와 까닭

| 후보 | 까닭 |
|---|---|
| `reasoning_load` | 생각 토큰이 많다 = 부하가 높다 의 문턱 근거가 없다. 생각 · 출력은 다른 정보(ρ 0.64)이지만 무엇을 뜻하는지 검증 안 됨. 지표 reasoning_tokens 로만 둔다 |
| `context_growth_rate` | '빠르다' 의 문턱 근거가 없다. 지표 context_growth 로만 둔다(≡ cache_write, 회계 항등식) |
| `context_compaction_risk` | context_pressure 의 ABOVE_COMPACTION_THRESHOLD 와 같은 것 -- 중복 |
| `context_budget_state` | context_pressure 와 같은 것 -- 중복 |
| `cache_growth_state · step_growth_state` | cache_read ~ 걸음 번호 ρ 0.99 -- 같은 현상(맥락이 자란다). 따로 두지 않는다 |
| `execution_latency · execution_stability` | 지연이 '느리다' 의 문턱 근거가 없다. 시간 센서는 수집기 정의에 달렸다(앞 실험) |
| `tool.availability` | 실패와 '쓸 수 없음' 을 관측으로 가르지 못한다(같은 is_error) |
| `tool.recent_failure` | tool_execution_health 의 UNRESOLVED_FAILURES 와 거의 같다 -- 중복 |
| `progress_state = ACTIVE/SLOW` | 활동(호출 수)은 진행이 아니다. 진행을 재는 검증된 근거가 없다 |
| `timeout_state` | 꼴 v3 의 timed_out(런타임 문구)으로 관측할 수 있게 되어 execution_interruption 이 맡는다 -- 따로 두지 않는다 |
| `execution_state(합성 열거)` | completion_state · execution_health · execution_interruption · rate_limit_state 를 한 값으로 접으면 정보가 사라진다(t11: 도구 시간 초과, 실행은 정상 종료) -- docs/MS_SENSING_REVIEW.md C2 |
| `provider_health` | runtime_reliability 와 같은 개념 -- HEALTHY 는 '관측 없음 ≠ 건강' 원칙에 어긋난다(리뷰 C4) |
| `quality_score` | 외부 라벨 없이 수를 만들지 않는다 -- quality_state 는 외부 평가 라벨을 옮길 뿐 |
| `token_budget_state` | 토큰 예산 설정이 없다. 필요하면 resource_state 와 같은 꼴로 더한다 |
| `interaction_state` | 사람 말 · 턴 관측이 텔레메트리 꼴에 없다 |
| `uncertainty_state` | 저장하지 않는다 -- 결정 문맥이 상태들의 유효성에서 투영한다(cogito5170/DC 의 validity.uncertain) |
| `liveness DEAD · ALIVE` | DEAD: 기록이 끊긴 것만으로 '대상이 죽음' 과 '수집이 죽음' 을 못 가른다(기록 밖 채널 필요). ALIVE: ACTIVE 와 같은 말을 문턱 없이 하게 된다 -- liveness_state 는 IN_TURN 에서 멈춘다 |
| `generation_state(stop_reason)` | 멈춤 사유를 이름만 바꾼 상태가 된다. 한도에 잘린 것만 runtime_reliability 의 근거로 쓴다 |
