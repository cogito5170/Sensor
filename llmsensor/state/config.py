"""운영자 설정 -- **가정이 든 값은 전부 여기에** 있고, 상태마다 config_version 이 남는다.

기본 설정(DEFAULT_CONFIG)은 경험적 근거가 없는 문턱을 **하나도 주지 않는다**: 예산 없음, 압력 띠 없음, 정체 문턱 없음.
그래서 그 문턱에 기대는 상태는 기본에서 NOT_APPLICABLE 이나 UNKNOWN 이다. TTL 은 예외적으로 기본값이 있다 -- 없으면
낡은 상태를 지금 값처럼 쓰게 되기 때문이다. 그 기본 TTL 도 **잰 값이 아니다**(OPERATOR_ASSUMED).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Band:
    """띠 하나. enter 이상이면 들어가고, 이미 들어와 있으면 exit 밑으로 내려가야 나간다(흔들림 억제)."""
    label: str
    enter: float
    exit: float

    def __post_init__(self):
        if self.exit > self.enter:
            raise ValueError(f"{self.label}: exit({self.exit}) > enter({self.enter}) -- 흔들림 억제가 거꾸로다")


@dataclass(frozen=True)
class StateConfig:
    version: str = "default-v1"
    # TTL(ms) -- 근거의 마지막 관측 뒤 이만큼 지나면 STALE. None 이면 낡음을 판정하지 않는다(질의에 나이는 늘 붙는다)
    ttl_ms: dict = field(default_factory=lambda: {
        "context_pressure": 10 * 60_000, "execution_health": 10 * 60_000, "tool_execution_health": 10 * 60_000,
        "completion_state": 10 * 60_000, "progress_state": 10 * 60_000, "resource_state": 10 * 60_000,
        "resource_pressure": 10 * 60_000, "rate_limit_state": 5 * 60_000, "runtime_reliability": 10 * 60_000,
        "liveness_state": 10 * 60_000,
    })
    # 아래는 전부 OPERATOR_ASSUMED. 기본은 없음
    cost_budget_usd: "float | None" = None
    resource_bands: "tuple | None" = None          # (Band, ...) 오름차순, 비용/예산 비율
    stall_repeat_threshold: "int | None" = None    # 같은 (도구, 인자)가 이 횟수 이상 -> STALLED 후보
    min_consecutive: dict = field(default_factory=dict)   # 상태 이름 -> 새 값이 이 횟수 이어져야 전이(Prometheus 'for')
    context_window_override: "int | None" = None   # 런타임이 창을 안 주면(Claude Code JSONL) 문서 값으로 채운다
    # 지연 SLO -- {"metric": "call_latency"|"first_chunk_latency"|"tool_latency", "percentile": "p50"|"p95"|"p99",
    #             "bands": (Band("ELEVATED", ..), Band("DEGRADED", ..))}. 없으면 latency_state 는 NOT_APPLICABLE
    latency_slo: "dict | None" = None
    # liveness 의 무음 문턱(ms) -- 차례가 열려 있는데 이만큼 아무 사건도 없으면 STALLED. 없으면 ACTIVE/STALLED 를 내지 않는다
    # (F´ Svc::Health: 핑 timeout 은 포트마다 운영자 설정 -- 관측된 heartbeat 간격은 '선언' 이 아니다)
    liveness_timeout_ms: "int | None" = None

    def with_(self, **kw) -> "StateConfig":
        return replace(self, **kw)

    def assumptions(self) -> dict:
        """이 설정이 담은 가정들 -- 상태 설명에 붙인다."""
        a = {"ttl_ms": dict(self.ttl_ms)}
        for k in ("cost_budget_usd", "resource_bands", "stall_repeat_threshold", "context_window_override",
                  "latency_slo", "liveness_timeout_ms"):
            v = getattr(self, k)
            if v is not None:
                a[k] = v
        if self.min_consecutive:
            a["min_consecutive"] = dict(self.min_consecutive)
        return a


DEFAULT_CONFIG = StateConfig()
