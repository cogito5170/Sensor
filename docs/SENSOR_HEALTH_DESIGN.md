# 센서 설계 -- 건강 차원 (2026-10-02, 설계만 · 구현 전)

**범위: 센서 계층만.** 텔레메트리(원천에서 꺼내 정준 관측으로 만드는 일)는 따로 만들고 있다. 이 문서는 그 일을 하지 않는다.

센서가 텔레메트리에 바라는 것은 **§1 의 입력 계약**뿐이다.

    텔레메트리 계층 (별도)                 센서 계층 (이 문서)
    원천 -> 정준 관측(canonical) ──계약──> 지표(Metric) -> 상태(State) -> Decision Context

- 센서는 원천 꼴(stream-json · JSONL · traj)을 **모른다.** 정준 이름 · 값 · 근거(Basis) · null 의 뜻만 안다.
- 계약에 있는 입력이 안 오면 **UNKNOWN** 이다. 텔레메트리가 아직 그 입력을 못 내도 센서는 설계대로 돌고, 정직하게 UNKNOWN 을 낸다.
- 센서 시험은 **가짜 정준 관측**으로 한다. 원천 파일을 읽지 않는다.

근거는 `docs/MS_HEALTH_INVENTORY.md` 의 재고(원천에 무엇이 실제로 있었나)다. 이 문서의 판정 규칙은 그 재고 결과에 맞춘다.

## 0. 무엇을 짓고 무엇을 안 짓나

| # | 센서 | 꼴 | 새 상태? |
|---|---|---|---|
| S1 | **liveness** | 새 상태 `liveness_state` | 예 -- 유일한 새 상태 |
| S2 | 시간 초과의 **처분** | `execution_interruption` 규칙 v2 | 아니오(값 추가) |
| S3 | **dependency** 결함 격리 | 새 실체 DEPENDENCY + 상태 `dependency_fault` | 예(실체는 새것, 판정은 선언된 원인만) |
| S4 | 요금 한도 **여유** | provider 팩 지표 2개 | 아니오 |
| S5 | 런타임 **행동 결과**(압축 · 백그라운드 이동 · 권한 거부) | 지표 `runtime_actions` | 아니오 |
| S6 | **우리 정책의 행동 결과** | 상태 `action_state` -- 입력 계약만 정한다 | 예. 실행 주체가 행동 기록을 내야 돈다 |
| S7 | `resource_state` v2 | 규칙 v2 | 아니오(값 뜻 변경 -- **사용자 확인 대기**) |

**안 짓는 것과 이유**

- API 재시도 **횟수 · 원인** 센서: 세 원천 어디에도 없다. 계약에 선택 입력(`api.retry_attempt`)으로만 적는다.
- `provider_health = HEALTHY/DEGRADED`: 오류 부재는 건강의 증거가 아니다. 실측 반례도 있다(재고 D2: 429 가 있었는데 NO_FAILURE_OBSERVED). 단계를 나누려면 설정된 문턱이 있어야 한다(Circuit Breaker, [출처:전문]).
- `DEAD`: 기록이 끊긴 것만으로는 "대상이 죽음" 과 "수집이 죽음" 을 가를 수 없다. 기록 밖 채널이 필요하다.
- 요금 한도 **소진 예측**: 사용률이 0.01 단위로 양자화돼 있고 계정 전체의 소모다. 외삽하면 지어낸 수가 된다.
- `recovery_state` 를 따로 세우기: 같은 사건을 두 상태가 나눠 말하게 된다. 회복은 S2(처분)와 기존 `RECOVERED_FAILURES` 가 말한다.

## 1. 입력 계약 -- 센서가 텔레메트리에 바라는 정준 관측

꼴은 기존과 같다: `이름: (레코드 종류, 필드, 실체, Basis)`. null 의 뜻은 schema v2 규약을 따른다.

- `unobserved` -- 키 없음.
- `reported_null` -- 원천이 null 이라고 말함.

센서는 둘을 다르게 다룬다.

### 1.1 새 정준 관측

