# 상태 생애 (State Lifecycle) -- 2026-10-01

## 1. 유효성 -- UNKNOWN 은 일급 값이다

| status | 뜻 | 정책이 할 일 |
|---|---|---|
| `OBSERVED` | 런타임이 직접 보고(층 1) | -- |
| `DERIVED` | 관측에서 계산(층 2) | -- |
| `INFERRED` | 규칙으로 해석(층 3) | 값을 쓴다 |
| `UNKNOWN` | **판정할 근거가 없다** | 0 · 거짓 · 정상으로 읽지 마라. `reason` 이 왜 모르는지 말한다 |
| `STALE` | 값은 있으나 TTL 을 넘겼다(질의 때 판정) | 지금 값으로 쓰지 마라 |
| `INVALID` | 더 나은 근거로 대체되었거나 명시적으로 무효화 | 쓰지 마라 |
| `NOT_APPLICABLE` | 이 배치에서 정의되지 않음(예산 없음 · 끝난 과업의 진행) | 묻지 마라 |

**"실패를 못 봤다" ≠ "건강하다".** 그래서 건강 값 이름이 `HEALTHY` 가 아니라 `NO_FAILURE_OBSERVED` 이고, 이유 문자열이
"건강이 증명된 것은 아니다" 로 끝난다. 본 도구 실행이 하나도 없으면 `NO_FAILURE_OBSERVED` 가 아니다 --
`execution-health-v3`(baseline BD-84)부터 두 경우를 가른다:

| 경우 | 값 | 까닭 |
|---|---|---|
| (a) 모델 호출은 봤고 도구 레코드가 **하나도 없다** | `NO_TOOL_RUN_YET` (INFERRED, 근거 OBSERVED) | "도구 실행이 아직 없다" 는 관측된 사실이다. **건강을 말하지 않는다.** 시각은 마지막 모델 호출(없음의 주장 -- BD-74) |
| (b) 도구 레코드가 있는데 결과(`is_error`)를 **못 본다** -- SWE-agent · 아직 도는 호출 | `UNKNOWN` | 판정할 근거가 없다(v2 와 같다). `observation` 글에서 오류를 읽어 내지 않는다(BD-10) |
| 모델 호출도 못 봤다 | `UNKNOWN` | "아직 없다" 를 말할 관측이 없다 |

`NOT_APPLICABLE` 로 쓰지 않는다 -- 실행 건강은 이 배치에서 **정의되고**, 아직 잴 근거가 없을 뿐이다. 실데이터의 첫 평가점: `eval/first_eval.py`.

**관측이 없는 것과 보고된 null 은 다르다**(텔레메트리 꼴 v2). 정상 종료 요약의 `api_error_status: null` 은 "오류 보고
없음" 이라는 **관측**이라 `runtime_reliability = NO_FAILURE_OBSERVED` 의 근거가 된다. 키가 아예 없으면(오류로 끝난 t08)
근거가 되지 않는다.

**빈 칸을 이전 값으로 메우지 않는다.** 마지막 호출의 입력 토큰 셋 중 하나라도 못 봤으면 `context_tokens` 는 UNKNOWN 이다
-- 앞 호출의 값은 낡은 근거다.

## 2. 신선도

| freshness | 언제 |
|---|---|
| `FRESH` | 근거의 최신 관측 시각에서 `now` 까지가 TTL 안 |
| `STALE` | TTL 을 넘김 -- 질의 결과의 `status` 도 `STALE` 이 된다(값은 남는다) |
| `UNTIMED` | 근거에 시각이 없다(SWE-agent 추적) -- 신선도를 판정할 수 없다 |
| `PERMANENT` | 끝난 일에 대한 사실(`completion_state` 의 종료 값, 끝난 과업의 progress NOT_APPLICABLE) |

`now` 는 질의 인자다. 주지 않으면 그 실행의 마지막 관측 시각("마지막 관측 시점 기준")이다 -- 엔진은 시계를 읽지 않는다.
시간 기준은 원천마다 다르다(Claude Code JSONL = 유닉스 ms, stream-json = 수집기 단조 ms). `now` 는 그 실행의 기준으로 준다.
TTL 은 설정(`StateConfig.ttl_ms`)이고 기본값(10 분, 요금 한도 5 분)은 **잰 값이 아니다.**

## 3. 생애 사건

