# 센서 목록 (catalog.py 에서 생성 -- 손으로 고치지 말 것)

가용성: **O** 이 세션의 실제 추적에서 봄 · **D** 이 세션에서 읽은 문서/SDK 소스에 있음 · **A** 그 추적 꼴에 없음 · **U** 모름 · **-** 해당 없음(파생은 입력의 가용성을 따른다)

원천: anthropic · openai · gemini · otel · cc_jsonl · cc_stream · sweagent

## token

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `input_tokens` | 1 | O | D | D | D | O | O | A | 모형 호출마다(응답 끝; 스트림은 message_start) | 그 호출에서 캐시 밖으로 새로 읽은 입력 토큰 | **공급자마다 뜻이 다르다**: Anthropic input_tokens 는 캐시 읽기 · 쓰기를 뺀 것, OpenAI prompt_tokens 와 Gemini prompt_token_count 는 캐시 분을 포함한다. 그대로 비교하면 안 된다 |  |
| `output_tokens` | 1 | O | D | D | D | O | O | A | 모형 호출마다(스트림: message_delta 에 누적값) | 그 호출이 만든 출력 토큰(생각 토큰 포함) | Gemini candidates_token_count 는 생각 토큰을 **뺀다**(total = prompt+candidates+tool_use+thoughts). Anthropic · OpenAI 는 포함 |  |
| `cache_read_input_tokens` | 1 | O | D | D | D | O | O | A | 모형 호출마다 | 캐시에서 읽은 입력 토큰 | OpenAI cached_tokens 는 prompt_tokens 의 부분집합 |  |
| `cache_creation_input_tokens` | 1 | O | D | U | D | O | O | A | 모형 호출마다 | 캐시에 새로 쓴 입력 토큰(5분/1시간 나눔 포함) | Gemini 에 대응 필드를 SDK 소스에서 못 찾았다 |  |
| `thinking_tokens` | 1 | O | D | D | D | O | O | A | 모형 호출마다 | 출력 중 생각(추론)에 쓴 토큰 | 내용은 안 보인다(요약/생략). 일부 호출에서만 필드가 나온다 -- 없을 때 0 인지 미보고인지 구분 못 한다 |  |
| `tool_result_input_tokens` | 1 | A | A | D | U | A | A | A | 모형 호출마다 | 도구 결과가 입력으로 들어간 토큰 | Gemini 만 따로 센다(tool_use_prompt_token_count). Anthropic 은 입력에 섞인다 |  |
| `server_tool_requests` | 1 | O | A | U | U | O | O | A | 모형 호출마다 | 서버 도구(웹 검색 · 가져오기) 요청 수 | 클라이언트 도구는 안 센다 |  |
| `usage_iterations` | 1 | O | A | U | U | O | O | A | 모형 호출마다 | 한 요청 안의 서버 측 하위 단계(압축 등)별 사용량 목록 | 새 필드 -- 대부분 길이 1 |  |
| `stream_thinking_estimate` | 1 | A | A | A | A | A | O | A | 생각 중 수시로(런타임 추정) | 생성 **도중** 생각 토큰 추정치(누적 · 증분) | **추정치**다. Claude Code 런타임이 내는 것이지 API 값이 아니다 |  |
| `stream_chunks` | 1 | O | A | U | D | A | O | A | 출력 조각마다 | 출력 조각(content_block_delta) 수 -- 생성 도중 볼 수 있는 유일한 진행 신호 | 조각 ≠ 토큰. 조각당 토큰 수는 일정하지 않다 |  |
| `context_tokens` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | 그 호출에서 모형이 본 입력 전체 = input + cache_read + cache_creation | OpenAI · Gemini 는 prompt_tokens 가 이미 이것 | `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` |
| `total_tokens` | 2 | - | D | D | - | - | - | - | 모형 호출마다 | context_tokens + output_tokens | OpenAI · Gemini 는 직접 준다(total_tokens · total_token_count) | `context_tokens`, `output_tokens` |
| `cumulative_output_tokens` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | Σ output_tokens(실행 시작부터) | 단조 증가 -- 걸음 번호와 강하게 겹칠 것 | `output_tokens` |
| `output_token_growth` | 2 | - | - | - | - | - | - | - | 연속 두 호출 사이 | Δ output_tokens |  | `output_tokens` |
| `output_token_acceleration` | 2 | - | - | - | - | - | - | - | 연속 세 호출 | Δ² output_tokens | 잡음이 크다 | `output_tokens` |
| `output_tokens_per_sec` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | output_tokens / 생성 구간(첫 조각 ~ 끝) | cc_jsonl 은 블록 단위 시각뿐이라 거칠다 | `output_tokens`, `call_span_ms` |
| `cache_hit_ratio` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | cache_read / context_tokens | 되풀이된 맥락의 비율의 대용 | `cache_read_input_tokens`, `context_tokens` |
| `thinking_ratio` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | thinking_tokens / output_tokens |  | `thinking_tokens`, `output_tokens` |
| `token_burst` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | output_tokens > 그때까지 그 실행의 중앙값 × 4 (첫 3 호출은 판정 안 함) | 문턱 4 는 정한 것이지 잰 것이 아니다 | `output_tokens` |
| `token_stagnation` | 2 | - | - | - | - | - | - | - | 연속 3 호출 | context_growth 가 3 호출 연속 < 1% of context_tokens |  | `context_growth`, `context_tokens` |
| `token_oscillation` | 2 | - | - | - | - | - | - | - | 창 6 호출 | 창 안에서 Δ output_tokens 의 부호가 바뀐 횟수 |  | `output_tokens` |

