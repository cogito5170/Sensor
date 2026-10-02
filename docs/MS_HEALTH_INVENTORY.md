# 건강 차원 재고 -- liveness · retry · recovery · dependency · action outcome 이 원천에 이미 있나 (2026-10-02)

**짓기 전 조사다. 새 센서는 아직 하나도 짓지 않았다.** 무엇을 더할지는 이 문서를 보고 정한다.

잰 것: `eval/health_inventory.py` -> `eval/results/health_inventory.json`. 원천은 앞 실험의 원본 그대로다.

- claude -p stream-json 12 실행
- 이 세션 자신의 Claude Code JSONL(02:13 재개 · 02:58 압축 이후까지 포함한 사본)
- SWE-agent traj 288

결과 JSON 에는 개수 · 키 · 값 집합만 싣는다. 원문에는 이 세션의 대화가 들어 있어 싣지 않는다.

## 0. 요지

| 차원 | 상태로 이미 있다 | 원천에 있는데 안 거둔다 | 원천에 없다 | 판정 |
|---|---|---|---|---|
| **liveness** | 없음 | stream 줄 도착 시각, `status:requesting` 41(= message_start 41), `tool_progress` 8(30초마다 `heartbeat:true`), 끝 `result` 12/12, JSONL 의 `queue-operation`(사용자 입력 도착) | SWE-agent 는 시각이 없다. **수집기 자신의 죽음은 같은 기록으로 못 본다** | **추가(P0)** -- 단 문턱 없이 되는 값만 |
| **retry** | `tool_retries`(겨냥 단위), `api_retry_time`(세션 끝 시간 합) | -- | **API 재시도 횟수 · 원인은 세 원천 어디에도 없다** | **추가 안 함** -- 못 보는 것은 UNKNOWN |
| **recovery** | `execution_health = RECOVERED_FAILURES`(= 제안의 SUCCESS_AFTER_RETRY, 겨냥 단위), 엔진 Lifecycle `RECOVER` | 시간 초과 뒤 **백그라운드로 옮김** 1(`timedOutAfterMs`+`backgroundTaskId`), `unifiedRateLimitFallbackAvailable:false`, `subagent_stats`(전부 0) | 재시도 **상한**(maxRetries) 선언이 없다 -> RECOVERY_EXHAUSTED 근거 없음 | **새 상태 말고 기존 상태에 증거를 더한다** |
| **dependency** | `api_error` · `runtime_reliability`(공급자), `tool_execution_health`(**도구 실체마다** -- 이미 도구 단위 격리) | WebFetch `EGRESS_BLOCKED` 2(오류 종류 · 도메인이 구조화돼 있다), WebFetch `code` · `durationMs`, `init.mcp_servers`(12/12 빈 목록), stop hook 오류 0/6, `quotaLimits`(**계정** 단위) | Bash 안의 원인(네트워크/파일시스템)은 글을 해석해야 한다 | **부분 추가(P1)** -- 런타임이 구조화해 준 원인만 |
| **action outcome** | 없음. 참조 정책은 Decision 만 내고 **실행하는 주체가 없다** | 런타임 **자신의** 행동과 결과: `compact_boundary` 1(auto, 783,484 -> 7,209 토큰, 69.7초), 백그라운드 이동 1, `permission_denials` 0, `queue remove absorbed_mid_turn` 2 | 우리 정책의 행동을 실행하는 주체 | **두 갈래** -- 런타임 행동은 지금 거둘 수 있다. 우리 정책의 action_state 는 실행기가 정해져야 한다(사용자 결정) |

## 1. 이 조사에서 찾은 결함 -- 이미 지은 센서가 틀리게 말하고 있었다

조사하다 넷이 나왔다. 넷 다 **수집기가 원천에 있는 것을 놓쳐서** 났다.

**D1 · 시간 초과 판정이 글자를 본다 -- 거짓 양성 2, 거짓 음성 1 (이 세션 Bash 204 결과 중).**