| 이름 | 실체 | Basis | 뜻 | 없으면 |
|---|---|---|---|---|
| `run.activity_at_ms` | TASK | OBSERVED | 이 실행에서 **어떤 사건이든** 마지막으로 온 시각(시간 기준은 레코드의 `time_base`) | liveness UNKNOWN |
| `run.terminal_seen` | TASK | OBSERVED | 런타임의 **종료 사건**(결과 레코드)을 받았나 | liveness UNKNOWN |
| `run.transport_closed` | TASK | OBSERVED | 원천의 흐름이 닫혔나(스트림 EOF · 프로세스 종료) | ENDED_WITHOUT_TERMINAL 판정 불가 |
| `run.turn_open` | TASK | OBSERVED | 차례가 열려 있나 -- 입력을 **받은 순간부터** 차례가 끝날 때까지 true | AWAITING_INPUT 판정 불가 -> UNKNOWN |
| `run.heartbeat_at_ms` | TASK | RUNTIME_DECLARED | 런타임이 **진행 중**이라고 보낸 마지막 신호 시각(구현 때 도구 단위 -> 실행 단위로) | 활동으로 안 셈(무음으로 봄) |
| `tool.timeout_disposition` | TOOL | RUNTIME_DECLARED | 시간 초과 뒤 런타임의 처분: `KILLED` · `BACKGROUNDED` | S2 는 v1 처럼 동작 |
| `dep.id` · `dep.kind` | DEPENDENCY | OBSERVED | 의존 대상과 종류: `provider` · `tool` · `network_policy` · `mcp_server` · `hook` · `external_http` | S3 UNKNOWN |
| `dep.fault` | DEPENDENCY | RUNTIME_DECLARED | **런타임이 구조화해 준** 결함 원인(예: `EGRESS_BLOCKED`, HTTP 상태, MCP 상태, 훅 오류) | NO_FAULT_DECLARED 아님 -> UNKNOWN |
| `dep.call_ok` | DEPENDENCY | OBSERVED | 그 대상에 대한 호출이 성공했나 | 덮임(coverage) 계산 불가 |
| `quota.window` · `quota.utilization` · `quota.status` · `quota.resets_at_ms` | ACCOUNT | PROVIDER_DECLARED | 계정 요금 한도 창마다 사용률 · 상태(`allowed` · `allowed_warning` · `rejected`) · 리셋 시각 | S4 지표 None |
| `runtime_action.kind` · `.trigger` · `.before` · `.after` · `.duration_ms` | TASK | RUNTIME_DECLARED | 런타임이 **스스로 한** 행동과 결과(압축: 전후 토큰, 백그라운드 이동, 권한 거부) | S5 지표 None(= 일어나지 않음이 **아니다**) |
| `action.decision_id` · `.context_id` · `.name` · `.executor` · `.status` · `.at_ms` | TASK | OBSERVED | **실행 주체가 내는** 행동 기록 -- S6 | action_state UNKNOWN |
| `api.retry_attempt` (선택) | RUNTIME | RUNTIME_DECLARED | API 재시도 회차 -- 원천이 줄 때만 | 지표 None |

새 실체 둘: `DEPENDENCY`(`dependency:<run>:<kind>:<id>`), `ACCOUNT`(`account:<계정 해시>`).

**요금 한도는 실행이 아니라 계정에 단다.** 같은 계정을 여러 세션이 함께 쓴다. 실행에 달면 "이 실행이 소모했다" 로 잘못 읽힌다.

### 1.2 기존 정준 관측에 대한 계약 조건 (재고에서 나온 것)

센서는 아래 조건이 지켜졌다고 **가정하고** 판정한다. 지켜지지 않으면 센서가 틀린 말을 한다. 그래서 텔레메트리 계층에 요구사항으로 넘긴다. 고치는 일은 그쪽 몫이다.

| 정준 관측 | 조건 | 어겼을 때 실측(재고) |
|---|---|---|
| `tool.timed_out` | **런타임이 구조화해 준 값**에서만 온다. 도구 출력 글 속 문구로 만들지 않는다 | 글 판정이 거짓 양성 2 · 거짓 음성 1 |
| 모델 호출 레코드 | **오류 응답(런타임이 합성한 메시지)은 모델 호출이 아니다** | 429 두 번이 `<synthetic>` 호출로 들어가 세션 비용 전체가 계산 불가 |
| `runtime.api_error_status` · `quota.status` | 실행 **중** 오류 · 거절도 채운다(실행 끝 요약에만 있는 원천이라도) | 429 거절이 있었는데 `NO_FAILURE_OBSERVED` |
| `runtime_action`(압축) | 압축 사건을 낸다 | 압축이 있었는데 없던 것처럼 됨 |

