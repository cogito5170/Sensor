"""후보 센서 목록 -- 2026-10-01 에 얼렸다(측정 전). 측정을 보고 이 목록의 정의를 바꾸지 않는다.

형:
    1  직접 관측 -- API/런타임이 그 값을 준다
    2  파생 -- 형 1 의 값들로 계산한다(derived_from 에 적는다)
    (형 3 -- 의미 해석 -- 은 센서가 아니다. 아래 NOT_SENSORS 에 따로 적는다)

원천별 가용성 부호:
    O  이 세션에서 모은 실제 추적에서 **보았다** (evidence 에 어느 파일인지)
    D  이 세션에서 읽은 공급자 문서 · SDK 소스에 **적혀 있다** (보지는 않았다)
    A  그 추적 꼴을 열어 보았고 **없다**
    U  모른다 -- 확인 못 했다(문서 접근 막힘 등). 있다고도 없다고도 하지 않는다
    -  해당 없음(그 원천의 개념이 아니다)

원천:
    anthropic   Anthropic Messages API (문서: platform.claude.com streaming.md · claude-api 스킬; 실제 SSE 사건은
                claude -p --include-partial-messages 의 stream_event 로 보았다)
    openai      OpenAI API (openai-python 의 completion_usage.py · response_usage.py 소스; 문서 사이트는 막힘)
    gemini      Gemini API (google-genai python 의 types.py 소스; 문서 사이트는 막힘)
    otel        OpenTelemetry GenAI semantic conventions (gen-ai-spans.md · gen-ai-metrics.md) -- 꼴만, 값 아님
    cc_jsonl    Claude Code 세션 JSONL (~/.claude/projects/...)
    cc_stream   claude -p --output-format stream-json --verbose --include-partial-messages
    sweagent    SWE-agent .traj (SWE-bench Lite 제출 20240620)
"""
from __future__ import annotations

SOURCES = ("anthropic", "openai", "gemini", "otel", "cc_jsonl", "cc_stream", "sweagent")
GROUPS = ("token", "tool", "temporal", "error", "context", "output", "cost")


def S(name, group, typ, avail, sampling, meaning, limitation, derived_from=(), cost="0", persistence="누적 가능",
      evidence=""):
    a = dict(zip(SOURCES, avail.split()))
    assert len(a) == len(SOURCES), name
    return {"name": name, "group": group, "type": typ, "availability": a, "sampling": sampling,
            "meaning": meaning, "limitation": limitation, "derived_from": list(derived_from), "cost": cost,
            "persistence": persistence, "evidence": evidence}