- *거짓 양성 2.* 내 분석 출력이 `Command timed out after` 문구를 **인용**하고 있었다(is_error=false).
- *거짓 음성 1.* 실제 600초 초과는 문구가 달랐다: "Command did not complete within its 600s timeout and was moved to the background".
- 그래서 `execution_interruption = TIMEOUT_OBSERVED` 는 **맞지만 틀린 근거로** 나왔다. `explain()` 은 엉뚱한 두 호출을 가리킨다.
- 런타임은 `toolUseResult.timedOutAfterMs` 로 **구조화해서** 준다.

**D2 · 429 를 못 거둔다.** 이 세션은 20:45 에 실제로 한도에 걸렸다. 원천에 남은 것은 이렇다.

    apiErrorStatus 429, error "rate_limit"
    quotaLimits {status rejected, rateLimitType five_hour, overageStatus rejected,
                 overageDisabledReason out_of_credits, unifiedRateLimitFallbackAvailable false}

수집기는 이것을 **모델 호출 2개**(`model: "<synthetic>"`, 토큰 0)로 만들었다. 그 결과 이렇게 나왔다.

- `rate_limit_state = UNKNOWN`
- **`runtime_reliability = NO_FAILURE_OBSERVED`** -- 거절이 있었는데 "실패 관측 없음" 이다.

**D3 · 그 여파로 세션 전체 비용이 계산 불가.** `<synthetic>` 은 단가표에 없다. 부분 합을 안 내는 규칙(옳다)이 세션 전체를 None 으로 만든다. 두 줄을 빼면 $44.26 이다.

**D4 · 압축 사건을 못 거둔다.** `compact_boundary` 가 원천에 있다. 카탈로그는 아직 "이 세션에서 실제로 일어나지 않아 꼴을 못 보았다" 라고 적고 있다.

**Phase 8 수치에 미치는 영향 -- 없다.** 평가 레코드의 이 세션 스냅숏은 19:53 것이다. 429(20:45), D1 의 두 거짓 양성(19:55 · 03:15), 600초 초과(02:39), 압축(02:58)은 모두 그 뒤다.

**그러나 Phase 8 의 두 문장은 고쳐 읽어야 한다.** "LIMITED · EXHAUSTED 가 한 번도 관측되지 않았다" 와 "압축이 없었다" 는 **그 스냅숏에 한한 말**이다. 같은 세션이 그 뒤에 두 상황을 다 겪었고, 지금 수집기는 그것을 **못 본다.**

## 2. 차원별 근거

### liveness

**재 보니 이렇다.**

- stream 12 실행 중 11 은 최대 무음 간격이 ≤ 2.7초였다. t11(150초 sleep, 120초에 끊김)만 26.7초였다.
- t11 은 그 동안 런타임이 `tool_progress` 를 3초 · 30초 · 33초 … 로 보냈다. `heartbeat:true` 는 30 · 60 · 90 · 120초에 왔다.
- **12/12 가 `result` 줄로 끝났다** -- 멈춘 실행이 이 데이터에는 없다.

**문턱 없이 되는 값.**

- `ENDED` -- `result` 줄을 받음.
- `ENDED_WITHOUT_RESULT` -- 스트림이 닫혔는데 `result` 가 없음. 정의로 결함이다.
- `AWAITING_INPUT` -- JSONL 에서 차례가 끝나고 다음 `enqueue` 전.
  - 이 세션의 20:46 -> 02:13 공백 5.5시간이 이것이다. **죽은 것이 아니라 사람을 기다린 것이다.**
- `ACTIVE` -- 차례가 열려 있고 마지막 줄 이후 아직 판정 문턱을 안 넘음.

**문턱이 있어야 하는 값.**

- `STALLED` 는 "얼마나 조용하면 멈춘 것인가" 를 정해야 한다.
- 30초 heartbeat 간격은 **관측된** 값이지 **선언된** 값이 아니다.
- F´ Svc::Health 도 핑 timeout 을 **포트마다 운영자가 설정**한다([출처:전문], `paper/선행조사/MS센싱.md`).
- -> 운영자 timeout 이 없으면 N/A. latency 와 같은 규약이다.

