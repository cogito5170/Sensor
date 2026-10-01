# LLM 센서 층 -- 설계 (2026-10-01)

```
LLM / 에이전트 실행
      │  (원천: API 응답 · 스트림 사건 · 런타임 기록)
      ▼
SENSOR LAYER     llmsensor/telemetry/collect.py   원천 -> 레코드(원천이 준 값만)
      │
TELEMETRY        schema/telemetry.schema.json     model_call · tool_call · run (못 본 값 = null + unobserved)
      │          llmsensor/telemetry/derive.py    레코드 -> 파생(레코드만 본다)
      ▼
STATE MANAGER    (다음 단계 -- 여기에는 해석이 없다)
```

**Telemetry ≠ State.** 이 층에는 관측값과 그 산술만 있다. "압박 · 혼란 · 수렴 안 함" 같은 해석(형 3)은 센서가 아니다 --
[`sensor_catalog.md`](sensor_catalog.md) 끝의 목록.

측정 근거: [`eval/RESULTS_sensor_layer.md`](../eval/RESULTS_sensor_layer.md) (사전등록 · 얼린 커밋 1719258).

---

## 1. 센서 목록 -- 71 개

[`sensor_catalog.md`](sensor_catalog.md) (코드 `catalog.py` 에서 생성). 형 1(직접) 39 · 형 2(파생) 32,
무리별: token 21 · tool 15 · temporal 13 · context 8 · error 8 · output 5 · cost 1. 센서마다 원천 7 곳의 가용성을
**O**(실제 추적에서 봄) · **D**(문서/SDK 소스에 있음) · **A**(그 꼴에 없음) · **U**(모름)로 적었다.

## 2. 근거 -- 토큰 센서 Q1~Q8

**Q1. 토큰 메타데이터에 정확히 무엇이 있나**

| | Anthropic (O: 실제 응답) | OpenAI (D: openai-python 소스) | Gemini (D: google-genai 소스) |
|---|---|---|---|
| 입력 | `input_tokens` -- **캐시 분 제외** | `prompt_tokens` -- 캐시 분 **포함** | `prompt_token_count` -- 캐시 분 **포함** |
| 캐시 읽기 | `cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` | `cached_content_token_count` |
| 캐시 쓰기 | `cache_creation_input_tokens` + `cache_creation.{ephemeral_5m,1h}` | `cache_write_tokens` | 못 찾음(U) |
| 출력 | `output_tokens` (생각 포함) | `completion_tokens` (추론 포함) | `candidates_token_count` (**생각 제외**) |
| 생각/추론 | `output_tokens_details.thinking_tokens` | `completion_tokens_details.reasoning_tokens` | `thoughts_token_count` |
| 도구 결과 입력 | 없음(입력에 섞임) | 없음 | `tool_use_prompt_token_count` |
| 합계 | 없음(파생) | `total_tokens` | `total_token_count` |
| 기타 | `server_tool_use` · `iterations` · `service_tier` · `speed` · `inference_geo` | `audio/image/text_tokens`, 예측 수락/거절 | 모달리티별 세부 |
| 멈춘 까닭 | `stop_reason` (end_turn · tool_use · max_tokens · stop_sequence · pause_turn · refusal · model_context_window_exceeded · compaction) + `stop_details` | `finish_reason` (U: 문서 막힘) | `FinishReason` (STOP · MAX_TOKENS · SAFETY · MALFORMED_FUNCTION_CALL · TOO_MANY_TOOL_CALLS ...) |

**Q2. 스트리밍 중에 토큰을 실시간으로 얻나 -- 아니다(Anthropic).** `message_start` 에 입력 + 출력 1~4,
`message_delta` 에 **누적 최종값**(문서: "The token counts shown in the usage field of the message_delta event are cumulative").
도중에 얻는 것은 `content_block_delta` 조각 수(≠ 토큰)와 Claude Code 런타임의 생각 추정(`system/thinking_tokens`) --
실측 21 호출에서 최종값의 **중앙 1.68 배**. OpenAI · Gemini 스트림의 usage 는 U(문서 접근 막힘).

**Q3. 호출마다 얻나 -- 예(Anthropic · Claude Code). SWE-agent 는 아니다**(실행 합계 `tokens_sent/received` 만).

**Q4. 시간축으로 누적되나 -- 예.** Claude Code JSONL 은 줄마다 유닉스 시각, stream-json 은 사건 시각이 없어
수집기가 도착 시각을 찍는다. 실측(t10, Haiku 4.5):