#               anthropic openai gemini otel cc_jsonl cc_stream sweagent
CATALOG = [
    # ---- A. 토큰 (직접) ----
    S("input_tokens", "token", 1, "O D D D O O A", "모형 호출마다(응답 끝; 스트림은 message_start)",
      "그 호출에서 캐시 밖으로 새로 읽은 입력 토큰",
      "**공급자마다 뜻이 다르다**: Anthropic input_tokens 는 캐시 읽기 · 쓰기를 뺀 것, OpenAI prompt_tokens 와 "
      "Gemini prompt_token_count 는 캐시 분을 포함한다. 그대로 비교하면 안 된다",
      evidence="cc_jsonl usage.input_tokens; cc_stream message_start.usage; openai CompletionUsage.prompt_tokens; "
               "gemini prompt_token_count; otel gen_ai.usage.input_tokens; sweagent 는 과업 합계 tokens_sent 뿐"),
    S("output_tokens", "token", 1, "O D D D O O A", "모형 호출마다(스트림: message_delta 에 누적값)",
      "그 호출이 만든 출력 토큰(생각 토큰 포함)",
      "Gemini candidates_token_count 는 생각 토큰을 **뺀다**(total = prompt+candidates+tool_use+thoughts). "
      "Anthropic · OpenAI 는 포함",
      evidence="streaming.md: 'The token counts shown in the usage field of the message_delta event are cumulative.'"),
    S("cache_read_input_tokens", "token", 1, "O D D D O O A", "모형 호출마다",
      "캐시에서 읽은 입력 토큰", "OpenAI cached_tokens 는 prompt_tokens 의 부분집합",
      evidence="openai PromptTokensDetails.cached_tokens; gemini cached_content_token_count; "
               "otel gen_ai.usage.cache_read.input_tokens"),
    S("cache_creation_input_tokens", "token", 1, "O D U D O O A", "모형 호출마다",
      "캐시에 새로 쓴 입력 토큰(5분/1시간 나눔 포함)", "Gemini 에 대응 필드를 SDK 소스에서 못 찾았다",
      evidence="cc_jsonl usage.cache_creation.ephemeral_1h_input_tokens; openai cache_write_tokens; "
               "otel gen_ai.usage.cache_write.input_tokens"),
    S("thinking_tokens", "token", 1, "O D D D O O A", "모형 호출마다",
      "출력 중 생각(추론)에 쓴 토큰",
      "내용은 안 보인다(요약/생략). 일부 호출에서만 필드가 나온다 -- 없을 때 0 인지 미보고인지 구분 못 한다",
      evidence="cc_jsonl usage.output_tokens_details.thinking_tokens; openai reasoning_tokens; "
               "gemini thoughts_token_count; otel gen_ai.usage.reasoning.output_tokens"),
    S("tool_result_input_tokens", "token", 1, "A A D U A A A", "모형 호출마다",
      "도구 결과가 입력으로 들어간 토큰", "Gemini 만 따로 센다(tool_use_prompt_token_count). Anthropic 은 입력에 섞인다",
      evidence="gemini tool_use_prompt_token_count"),
    S("server_tool_requests", "token", 1, "O A U U O O A", "모형 호출마다",
      "서버 도구(웹 검색 · 가져오기) 요청 수", "클라이언트 도구는 안 센다",
      evidence="usage.server_tool_use.web_search_requests"),
    S("usage_iterations", "token", 1, "O A U U O O A", "모형 호출마다",
      "한 요청 안의 서버 측 하위 단계(압축 등)별 사용량 목록", "새 필드 -- 대부분 길이 1",
      evidence="usage.iterations; cost-optimization.md: 'itemizes that step's tokens under usage.iterations'"),
    S("stream_thinking_estimate", "token", 1, "A A A A A O A", "생각 중 수시로(런타임 추정)",
      "생성 **도중** 생각 토큰 추정치(누적 · 증분)", "**추정치**다. Claude Code 런타임이 내는 것이지 API 값이 아니다",
      evidence="cc_stream system/thinking_tokens {estimated_tokens, estimated_tokens_delta}"),
    S("stream_chunks", "token", 1, "O A U D A O A", "출력 조각마다",
      "출력 조각(content_block_delta) 수 -- 생성 도중 볼 수 있는 유일한 진행 신호", "조각 ≠ 토큰. 조각당 토큰 수는 일정하지 않다",
      evidence="cc_stream stream_event content_block_delta; otel gen_ai.client.operation.time_per_output_chunk"),
    # ---- A'. 토큰 (파생) ----
    S("context_tokens", "token", 2, "- - - - - - -", "모형 호출마다",
      "그 호출에서 모형이 본 입력 전체 = input + cache_read + cache_creation",
      "OpenAI · Gemini 는 prompt_tokens 가 이미 이것", ["input_tokens", "cache_read_input_tokens",
                                                       "cache_creation_input_tokens"]),
    S("total_tokens", "token", 2, "- D D - - - -", "모형 호출마다", "context_tokens + output_tokens",
      "OpenAI · Gemini 는 직접 준다(total_tokens · total_token_count)", ["context_tokens", "output_tokens"]),
    S("context_growth", "context", 2, "- - - - - - -", "연속 두 호출 사이", "Δ context_tokens",
      "압축이 일어나면 음수", ["context_tokens"]),
    S("context_utilization", "context", 2, "- - - - - - -", "모형 호출마다", "context_tokens / context_window",
      "창 크기가 필요하다 -- cc_jsonl 에는 없다(문서의 모형 표나 Models API 로 채워야)", ["context_tokens",
                                                                                    "context_window"]),
    S("context_remaining", "context", 2, "- - - - - - -", "모형 호출마다", "context_window − context_tokens",
      "context_utilization 과 같은 정보(창이 일정하면 완전 중복 -- 정의상)", ["context_tokens", "context_window"]),
    S("cumulative_output_tokens", "token", 2, "- - - - - - -", "모형 호출마다", "Σ output_tokens(실행 시작부터)",
      "단조 증가 -- 걸음 번호와 강하게 겹칠 것", ["output_tokens"]),
    S("output_token_growth", "token", 2, "- - - - - - -", "연속 두 호출 사이", "Δ output_tokens", "", ["output_tokens"]),
    S("output_token_acceleration", "token", 2, "- - - - - - -", "연속 세 호출", "Δ² output_tokens", "잡음이 크다",
      ["output_tokens"]),
    S("output_tokens_per_sec", "token", 2, "- - - - - - -", "모형 호출마다",
      "output_tokens / 생성 구간(첫 조각 ~ 끝)", "cc_jsonl 은 블록 단위 시각뿐이라 거칠다",
      ["output_tokens", "call_span_ms"]),
    S("cache_hit_ratio", "token", 2, "- - - - - - -", "모형 호출마다", "cache_read / context_tokens",
      "되풀이된 맥락의 비율의 대용", ["cache_read_input_tokens", "context_tokens"]),
    S("thinking_ratio", "token", 2, "- - - - - - -", "모형 호출마다", "thinking_tokens / output_tokens", "",
      ["thinking_tokens", "output_tokens"]),
    S("token_burst", "token", 2, "- - - - - - -", "모형 호출마다",
      "output_tokens > 그때까지 그 실행의 중앙값 × 4 (첫 3 호출은 판정 안 함)", "문턱 4 는 정한 것이지 잰 것이 아니다",
      ["output_tokens"]),
    S("token_stagnation", "token", 2, "- - - - - - -", "연속 3 호출",
      "context_growth 가 3 호출 연속 < 1% of context_tokens", "", ["context_growth", "context_tokens"]),
    S("token_oscillation", "token", 2, "- - - - - - -", "창 6 호출",
      "창 안에서 Δ output_tokens 의 부호가 바뀐 횟수", "", ["output_tokens"]),
    # ---- B. 도구 (직접) ----
    S("tool_name", "tool", 1, "O D D D O O O", "도구 호출마다", "부른 도구 이름",
      "SWE-agent 는 명령 문자열(첫 낱말을 이름으로)", evidence="tool_use.name; otel gen_ai.tool.name"),
    S("tool_input_chars", "tool", 1, "O D D D O O O", "도구 호출마다", "도구 인자 길이(문자)", "토큰이 아니다"),
    S("tool_is_error", "tool", 1, "O - - U O O A", "도구 결과마다",
      "도구 결과의 오류 깃발", "Anthropic API 에서는 **클라이언트(하네스)가 다는 값**이다. SWE-agent 추적에는 없다 -- "
      "그때 쓰던 글 탐색(어댑터)은 형 2 추정이다",
      evidence="tool_result.is_error; cc_stream 'Exit code 2 ... is_error: true'"),
    S("tool_output_chars", "tool", 1, "O - - U O O O", "도구 결과마다", "도구 결과 길이(문자)", ""),
    S("tool_reported_duration", "tool", 1, "A - - U O U A", "도구 결과마다",
      "런타임이 적은 도구 소요 시간", "일부 도구(웹 검색 등)만 적는다 -- toolUseResult.durationSeconds",
      evidence="cc_jsonl toolUseResult.durationSeconds"),
    S("tool_interrupted", "tool", 1, "A - - U O O A", "도구 결과마다", "사용자/런타임이 끊었나", "",
      evidence="toolUseResult.interrupted"),
    S("tool_calls_per_message", "tool", 1, "O D D U O O A", "모형 호출마다", "한 응답 안의 tool_use 블록 수(병렬 호출)",
      "SWE-agent 는 걸음당 하나로 고정"),
    S("permission_denials", "tool", 1, "- - - - A O A", "실행 끝", "권한으로 거절된 도구 호출 목록", "",
      evidence="cc_stream result.permission_denials"),
    # ---- B'. 도구 (파생) ----
    S("tool_call_count", "tool", 2, "- - - - - - -", "누적", "도구 호출 수", "", ["tool_name"]),
    S("tool_error_rate", "tool", 2, "- - - - - - -", "누적", "오류 결과 / 도구 호출", "", ["tool_is_error"]),
    S("identical_call_repeats", "tool", 2, "- - - - - - -", "누적", "(이름, 인자) 같은 호출의 최대 반복 수", "",
      ["tool_name", "tool_input"]),
    S("retry_count", "tool", 2, "- - - - - - -", "누적", "오류 뒤 같은 겨냥으로 다시 부른 수(llmsensor.trace.retries)",
      "겨냥 = 이름 + 명령 첫 낱말/경로 -- 거친 지문", ["tool_name", "tool_input", "tool_is_error"]),
    S("failed_retry_count", "tool", 2, "- - - - - - -", "누적", "재시도 중 다시 오류난 수", "",
      ["retry_count", "tool_is_error"]),
    S("action_diversity", "tool", 2, "- - - - - - -", "누적", "서로 다른 (이름, 인자) 수 / 호출 수", "", ["tool_name",
                                                                                                 "tool_input"]),
    S("tool_type_entropy", "tool", 2, "- - - - - - -", "누적", "도구 이름 분포의 섀넌 엔트로피(bit)", "", ["tool_name"]),
    S("tool_latency_ms", "temporal", 2, "- - - - - - -", "도구 호출마다", "결과 시각 − 호출 시각",
      "호출 시각은 그 tool_use 가 담긴 줄의 시각 -- 실행 시작이 아니다", ["t_issued", "t_result"]),
    # ---- C. 시간 (직접) ----
    S("event_timestamp", "temporal", 1, "A U U D O A A", "줄/사건마다",
      "런타임이 적은 사건 시각", "**cc_stream 의 stream_event 에는 시각이 없다** -- 수집기가 도착 시각을 찍는다(아래). "
      "SWE-agent 추적에는 걸음 시각이 없다", evidence="cc_jsonl timestamp; cc_stream 는 assistant/user 줄에만"),
    S("arrival_time", "temporal", 1, "- - - - - O -", "사건마다(수집기)",
      "수집기가 stdout 줄을 받은 단조 시각(ms)", "수집기의 관측 시각이지 서버 시각이 아니다 -- 파이프 지연 포함"),
    S("run_duration_ms", "temporal", 1, "- - - - A O A", "실행 끝", "실행 전체 벽시계 시간", "",
      evidence="cc_stream result.duration_ms; cc_jsonl cost-state.totalDuration(세션)"),
    S("api_duration_ms", "temporal", 1, "- - - - O O A", "실행 끝", "모형 API 에 쓴 시간 합",
      "cc_jsonl 은 세션 누적(cost-state) -- 과업 단위 아님", evidence="result.duration_api_ms; cost-state.totalAPIDuration"),
    S("api_retry_time_ms", "error", 2, "- - - - - - -", "세션 끝",
      "totalAPIDuration − totalAPIDurationWithoutRetries", "cc_jsonl cost-state 에만", ["api_duration_ms"]),
    S("ttft_ms", "temporal", 1, "U - - D A O A", "실행(첫 호출)", "첫 출력까지 시간",
      "cc_stream result.ttft_ms 는 **첫 호출**만. 호출마다는 도착 시각으로 파생", evidence="result.ttft_ms; otel time_to_first_chunk"),
    S("thinking_duration_ms", "temporal", 1, "A - - U O A A", "모형 호출마다", "생각에 쓴 시간", "cc_jsonl 만",
      evidence="cc_jsonl thinkingDurationMs"),
    # ---- C'. 시간 (파생) ----
    S("call_span_ms", "temporal", 2, "- - - - - - -", "모형 호출마다", "그 호출의 첫 관측 ~ 마지막 관측", "", ["event_timestamp"]),
    S("inter_call_gap_ms", "temporal", 2, "- - - - - - -", "연속 호출", "앞 호출 끝 ~ 이번 호출 시작", "도구 시간 포함",
      ["event_timestamp"]),
    S("idle_ms", "temporal", 2, "- - - - - - -", "실행 끝", "run_duration − api_duration − Σ tool_latency", "음수면 겹침",
      ["run_duration_ms", "api_duration_ms", "tool_latency_ms"]),
    S("latency_variance", "temporal", 2, "- - - - - - -", "누적", "call_span_ms 의 분산", "", ["call_span_ms"]),
    S("execution_rate", "temporal", 2, "- - - - - - -", "누적", "모형 호출 수 / 분", "", ["event_timestamp"]),
    S("burstiness", "temporal", 2, "- - - - - - -", "누적", "(σ−μ)/(σ+μ) of inter_call_gap_ms (Goh-Barabási)", "",
      ["inter_call_gap_ms"]),
    # ---- D. 오류 · 종료 (직접) ----
    S("stop_reason", "error", 1, "O D D D O O A", "모형 호출마다",
      "호출이 멈춘 까닭(end_turn · tool_use · max_tokens · stop_sequence · pause_turn · refusal · "
      "model_context_window_exceeded · compaction)", "OpenAI finish_reason · Gemini FinishReason 은 값 집합이 다르다",
      evidence="cc_jsonl stop_reason {tool_use, end_turn}; gemini FinishReason MALFORMED_FUNCTION_CALL, TOO_MANY_TOOL_CALLS ..."),
    S("stop_details", "error", 1, "D U U U O O A", "모형 호출마다", "거절일 때 분류", "refusal 일 때만 채워진다"),
    S("stream_error_event", "error", 1, "D U U U U U A", "스트림 도중", "스트림 안의 error 사건(overloaded_error 등)",
      "이 세션에서 실제로 보지 못했다", evidence="streaming.md 'event: error ... overloaded_error'"),
    S("api_error_status", "error", 1, "- - - - A O A", "실행 끝", "API 오류 상태", "이 세션의 값은 전부 null 이었다",
      evidence="cc_stream result.api_error_status"),
    S("terminal_reason", "error", 1, "- - - - A O O", "실행 끝", "실행이 끝난 까닭",
      "cc_stream result.terminal_reason/subtype; sweagent info.exit_status(submitted · exit_cost ...)"),
    S("rate_limit_state", "error", 1, "D - - - A O A", "실행 중 사건",
      "요금 한도 상태 · 사용률(5시간/7일)", "API 는 429 + retry-after · x-ratelimit-* 헤더(문서). 런타임은 사건으로",
      evidence="cc_stream rate_limit_event.rate_limit_info.utilization; error-codes.md headers"),
    S("hook_errors", "error", 1, "- - - - O U A", "턴 끝", "훅 실행 오류 · 소요", "Claude Code 만",
      evidence="cc_jsonl system/stop_hook_summary.hookErrors"),
    # ---- E. 맥락 · 기억 (직접) ----
    S("context_window", "context", 1, "D U U U A O A", "실행 시작/끝", "모형의 맥락 창 크기",
      "Anthropic 은 Models API max_input_tokens(문서). cc_stream result.modelUsage.contextWindow",
      evidence="models.md 'max_input_tokens # context window'; cc_stream contextWindow=200000(haiku)"),
    S("max_output_tokens", "context", 1, "D U U U A O A", "실행 시작/끝", "출력 상한", ""),
    S("autocompact_threshold", "context", 1, "- - - - A O A", "실행 시작", "자동 압축 문턱 · 유효 창",
      "Claude Code 런타임 설정값", evidence="cc_stream autocompact_state {effective_window, threshold}"),
    S("compaction_event", "context", 1, "D U U U U U A", "일어날 때", "맥락 압축/요약이 일어났다",
      "이 세션에서 실제로 일어나지 않아 꼴을 못 보았다", evidence="compaction.md(stop_reason 'compaction')"),
    S("memory_retrieval", "context", 1, "U U U D U U A", "일어날 때", "기억 저장소 조회 수 · 크기 · 지연",
      "OTel 에 gen_ai.memory.* 꼴이 있다. 우리가 본 런타임에는 기억 도구가 없었다"),
    # ---- F. 출력 · 행동 (직접) ----
    S("output_text_chars", "output", 1, "O D D U O O O", "모형 호출마다", "보이는 글 출력 길이(문자)", "생각 내용은 빠진다"),
    S("logprobs", "output", 1, "U U U U A A A", "토큰마다", "토큰 확률(엔트로피 계산용)",
      "Anthropic 스킬 문서에 언급이 없다 -- 없다고 단정하지 않고 U. 우리가 본 추적에는 없다"),
    # ---- F'. 출력 (파생) ----
    S("text_repetition", "output", 2, "- - - - - - -", "모형 호출마다", "이번 글의 3-gram 중 앞 글들에 이미 나온 비율", "",
      ["output_text"]),
    S("type_token_ratio", "output", 2, "- - - - - - -", "모형 호출마다", "서로 다른 낱말 / 낱말", "짧은 글에서 불안정",
      ["output_text"]),
    S("schema_violation", "output", 2, "- - - - - - -", "최종 답", "제약 센서(ConstraintSensor)의 위반 수", "제약을 줘야 잰다",
      ["output_text"]),
    # ---- 비용 ----
    S("cost_usd", "cost", 1, "A A A A O O O", "실행 끝(cc_jsonl 은 세션 누적)", "런타임이 계산한 비용",
      "API 응답에는 없다 -- 단가표로 파생해야", evidence="result.total_cost_usd; cost-state.totalCostUSD; info.model_stats.instance_cost"),
]