**못 하는 것.** 제안의 "C. collector 가 놓침" 과 "A. 모델이 죽음" 은 **같은 기록 안에서는 구별할 수 없다.** 기록이 끊긴 것 자체가 유일한 증거이기 때문이다. 기록 밖의 채널(프로세스 확인 · 합성 점검)이 있어야 한다. 그래서 `DEAD` 는 이 원천으로 내지 않는다.

### retry

- 도구 재시도는 이미 있다(`tool_retries`).
- API 재시도는 `totalAPIDuration − totalAPIDurationWithoutRetries` 로 **시간 합**만 있다(이 세션 129ms, 자식 실행 11ms). **횟수와 원인은 어느 원천에도 없다.**
- stream 에 재시도 사건이 있는지는 **재시도가 한 번도 안 일어나서 꼴을 못 보았다.** "없다" 가 아니라 "못 봤다" 이다.

### recovery

- 제안의 SUCCESS_AFTER_RETRY 는 `RECOVERED_FAILURES` 로 이미 있다(실패했던 겨냥이 뒤에 성공).
- 새로 보인 것은 **처분**이다. 같은 시간 초과라도 둘은 다른 결과다.
  - t11 은 죽였다(exit 143, is_error=true).
  - 이 세션의 600초는 **백그라운드로 옮겼다**(is_error=false).
  - Google `DEADLINE_EXCEEDED` 주석의 "may be returned even if the operation has completed successfully"([출처:전문])와 같은 결이다.
- 그래서 `recovery_state` 를 따로 세우기보다, **`execution_interruption` 에 처분(KILLED · MOVED_TO_BACKGROUND)을 더하는 것**이 맞다. 같은 사건을 두 상태가 나눠 말하지 않게 하려는 것이다.
- `RECOVERY_EXHAUSTED` 는 재시도 상한이 선언돼야 판정된다. 원천에 없다.

### dependency

- **도구 단위 격리는 이미 있다** -- `tool_execution_health` 는 도구 실체마다 따로 선다.
- 런타임이 원인을 **구조화해 주는** 것은 이렇다.
  - WebFetch `{"error_type":"EGRESS_BLOCKED","domain":...}`
  - WebFetch `code`/`codeText`/`durationMs`
  - `init.mcp_servers`
  - stop hook `hookErrors`
  - 이것들만 거두면 문턱도 해석도 없이 네트워크 정책 · 외부 서비스 · MCP · 훅을 가를 수 있다.
- Bash 안의 원인(네트워크인지 파일시스템인지)은 stderr 글을 해석해야 한다. 그것은 짐작이라 UNKNOWN 으로 둔다.
- **요금 한도는 실행이 아니라 계정의 것이다.**
  - stream 12 실행의 `five_hour` 사용률은 0.70 -> 0.72 로 올랐다. 그 사이 같은 계정의 이 세션도 쓰고 있었다.
  - 그러니 실행 실체에 달면 "이 실행이 소모했다" 로 잘못 읽힌다. 계정 실체가 따로 있어야 한다.

### action outcome

- 우리 쪽: 정책은 `Decision` 을 낼 뿐 실행하지 않는다. **실행 결과를 관측하려면 먼저 누가 실행하는지가 정해져야 한다.** 이것은 사용자 결정이다(§4).
- 런타임 쪽: 런타임이 스스로 한 행동과 그 결과는 지금도 원천에 있다.
  - 압축: trigger · 전후 토큰 · 걸린 시간
  - 백그라운드 이동
  - 권한 거부
  - **특히 압축은 `context_pressure` 의 실패 영역이 실제로 일어났다는 직접 증거다.**
- `post_turn_summary`(completed 10 · blocked 1)는 **모델이 쓴 요약**이다. 관측이 아니라 판단이므로 결과 센서로 쓰지 않는다.

## 3. 제안 중 근거와 부딪히는 것