```
t=  0.0s  ctx=29,706              out=215  think=85   cum_out=  215  span=1.6s  132 tok/s  tools=1
t=  2.3s  ctx=30,002  Δctx=  296  out=517  think=37   cum_out=  732  span=4.0s  129 tok/s  tools=5
t=  6.9s  ctx=30,841  Δctx=  839  out=926  think=80   cum_out=1,658  span=6.1s  152 tok/s  tools=5
t= 13.4s  ctx=32,425  Δctx=1,584  out=277  think=67   cum_out=1,935  span=2.6s  108 tok/s  tools=1
t= 16.5s  ctx=32,783  Δctx=  358  out=203  think=135  cum_out=2,138  span=1.7s  118 tok/s  end_turn
```

**Q5. 맥락 창 이용률 -- 계산된다, 단 분모가 둘이다.** 분자 = input + cache_read + cache_creation. 분모: 모형 창
(`result.modelUsage.contextWindow` = 200,000, 또는 Models API `max_input_tokens`) 또는 런타임의 **유효 창**
(`autocompact_state.effective_window` = 180,000, 압축 문턱 144,000). Claude Code JSONL 에는 창 크기가 없다.

**Q6. 생각 토큰을 가를 수 있나 -- 예.** Anthropic 은 실측 119/119 호출에 `thinking_tokens` 가 있었다. 출력 토큰 대비 ρ = 0.64
-- 다른 정보다. 생각 **내용**은 안 보인다.

**Q7. 캐시 토큰을 가를 수 있나 -- 예.** 읽기 · 쓰기 따로, 쓰기는 5분/1시간 따로(Anthropic O).

**Q8. 공급자마다 다른 점** -- 비교 전에 반드시 맞춰야 할 셋:
1. **입력에 캐시가 들어가나**: Anthropic 은 빼고, OpenAI · Gemini 는 넣는다. → 꼴에는 Anthropic 식으로 셋을 따로 두고,
   `context_tokens` 를 파생으로 만든다.
2. **출력에 생각이 들어가나**: Anthropic · OpenAI 는 넣고, Gemini `candidates` 는 뺀다.
3. **멈춤 까닭 값 집합이 다르다** -- 공통 이름으로 옮기는 표가 필요하다(아직 안 지음).

## 3. 텔레메트리 꼴

[`schema/telemetry.schema.json`](../schema/telemetry.schema.json) -- JSON Schema(2020-12). 세 레코드, 모든 칸이 늘
있고 못 본 값은 `null` + `unobserved` 목록. 실제 레코드(t11, 시간 초과):

```json
{"kind": "model_call", "run_id": "cc_stream:t11_timeout", "source": "cc_stream", "call_index": 0,
 "model": "claude-haiku-4-5-20251001", "t_start_ms": 2076.3, "t_end_ms": 5665.2, "time_base": "monotonic_ms",
 "input_tokens": 10, "cache_read_input_tokens": 25350, "cache_creation_input_tokens": 4330, "output_tokens": 382,
 "thinking_tokens": 296, "server_tool_requests": null, "iterations": 1, "stop_reason": "tool_use",
 "tool_calls_per_message": 1, "output_text_chars": 0, "thinking_duration_ms": null, "first_chunk_ms": 491.9,
 "stream_chunks": 14, "stream_thinking_estimate": 384, "context_window": 200000,
 "unobserved": ["server_tool_requests", "thinking_duration_ms"]}
{"kind": "tool_call", "run_id": "cc_stream:t11_timeout", "source": "cc_stream", "call_index": 0, "tool_index": 0,
 "tool_name": "Bash", "tool_head": "Bash:sleep", "tool_sig": "ffd8be180a6b", "tool_input_chars": 100,
 "t_issued_ms": 5647.2, "t_result_ms": 125950.0, "time_base": "monotonic_ms", "reported_duration_ms": null,
 "is_error": true, "interrupted": null, "tool_output_chars": 43, "unobserved": ["reported_duration_ms", "interrupted"]}
{"kind": "run", "run_id": "cc_stream:t11_timeout", "source": "cc_stream", "model": "claude-haiku-4-5",
 "run_duration_ms": 127932, "api_duration_ms": 6634, "ttft_ms": 3575, "num_turns": 2, "cost_usd": 0.018166,
 "terminal_reason": "completed", "result_subtype": "success", "is_error": false, "permission_denials": 0,
 "context_window": 200000, "max_output_tokens": 32000, "autocompact_threshold": 144000,
 "rate_limit_utilization": 0.8, "reported_input_tokens": 18, "reported_output_tokens": 615, "...": "..."}
```

