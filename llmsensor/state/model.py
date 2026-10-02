"""상태 층의 형(型). 세 층을 형으로 갈라 섞이지 않게 한다.

    Observation  층 1 -- 런타임이 보고한 것(값, 또는 '보고된 null')
    Metric       층 2 -- 관측에서 계산한 양
    State        층 3 -- 지금 참이라고 믿는 의미 상태(무엇을 뜻하나는 registry 의 StateDefinition)

JSON 에 묶이지 않는다 -- 직렬화는 to_dict() 뿐이고 내부 표현은 dataclass 다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Level(str, Enum):
    OBSERVATION = "OBSERVATION"
    METRIC = "METRIC"
    STATE = "STATE"


class Status(str, Enum):
    """값의 유효성. STALE 은 저장하지 않고 질의 때 나이로 판정한다."""
    OBSERVED = "OBSERVED"            # 층 1 -- 런타임이 직접 보고
    DERIVED = "DERIVED"              # 층 2 -- 관측에서 계산
    INFERRED = "INFERRED"            # 층 3 -- 규칙으로 해석
    UNKNOWN = "UNKNOWN"              # 판정할 근거가 없다. 0 · 거짓 · 정상이 **아니다**
    STALE = "STALE"                  # 값은 있으나 TTL 이 지났다 -- 지금 값으로 쓰지 마라
    INVALID = "INVALID"              # 더 나은 근거로 대체되었거나(예: 생각 추정 -> 최종값) 명시적으로 무효화
    NOT_APPLICABLE = "NOT_APPLICABLE"  # 이 배치 · 이 실체에는 정의되지 않는다(예: 예산이 설정되지 않음)

    @property
    def usable(self) -> bool:
        return self in (Status.OBSERVED, Status.DERIVED, Status.INFERRED)


class Basis(str, Enum):
    """규칙 · 지표의 인식 근거 -- 문턱이 어디서 왔나."""
    OBSERVED = "OBSERVED"                    # 관측값을 그대로 옮김
    DEFINITIONAL = "DEFINITIONAL"            # 정의에서 따라 나온다(비용 ≥ 예산 = 소진). 경험적 문턱이 없다
    RUNTIME_DECLARED = "RUNTIME_DECLARED"    # 경계를 런타임이 선언했다(자동 압축 문턱 · 종료 사유)
    OPERATOR_ASSUMED = "OPERATOR_ASSUMED"    # 운영자가 설정에 준 문턱 -- 잰 것이 아니다
    ESTIMATE = "ESTIMATE"                    # 런타임의 추정치(권위가 없다)
    PROVIDER_DECLARED = "PROVIDER_DECLARED"  # 공급자가 선언한 값(단가표 · retry-after)
    VALIDATED_EXPERIMENT = "VALIDATED_EXPERIMENT"  # 실험으로 확인한 문턱 · 계산(무엇으로 확인했는지 같이 적는다)
    EXTERNAL_LABEL = "EXTERNAL_LABEL"        # 외부 평가(숨은 시험 등)의 판정 -- 우리가 만든 점수가 아니다


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNTIMED = "UNTIMED"        # 근거에 시각이 없다(SWE-agent) -- 신선도를 판정할 수 없다
    PERMANENT = "PERMANENT"    # 끝난 일에 대한 사실(실행 종료) -- 시간이 지나도 낡지 않는다


class Lifecycle(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"          # 값이 바뀌었다(전이가 함께 남는다)
    REFRESH = "REFRESH"        # 같은 값, 새 근거
    STALE = "STALE"            # tick() 이 TTL 초과를 발견
    INVALIDATE = "INVALIDATE"
    RECOVER = "RECOVER"        # UNKNOWN · STALE · INVALID 에서 쓸 수 있는 값으로


class EntityType(str, Enum):
    AGENT = "agent"
    TASK = "task"
    RUNTIME = "runtime"
    TOOL = "tool"


@dataclass(frozen=True)
class Observation:
    id: str                    # "<run_id>/<kind>/<index>#<field>"
    entity_id: str
    field: str                 # 정준 이름(normalize.CANONICAL)
    value: Any
    reported_null: bool        # 런타임이 그 칸을 null 로 보고(봤다, 값이 null)
    observed_at: "float | None"
    time_base: "str | None"
    source: str                # cc_jsonl · cc_stream · sweagent · anthropic · openai · gemini
    basis: Basis = Basis.OBSERVED


@dataclass(frozen=True)
class Metric:
    id: str                    # "<entity>/<name>@<seq>"
    entity_id: str
    name: str
    value: Any
    status: Status             # DERIVED · UNKNOWN · INVALID
    basis: Basis
    inputs: tuple              # Observation 또는 Metric 의 id
    reason: str = ""
    computed_at: "float | None" = None


@dataclass(frozen=True)
class Evidence:
    ref: str                   # Metric 또는 Observation id
    level: Level
    name: str
    value: Any


@dataclass
class State:
    entity_id: str
    name: str
    value: Any
    status: Status
    basis: Basis
    rule_id: str
    rule_version: int
    config_version: str
    reason: str                # K8s Condition 의 reason 처럼 -- 왜 이 값인가(한 줄)
    evidence: tuple            # Evidence
    observed_at: "float | None"    # 근거 중 가장 늦은 관측 시각
    updated_at: "float | None"     # 마지막으로 다시 계산한 사건 시각
    since: "float | None"          # 이 값이 시작된 시각(마지막 전이)
    seq: int = 0                   # 다시 계산한 횟수 -- 결정성 확인용
    final: bool = False            # 끝난 일에 대한 사실(낡지 않는다)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["basis"] = self.basis.value
        d["evidence"] = [{"ref": e.ref, "level": e.level.value, "name": e.name, "value": e.value}
                         for e in self.evidence]
        return d


@dataclass(frozen=True)
class Transition:
    entity_id: str
    name: str
    previous: Any
    new: Any
    trigger: str               # 규칙의 reason
    rule_id: str
    evidence: tuple
    at: "float | None"
    seq: int


@dataclass(frozen=True)
class LifecycleEvent:
    entity_id: str
    name: str
    event: Lifecycle
    at: "float | None"
    detail: str = ""


@dataclass
class Relationship:
    subject: str
    predicate: str             # uses · executed_by · runs_on
    object: str
    first_at: "float | None"
    last_at: "float | None"
    evidence: list = field(default_factory=list)


@dataclass(frozen=True)
class Proposal:
    """LLM(또는 사람)의 해석 제안. **권위가 없다** -- 상태에 들어가지 않는다."""
    entity_id: str
    name: str
    suggested: Any
    author: str
    rationale: str
    at: "float | None"


@dataclass(frozen=True)
class StateView:
    """질의 결과 -- 값과 함께 유효성 · 신선도 · 근거 요약이 늘 붙는다."""
    entity_id: str
    name: str
    value: Any
    status: Status             # 저장 상태 또는 STALE
    freshness: Freshness
    age_ms: "float | None"
    basis: Basis
    rule: str
    reason: str
    evidence_refs: tuple
    since: "float | None"