- **`provider_health = HEALTHY`** -- 이번에 반례가 실제로 나왔다.
  - D2 에서 429 가 있었는데도 오류 부재로 `NO_FAILURE_OBSERVED` 가 나왔다.
  - 부재를 HEALTHY 로 읽었다면 "건강" 이라고 말했을 것이다.
  - THROTTLED · UNAVAILABLE 처럼 **선언된 신호로만** 내는 값은 된다. HEALTHY · DEGRADED 는 Circuit Breaker 처럼 **설정된 문턱**이 있어야 한다([출처:전문]).
- **`context_pressure` 의 HEADROOM · RATE_OF_GROWTH** -- 이미 있다(`compaction_margin` · `context_growth`).
  - PROJECTED_LIMIT 는 둘의 비(margin/growth)이고, 선형 외삽이라 ESTIMATE 다.
  - 이 세션의 압축은 opus 의 창 크기가 JSONL 에 선언되지 않아 margin 자체를 못 쟀다. `context_pressure = UNKNOWN`.
- **`resource_capacity` 의 "언제 한도에 닿나"** -- 남은 양(1 − 사용률)과 리셋 시각은 **런타임이 선언**한다. 운영자 문턱 없이 된다.
  - 그러나 **소모 속도는 이 데이터로 못 잰다.** 사용률이 0.01 단위로 양자화돼 있고, 12 실행 동안 0.70 -> 0.72 로 두 칸 움직였을 뿐이다.
  - 게다가 계정 전체의 소모라 이 실행의 속도가 아니다(사소한 설명). 외삽하지 않는다.

## 4. 다음에 지을 것 -- 순서 제안 (승인 뒤 짓는다)

1. **결함 D1-D4 고침(수집기, schema v4).**
   - 시간 초과: 구조화 필드 우선, 글 판정은 is_error 이고 결과가 `Exit code` 로 시작할 때만.
   - 429: `run.api_error_status` · `rate_limit_status` 로 거두고 `<synthetic>` 은 모델 호출에서 뺀다.
   - 압축 사건을 거둔다.
   - 고치고 나서 Phase 8 을 지금 원천(429 · 압축이 든 것)으로 다시 잰다.
2. **`liveness_state` v1** -- ENDED · ENDED_WITHOUT_RESULT · AWAITING_INPUT · ACTIVE · UNKNOWN. STALLED 는 운영자 timeout 이 있을 때만.
3. **처분** -- `execution_interruption` 에 KILLED · MOVED_TO_BACKGROUND.
4. **dependency** -- 구조화된 원인만(EGRESS_BLOCKED · HTTP code · MCP status · hook error). 계정 실체(요금 한도).
5. **런타임 행동 결과** -- 압축 사건을 context 쪽 관측으로.

새 상태는 1개(liveness)다. 나머지는 거두기와 기존 상태의 값 추가다.

**사용자가 정할 것**

- **우리 정책의 행동을 누가 실행하나.** 그것이 정해져야 `action_state` 를 지을 수 있다. 지금은 실행기가 없어 관측할 대상이 없다.
- **(앞 §6-1 · 6-2 에 대한 답으로 읽은 것 -- 맞는지 확인)**
  - 예산이 없으면 `resource_state = UNKNOWN`.
  - 실행 중 비용으로 `resource_state` 를 낸다.
  - 둘 다 규칙 v2 로 1 번 다음에 넣는다.

## 5. 출처

- **사용자가 붙인 링크는 읽지 못했다.** learn.microsoft.com · nodis3.gsfc.nasa.gov · swehb.nasa.gov · techport.nasa.gov 다섯 곳 모두 이 환경의 네트워크 정책이 막았다(프록시 CONNECT 403, 2026-10-02 재확인). **[출처:사용자 제공 · 미확인]**. 이 문서의 판단은 그 링크에 기대지 않는다.
- 판단에 쓴 외부 근거는 앞 조사에서 **전문을 읽은** 것뿐이다(`paper/선행조사/MS센싱.md`).
  - F´ Svc::Health -- 핑 timeout 은 운영자 설정
  - Health Endpoint Monitoring -- 비핵심 의존성 불가 시 degraded
  - Circuit Breaker -- 단계는 설정된 문턱으로
  - google.rpc.Code
- 나머지는 전부 이 저장소 원천을 직접 센 것이다.