## tool

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tool_name` | 1 | O | D | D | D | O | O | O | 도구 호출마다 | 부른 도구 이름 | SWE-agent 는 명령 문자열(첫 낱말을 이름으로) |  |
| `tool_input_chars` | 1 | O | D | D | D | O | O | O | 도구 호출마다 | 도구 인자 길이(문자) | 토큰이 아니다 |  |
| `tool_is_error` | 1 | O | - | - | U | O | O | A | 도구 결과마다 | 도구 결과의 오류 깃발 | Anthropic API 에서는 **클라이언트(하네스)가 다는 값**이다. SWE-agent 추적에는 없다 -- 그때 쓰던 글 탐색(어댑터)은 형 2 추정이다 |  |
| `tool_output_chars` | 1 | O | - | - | U | O | O | O | 도구 결과마다 | 도구 결과 길이(문자) |  |  |
| `tool_reported_duration` | 1 | A | - | - | U | O | U | A | 도구 결과마다 | 런타임이 적은 도구 소요 시간 | 일부 도구(웹 검색 등)만 적는다 -- toolUseResult.durationSeconds |  |
| `tool_interrupted` | 1 | A | - | - | U | O | O | A | 도구 결과마다 | 사용자/런타임이 끊었나 |  |  |
| `tool_calls_per_message` | 1 | O | D | D | U | O | O | A | 모형 호출마다 | 한 응답 안의 tool_use 블록 수(병렬 호출) | SWE-agent 는 걸음당 하나로 고정 |  |
| `permission_denials` | 1 | - | - | - | - | A | O | A | 실행 끝 | 권한으로 거절된 도구 호출 목록 |  |  |
| `tool_call_count` | 2 | - | - | - | - | - | - | - | 누적 | 도구 호출 수 |  | `tool_name` |
| `tool_error_rate` | 2 | - | - | - | - | - | - | - | 누적 | 오류 결과 / 도구 호출 |  | `tool_is_error` |
| `identical_call_repeats` | 2 | - | - | - | - | - | - | - | 누적 | (이름, 인자) 같은 호출의 최대 반복 수 |  | `tool_name`, `tool_input` |
| `retry_count` | 2 | - | - | - | - | - | - | - | 누적 | 오류 뒤 같은 겨냥으로 다시 부른 수(llmsensor.trace.retries) | 겨냥 = 이름 + 명령 첫 낱말/경로 -- 거친 지문 | `tool_name`, `tool_input`, `tool_is_error` |
| `failed_retry_count` | 2 | - | - | - | - | - | - | - | 누적 | 재시도 중 다시 오류난 수 |  | `retry_count`, `tool_is_error` |
| `action_diversity` | 2 | - | - | - | - | - | - | - | 누적 | 서로 다른 (이름, 인자) 수 / 호출 수 |  | `tool_name`, `tool_input` |
| `tool_type_entropy` | 2 | - | - | - | - | - | - | - | 누적 | 도구 이름 분포의 섀넌 엔트로피(bit) |  | `tool_name` |

## temporal

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tool_latency_ms` | 2 | - | - | - | - | - | - | - | 도구 호출마다 | 결과 시각 − 호출 시각 | 호출 시각은 그 tool_use 가 담긴 줄의 시각 -- 실행 시작이 아니다 | `t_issued`, `t_result` |
| `event_timestamp` | 1 | A | U | U | D | O | A | A | 줄/사건마다 | 런타임이 적은 사건 시각 | **cc_stream 의 stream_event 에는 시각이 없다** -- 수집기가 도착 시각을 찍는다(아래). SWE-agent 추적에는 걸음 시각이 없다 |  |
| `arrival_time` | 1 | - | - | - | - | - | O | - | 사건마다(수집기) | 수집기가 stdout 줄을 받은 단조 시각(ms) | 수집기의 관측 시각이지 서버 시각이 아니다 -- 파이프 지연 포함 |  |
| `run_duration_ms` | 1 | - | - | - | - | A | O | A | 실행 끝 | 실행 전체 벽시계 시간 |  |  |
| `api_duration_ms` | 1 | - | - | - | - | O | O | A | 실행 끝 | 모형 API 에 쓴 시간 합 | cc_jsonl 은 세션 누적(cost-state) -- 과업 단위 아님 |  |
| `ttft_ms` | 1 | U | - | - | D | A | O | A | 실행(첫 호출) | 첫 출력까지 시간 | cc_stream result.ttft_ms 는 **첫 호출**만. 호출마다는 도착 시각으로 파생 |  |
| `thinking_duration_ms` | 1 | A | - | - | U | O | A | A | 모형 호출마다 | 생각에 쓴 시간 | cc_jsonl 만 |  |
| `call_span_ms` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | 그 호출의 첫 관측 ~ 마지막 관측 |  | `event_timestamp` |
| `inter_call_gap_ms` | 2 | - | - | - | - | - | - | - | 연속 호출 | 앞 호출 끝 ~ 이번 호출 시작 | 도구 시간 포함 | `event_timestamp` |
| `idle_ms` | 2 | - | - | - | - | - | - | - | 실행 끝 | run_duration − api_duration − Σ tool_latency | 음수면 겹침 | `run_duration_ms`, `api_duration_ms`, `tool_latency_ms` |
| `latency_variance` | 2 | - | - | - | - | - | - | - | 누적 | call_span_ms 의 분산 |  | `call_span_ms` |
| `execution_rate` | 2 | - | - | - | - | - | - | - | 누적 | 모형 호출 수 / 분 |  | `event_timestamp` |
| `burstiness` | 2 | - | - | - | - | - | - | - | 누적 | (σ−μ)/(σ+μ) of inter_call_gap_ms (Goh-Barabási) |  | `inter_call_gap_ms` |