## 2. 센서별 설계

공통 규약은 기존 그대로다.

- Basis 가 없는 문턱은 쓰지 않는다.
- UNKNOWN 을 건강으로 바꾸지 않는다.
- STALE 은 현재로 쓰지 않는다.
- 모든 값은 `explain()` 으로 관측 id 까지 닿는다.

### S1 `liveness_state` -- 대상이 아직 움직이고 있나 (execution 과 다른 질문)

execution 은 "어떻게 끝났나", liveness 는 "지금 움직이나" 를 묻는다.

**지표**

- `silence_ms` = now − max(`run.activity_at_ms`, 열린 도구의 `tool.heartbeat_at_ms`) -- OBSERVED.
  - `now` 는 엔진이 받는 평가 시각이다. 엔진은 시계를 읽지 않는다(결정성 유지).
- `liveness_timeout_ms` -- **OPERATOR_ASSUMED.** 기본값이 없다.
  - 실체 종류마다 따로 둔다(F´ Svc::Health: 포트마다 운영자 설정 timeout, [출처:전문]).

**규칙 `liveness-state-v1`** (위에서부터 먼저 맞는 것)

| 값 | 조건 | Basis | 문턱 |
|---|---|---|---|
| `ENDED` | `run.terminal_seen` = true | OBSERVED | 없음 |
| `ENDED_WITHOUT_TERMINAL` | `run.transport_closed` = true 이고 종료 사건 없음 | DEFINITIONAL | 없음 |
| `AWAITING_INPUT` | `turn.open` = false 이고 그 뒤 새 입력 없음 | OBSERVED | 없음 |
| `IN_TURN` | `turn.open` = true, 운영자 timeout **없음** | OBSERVED | 없음 |
| `ACTIVE` | `turn.open` = true, `silence_ms` ≤ timeout | OPERATOR_ASSUMED | 운영자 |
| `STALLED` | `turn.open` = true, `silence_ms` > timeout (`min_consecutive` 로 흔들림 억제) | OPERATOR_ASSUMED | 운영자 |
| `UNKNOWN` | 시각 · 차례 관측이 없음(예: SWE-agent traj) | -- | -- |

- `ENDED_WITHOUT_TERMINAL` 는 정의로 결함이다. 흐름은 닫혔는데 런타임이 끝났다고 말하지 않았다.
- `AWAITING_INPUT` 은 죽은 것이 아니라 사람을 기다리는 것이다. 재고: 이 세션의 5.5시간 공백이 이것이다.
- 운영자 timeout 이 없으면 `ACTIVE` 와 `STALLED` 를 **둘 다** 내지 않고 `IN_TURN` 에서 멈춘다. ACTIVE 도 "멈추지 않았다" 는 판정이라 문턱이 필요하기 때문이다.
- TTL: `ENDED` 는 PERMANENT, 나머지는 평가 시각에 묶여 있어 다음 `tick` 에서 다시 판정한다.

**사소한 설명을 막는 장치** -- 시험으로 붙든다.

- 오래 도는 도구가 heartbeat 를 보내는 동안은 무음이 아니다. 재고: t11 은 26.7초 무음이었지만 heartbeat 가 있었다.
- 차례가 닫힌 뒤 공백은 STALLED 가 아니라 AWAITING_INPUT 이다.
- 수신 시각과 런타임 시각을 섞어 빼지 않는다(레코드의 `time_base` 가 다르면 UNKNOWN).

**상태로 내지 않는 것:** `DEAD`(기록 안에서 판정 불가), `ALIVE`(ACTIVE 와 같은 뜻을 문턱 없이 말하게 된다).

#### S1 구현 (2026-10-02) -- 설계에서 달라진 점

코드: `llmsensor/sensing/liveness/`. 시험은 `tests/test_liveness.py` 22개로, 가짜 정준 입력만 씁니다. 변이 9개는 `eval/mutation_ms.py` 에 있고 전부 RED 입니다.

