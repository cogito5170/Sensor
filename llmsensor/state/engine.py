"""상태 엔진 -- 관측 묶음을 받아 지표와 상태를 다시 계산하고, 이력 · 전이 · 생애 사건 · 관계를 남긴다.

결정론: 엔진은 시계를 읽지 않는다(시각은 관측에서, '지금' 은 질의 인자로). 무작위도 없다.
같은 관측 + 같은 설정 버전 + 같은 규칙 버전 -> 같은 상태(시험이 붙든다).

정책은 여기 없다. LLM 의 해석은 propose() 로만 들어오고 **상태를 바꾸지 않는다.**
"""
from __future__ import annotations

from . import export as _export
from .config import DEFAULT_CONFIG, StateConfig
from .metrics import Ledger, tool_metric_defs
from .model import (Basis, EntityType, Evidence, Freshness, Level, Lifecycle, LifecycleEvent, Proposal,
                    Relationship, State, StateView, Status, Transition)
from .normalize import entity_id
from .registry import REGISTRY

TOOL_RULE = "tool_execution_health"


class StateEngine:
    def __init__(self, config: StateConfig = DEFAULT_CONFIG, registry=REGISTRY):
        self.cfg, self.reg = config, registry
        self.ledgers: dict = {}
        self.observations: dict = {}
        self.metrics: dict = {}
        self.current: dict = {}             # (entity, name) -> State
        self.history: list = []             # State 사본(값이 바뀔 때마다)
        self.transitions: list = []
        self.lifecycle: list = []
        self.relationships: dict = {}
        self.proposals: list = []
        self._pending: dict = {}            # (entity, name) -> (후보 값, 연속 횟수)
        self.by_run: dict = {}              # run_id -> {(entity, name)} -- 실행 하나의 상태만 빠르게 찾으려고(뜻 없음)

    # ---------------- 받아들이기 ----------------
    def ingest(self, batch) -> bool:
        """멱등이다 -- 같은 레코드(record_id)를 두 번 받으면 두 번째는 버린다(스트림 재전송). 받았으면 True."""
        L = self.ledgers.setdefault(batch.run_id, Ledger(batch.run_id))
        if batch.record_id in L.seen:
            return False
        L.seen.add(batch.record_id)
        L.seq += 1
        L.time_base = L.time_base or batch.time_base
        L.source = L.source or batch.source
        if batch.at is not None:
            L.last_at = batch.at if L.last_at is None else max(L.last_at, batch.at)
        for o in batch.observations:
            self.observations[o.id] = o
        row = {o.field: o for o in batch.observations}
        if batch.kind == "model_call":
            L.calls.append(row)
        elif batch.kind == "tool_call":
            row["_tool"] = batch.tool
            L.tools.append(row)
            self._relate(entity_id(EntityType.AGENT, L.run_id), "uses",
                         entity_id(EntityType.TOOL, L.run_id, batch.tool), batch.at, batch.record_id)
        elif batch.kind == "run":
            L.run.update(row)
        elif batch.kind == "external":
            L.external.update(row)
        self._relate(entity_id(EntityType.TASK, L.run_id), "executed_by", entity_id(EntityType.AGENT, L.run_id),
                     batch.at, batch.record_id)
        self._relate(entity_id(EntityType.AGENT, L.run_id), "runs_on", entity_id(EntityType.RUNTIME, L.run_id),
                     batch.at, batch.record_id)
        self._evaluate(L, batch.at, batch.record_id)
        return True

    def ingest_all(self, batches) -> "StateEngine":
        for b in batches:
            self.ingest(b)
        return self

    def _relate(self, s, p, o, at, ev):
        r = self.relationships.get((s, p, o))
        if r is None:
            r = self.relationships[(s, p, o)] = Relationship(s, p, o, at, at)
        r.last_at = at if at is not None else r.last_at
        r.evidence.append(ev)

    # ---------------- 계산 ----------------
    def _metrics(self, L, defs, entity_for, at):
        M = {}
        for md in defs:
            ctx = {"entity": entity_for(md), "seq": L.seq, "at": at, "config": self.cfg}
            m = md.fn(L, ctx, M)
            M[md.name] = m
            self.metrics[m.id] = m
        return M

    def _evaluate(self, L, at, trigger):
        M = self._metrics(L, self.reg.metrics.values(), lambda md: entity_id(md.entity, L.run_id), at)
        for name, rule in self.reg.rules.items():
            if name == TOOL_RULE:
                continue
            self._apply(entity_id(rule.entity, L.run_id), rule, M, at, trigger, L.run_id)
        tools = sorted({t["_tool"] for t in L.tools if t.get("_tool")})
        rule = self.reg.rules[TOOL_RULE]
        for tool in tools:
            ent = entity_id(EntityType.TOOL, L.run_id, tool)
            Mt = self._metrics(L, tool_metric_defs(tool), lambda md, e=ent: e, at)
            self._apply(ent, rule, Mt, at, trigger, L.run_id)

    def _evidence_time(self, M, names):
        ts = []
        for n in names:
            m = M.get(n)
            for ref in (m.inputs if m else ()):
                o = self.observations.get(ref)
                if o is not None and o.observed_at is not None:
                    ts.append(o.observed_at)
                inner = self.metrics.get(ref)
                for r2 in (inner.inputs if inner else ()):
                    o2 = self.observations.get(r2)
                    if o2 is not None and o2.observed_at is not None:
                        ts.append(o2.observed_at)
        return max(ts) if ts else None

    def _apply(self, ent, rule, M, at, trigger, run_id=None):
        key = (ent, rule.state)
        if run_id is not None:
            self.by_run.setdefault(run_id, set()).add(key)
        prev = self.current.get(key)
        if prev is not None and prev.final:
            return                                       # 끝난 일에 대한 사실은 다시 계산하지 않는다
        res = rule.fn(M, prev.value if prev else None, self.cfg)
        ev = tuple(Evidence(M[n].id, Level.METRIC, n, M[n].value) for n in res.evidence if n in M)
        obs_at = self._evidence_time(M, res.evidence)
        # 흔들림 억제(Prometheus 'for' 와 같은 생각): 새 값이 min_consecutive 번 이어져야 바뀐다
        k = self.cfg.min_consecutive.get(rule.state, 1)
        if prev is not None and (res.value, res.status) != (prev.value, prev.status) and k > 1:
            cand, n = self._pending.get(key, (None, 0))
            n = n + 1 if cand == (res.value, res.status) else 1
            self._pending[key] = ((res.value, res.status), n)
            if n < k:
                prev.updated_at, prev.seq = at, prev.seq + 1
                return
        self._pending.pop(key, None)
        st = State(entity_id=ent, name=rule.state, value=res.value, status=res.status, basis=rule.basis,
                   rule_id=rule.id, rule_version=rule.version, config_version=self.cfg.version, reason=res.reason,
                   evidence=ev, observed_at=obs_at, updated_at=at, since=at, seq=(prev.seq + 1 if prev else 1),
                   final=res.final)
        if prev is None:
            self._life(ent, rule.state, Lifecycle.CREATE, at, f"{res.status.value} {res.value}")
            self.history.append(st)
        elif (prev.value, prev.status) == (res.value, res.status):
            st.since = prev.since
            self._life(ent, rule.state, Lifecycle.REFRESH, at)
        else:
            self.transitions.append(Transition(ent, rule.state, prev.value, res.value, res.reason, rule.id, ev, at,
                                               st.seq))
            ev_kind = Lifecycle.RECOVER if (not prev.status.usable and res.status.usable) else Lifecycle.UPDATE
            self._life(ent, rule.state, ev_kind, at, f"{prev.value} -> {res.value}")
            self.history.append(st)
        self.current[key] = st

    def _life(self, ent, name, ev, at, detail=""):
        self.lifecycle.append(LifecycleEvent(ent, name, ev, at, detail))

    # ---------------- 명시적 무효화 · 제안 ----------------
    def invalidate(self, ent, name, reason, at=None):
        st = self.current.get((ent, name))
        if st is None:
            raise KeyError((ent, name))
        self.transitions.append(Transition(ent, name, st.value, st.value, f"INVALIDATE: {reason}", st.rule_id,
                                           st.evidence, at, st.seq + 1))
        st.status, st.reason, st.updated_at, st.seq = Status.INVALID, f"무효화: {reason}", at, st.seq + 1
        self._life(ent, name, Lifecycle.INVALIDATE, at, reason)

    def propose(self, ent, name, suggested, author, rationale, at=None) -> Proposal:
        """LLM 등의 해석 제안 -- 보관만 한다. 상태 · 전이 · 생애 사건 어디에도 손대지 않는다."""
        p = Proposal(ent, name, suggested, author, rationale, at)
        self.proposals.append(p)
        return p

    # ---------------- 신선도 ----------------
    def _now(self, ent, now):
        if now is not None:
            return now
        run = ent.split(":", 1)[1].rsplit(":", 1)[0] if ent.startswith("tool:") else ent.split(":", 1)[1]
        L = self.ledgers.get(run)
        return L.last_at if L else None

    def _freshness(self, st, now):
        if st.final:
            return Freshness.PERMANENT, None
        if st.observed_at is None or now is None:
            return Freshness.UNTIMED, None
        age = now - st.observed_at
        ttl = self.cfg.ttl_ms.get(st.name)
        return (Freshness.STALE if ttl is not None and age > ttl else Freshness.FRESH), age

    def tick(self, now_by_run: dict) -> "list[LifecycleEvent]":
        """실행마다 '지금' 을 주면 TTL 을 넘긴 상태를 STALE 생애 사건으로 남긴다(값은 지우지 않는다)."""
        out = []
        for (ent, name), st in sorted(self.current.items()):
            run = ent.split(":", 1)[1].rsplit(":", 1)[0] if ent.startswith("tool:") else ent.split(":", 1)[1]
            if run not in now_by_run:
                continue
            fr, _ = self._freshness(st, now_by_run[run])
            already = any(e.entity_id == ent and e.name == name and e.event is Lifecycle.STALE and e.at == st.observed_at
                          for e in self.lifecycle[-200:])
            if fr is Freshness.STALE and not already:
                ev = LifecycleEvent(ent, name, Lifecycle.STALE, st.observed_at, f"TTL 초과 (now={now_by_run[run]})")
                self.lifecycle.append(ev)
                out.append(ev)
        return out

    # ---------------- 질의 ----------------
    def view(self, st: State, now=None) -> StateView:
        fr, age = self._freshness(st, self._now(st.entity_id, now))
        status = Status.STALE if fr is Freshness.STALE and st.status.usable else st.status
        return StateView(st.entity_id, st.name, st.value, status, fr, age, st.basis, f"{st.rule_id}", st.reason,
                         tuple(e.ref for e in st.evidence), st.since)

    def query(self, ent, names=None, now=None) -> "list[StateView]":
        out = []
        if names is None:
            for (e, n), st in sorted(self.current.items()):
                if e == ent:
                    out.append(self.view(st, now))
        else:           # 이름을 주면 바로 찾는다(예전 판은 저장소 전체를 정렬 -- 순서 · 결과는 같다)
            for n in sorted(set(names)):
                st = self.current.get((ent, n))
                if st is not None:
                    out.append(self.view(st, now))
        if names:
            have = {v.name for v in out}
            for n in names:
                if n not in have:      # 정의는 있는데 상태가 없으면 UNKNOWN 으로 답한다(K8s: 없음 = Unknown)
                    r = self.reg.rules.get(n)
                    out.append(StateView(ent, n, None, Status.UNKNOWN, Freshness.UNTIMED, None,
                                         r.basis if r else Basis.OBSERVED, r.id if r else "", "아직 계산되지 않았다",
                                         (), None))
        return out

    def explain(self, ent, name) -> dict:
        """상태 -> 규칙 -> 지표 -> 관측 의 사슬. 압축(상태)을 되돌릴 수 있어야 한다."""
        st = self.current[(ent, name)]
        rule = self.reg.rules[name]

        def metric_node(mid, depth=0):
            m = self.metrics.get(mid)
            if m is None or depth > 3:
                return {"id": mid}
            kids = []
            for i in m.inputs:
                if i in self.observations:
                    o = self.observations[i]
                    kids.append({"observation": o.id, "field": o.field, "value": o.value,
                                 "reported_null": o.reported_null, "observed_at": o.observed_at, "source": o.source,
                                 "basis": o.basis.value})
                else:
                    kids.append(metric_node(i, depth + 1))
            return {"metric": m.id, "name": m.name, "value": m.value, "status": m.status.value, "basis": m.basis.value,
                    "reason": m.reason, "inputs": kids}

        return {"state": st.to_dict(), "rule": {"id": rule.id, "version": rule.version, "basis": rule.basis.value,
                                                "meaning": rule.meaning},
                "config": {"version": self.cfg.version, "assumptions": self.cfg.assumptions()},
                "evidence": [metric_node(e.ref) for e in st.evidence],
                "transitions": [t for t in self.transitions if t.entity_id == ent and t.name == name]}

    def observation_ids(self, ent, name) -> set:
        """explain 사슬 끝의 관측 id 들 -- 되돌림 가능성 검사용."""
        out = set()

        def walk(n):
            if "observation" in n:
                out.add(n["observation"])
            for k in n.get("inputs", []):
                walk(k)
        for n in self.explain(ent, name)["evidence"]:
            walk(n)
        return out

    # ---------------- 내보내기 계약(상태 층 밖이 읽는 길) ----------------
    EXPORT_CONTRACT = _export.CONTRACT

    def state_catalog(self) -> dict:
        return _export.catalog(self)

    def export_state(self, ent, name, now=None) -> dict:
        return _export.read(self, ent, name, now)

    def subjects(self, run_id) -> dict:
        return _export.subjects(self, run_id)

    def as_of(self, run_id) -> dict:
        return _export.as_of(self, run_id)

    # ---------------- 결정성 ----------------
    def snapshot(self) -> dict:
        return {"current": {f"{e}|{n}": s.to_dict() for (e, n), s in sorted(self.current.items())},
                "transitions": [(t.entity_id, t.name, t.previous, t.new, t.rule_id, t.at, t.seq)
                                for t in self.transitions],
                "lifecycle": [(x.entity_id, x.name, x.event.value, x.at) for x in self.lifecycle]}