NOT_SENSORS = [
    ("reasoning_pressure", "생각 토큰 · 출력 길이를 '압박' 으로 읽는 해석"),
    ("confusion", "반복 · 진동을 '혼란' 으로 읽는 해석"),
    ("non_convergence", "맥락이 자라는데 진전이 없다는 판단 -- 진전의 정의가 필요"),
    ("planning_failure", "도구 순서를 계획 실패로 읽는 해석"),
    ("execution_instability", "오류 · 재시도를 불안정으로 읽는 해석"),
    ("context_saturation", "이용률이 높다는 관측 + 그것이 해롭다는 해석. 관측 부분은 context_utilization"),
    ("success / failure", "외부 결과(라벨) -- 센서 층이 아니라 State 검증의 몫"),
]

# 분석에 쓸 호출 단위 · 실행 단위 변수(얼렸다) -- eval/sensor_layer.py 가 이 이름을 그대로 쓴다
CALL_VARS = ["step_index", "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens",
             "thinking_tokens", "tool_calls_per_message", "tool_errors", "tool_output_chars", "tool_latency_ms",
             "call_span_ms", "inter_call_gap_ms", "output_text_chars", "context_tokens", "context_growth",
             "cumulative_output_tokens", "cache_hit_ratio", "thinking_ratio", "output_tokens_per_sec"]
# text_repetition · type_token_ratio 는 글 내용이 있어야 한다 -- 레코드 꼴은 내용을 안 담는다(사생활). 분석에서 뺀다
RUN_VARS = ["tokens_sent", "tokens_received", "model_calls", "tool_call_count", "tool_error_rate",
            "identical_call_repeats", "retry_count", "action_diversity", "tool_type_entropy", "cost_usd",
            "mean_tool_output_chars"]
# 정의상 같은 것 -- 상관이 나와도 발견이 아니다
IDENTITIES = [("context_utilization", "context_tokens", "창이 일정하면 상수배"),
              ("context_remaining", "context_tokens", "창이 일정하면 음의 일차"),
              ("total_tokens", "context_tokens + output_tokens", "합"),
              ("cost_usd", "토큰들의 단가 가중합", "모형 하나면 선형")]
