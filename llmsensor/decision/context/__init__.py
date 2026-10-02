"""Decision Context -- "이번 결정에 어떤 상태가 필요한가". 상태 저장소 -> Select -> Filter -> Validate -> Project -> Freeze.

    System State     = 무슨 일이 일어나고 있나        (llmsensor.state)
    Decision Context = 이 결정에 무엇이 중요한가        (여기)
    LLM Context      = LLM 이 무엇을 볼까             (Context Policy 의 일 -- 여기서 만들지 않는다)

- 목적(purpose)마다 필요한 상태가 다르다 -- 목적 표(PURPOSES)에 적는다.
- 원 텔레메트리 · 지표 값 · 이유 문자열을 넣지 않는다. 상태 값 · 유효성 · 시각 · 규칙 · 근거 참조만.
- 행동은 **고르지 않는다.** available_actions 는 사실(실행이 끝났나 · 설정된 공급자 수 · 런타임 능력)로 본 '가능한 것' 뿐.
- 제약(constraints)은 넘겨줄 뿐 평가하지 않는다. 목표('비용을 줄여라')는 받지 않는다 -- 정책의 일.
- 만든 뒤에는 얼어 있다. 상태 저장소가 바뀌어도 그대로다. 근거 사슬도 얼릴 때 함께 떠 둔다 -> explain(context_id).
- 결정론: 같은 상태 + 같은 목적 + 같은 as_of -> 같은 context_id(내용의 해시).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from ...state.model import EntityType, Freshness, Status
from ...state.normalize import entity_id

A, T, R = EntityType.AGENT, EntityType.TASK, EntityType.RUNTIME


@dataclass(frozen=True)
class Need:
    entity: EntityType
    state: str
    required: bool


@dataclass(frozen=True)
class Purpose:
    name: str
    question: str
    needs: tuple
    actions: tuple


PURPOSES = {
    "manage_context": Purpose(
        "manage_context", "다음 모형 호출 전에 맥락을 어떻게 다룰까",
        (Need(A, "context_pressure", True), Need(A, "execution_interruption", False)),
        ("KEEP_CONTEXT", "REDUCE_CONTEXT", "COMPACT_CONTEXT")),
    "select_provider": Purpose(
        "select_provider", "다음 요청을 어느 공급자로 보낼까",
        (Need(R, "runtime_reliability", True), Need(R, "rate_limit_state", True), Need(A, "latency_state", False),
         Need(A, "resource_state", False), Need(A, "resource_pressure", False)),
        ("STAY_PROVIDER", "SWITCH_PROVIDER", "WAIT")),
    "continue_or_stop": Purpose(
        "continue_or_stop", "이 실행을 이어갈까 · 다시 할까 · 멈출까",
        (Need(T, "completion_state", True), Need(A, "execution_health", True), Need(A, "execution_interruption", False),
         Need(T, "progress_state", False), Need(A, "resource_state", False), Need(T, "quality_state", False)),
        ("CONTINUE", "RETRY", "STOP", "ESCALATE")),
    "optimize_llm_request": Purpose(
        "optimize_llm_request", "다음 LLM 요청을 어떻게 낼까(맥락 · 공급자 · 재시도)",
        (Need(A, "context_pressure", True), Need(A, "execution_health", False), Need(A, "execution_interruption", False),
         Need(A, "latency_state", False), Need(R, "rate_limit_state", False), Need(R, "runtime_reliability", False),
         Need(A, "resource_state", False)),
        ("KEEP_CONTEXT", "REDUCE_CONTEXT", "COMPACT_CONTEXT", "SWITCH_PROVIDER", "RETRY", "STOP")),
}

CONSTRAINT_KEYS = {"max_cost_usd": (int, float), "max_latency_ms": (int, float), "required_capabilities": (tuple,),
                   "permission_requirements": (tuple,)}
ENDED = ("ENDED_NORMALLY", "ENDED_BY_LIMIT", "ENDED_WITH_ERROR")


@dataclass(frozen=True)
class StateView:
    entity: str
    name: str
    value: object
    status: str
    freshness: str
    observed_at: "float | None"
    age_ms: "float | None"
    ttl_ms: "float | None"
    basis: str
    rule_id: str
    rule_version: int
    evidence_refs: tuple
    usable: bool                 # INFERRED/DERIVED/OBSERVED 이고 STALE 이 아니다(또는 정책이 낡음을 허락했다)
    stale_allowed: bool = False


@dataclass(frozen=True)
class DecisionContext:
    context_id: str
    purpose: str
    run_id: str
    created_at: "float | None"   # 사건 시각(as_of) -- 벽시계가 아니다
    states: tuple                # StateView
    omitted: tuple               # (이름, 까닭) -- 거른 것
    constraints: tuple           # (키, 값)
    available_actions: tuple
    validity: str                # VALID · DEGRADED · INVALID
    validity_reasons: tuple
    config_version: str
    _provenance: str = field(repr=False, default="")   # 얼린 근거 사슬(JSON 문자열 -- 바꿀 수 없다)

    def get(self, name) -> "StateView | None":
        return next((s for s in self.states if s.name == name), None)

    def value(self, name, allow_stale: bool = False):
        """정책용 접근자. 쓸 수 없는 상태(UNKNOWN · STALE · INVALID)는 None. STALE 은 정책이 명시적으로 허락할 때만."""
        s = self.get(name)
        if s is None:
            return None
        if s.usable or (allow_stale and s.status == Status.STALE.value):
            return s.value
        return None

    def explain(self) -> dict:
        return json.loads(self._provenance)


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _available(purpose: Purpose, views: dict, capabilities: dict) -> tuple:
    """사실로 본 '가능한 행동'. 선호가 아니라 전제 조건만 본다."""
    comp = views.get("completion_state")
    ended = comp is not None and comp.usable and comp.value in ENDED
    out = []
    for a in purpose.actions:
        if a == "COMPACT_CONTEXT" and not capabilities.get("compaction", False):
            continue                              # 런타임이 압축을 할 수 있다고 선언하지 않았으면 불가능
        if a == "SWITCH_PROVIDER" and capabilities.get("providers", 1) < 2:
            continue                              # 다른 공급자가 설정되지 않았으면 불가능
        if a in ("CONTINUE", "RETRY", "STOP") and ended:
            continue                              # 이미 끝난 실행
        out.append(a)
    return tuple(out)


class ContextBuilder:
    def __init__(self, engine, capture_provenance: bool = True):
        self.engine = engine
        self.capture = capture_provenance

    def build(self, run_id, purpose: str, now=None, constraints=None, capabilities=None,
              allow_stale=()) -> DecisionContext:
        if purpose not in PURPOSES:
            raise KeyError(f"모르는 목적 {purpose!r} -- PURPOSES 에 먼저 정의한다")
        P = PURPOSES[purpose]
        E, reg = self.engine, self.engine.reg
        cons = []
        for k, v in sorted((constraints or {}).items()):
            if k not in CONSTRAINT_KEYS:
                raise ValueError(f"제약 {k!r} 은 받지 않는다 -- 목표 · 선호는 정책의 일이다")
            if not isinstance(v, CONSTRAINT_KEYS[k]):
                raise TypeError(f"제약 {k} 의 꼴이 {CONSTRAINT_KEYS[k]} 가 아니다")
            cons.append((k, v))
        views, omitted, problems, prov = {}, [], [], {}
        for need in P.needs:                                            # Select
            ent = entity_id(need.entity, run_id)
            if need.state not in reg.rules:
                problems.append(f"{need.state}: 정의되지 않은 상태")
                continue
            sv = E.query(ent, [need.state], now)[0]
            if sv.status is Status.NOT_APPLICABLE and not need.required:  # Filter
                omitted.append((need.state, "NOT_APPLICABLE"))
                continue
            rule = reg.rules[need.state]
            stale_ok = need.state in allow_stale and sv.status is Status.STALE
            usable = sv.status.usable and sv.freshness is not Freshness.STALE    # Validate
            st = E.current.get((ent, need.state))
            views[need.state] = StateView(                                # Project
                ent, need.state, sv.value, sv.status.value, sv.freshness.value, st.observed_at if st else None,
                sv.age_ms, E.cfg.ttl_ms.get(need.state), sv.basis.value, rule.id, rule.version, sv.evidence_refs,
                usable or stale_ok, stale_ok)
            if need.required and not (usable or stale_ok):
                problems.append(f"{need.state}: {sv.status.value}")
            if self.capture and st is not None:
                ex = E.explain(ent, need.state)
                ex["transitions"] = [asdict(t) for t in ex["transitions"]]
                prov[need.state] = ex
        undefined = any("정의되지 않은" in p for p in problems)
        validity = "INVALID" if undefined else ("DEGRADED" if problems else "VALID")
        avail = _available(P, views, capabilities or {})
        states = tuple(views[n.state] for n in P.needs if n.state in views)
        as_of = E._now(entity_id(A, run_id), now)
        body = {"purpose": purpose, "run": run_id, "as_of": as_of, "states": [asdict(s) for s in states],
                "omitted": omitted, "constraints": cons, "actions": list(avail), "validity": validity,
                "config": E.cfg.version}
        prov_doc = {"context": body, "chains": prov, "registry_rules": {n: reg.rules[n].id for n in views}}
        return DecisionContext(                                          # Freeze
            _digest(body), purpose, run_id, as_of, states, tuple(omitted), tuple(cons), avail, validity,
            tuple(problems), E.cfg.version, json.dumps(prov_doc, ensure_ascii=False, default=str, sort_keys=True))


class ContextStore:
    """얼린 결정 문맥 보관 -- explain(context_id) 로 그때의 근거 사슬을 다시 낸다(상태 저장소가 그 뒤 바뀌어도)."""

    def __init__(self):
        self._d: dict = {}

    def put(self, ctx: DecisionContext) -> str:
        self._d.setdefault(ctx.context_id, ctx)
        return ctx.context_id

    def get(self, context_id) -> DecisionContext:
        return self._d[context_id]

    def explain(self, context_id) -> dict:
        return self._d[context_id].explain()
