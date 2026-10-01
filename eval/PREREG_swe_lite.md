# 사전등록 -- LLM 센서가 실제 실패를 잡나 (SWE-bench Lite) · 2026-10-01

**분석 코드(`eval/swe_lite.py`)와 어댑터(`llmsensor/adapters/sweagent.py`)를 이 문서와 같은 커밋에 얼린 뒤
한 번만 돌린다.** 돌린 뒤 어느 것을 고치면 그것은 탐색이고, 탐색이라고 적는다.

## 데이터

- SWE-agent + Claude 3.5 Sonnet, SWE-bench Lite, 제출 `20240620_sweagent_claude3.5sonnet`
  (SWE-bench/experiments 저장소의 `results.json` + 공개 S3 의 `.traj`). 받기: `bash eval/fetch_swe_lite.sh <곳>`.
- 300 개 중 추적이 있는 것 288. 라벨을 모르는 `no_logs` 1 개(psf__requests-863)를 빼서 **287**:
  resolved 69 · unresolved 218.
- **라벨 = SWE-bench 의 숨은 시험(외부 결과).** 그래서 외부 결과 센서는 끈다(UNKNOWN) -- 라벨을 입력으로 쓰지 않는다.
- 나눔: `sha256(instance_id) % 2` -> fit / test. fit 으로 성능모형 M_P(저장소별, min_n=5)와 LR 보정을 짓고,
  test 에서만 잰다.

## 이 데이터에서 센서가 볼 수 있는 것 · 없는 것 (돌리기 전에 적는다)

- **실행 센서:** SWE-agent 추적에는 종료 코드가 없다. 어댑터가 관측 글에서 오류(Traceback · `XxxError:` ·
  command not found ...)를 찾아 ok 를 추정한다. 버그 재현 스크립트가 일부러 낸 오류도 실패로 읽힌다 -- 잡음이 크다.
- **제약 센서:** 걸 제약이 없다 -> 전부 UNKNOWN. 측정 대상이 아니다.
- **일관성 센서:** VERIFY 정규식은 pytest 등을 찾는데 SWE-agent 는 주로 `python reproduce.py` 를 돌린다.
  그래서 claim 하위 판독은 대개 "검증 호출 없음" SUSPECT 로 기울 것이다.
- **행동 센서:** 토큰은 과업 합계 하나뿐(턴별 없음). 지연 없음. 고리 · 재시도 · 토큰 팽창은 볼 수 있다.

## 조건

- **A** -- 커밋 d4b80b3 의 기본값 그대로(보정 전 LR). prior = M_P 의 저장소별 성공률.
- **B** -- fit 라벨로 LR 보정(`OutcomeModel.calibrate`).
- 둘 다 prior 를 0.5 로 둔 판(`_noprior`)도 낸다 -- Q 가 저장소 성공률을 되돌려주는 것인지 가르려고.

## 사소한 기준선 (Q 는 이것들을 이겨야 뜻이 있다)

`neg_log_tokens` · `neg_api_calls` · `neg_steps` · `exit_submitted`(제출로 끝났나) · `patch_nonempty` · `repo_prior`(저장소별 성공률만)

## 판정 규칙

1. 지표: test 의 AUROC(resolved 를 양성). 순위법(Mann-Whitney)과 ROC 사다리꼴 두 길로 구하고 차가 1e-9 를 넘으면
   **분석 무효**.
2. **"센서가 사소한 것 이상을 본다"** 고 말하는 조건: `Q_B_calibrated` 의 AUROC − 가장 좋은 기준선의 AUROC ≥ 0.05
   **그리고** 쌍 부트스트랩(2000 회) 95% 구간의 아래 끝 > 0. 못 넘으면 "이 데이터에서 센서 Q 는 사소한 기준선보다
   낫다는 증거가 없다" 고 적는다.
3. 판정기: test 에서 ACCEPT 의 resolved 비율(정밀도)과, unresolved 중 ACCEPT 를 받은 수(놓침)를 적는다.
4. 센서별: test 에서 상태(OK/SUSPECT/FAULT/UNKNOWN)마다 resolved 비율.

## 무효화 · 한계 조건

- 한 센서가 전체의 90% 넘게 UNKNOWN 이면 그 센서는 **안 잰 것**이다(제약은 100% 로 예상).
- 실행 센서 FAULT 가 80% 를 넘으면 포화 -- 어댑터의 오류 추정이 정보를 못 준 것이다.
- Q 의 표준편차가 0 이면 상수 -- 무효.
- test 는 약 140 개, 양성 약 35 개다. AUROC 의 구간이 넓다(±0.1 안팎으로 예상).
- **일반화 못 한다:** 에이전트 하나(SWE-agent) · 모형 하나 · 벤치마크 하나 · 2024 년 추적. Claude Code 세션이
  아니고, 이 결과가 Claude Code 에 옮겨진다는 근거가 아니다.

## 돌리기 전 예상 (틀려도 지우지 않는다)

- 대부분의 신호는 행동 센서의 토큰 팽창에서 나올 것이다 -- 그런데 그것은 기준선 `neg_log_tokens` 와 거의 같은 정보다.
- 그래서 **판정 규칙 2 를 못 넘을 가능성이 높다**고 본다. Q_B 의 AUROC 는 0.6~0.7, 가장 좋은 기준선과 비슷.
- 판정기는 외부 결과 없이 근거(claim OK)를 거의 못 얻으므로 대부분 DEGRADE 를 낼 것이다.