프롬프트 · 답 · 도구 출력의 글은 **담지 않는다** -- 해시(`tool_sig`)와 길이만. 그래서 내용이 필요한 파생
(text_repetition · type_token_ratio)은 이 꼴로는 못 낸다. **단 `tool_head` 에는 겨냥이 글 그대로 들어간다** -- 명령의
첫 낱말, 파일 경로, Grep 패턴, 웹 검색어. 민감한 경로 · 검색어가 있는 곳에서는 `tool_head` 도 해시로 바꿔야 한다
(다음 판의 숙제).

## 4. 파생 텔레메트리 (`derive.py`)

| 파생 | 식 | 입력 |
|---|---|---|
| context_tokens | input + cache_read + cache_creation | 토큰 셋 |
| context_growth | Δ context_tokens | context_tokens |
| context_utilization · remaining | context / window · window − context | context_tokens, context_window |
| cumulative_output_tokens | Σ output | output_tokens |
| output_token_growth · acceleration | Δ · Δ² output | output_tokens |
| output_tokens_per_sec | output / call_span | output_tokens, 시각 |
| cache_hit_ratio | cache_read / context | |
| thinking_ratio | thinking / output | |
| token_burst | output > 그 실행의 중앙값 × 4 (호출 3 개 뒤부터) | output_tokens |
| token_stagnation | 3 호출 연속 \|Δcontext\| < 1% | context_growth |
| token_oscillation | 창 6 호출 안 Δoutput 부호 바뀜 수 | output_tokens |
| call_span_ms · inter_call_gap_ms | 끝−처음 · 이번 처음 − 앞 끝 | 시각 |
| tool_latency_ms | t_result − t_issued | 도구 시각 |
| tool_error_rate · retry_count · identical_call_repeats · action_diversity · tool_type_entropy | (catalog 정의) | tool_name, tool_sig, is_error |
| timeout (사건) | is_error ∧ 지연 ≥ 도구 한도(Bash 120 s) -- **전용 칸이 없어서** | is_error, 지연 |
| idle_ms | run_duration − api_duration − Σ tool 지연 | |

## 5. 의존 그래프

```
input_tokens ──────────┐
cache_read_input ──────┼─► context_tokens ─┬─► context_growth  (≡ cache_creation, 캐시 런타임의 회계 항등식)
cache_creation_input ──┘                   ├─► context_utilization ◄── context_window
                                           ├─► context_remaining   ◄── context_window
                                           ├─► cache_hit_ratio ◄── cache_read
                                           └─► token_stagnation
output_tokens ─────────┬─► cumulative_output ─► (시계: step 과 ρ 0.73~1.00)
                       ├─► growth · acceleration · burst · oscillation
                       ├─► thinking_ratio ◄── thinking_tokens
                       └─► output_tokens_per_sec ◄── call_span ◄── 사건 시각
context_tokens + output_tokens ─► total_tokens ─► cost (단가표, 모형 하나면 선형)

tool_name ─┬─► tool_call_count · tool_type_entropy
tool_sig  ─┼─► identical_call_repeats · action_diversity
is_error  ─┴─► tool_error_rate · retry_count · failed_retry ;  is_error + 지연 ─► timeout
t_issued · t_result ─► tool_latency ─► idle_ms ◄── run_duration, api_duration
```

## 6. 최소 비중복 관측 집합

"가장 좋은" 이 아니라 **텔레메트리를 짓는 데 모아야 하는, 서로 겹치지 않는 형 1 관측값**이다. 나머지는 이것에서 계산된다.
겹침 판정은 사전등록 규칙(|ρ| ≥ 0.9, 두 원천 모두) -- 결과 문서 §5 · §6.