```
            (첫 계산)
               │ CREATE
               ▼
   UNKNOWN ──RECOVER──► INFERRED ──UPDATE──► INFERRED(다른 값)
      ▲                    │  ▲                   │
      │ UPDATE(근거 사라짐) │  │ REFRESH(같은 값, 새 근거)
      └────────────────────┘  │
                    STALE ◄── tick(now): TTL 초과 (값 유지, 표시만)
                    INVALIDATE ◄── invalidate() / 대체된 추정
```

| 사건 | 언제 | 남는 것 |
|---|---|---|
| `CREATE` | 그 (실체, 상태)를 처음 계산 | 생애 사건 + history |
| `UPDATE` | 값 또는 유효성이 바뀜 | 생애 사건 + **전이** + history |
| `REFRESH` | 같은 값, 새 근거 | 생애 사건 (`since` 는 그대로) |
| `STALE` | `tick(now)` 가 TTL 초과를 발견 | 생애 사건(같은 낡음은 한 번만) |
| `INVALIDATE` | `invalidate()` 호출 | 생애 사건 + 전이, status INVALID |
| `RECOVER` | UNKNOWN · STALE · INVALID 에서 쓸 수 있는 값으로 | 생애 사건 + 전이 |

생성 도중 생각 토큰 추정(`reasoning_estimate`, ESTIMATE)은 같은 호출의 최종값이 오면 지표 status 가 `INVALID`
("대체되었다")가 된다 -- 추정은 권위가 없다(앞 실험: 최종값의 중앙 1.68 배).

끝난 일(`final`)은 다시 계산하지 않는다 -- 늦게 온 관측이 종료 사실을 바꾸지 못한다(시험).

## 4. 전이

전이마다 `previous` · `new` · `trigger`(규칙의 이유) · `rule_id` · `evidence`(지표 id) · `at` · `seq`. 실제 예(시연):

```
execution_health:  NO_TOOL_RUN_YET -> NO_FAILURE_OBSERVED  @ 2050   결과 1 개 중 실패 없음  (v3 -- v2 에서는 None -> )
                   NO_FAILURE_OBSERVED -> UNRESOLVED  @ 5350   겨냥 1/2 의 마지막 결과가 실패 (pytest)
                   UNRESOLVED -> RECOVERED_FAILURES   @ 8650   실패했던 겨냥 1 개가 뒤에 성공
                   RECOVERED -> UNRESOLVED_FAILURES   @ 16900  겨냥 1/7 의 마지막 결과가 실패 (WebFetch)
```

규칙에 없는 전이는 생기지 않는다 -- 전이는 규칙 출력이 바뀔 때만 나온다. `HEALTHY → DEGRADED → FAILING → FAILED` 같은
사다리는 만들지 않았다: 단계를 가를 문턱 근거가 없다.

## 5. 흔들림 억제

두 장치, 둘 다 **운영자 설정**이고 기본은 꺼져 있다(근거 없이 켜지 않는다):

- **띠의 enter/exit** (`config.Band`) -- 들어가려면 `enter` 이상, 나가려면 `exit` 밑. `exit > enter` 는 거부한다.
  예(시험): MEDIUM(0.5/0.45) · HIGH(0.75/0.7)에서 0.40 0.76 0.72 0.74 0.69 0.47 0.44 → LOW HIGH HIGH HIGH MEDIUM MEDIUM LOW.
- **연속 횟수** (`config.min_consecutive`) -- 새 값이 N 번 이어져야 바뀐다(Prometheus `for` 와 같은 생각, 시간 대신 횟수 --
  SWE-agent 처럼 시각이 없는 원천에서도 동작하게).

실제 레코드 301 실행에서는 상태당 전이가 최대 2 회였다 -- 흔들림이 관측되지 않아 기본으로 켤 근거도 없었다.

## 6. 결정성 · 멱등

- 같은 관측 + 같은 설정 버전 + 같은 규칙 버전 → 같은 상태 · 전이 · 생애 사건. 입력 레코드 순서를 뒤집어도 같다
  (`from_telemetry` 가 실행마다 인과 순서로 다시 세운다). 실제 레코드 301 실행에서 두 번 돌려 스냅숏이 같았다.
- 같은 레코드(record_id)를 다시 받으면 버린다 -- 스트림 재전송이 두 번 세어지지 않는다. (처음 판에는 이것이 없어서,
  시연에서 멈춤 사유 11 개가 12 개로 세어졌다.)
- 상태마다 `rule_id` · `rule_version` · `config_version` 이 남아, 규칙이나 설정이 바뀐 뒤의 상태와 섞이지 않는다.
