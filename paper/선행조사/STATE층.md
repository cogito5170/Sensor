# 선행조사 -- 의미 상태(State) 층 (2026-10-01)

코드보다 먼저 커밋한다. 이 층이 하려는 것(관측 → 파생 → 의미 상태, UNKNOWN 을 일급으로, 근거 추적, 시간 유효성,
흔들림 억제)은 **새것이 아니다.** 가장 가까운 셋을 읽고 무엇을 빌리는지 적는다.

## 가장 가까운 선행

| 무엇 | 어디 | 확인수준 | 빌리는 것 | 다른 점 |
|---|---|---|---|---|
| Kubernetes **Conditions** | kubernetes/community `api-conventions.md` (Typical status properties · Conditions) | [출처:전문 -- 해당 절] | **Unknown 을 일급 값으로**("the absence of a condition status should be interpreted the same as Unknown"), 처음 볼 때부터 Unknown 이라도 적는다, 조건의 뜻은 정의되면 함부로 못 바꾼다(버전), `reason` · `message` · `lastTransitionTime`, 상세 관측을 **대신하지 않고 보완**한다("complement more detailed information ... rather than replace it") | 조건은 True/False/Unknown 셋. 우리는 열거값이 여럿이고, 근거(관측 ID)를 사슬로 남긴다 |
| Prometheus **alerting rules** | prometheus/prometheus `docs/configuration/alerting_rules.md` | [출처:전문] | 흔들림 억제: `for`(조건이 그만큼 이어져야 firing, 그 사이 pending), `keep_firing_for`("prevent situations such as flapping alerts, false resolutions due to lack of data") | 경보는 정책에 가깝다(알림). 우리는 상태만 내고 정책은 밖에 둔다 |
| W3C **PROV** (PROV-DM / PROV-O) | w3.org/TR/prov-dm | **[출처:기억]** -- 이 환경에서 w3.org 가 403. 읽지 않았다 | entity · activity · wasDerivedFrom · wasGeneratedBy 의 근거 사슬이라는 발상 | 우리는 PROV 어휘를 쓰지 않는다. 상태 → 규칙(버전) → 파생값 → 관측 ID 의 좁은 사슬만 |
| 앞 실험 -- 이 저장소의 센서 층 | `docs/SENSOR_LAYER.md`, `eval/RESULTS_sensor_layer.md` | 직접 함 | 관측 가능한 것 · 중복 무리 · UNKNOWN 목록 · `unobserved`/`reported_null` 구분 | -- |

## 우리가 다른 점 (주장이 아니라 범위)

- **문턱을 지어내지 않는다.** K8s 조건의 True/False 는 컨트롤러가 정의를 안다. 우리에겐 "출력 토큰이 많으면 추론 부하가
  높다" 같은 문턱의 경험적 근거가 **없다**(앞 SWE-bench 실험에서 센서 Q 가 토큰 수 하나를 못 이겼다). 그래서 규칙마다
  근거 종류를 적고(정의상 · 런타임이 선언한 경계 · 운영자가 가정한 문턱), 운영자가 문턱을 주지 않으면 그 상태는
  내지 않는다.
- LLM 이 상태를 정하지 않는다 -- 결정론적 규칙만.

## 찾아본 곳

- kubernetes/community api-conventions.md (raw.githubusercontent.com)
- prometheus/prometheus docs/configuration/alerting_rules.md
- w3.org/TR/prov-o, w3.org/TR/prov-dm -- 403, w3c/prov 저장소 README -- 404

## 아직 못 지운 가능성

- 관측가능성 제품(Datadog · Honeycomb · Langfuse · AgentOps)의 "agent health" 류 상태 모형 -- 안 찾아봤다.
- 디지털 트윈 · 상태 추정(칼만 류) 문헌 -- 연속 상태 추정은 이 판의 범위가 아니라서 안 봤다.
- OTel 의 entity / resource 모형과 겹칠 수 있다 -- 확인 안 함.