| # | 관측값 (형 1) | 단위 | 왜 따로 두나 |
|---|---|---|---|
| 1 | input_tokens | 호출 | cache_read 와 −0.8 -- 겹치지 않음 |
| 2 | cache_read_input_tokens | 호출 | 맥락 크기의 거의 전부. **시계와 0.99**(아래 주의) |
| 3 | cache_creation_input_tokens | 호출 | = 맥락 증가분. context_growth 는 따로 모을 필요가 없다 |
| 4 | output_tokens | 호출 | |
| 5 | thinking_tokens | 호출 | output 과 0.64 |
| 6 | stop_reason | 호출 | 범주 |
| 7 | 사건 시각(호출 처음/끝) | 호출 | 생성 시간 · 간격. **stream 수집기에서는 output 과 0.99** -- 처리율이 일정하면 output 이 대신한다 |
| 8 | output_text_chars | 호출 | output 과 ≈ 0 -- 보이는 글은 출력 토큰의 작은 부분 |
| 9 | tool_calls_per_message | 호출 | |
| 10 | tool_name + tool_sig | 도구 | 반복 · 다양성 · 분포 |
| 11 | tool is_error | 도구 | 오류 · 재시도 · 시간 초과의 바탕 |
| 12 | 도구 시각(호출/결과) | 도구 | 지연 · 시간 초과 |
| 13 | tool_output_chars | 도구 | 다음 호출의 맥락 증가의 원인 쪽 |
| 14 | terminal_reason (+ result subtype) | 실행 | 회전 상한 · 정상 종료 |
| 15 | context_window | 실행 | 이용률의 분모 -- 정적 |
| 16 | rate_limit_utilization | 실행 | 외부 자원 상태 -- 다른 것으로 못 만든다 |

**모을 필요 없는 것**(위에서 계산된다 또는 겹친다): context_tokens · total_tokens · context_growth · utilization ·
remaining · cumulative_output · cost(모형 하나면 토큰의 선형) · step_index.
실행 단위에서 tokens_sent · tokens_received · model_calls · tool_call_count · cost 는 **한 차원**('얼마나 오래 돌았나',
SWE-agent 288 실행에서 ρ 0.92~1.00) -- 하나로 충분하다.

**주의 -- 시계.** cache_read_input_tokens 는 걸음 번호와 ρ 0.99 다. 실행 안에서 맥락이 자라는 것만으로 생기는 추세라,
State 를 만들 때는 이것을 **걸음 번호에 대해 정규화하거나 차분해서** 써야 한다(차분하면 cache_read ~ context 가 0.31 로
떨어진다).

## 7. UNKNOWN -- 지금 관측 못 한 것

| 무엇 | 왜 |
|---|---|
| 생성 **도중**의 정확한 토큰 수 | API 가 안 준다(끝에만 누적값). 런타임 추정은 1.7 배 과대 |
| 잘못된 인자 · 잘못된 호출 | 유발하려 했지만 런타임이 받아들였다(t12). 꼴을 못 보았다 |
| 시간 초과 전용 신호 | 없다 -- is_error + 지연 + 글로만 드러난다(형 2) |
| 압축(compaction) 사건 | 문서에 `stop_reason: compaction` 이 있으나 이 수집에서 안 일어났다 |
| 스트림 중 오류 사건 · API 오류 · 429 | 문서(D)뿐 -- 안 일어났다 |
| stop_reason 의 max_tokens · refusal · pause_turn · model_context_window_exceeded | 문서(D)뿐 -- tool_use · end_turn 만 보았다 |
| logprobs · 응답 엔트로피 | 우리가 본 추적에 없다. Anthropic 문서에서 언급을 못 찾았다(없다고 단정하지 않음) |
| 기억 조회 수 · 지연 · 크기 | OTel 에 꼴(gen_ai.memory.*)만 있다. 본 런타임에 기억 도구가 없었다 |
| OpenAI · Gemini 의 실제 값 · 스트림 usage · finish_reason | SDK 소스(D)만. 문서 사이트가 이 환경에서 막혔다 |
| SWE-agent 의 호출별 토큰 · 시각 · 도구 오류 | 그 추적 꼴에 없다(A) |
| null 이 값인 칸(api_error_status) | 꼴이 '오류 없음' 과 '못 봄' 을 못 가른다 -- 다음 판의 숙제 |
| (꼴의 한계) tool_head 의 글 | 경로 · 검색어가 그대로 남는다 -- 위 §3 |

## 다음 단계 (State)

이 층은 센서와 텔레메트리까지다. State 해석(형 3)은 이 레코드를 입력으로 받는 별도 층에서, 별도 사전등록으로 검증한다.
그때 쓸 라벨은 앞 실험(SWE-bench Lite)처럼 **외부 결과**여야 하고, 시계 효과(§6 주의)를 먼저 걷어내야 한다.
