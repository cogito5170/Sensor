# 선행조사 -- LLM 전용 센서 (2026-10-01)

코드보다 먼저 커밋한다. **이 조사는 얕다** -- 아래 인용은 전부 검색 조각만 보고 단 것이다
(`[출처:조각]`). 전문을 읽은 것은 하나도 없다.

## 가장 가까운 선행연구

| 무엇 | 어디 | 확인수준 | 우리와 겹치는 것 |
|---|---|---|---|
| False success: 에이전트가 "완료" 를 말하는데 환경 상태는 실패 | arXiv:2606.09863 (Advani, 2026, ICML'26 워크숍) | [출처:조각] | **주장↔증거 불일치 센서**와 같은 대상. 조각에 따르면 LLM 판정자는 AUROC 0.65 를 못 넘고 TF-IDF 탐지기가 0.83~0.95 |
| 관측 가능한 궤적만으로 웹 에이전트 감시 | arXiv:2609.02057 (2026) | [출처:조각] | 내부 신호 없이 궤적만 본다 -- 우리 행동 센서와 같은 전제 |
| 실패 인지 관측가능성으로 낭비 계산 조기 진단 | arXiv:2606.01365 (2026) | [출처:조각] | 토큰 · 도구 호출 · 재시도를 계산 소비로 본다 -- 우리 텔레메트리 벡터와 같다 |
| 궤적 연구: 실패 궤적이 더 길고 토큰을 더 쓴다 | ASE 2025, software-lab.org "Thought-Action-Result Trajectories" | [출처:조각] | 토큰 팽창을 실패 증거로 쓰는 근거. **방향만** 같고 문턱은 우리가 따로 재야 한다 |
| Outcome monitors: 조용한 도구 실패 | arXiv:2608.19303 (2026) | [출처:조각] | 실행 센서 |
| 과대주장 성향 정량화 | arXiv:2609.20812 (2026) | [출처:조각] | 일관성 센서의 "증거 없는 완료 주장" |
| OpenTelemetry GenAI semantic conventions (agent spans, `gen_ai.usage.*_tokens`) | github.com/open-telemetry/semantic-conventions-genai | [출처:조각] | 텔레메트리 **스키마**. 우리는 판정까지 간다 |
| Analytical redundancy · parity space | Chow & Willsky 1984 (IEEE TAC) | [출처:조각] | 잔차 생성 → 결정의 두 단계 구조. 우리는 이것을 그대로 빌린다 |

## 우리가 다른 점 (주장이 아니라 범위)

1. **새 방법이 아니다.** 위의 것들을 한 패키지로 묶은 공학이다: 다섯 센서 → 성능모형(M_P) 잔차 →
   증거 융합(Q) → 결정론적 판정기(ACCEPT/REJECT/RETRY/DEGRADE).
2. **세 값 판독.** 센서가 평가를 못 했으면 UNKNOWN 이고, UNKNOWN 은 OK 로 세지 않는다
   (se_new `agentic/loop.py` 의 "로그가 없으니 루프가 없다의 길은 없다" 를 따른다).
3. **토큰만으로 ACCEPT 하지 않는다.** 판정기가 외부/실행/제약 센서 중 하나의 OK 를 요구한다.
4. Claude Code 세션 JSONL 을 바로 읽는다(walp `trace_stats.py` 와 같은 원천).

## 찾아본 질의

- `LLM agent failure detection token usage trajectory signals predict task success`
- `OpenTelemetry GenAI semantic conventions agent spans token usage`
- `analytical redundancy residual generation fault diagnosis Chow Willsky parity space`
- `"False Success" LLM agents confident closing silent failure detection claim versus tool output`

## 아직 못 지운 가능성

- 상용 관측 도구(LangSmith · Langfuse · Arize · AgentOps)가 이미 같은 판정층을 갖고 있을 수 있다. **안 찾아봤다.**
- semantic entropy / self-consistency 계열(교차모형 일치)을 안 찾아봤다. 교차모형 센서는 단순 유사도로만 지었다.
- 2606.09863 의 TF-IDF 탐지기가 우리 정규식 주장 탐지보다 낫다는 것은 거의 확실하다. 우리 것은 기준선이다.
- **기본 우도비(LR)는 잰 것이 아니라 손으로 둔 사전값이다.** 라벨 붙은 이력으로 `calibrate()` 하기 전의 Q 는
  확률이 아니라 순서 점수로 읽어야 한다.
