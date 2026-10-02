"""모형(Model) -- 무슨 상태가 있고 무엇을 뜻하나. 상태의 **현재 값**은 엔진에 있고, 여기는 정의만.

    REGISTRY.states        상태 정의(규칙에서): 이름 · 실체 · 값 집합 · 근거 · 입력 · 뜻 · 결정 · TTL
    REGISTRY.metrics       지표 정의
    REGISTRY.graph()       의존 그래프(관측 -> 지표 -> 상태)
    REGISTRY.candidates    **넣지 않은** 후보 상태와 까닭(§32 의 일곱 질문)
"""
from __future__ import annotations

from .metrics import METRICS


CANDIDATES = [   # (이름, 왜 넣지 않았나)
    ("reasoning_load", "생각 토큰이 많다 = 부하가 높다 의 문턱 근거가 없다. 생각 · 출력은 다른 정보(ρ 0.64)이지만 무엇을 뜻하는지 검증 안 됨. "
                       "지표 reasoning_tokens 로만 둔다"),
    ("context_growth_rate", "'빠르다' 의 문턱 근거가 없다. 지표 context_growth 로만 둔다(≡ cache_write, 회계 항등식)"),
    ("context_compaction_risk", "context_pressure 의 ABOVE_COMPACTION_THRESHOLD 와 같은 것 -- 중복"),
    ("context_budget_state", "context_pressure 와 같은 것 -- 중복"),
    ("cache_growth_state · step_growth_state", "cache_read ~ 걸음 번호 ρ 0.99 -- 같은 현상(맥락이 자란다). 따로 두지 않는다"),
    ("execution_latency · execution_stability", "지연이 '느리다' 의 문턱 근거가 없다. 시간 센서는 수집기 정의에 달렸다(앞 실험)"),
    ("tool.availability", "실패와 '쓸 수 없음' 을 관측으로 가르지 못한다(같은 is_error)"),
    ("tool.recent_failure", "tool_execution_health 의 UNRESOLVED_FAILURES 와 거의 같다 -- 중복"),
    ("progress_state = ACTIVE/SLOW", "활동(호출 수)은 진행이 아니다. 진행을 재는 검증된 근거가 없다"),
    ("timeout_state", "꼴 v3 의 timed_out(런타임 문구)으로 관측할 수 있게 되어 execution_interruption 이 맡는다 -- 따로 두지 않는다"),
    ("execution_state(합성 열거)", "completion_state · execution_health · execution_interruption · rate_limit_state 를 한 값으로 접으면 "
                                  "정보가 사라진다(t11: 도구 시간 초과, 실행은 정상 종료) -- docs/MS_SENSING_REVIEW.md C2"),
    ("provider_health", "runtime_reliability 와 같은 개념 -- HEALTHY 는 '관측 없음 ≠ 건강' 원칙에 어긋난다(리뷰 C4)"),
    ("quality_score", "외부 라벨 없이 수를 만들지 않는다 -- quality_state 는 외부 평가 라벨을 옮길 뿐"),
    ("token_budget_state", "토큰 예산 설정이 없다. 필요하면 resource_state 와 같은 꼴로 더한다"),
    ("interaction_state", "사람 말 · 턴 관측이 텔레메트리 꼴에 없다"),
    ("uncertainty_state", "저장하지 않는다 -- 질의 때 상태들의 유효성에서 투영한다(decision_context.uncertain)"),
    ("generation_state(stop_reason)", "멈춤 사유를 이름만 바꾼 상태가 된다. 한도에 잘린 것만 runtime_reliability 의 근거로 쓴다"),
]


class Registry:
    """센싱 팩을 조립한다. 기존 지표 · 규칙은 원래 순서 그대로 먼저(생애 사건 순서 보존), 새 것은 팩 순서로 뒤에."""

    def __init__(self):
        from ..sensing import BASELINE_ORDER, canonical_all, packs
        self.packs = packs()
        rules = {}
        for p in self.packs:
            for r in p.rules:
                if r.state in rules:
                    raise ValueError(f"상태 {r.state} 를 두 팩이 정의한다")
                rules[r.state] = r
        order = [n for n in BASELINE_ORDER if n in rules] + [r.state for p in self.packs for r in p.rules
                                                             if r.state not in BASELINE_ORDER]
        self.rules = {n: rules[n] for n in order}
        pack_metrics = {m.name: m for p in self.packs for m in p.metrics}
        lost = {m.name for m in METRICS} - set(pack_metrics)
        if lost:
            raise ValueError(f"어느 팩에도 묶이지 않은 기존 지표 {sorted(lost)}")
        self.metrics = {m.name: m for m in METRICS}
        for p in self.packs:
            for m in p.metrics:
                self.metrics.setdefault(m.name, m)
        self.canonical = canonical_all()
        self.candidates = CANDIDATES

    def pack_of(self, state: str) -> "str | None":
        return next((p.name for p in self.packs if any(r.state == state for r in p.rules)), None)

    def state_definition(self, name, config=None) -> dict:
        r = self.rules[name]
        ttl = (config.ttl_ms.get(name) if config else None)
        return {"id": name, "entity": r.entity.value, "value_type": "enum",
                "allowed_values": list(r.values) + ["UNKNOWN", "NOT_APPLICABLE"], "basis": r.basis.value,
                "dependencies": list(r.inputs), "rule": f"{r.id}", "version": r.version, "meaning": r.meaning,
                "decision_supported": r.decision, "ttl_ms": ttl}

    def graph(self) -> "list[tuple[str, str]]":
        """(from, to) 간선. 관측 이름은 'obs:', 지표 'metric:', 상태 'state:'."""
        e = []
        for m in self.metrics.values():
            for i in m.inputs:
                e.append((("metric:" if i in self.metrics else "obs:") + i, "metric:" + m.name))
        for r in self.rules.values():
            for i in r.inputs:
                e.append(("metric:" + i, "state:" + r.state))
        return sorted(set(e))

    def check(self) -> "list[str]":
        """정의가 서로 맞나 -- 없는 지표 · 관측을 가리키는 간선이 없어야 한다."""
        errs = []
        for a, b in self.graph():
            kind, name = a.split(":", 1)
            if kind == "obs" and name not in self.canonical:
                errs.append(f"{b}: 없는 관측 {name}")
            if kind == "metric" and name not in self.metrics:
                errs.append(f"{b}: 없는 지표 {name}")
        return errs

    def render_graph(self) -> str:
        """상태마다 상태 <- 지표 <- 관측 의 나무."""
        L = []
        for r in self.rules.values():
            L.append(f"state:{r.state}  [{r.id}, {r.basis.value}]")
            for i in r.inputs:
                m = self.metrics[i]
                L.append(f"  <- metric:{i}  [{m.basis.value}]")
                for j in m.inputs:
                    L.append(f"       <- {'metric' if j in self.metrics else 'obs'}:{j}")
        return "\n".join(L)


REGISTRY = Registry()
