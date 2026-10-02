# 선행조사 -- MS 센싱 확장 (실행 · 지연 · 공급자 · 비용) + Decision Context (2026-10-02)

코드보다 먼저 커밋한다. 과제 지시대로 NASA · Microsoft · Google 의 1 차 자료를 먼저 찾았다. **이 환경에서 막힌 곳이
많았다** -- sre.google(403), learn.microsoft.com(403), nasa.gov · ntrs.nasa.gov(403), ai.google.dev(403). 그래서 같은
기관이 GitHub 에 공개한 1 차 원문(소스 · 문서 저장소)을 읽었다.

## 읽은 것 (전문 또는 해당 절)

| 기관 | 자료 | 확인수준 | 빌린 설계 결정 |
|---|---|---|---|
| NASA | cFS **Limit Checker (LC)** README -- nasa/LC | [출처:전문 -- README] | "monitors telemetry data points ... compares the values against **predefined threshold limits**. When a threshold condition is encountered, an **event message** is issued and a Relative Time Sequence (RTS) command script **may be initiated** to respond." -> 문턱은 **미리 정의된** 것(우리: 출처가 명시된 문턱만), 감지(event)와 대응(RTS)은 **다른 단계**(우리: State 와 Policy 분리) |
| NASA | F´ **Svc::Health** SDD -- nasa/fprime | [출처:전문] | 핑 응답 시간을 **포트마다 설정된 최대 timeout** 으로 판정(HTH-002/003), timeout 값은 **명령으로 갱신**(HTH-006) -> 지연 · 시간 초과 문턱은 **운영자 설정**이며 실체(포트/도구)마다 따로 |
| Microsoft | Azure Architecture Center **Circuit Breaker** -- MicrosoftDocs/architecture-center | [출처:전문] | Closed/Open/Half-Open 세 상태, 전이는 **failure threshold**(설정) 도달 · timeout timer 만료 · success count threshold 로 -> 공급자 건강의 단계는 **설정된 문턱** 없이는 만들 수 없다. 우리는 그 문턱을 기본으로 두지 않는다 |
| Microsoft | **Health Endpoint Monitoring** -- 같은 저장소 | [출처:전문] | "report **degraded** rather than unhealthy when a noncritical dependency is unavailable", 상태를 주기적으로 재서 **캐시**하고 그 결과를 노출 -> 우리 TTL · STALE, 실체별 상태 |
| Microsoft | **Retry** 패턴 | [출처:목록] -- 저장소에는 yml 껍데기만(726 바이트), 본문은 learn.microsoft.com(403) | 재시도는 정책의 일이다 -- 센싱은 재시도 **횟수**만 관측 |
| Google | **google.rpc.Code** -- googleapis/googleapis `code.proto` | [출처:전문] | `RESOURCE_EXHAUSTED`(8) = HTTP 429 "per-user quota", `UNAVAILABLE`(14) "client can retry just the failing call", `DEADLINE_EXCEEDED`(4) = 504 "**may be returned even if the operation has completed successfully**" -> 시간 초과를 실패로 동일시하지 않는다. 공급자 오류를 정준 분류로 옮길 때 이 표를 쓴다 |
| Google | **google.rpc.RetryInfo** -- `error_details.proto` | [출처:전문] | "Clients should wait at least this long between retrying" -> `retry_after` 는 **공급자가 선언한** 값(PROVIDER_DECLARED) |
| Google | **AIP-193 Errors** -- aip-dev/google.aip.dev | [출처:전문] | 오류 꼴에 status 문자열(`RESOURCE_EXHAUSTED`)이 들어간다 -> Gemini 오류 정규화 |
| -- | 앞 단계에서 읽은 K8s Conditions · Prometheus `for`/`keep_firing_for` | [출처:전문] | 상위 요약 조건("a common top-level condition which summarizes more detailed conditions"), 흔들림 억제 |

## 못 읽은 것 -- 인용하지 않는다

- Google SRE Book "Monitoring Distributed Systems" · "Service Level Objectives" (네 황금 신호, 백분위, SLO 는 운영자가 정한다)
  -- **[출처:기억]**. 403. 설계 근거로 쓰지 않고, 같은 결론(지연 문턱은 운영자 SLO)을 F´ Health 와 Circuit Breaker 로 받친다.
- Azure OpenAI quotas & limits(`retry-after-ms`, `x-ratelimit-remaining-*` 헤더) -- 403 / 저장소 경로 404. 쓰지 않는다.
- NASA Fault Management Handbook (NASA-HDBK-1002) -- 403. FDIR 개념은 기억이라 쓰지 않는다.
- OpenAI 의 rate-limit 헤더 문서 -- 막힘. OpenAI 어댑터는 HTTP 429 만 정규화하고 헤더는 U.

## 우리가 다른 점

새 방법이 아니다. 위 자료들이 공통으로 말하는 것 -- **감지와 대응을 가르고, 문턱은 미리 정의된(설정된) 것만 쓴다** --
를 이 저장소의 State 층 규율(근거 종류 · UNKNOWN · STALE · 근거 사슬)에 맞춰 넓히는 공학이다.

## 아직 못 지운 가능성

- LLM 게이트웨이 제품(LiteLLM · Portkey · Azure API Management 의 AI gateway)이 이미 공급자 건강 · 비용 상태를 낸다 -- 안 찾아봤다.
- "MS" 라는 정책 런타임이 다른 저장소에 있을 수 있다 -- 이 세션의 네 저장소에서는 못 찾았다(리뷰 문서 참고).