**입력을 줄였다(§1.1 수정).**
- `tool.heartbeat_at_ms` 대신 `run.heartbeat_at_ms` 를 쓴다. 실행 하나의 liveness 에는 "가장 늦은 런타임 신호" 하나면 충분하다.
- `input.enqueued_at_ms` 를 뺐다. 대신 `run.turn_open` 의 뜻을 "입력을 **받은 순간부터** 차례가 끝날 때까지 true" 로 정했다. 받았는데 처리가 시작되지 않은 입력의 침묵도 그래서 잴 수 있다.
- `run.activity_clock` 을 뺐다. 기존 레코드의 `time_base` 로 같은 일을 한다. 두 시각의 기준이 다르면 빼지 않고 UNKNOWN 을 낸다.

**종료 판정에 기존 지표를 재사용한다.** 런타임 종료 선언(`termination`: result_subtype · terminal_reason · is_error)도 ENDED 의 근거로 받는다(RUNTIME_DECLARED).
- 단 종료 칸이 **전부 null 로 보고된** 요약은 종료 선언이 아니다.
- 이 경우는 시험이 먼저 잡았다. `termination` 지표는 전부 None 인 dict 도 값으로 내는데, 첫 구현이 그것을 ENDED 로 읽었다.

**엔진 변경 셋.** 다른 상태의 뜻은 그대로다.
1. `Result.basis` -- 값마다 근거를 따로 남긴다. 같은 상태라도 ENDED 는 OBSERVED 또는 RUNTIME_DECLARED, ACTIVE/STALLED 는 OPERATOR_ASSUMED 다.
2. `Rule.clock_values` -- 평가 순간에만 참인 값(ACTIVE · STALLED)이다. 평가 뒤 시각으로 질의하면 `view()` 가 STALE 로 돌려준다. STALE 을 현재로 쓰지 않는다.
3. `StateEngine.advance(run_id, now)` -- 시각에 기대는 규칙만 다시 잰다.
   - now 는 호출자가 준다. 엔진은 여전히 시계를 읽지 않는다(시험이 `time.time` 을 막고 확인한다).
   - 관측보다 이른 now 는 거절한다.

**설정.** `liveness_timeout_ms` 는 기본 None 이다. TTL 에 `liveness_state` 10분을 더했다(다른 상태와 같은 OPERATOR_ASSUMED 기본값).

**실제 레코드 301 실행에 돌린 결과.**
- liveness 를 뺀 나머지 상태 · 전이 · 생애 사건은 구현 전과 **같다.**
- liveness 자체는 이렇게 나왔다.
  - claude -p 12 · SWE-agent 288 은 ENDED(런타임 종료 선언).
  - 이 세션 스냅숏 1 은 UNKNOWN(차례 관측 없음).
- 입력 다섯은 아직 어느 레코드에도 없다. 그래서 ACTIVE · STALLED · AWAITING_INPUT 은 **텔레메트리 계층이 그 칸을 채운 뒤에야** 실제 데이터에서 나온다. 지금 실데이터로 확인된 것은 ENDED 와 UNKNOWN 뿐이다.

### S2 `execution_interruption` v2 -- 시간 초과가 **어떻게 처리됐나**

v1 값은 `TIMEOUT_OBSERVED` · `INTERRUPTED_OBSERVED` · `NONE_OBSERVED` · `UNKNOWN` 이다. v2 는 `TIMEOUT_OBSERVED` 를 처분으로 가른다.

| 값 | 조건 |
|---|---|
| `TIMEOUT_KILLED` | 시간 초과 + 처분 KILLED |
| `TIMEOUT_BACKGROUNDED` | 시간 초과 + 처분 BACKGROUNDED |
| `TIMEOUT_OBSERVED` | 시간 초과 + 처분 관측 없음 (v1 과 같은 값 -- 처분을 모르면 짓지 않는다) |
| `INTERRUPTED_OBSERVED` · `NONE_OBSERVED` · `UNKNOWN` | v1 그대로 |

