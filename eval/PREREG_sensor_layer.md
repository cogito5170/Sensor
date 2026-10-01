# 사전등록 -- LLM 센서 층: 무엇을 볼 수 있고, 무엇이 서로 다른 정보인가 · 2026-10-01

**목적은 실패 예측이 아니다.** 바깥에서 볼 수 있는 실행 신호를 찾고, 센서로 정의하고, 원천별로 실제로 얻히는지
확인하고, 서로 다른 정보를 보는 최소 집합을 고르는 것이다. State · Policy 는 다음 단계다.

## 이 커밋에 얼린 것 (수집 전)

| 파일 | 무엇 |
|---|---|
| `llmsensor/telemetry/catalog.py` | 후보 71 개(형 1 직접 39 · 형 2 파생 32) · 원천 7 곳의 가용성 근거 · 형 3(센서 아님) 목록 · 분석 변수 |
| `llmsensor/telemetry/schema.py` · `schema/telemetry.schema.json` | 레코드 꼴 셋(model_call · tool_call · run). 못 본 값 = null + `unobserved` |
| `llmsensor/telemetry/collect.py` | 원천 3 곳 -> 레코드(원천이 준 값만) |
| `llmsensor/telemetry/derive.py` | 레코드 -> 파생(레코드만 본다) |
| `eval/sensor_tasks.py` · `eval/run_claude.py` | claude -p 과업 12 개(센서를 움직이게 고른 것) · 도착 시각 찍는 수집기 |
| `eval/sensor_layer.py` | 분석(아래 규칙 그대로) |

**수집 뒤에 센서 정의 · 꼴 · 분석 규칙을 바꾸지 않는다.** 수집이 정의의 버그를 드러내면 고치되, 고친 것과 까닭을
결과 문서의 '수집 뒤 바꾼 것' 에 적는다.

## 데이터

1. `cc_jsonl_self` -- 이 에이전트 세션 자신의 Claude Code JSONL(Opus 5.5). 수집 시점의 스냅숏.
2. `cc_stream` -- `claude -p` (Haiku 4.5) 과업 12 개, stream-json + 수집기 도착 시각.
3. `cc_jsonl_child` -- 2 와 **같은 실행**을 Claude Code 가 따로 남긴 JSONL. **분석에는 안 넣고 대조에만** 쓴다.
4. `sweagent` -- SWE-agent + Claude 3.5 Sonnet 추적 288 개(앞 실험에서 받은 것).

## 분석 규칙

- 가용성: 원천 × 칸마다 null 아닌 비율.
- **독립 대조**: 같은 모형 호출을 cc_stream 과 cc_jsonl_child 가 본 토큰 넷(input · output · cache_read ·
  cache_creation)이 호출마다 같아야 한다. 다르면 수집기 하나가 틀렸다 -- 그 칸은 결론에 쓰지 않는다.
  런타임이 준 합계(result.usage)와 호출 합도 비교한다.
- 호출 단위(1 + 2 합쳐서, 그리고 원천별로 따로): CALL_VARS 쌍마다 Spearman ρ, 정규화 상호정보(5 분위).
  쌍의 표본 < 30 이면 UNKNOWN.
- **중복**: |ρ| ≥ 0.9 이고, 두 원천 모두 n ≥ 30 이면 **둘 다에서** |ρ| ≥ 0.9. 한쪽에서만이면 '원천 의존' 으로
  따로 적고 중복으로 치지 않는다.
- **시계**: |ρ(변수, step_index)| ≥ 0.9 이면 그 변수는 '시간 추세' 를 본다고 표시한다. 1 차 차분 ρ 도 낸다.
- 비단조 의존: NMI ≥ 0.5 인데 |ρ| < 0.5 인 쌍은 따로 표시.
- 실행 단위: SWE-agent 288 실행의 RUN_VARS 쌍. claude 실행(13)은 n < 30 이라 상관을 내지 않고 값만 적는다.
- 중복 무리(|ρ| ≥ 0.9 의 연결 성분)마다 대표 하나: 형 1 > 형 2, 그다음 원천 가용성(O/D 수), 그다음 이름.
- 정의상 같은 것(catalog.IDENTITIES)은 상관이 나와도 발견으로 세지 않는다.

## 돌리기 전 예상 (틀려도 지우지 않는다)

- 호출 단위에서 cache_read_input_tokens · context_tokens · cumulative_output_tokens 는 서로 |ρ| ≥ 0.9, 그리고 시계다
  (Claude Code 는 맥락을 거의 다 캐시에서 읽고 맥락은 걸음마다 자란다).
- output_tokens 와 thinking_tokens 는 0.9 밑 -- 다른 정보.
- 도구 쪽(tool_output_chars · tool_latency_ms · tool_errors)은 토큰과 0.5 밑.
- SWE-agent 실행 단위에서 tokens_sent · model_calls · tool_call_count · cost_usd 는 한 무리.
- 독립 대조는 토큰 넷이 호출마다 정확히 같을 것.
- 압축 사건 · 스트림 오류 사건 · logprobs · 기억 조회는 이 수집에서 하나도 안 나올 것 -- UNKNOWN 으로 남는다.

## 이 실험이 말하지 않는 것

- 어떤 센서가 실패를 잘 예측하나(다음 단계).
- OpenAI · Gemini 의 **실제** 값 -- 그쪽은 SDK 소스(D)만 보았고 실행 추적이 없다.
- 상관 = 중복의 근사다. ρ 가 낮아도 조건부로 같은 정보일 수 있고, 높아도 다른 상황에서는 갈릴 수 있다.
