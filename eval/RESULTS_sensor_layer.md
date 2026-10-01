# 결과 -- LLM 센서 층 (사전등록 `PREREG_sensor_layer.md`, 얼린 커밋 1719258) · 2026-10-01

원자료: `results/sensor_layer.json`. 설계 문서는 [`docs/SENSOR_LAYER.md`](../docs/SENSOR_LAYER.md).

## 모은 것

| 원천 | 실행 | 모형 호출 | 도구 호출 | 모형 |
|---|---|---|---|---|
| cc_jsonl_self (이 세션) | 1 | 78 | 81 | Opus 5.5 |
| cc_stream (claude -p 과업 12) | 12 | 41 | 48 | Haiku 4.5 |
| cc_jsonl_child (같은 12 실행의 JSONL -- 대조 전용) | 12 | 41 | 48 | Haiku 4.5 |
| sweagent | 288 | 9,378 | 9,378 | Claude 3.5 Sonnet |

레코드 19,406 개, 꼴 위반 0. claude -p 12 실행 비용 합 $0.43.

## 1. 독립 대조 -- 통과

같은 모형 호출 41 개를 두 수집기(stream-json 의 `message_delta` · Claude Code JSONL)가 따로 보았다.
**토큰 넷(input · output · cache_read · cache_creation)이 41/41 호출에서 정확히 같았다.** 실행 12 개 모두, 호출 합이
런타임의 `result.usage` 와 정확히 같았다. → 토큰 센서의 수집 경로는 믿어도 된다.

## 2. 실측 가용성 (null 아닌 비율)

| 칸 | cc_jsonl_self | cc_stream | sweagent |
|---|---|---|---|
| 호출별 토큰 넷 | 1.00 | 1.00 | **0** (실행 합계만) |
| thinking_tokens | 1.00 | 1.00 | 0 |
| stop_reason | 1.00 | 1.00 | 0 |
| 호출 시각 | 1.00 (유닉스) | 1.00 (수집기 도착) | **0** |
| first_chunk_ms · stream_chunks | 0 | 1.00 | 0 |
| stream_thinking_estimate | 0 | 0.51 | 0 |
| thinking_duration_ms | 0.85 | 0 | 0 |
| context_window | 0 | 1.00 | 0 |
| 도구 is_error | 0.99 (진행 중 1) | 1.00 | **0** |
| 도구 지연(시각 차) | 0.99 | 1.00 | 0 |
| 런타임 보고 도구 시간 | 0.05 | 0 | 0 |

## 3. 사건 -- 무엇이 실제로 나왔나

| 유발하려던 것 | 나온 것 | 센서 |
|---|---|---|
| 도구 오류(t04 · t07) | `is_error: true` + "Exit code N" | tool_is_error (형 1) |
| 재시도(t07 flaky) | 실패 2 → 성공 1, 같은 겨냥 | retry_count (형 2) |
| 시간 초과(t11) | **전용 칸 없음.** `is_error: true`, 결과 글 "Exit code 143 · Command timed out after 2m 0s", 지연 120,303 ms | timeout 은 **형 2** (지연 ≈ 도구 한도 · 종료 143) |
| 회전 상한(t08) | `result.subtype = error_max_turns`, `terminal_reason = max_turns`, `is_error = true`, **ttft_ms · api_error_status 키가 없다** | terminal_reason (형 1) |
| 잘못된 인자(t12) | **안 일어났다** -- 런타임이 상대 경로를 받아들였다 | malformed_call = **UNKNOWN** |
| stop_reason | tool_use · end_turn 만 나왔다. max_tokens · refusal · pause_turn · model_context_window_exceeded · compaction 은 **한 번도 안 나왔다** | 값 집합은 문서(D)로만 안다 |
| 압축 · 스트림 오류 · logprobs · 기억 조회 | 안 나왔다 | UNKNOWN |

요금 한도 사건(`rate_limit_event`)은 매 실행에 나왔다(7일 사용률 0.80).

## 4. 생성 도중 토큰 -- Q2 의 실측

API 는 **생성 도중 토큰 수를 주지 않는다**: `message_start` 에 입력 + 출력 1~4, `message_delta`(끝)에 누적 최종값.
도중에 볼 수 있는 것은 둘이다.
- `content_block_delta` 조각 수 -- 조각 ≠ 토큰.
- Claude Code 런타임의 `system/thinking_tokens` 추정 -- 41 호출 중 21 호출에만 나왔고, 최종 thinking_tokens 대비
  **중앙 1.68 배**(0.86~2.25)로 과대했다. 실시간 근사로는 쓸 수 있으나 값으로는 못 믿는다.

## 5. 중복 -- 호출 단위 (n = 119: self 78 + stream 41)

| 쌍 | 합친 ρ | self | stream | 1차 차분 ρ | 판정 |
|---|---|---|---|---|---|
| step_index ~ cache_read_input_tokens | 0.992 | 0.991 | 0.953 | -- | **중복(시계)** -- 두 원천 모두 |
| cache_creation_input_tokens ~ context_growth | **1.000** | 1.000 | n=29(못 잼) | 1.000 | **중복 -- 그러나 회계 항등식** (아래) |
| cache_read ~ context_tokens | 0.988 | 0.991 | 0.851 | 0.306 | 원천 의존 -- 중복으로 안 셈 |
| step_index ~ context_tokens | 0.985 | 1.000 | 0.836 | -- | 원천 의존 |
| step_index ~ cumulative_output | 0.985 | 1.000 | 0.726 | -- | 원천 의존 |
| output_tokens ~ call_span_ms | 0.761 | 0.798 | **0.988** | 0.738 | 원천 의존 (아래) |
| output_tokens ~ thinking_tokens | 0.644 | 0.608 | 0.631 | 0.463 | **다른 정보** |
| output_tokens ~ output_text_chars | −0.046 | 0.057 | 0.162 | -- | **다른 정보** (출력 토큰 대부분이 생각 · 도구 인자) |
| tool_output_chars ~ tool_latency_ms | 0.401 | 0.409 | −0.057 | -- | 다른 정보 |
| input_tokens ~ cache_read | −0.825 | 상수 | −0.796 | -- | 다른 정보(문턱 밑) |