- `TIMEOUT_BACKGROUNDED` 는 런타임의 대체 경로로, 제안의 FALLBACK_USED 에 해당한다.
- 시간 초과가 실패와 같은 말이 아니라는 근거: Google `DEADLINE_EXCEEDED` 주석 "may be returned even if the operation has completed successfully"([출처:전문]).
- 새 처분 관측이 없으면 v1 과 **같은 값**이다. 회귀 시험으로 붙든다(앞 rate_limit v2 와 같은 방식).
- `RECOVERY_EXHAUSTED` 는 짓지 않는다 -- 재시도 상한이 선언되지 않는다.

### S3 `dependency_fault` -- 결함이 **어디서** 났나 (격리)

실체는 `DEPENDENCY` 이고, 의존 대상마다 하나씩 선다. 이미 있는 `tool_execution_health`(도구마다)는 그대로 두고, 그 아래 원인을 나눈다.

| 값 | 조건 | Basis |
|---|---|---|
| `FAULT_DECLARED` | `dep.fault` 가 하나 이상 -- 값에 원인 종류(`EGRESS_BLOCKED` 등)를 싣는다 | RUNTIME_DECLARED |
| `NO_FAULT_DECLARED` | 호출이 있었고(`dep.call_ok` 덮임 > 0) 선언된 결함 없음 | OBSERVED |
| `UNKNOWN` | 그 대상에 대한 관측 없음 | -- |

- `NO_FAULT_DECLARED` 는 **HEALTHY 가 아니다.** 이름부터 "선언된 결함 없음" 으로 둔다.
- 원인을 **해석하지 않는다.** Bash stderr 글에서 "네트워크 같다" 를 읽어 내지 않는다. 구조화되지 않은 실패는 `tool_execution_health` 에만 남고 S3 에는 안 온다.
- 비핵심 의존성의 결함을 상위에서 degraded 로 읽을지는 **정책/설정의 일**이다(Health Endpoint Monitoring, [출처:전문]). 센서는 핵심 여부를 모른다.
- DC 에는 실행 하나에 대해 `FAULT_DECLARED` 인 의존 대상 목록만 투영한다. 원 오류 글은 넣지 않는다.

### S4 요금 한도 여유 -- provider 팩 지표 (새 상태 없음)

| 지표 | 정의 | Basis | None 인 때 |
|---|---|---|---|
| `quota_headroom` | 창마다 1 − `quota.utilization` | PROVIDER_DECLARED | 사용률 미관측 |
| `quota_time_to_reset_ms` | 창마다 `quota.resets_at_ms` − now | PROVIDER_DECLARED | 리셋 시각 미관측 |

- 상태는 기존 `rate_limit_state` v2 가 낸다(WARNING · LIMITED · EXHAUSTED).
- 바꾸는 것은 입력 하나다. `quota.status = rejected` 를 LIMITED 의 증거로 **추가**한다. 지금은 HTTP 429 만 본다. 기존 값의 뜻은 그대로다.
- **소진 시각 예측은 내지 않는다.**
  - 양자화: 재고에서 0.70 -> 0.72, 두 칸.
  - 계정 공유: 이 실행의 속도가 아니다.
  - 둘 다 사소한 설명이고, 죽일 방법이 이 입력에는 없다.

### S5 `runtime_actions` -- 런타임이 스스로 한 행동과 그 결과 (지표)

- 종류마다 횟수와 마지막 결과를 낸다.
  - 압축: trigger · before/after 토큰 · 걸린 시간
  - 백그라운드 이동
  - 권한 거부
- 이 지표를 쓰는 곳은 두 군데다.
  - `context_pressure`: 압축 사건은 "압축 문턱을 실제로 넘었다" 는 **직접 증거**다. 창 크기가 선언되지 않아 margin 을 못 잴 때도(재고: 이 세션 opus) 그 사실은 남는다. 새 값을 만들지는 않는다. explain 근거로만 싣고, 압축 뒤 `after` 를 현재 맥락 토큰의 관측으로 쓴다.
  - S2: 백그라운드 이동이 처분의 근거다.
- **모델이 쓴 요약**(예: `post_turn_summary.status_category`)은 관측이 아니라 판단이다. 이 지표에 넣지 않는다.

### S6 `action_state` -- 우리 정책의 행동이 실제로 어떻게 됐나