## error

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `api_retry_time_ms` | 2 | - | - | - | - | - | - | - | 세션 끝 | totalAPIDuration − totalAPIDurationWithoutRetries | cc_jsonl cost-state 에만 | `api_duration_ms` |
| `stop_reason` | 1 | O | D | D | D | O | O | A | 모형 호출마다 | 호출이 멈춘 까닭(end_turn · tool_use · max_tokens · stop_sequence · pause_turn · refusal · model_context_window_exceeded · compaction) | OpenAI finish_reason · Gemini FinishReason 은 값 집합이 다르다 |  |
| `stop_details` | 1 | D | U | U | U | O | O | A | 모형 호출마다 | 거절일 때 분류 | refusal 일 때만 채워진다 |  |
| `stream_error_event` | 1 | D | U | U | U | U | U | A | 스트림 도중 | 스트림 안의 error 사건(overloaded_error 등) | 이 세션에서 실제로 보지 못했다 |  |
| `api_error_status` | 1 | - | - | - | - | A | O | A | 실행 끝 | API 오류 상태 | 이 세션의 값은 전부 null 이었다 |  |
| `terminal_reason` | 1 | - | - | - | - | A | O | O | 실행 끝 | 실행이 끝난 까닭 | cc_stream result.terminal_reason/subtype; sweagent info.exit_status(submitted · exit_cost ...) |  |
| `rate_limit_state` | 1 | D | - | - | - | A | O | A | 실행 중 사건 | 요금 한도 상태 · 사용률(5시간/7일) | API 는 429 + retry-after · x-ratelimit-* 헤더(문서). 런타임은 사건으로 |  |
| `hook_errors` | 1 | - | - | - | - | O | U | A | 턴 끝 | 훅 실행 오류 · 소요 | Claude Code 만 |  |