비단조 의존(NMI ≥ 0.5 · |ρ| < 0.5): 없음.

**사소한 설명 -- 둘을 잡았다.**
- `cache_creation_input_tokens ≡ context_growth` (ρ = 1.000, 차분해도 1.000)는 발견이 아니다. Claude Code 처럼 앞 맥락을
  모두 캐시에서 읽는 런타임에서는 `context_t − context_{t−1} = cache_creation_t + (input_t − input_{t−1})` 이고 input 이
  상수(2 토큰)라 그대로 같다. **사전등록의 정의상 항등식 목록에 넣었어야 했는데 빠뜨렸다.** 캐시를 안 쓰는 런타임에서는
  성립하지 않는다.
- `output_tokens ~ call_span_ms` 가 stream 에서 0.988 인 것은 그 수집기에서 호출 구간이 `message_start` 도착 ~ 끝 이라
  **생성 시간 = 토큰 / 일정한 처리율** 이기 때문이다(처리율 41 호출에서 91~152 tok/s, 중앙 125). JSONL 의 구간은 블록 줄 시각이라 정의가 달라
  0.798. **시간 센서의 뜻은 수집기에 달렸다.**

## 6. 중복 -- 실행 단위 (SWE-agent 288)

| 무리 | 쌍 ρ | 읽기 |
|---|---|---|
| tokens_sent · tokens_received · model_calls · tool_call_count · cost_usd | 0.92 ~ 1.00 | **한 차원: '얼마나 오래 돌았나'.** tokens_sent~cost 1.00 은 단가 항등식(사전 목록), model_calls~tool_call_count 1.00 은 SWE-agent 가 걸음마다 행동 하나라서(구조) |
| identical_call_repeats ~ action_diversity | −0.87 | 문턱 밑이지만 가깝다 |
| tool_error_rate · retry_count | -- | **못 잼** -- SWE-agent 추적에 is_error 가 없다 |

claude 실행(13)은 n < 30 이라 실행 단위 상관을 내지 않았다.

## 사전 예상과 맞춰 보기

| 예상 | 실제 |
|---|---|
| cache_read · context_tokens · cumulative_output 이 서로 중복이고 시계 | **절반 맞음.** cache_read 만 두 원천 모두 시계. 나머지는 이 세션(긴 실행 하나)에서만 ≥ 0.9, 짧은 claude -p 실행에서는 0.73~0.85 |
| output ~ thinking < 0.9 | 맞음 (0.64) |
| 도구 쪽은 토큰과 < 0.5 | 맞음 |
| SWE-agent 실행 단위 토큰 · 호출 · 비용 한 무리 | 맞음 |
| 토큰 넷이 호출마다 정확히 같다 | 맞음 (41/41) |
| 압축 · 스트림 오류 · logprobs · 기억 조회 안 나옴 | 맞음 |
| (예상 못 함) 시간 초과에 전용 칸이 없다 · 잘못된 인자가 유발되지 않았다 · 생각 추정이 1.7 배 과대 | 새로 안 것 |

## 수집 뒤 알게 된 꼴의 한계 (센서 정의는 안 바꿨다)

1. ~~**null 이 두 뜻이다.**~~ **고침 -- 꼴 v2.** `reported_null` 목록을 더해 '원천이 null 로 줬다'(봤다)와 `unobserved`
   (키가 없다, 못 봤다)를 가른다. null 인 칸은 정확히 한 목록에 있어야 한다. 다시 모아 분석한 결과: 상관 · 무리 · 대조 등
   **분석 출력은 v1 과 전부 같았고**, 바뀐 것은 cc_stream 실행의 `api_error_status` 가용성 0 → 0.917(11/12)뿐이다.
   남은 하나(t08)는 오류 result 에 그 키가 아예 없어서 정말로 못 본 것이다 -- v1 문서의 "ttft_ms = null" 도 실은 "키 없음" 이었다.
2. cc_stream 수집기는 `message_delta` 의 usage 만 읽는다. `server_tool_use` 는 `message_start` 쪽에만 있어서 cc_stream 의
   server_tool_requests 가 전부 null 이 되었다(cc_jsonl 은 있다). 수집기 버그다 -- 분석 변수는 아니라 결과에 영향 없음.
3. `tool_latency_ms` 는 한 응답의 병렬 도구들의 **합**이다. 벽시계 대기는 최대값이어야 한다.
4. 정의상 항등식 목록에 cache_creation ≡ context_growth 를 빠뜨렸다(위).
5. ~~`tool_head` 에 겨냥 글이 그대로 들어간다.~~ **고침.** 겨냥(경로 · URL · 패턴 · 검색어 · 경로꼴 실행 파일)과 인자는
   열쇠 해시(HMAC-SHA256, 열쇠는 수집마다 무작위 · 저장 안 함)로만 남고, 평문은 맨 프로그램 이름뿐이다. 커밋한 레코드를
   새 수집기로 다시 만들었다(경로 · 검색어 0 건; `tests/test_telemetry.py` 가 커밋한 파일을 훑어 지킨다).
   **단 git 이력의 앞 판(bd697b6)에는 옛 파일이 남아 있다** -- 임시 경로와 이 세션의 논문 검색어.