**지금은 우리 정책의 결정을 실행하는 주체가 없다.** 그래서 센서는 **실행 주체가 내야 할 기록의 꼴**(§1 `action.*`)만 정하고 판정한다. 실행 주체는 누구든 그 꼴만 맞추면 된다.

- 상태 값: `PROPOSED` · `ACCEPTED` · `STARTED` · `COMPLETED` · `FAILED` · `CANCELLED` · `UNKNOWN`
  - 행동 기록의 마지막 status. 전이 순서를 어긴 기록(예: STARTED 없이 COMPLETED)은 INVALID 다.
- **효과 판정은 상태가 아니라 비교 지표다** -- `action_effect`:
  - 행동의 `context_id` 로 얼린 DC 의 상태 값과, 행동 COMPLETED 뒤 첫 평가의 같은 상태 값을 짝지어 낸다.
  - "좋아졌다" 는 판정은 하지 않는다. 목표를 아는 것은 정책이다.
- 이것으로 고리가 닫힌다: DC(얼린 근거) -> Decision -> 행동 기록 -> 새 관측 -> 새 상태. `explain()` 은 행동에서 그 결정의 DC 까지 거슬러 간다.

### S7 `resource_state` v2 -- **사용자 확인 대기**

앞 답변을 이렇게 읽었다.

- 예산이 없으면 `UNKNOWN`. 지금은 `NOT_APPLICABLE`.
- 실행 중에도 비용 추정으로 판정한다. 공급자 단가로 계산한 값이 런타임 보고와 두 모형 모두 정확히 같았다.

확인되면 규칙 버전을 올린다. 정책 쪽에서는 `not_applicable` 목록이 `uncertain` 목록으로 옮겨 간다.

## 3. 시험 설계 -- 짓기 전에 정한다

모두 **가짜 정준 관측**으로 한다. 원천 파일을 읽지 않는다. 각 줄은 "이 고장을 심으면 빨개져야 한다" 이다.

| 센서 | 심을 고장 |
|---|---|
| S1 | 운영자 timeout 없이 ACTIVE/STALLED 를 낸다 · heartbeat 를 무음으로 센다 · 차례 밖 공백을 STALLED 로 · 종료 사건 없이 닫힌 흐름을 ENDED 로 · 엔진이 시계를 읽는다(결정성) |
| S2 | 처분 관측이 없는데 KILLED 로 짐작 · 처분 관측이 없을 때 v1 과 값이 달라진다 |
| S3 | 구조화되지 않은 실패를 원인으로 분류 · 호출 0 인데 NO_FAULT_DECLARED · 대상 하나의 결함을 다른 대상에 단다 |
| S4 | 사용률 없을 때 여유를 1.0 으로 · `rejected` 를 무시 · 계정 값을 실행 실체에 단다 |
| S5 | 사건이 없을 때 "0 회" 와 "관측 없음" 을 섞는다 · 모델 요약을 행동 결과로 받는다 |
| S6 | 순서를 어긴 기록을 받는다 · 효과 지표가 좋다/나쁘다를 판정한다 · 얼린 DC 대신 현재 상태와 비교한다 |
| 공통 | 계약 조건(§1.2)을 어긴 입력이 오면 센서가 **어떻게** 틀리는지를 시험으로 적어 둔다 -- 텔레메트리 쪽이 고쳤는지 확인하는 기준이 된다 |

평가는 Phase 8 과 같은 틀(계산 가능률 · UNKNOWN 률 · provenance · 결정성 · 변이 · 상태 영향률)이다. 단 **텔레메트리 계층의 새 출력이 나온 뒤**에 잰다. 지금 수집기로 재면 §1.2 결함이 그대로 섞인다.

## 4. 사용자가 정할 것

1. **S6 의 실행 주체.** 꼴은 정했다. 누가 `action.*` 기록을 내나(MS 쪽 실행기인가, 별도인가).
2. **S7 확인.** 예산 없음 -> UNKNOWN, 실행 중 비용으로 판정 -- 맞나.
3. **§1 계약을 텔레메트리 쪽 이름에 맞출지.** 정준 이름은 센서 쪽에서 정했다. 만들고 있는 텔레메트리의 필드 이름이 다르면 대응표 하나로 잇는다. 센서 코드는 정준 이름만 본다.