## context

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `context_growth` | 2 | - | - | - | - | - | - | - | 연속 두 호출 사이 | Δ context_tokens | 압축이 일어나면 음수 | `context_tokens` |
| `context_utilization` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | context_tokens / context_window | 창 크기가 필요하다 -- cc_jsonl 에는 없다(문서의 모형 표나 Models API 로 채워야) | `context_tokens`, `context_window` |
| `context_remaining` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | context_window − context_tokens | context_utilization 과 같은 정보(창이 일정하면 완전 중복 -- 정의상) | `context_tokens`, `context_window` |
| `context_window` | 1 | D | U | U | U | A | O | A | 실행 시작/끝 | 모형의 맥락 창 크기 | Anthropic 은 Models API max_input_tokens(문서). cc_stream result.modelUsage.contextWindow |  |
| `max_output_tokens` | 1 | D | U | U | U | A | O | A | 실행 시작/끝 | 출력 상한 |  |  |
| `autocompact_threshold` | 1 | - | - | - | - | A | O | A | 실행 시작 | 자동 압축 문턱 · 유효 창 | Claude Code 런타임 설정값 |  |
| `compaction_event` | 1 | D | U | U | U | U | U | A | 일어날 때 | 맥락 압축/요약이 일어났다 | 이 세션에서 실제로 일어나지 않아 꼴을 못 보았다 |  |
| `memory_retrieval` | 1 | U | U | U | D | U | U | A | 일어날 때 | 기억 저장소 조회 수 · 크기 · 지연 | OTel 에 gen_ai.memory.* 꼴이 있다. 우리가 본 런타임에는 기억 도구가 없었다 |  |

## output

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `output_text_chars` | 1 | O | D | D | U | O | O | O | 모형 호출마다 | 보이는 글 출력 길이(문자) | 생각 내용은 빠진다 |  |
| `logprobs` | 1 | U | U | U | U | A | A | A | 토큰마다 | 토큰 확률(엔트로피 계산용) | Anthropic 스킬 문서에 언급이 없다 -- 없다고 단정하지 않고 U. 우리가 본 추적에는 없다 |  |
| `text_repetition` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | 이번 글의 3-gram 중 앞 글들에 이미 나온 비율 |  | `output_text` |
| `type_token_ratio` | 2 | - | - | - | - | - | - | - | 모형 호출마다 | 서로 다른 낱말 / 낱말 | 짧은 글에서 불안정 | `output_text` |
| `schema_violation` | 2 | - | - | - | - | - | - | - | 최종 답 | 제약 센서(ConstraintSensor)의 위반 수 | 제약을 줘야 잰다 | `output_text` |

## cost

| 센서 | 형 | anthropic | openai | gemini | otel | cc_jsonl | cc_stream | sweagent | 측정 시점 | 무엇 | 한계 | 파생 입력 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `cost_usd` | 1 | A | A | A | A | O | O | O | 실행 끝(cc_jsonl 은 세션 누적) | 런타임이 계산한 비용 | API 응답에는 없다 -- 단가표로 파생해야 |  |

## 근거 (형 1)

- `input_tokens`: cc_jsonl usage.input_tokens; cc_stream message_start.usage; openai CompletionUsage.prompt_tokens; gemini prompt_token_count; otel gen_ai.usage.input_tokens; sweagent 는 과업 합계 tokens_sent 뿐
- `output_tokens`: streaming.md: 'The token counts shown in the usage field of the message_delta event are cumulative.'
- `cache_read_input_tokens`: openai PromptTokensDetails.cached_tokens; gemini cached_content_token_count; otel gen_ai.usage.cache_read.input_tokens
- `cache_creation_input_tokens`: cc_jsonl usage.cache_creation.ephemeral_1h_input_tokens; openai cache_write_tokens; otel gen_ai.usage.cache_write.input_tokens
- `thinking_tokens`: cc_jsonl usage.output_tokens_details.thinking_tokens; openai reasoning_tokens; gemini thoughts_token_count; otel gen_ai.usage.reasoning.output_tokens
- `tool_result_input_tokens`: gemini tool_use_prompt_token_count
- `server_tool_requests`: usage.server_tool_use.web_search_requests
- `usage_iterations`: usage.iterations; cost-optimization.md: 'itemizes that step's tokens under usage.iterations'
- `stream_thinking_estimate`: cc_stream system/thinking_tokens {estimated_tokens, estimated_tokens_delta}
- `stream_chunks`: cc_stream stream_event content_block_delta; otel gen_ai.client.operation.time_per_output_chunk
- `tool_name`: tool_use.name; otel gen_ai.tool.name
- `tool_is_error`: tool_result.is_error; cc_stream 'Exit code 2 ... is_error: true'
- `tool_reported_duration`: cc_jsonl toolUseResult.durationSeconds
- `tool_interrupted`: toolUseResult.interrupted
- `permission_denials`: cc_stream result.permission_denials
- `event_timestamp`: cc_jsonl timestamp; cc_stream 는 assistant/user 줄에만
- `run_duration_ms`: cc_stream result.duration_ms; cc_jsonl cost-state.totalDuration(세션)
- `api_duration_ms`: result.duration_api_ms; cost-state.totalAPIDuration
- `ttft_ms`: result.ttft_ms; otel time_to_first_chunk
- `thinking_duration_ms`: cc_jsonl thinkingDurationMs
- `stop_reason`: cc_jsonl stop_reason {tool_use, end_turn}; gemini FinishReason MALFORMED_FUNCTION_CALL, TOO_MANY_TOOL_CALLS ...
- `stream_error_event`: streaming.md 'event: error ... overloaded_error'
- `api_error_status`: cc_stream result.api_error_status
- `rate_limit_state`: cc_stream rate_limit_event.rate_limit_info.utilization; error-codes.md headers
- `hook_errors`: cc_jsonl system/stop_hook_summary.hookErrors
- `context_window`: models.md 'max_input_tokens # context window'; cc_stream contextWindow=200000(haiku)
- `autocompact_threshold`: cc_stream autocompact_state {effective_window, threshold}
- `compaction_event`: compaction.md(stop_reason 'compaction')
- `cost_usd`: result.total_cost_usd; cost-state.totalCostUSD; info.model_stats.instance_cost

## 센서가 아닌 것 (형 3 -- State 해석)

- `reasoning_pressure` -- 생각 토큰 · 출력 길이를 '압박' 으로 읽는 해석
- `confusion` -- 반복 · 진동을 '혼란' 으로 읽는 해석
- `non_convergence` -- 맥락이 자라는데 진전이 없다는 판단 -- 진전의 정의가 필요
- `planning_failure` -- 도구 순서를 계획 실패로 읽는 해석
- `execution_instability` -- 오류 · 재시도를 불안정으로 읽는 해석
- `context_saturation` -- 이용률이 높다는 관측 + 그것이 해롭다는 해석. 관측 부분은 context_utilization
- `success / failure` -- 외부 결과(라벨) -- 센서 층이 아니라 State 검증의 몫

## 정의상 같은 것 (상관이 나와도 발견이 아니다)

- `context_utilization` ~ context_tokens: 창이 일정하면 상수배
- `context_remaining` ~ context_tokens: 창이 일정하면 음의 일차
- `total_tokens` ~ context_tokens + output_tokens: 합
- `cost_usd` ~ 토큰들의 단가 가중합: 모형 하나면 선형

## 비용 · 지속성

모든 형 1 센서는 **추가 토큰 · API 호출이 0** 이다 -- 응답 · 런타임 출력에 이미 들어 있다. 예외: Models API 로 창 크기를 묻는 것(호출 1 회, 토큰 0), `count_tokens`(호출 1 회). 파생은 계산만 든다. 실행 안에서는 모두 누적할 수 있다. 실행을 넘는 지속성은 수집기가 레코드를 저장할 때만 생긴다.
