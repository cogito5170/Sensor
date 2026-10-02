"""상태 내보내기 계약 -- 상태 층 **밖**(Decision Context · 정책 · 다른 저장소)이 이 엔진을 읽는 유일한 길.

    CONTRACT = "llmsensor.state-export/2"      (소유: DC 세션, baseline BD-56 · 유일한 소비자: cogito5170/DC SensorSource)

/1 -> /2 (2026-10-02, baseline CMD-D7):
    entity_ref  {type, scope, local} 를 더했다 -- 실체 id 의 꼴 `<유형>:<범위>:<지역>`(BD-32). scope = 실행 id(원천을 품을 수 있다,
                예 cc_stream:demo -- 불투명한 문자열로 다룬다), local = 도구 이름(agent · task · runtime 은 실행마다 하나라 null).
                `entity`(엔진의 id 문자열)는 그대로다 -- 엔진의 id 규칙은 Sensor 세션의 것이다
    time_base   상태마다 시각 기준(unix_ms · monotonic_ms · null)을 싣는다(BD-33). 모든 시각 칸은 ms
    reason      뺐다 -- 원 수치가 경계 밖으로 새지 않게(DC 도 결정 문맥에서 뺐다, BD-08). 사람이 읽을 까닭은 엔진의 explain()
    catalog     근거 종류 8 개(`bases`)와 시각 기준 값(`time_bases`)을 명시한다

/2 에 더함 (2026-10-02, baseline CMD-D16 · BD-108 · BD-110) -- 실행기의 행동 실체 `action:<실행>:<command_id>`(BD-32 · BD-99):
    entity_ref  `action:` 을 {type: "action", scope: <실행>, local: <command_id>} 로 가른다. 실행 id 도 command_id 도 `:` 를 품을 수
                있다(cc_stream:demo, Telemetry 기본 ref `<실행>/a<n>`) -- 접두 · 뒤 `:` 규칙으로는 못 가른다. 그래서 **엔진이 기억한 그
                실체의 실행**(`_ent_run`, Sensor S24)을 쓰고, 엔진이 모르는 실체면 아는 실행 id 가운데 가장 긴 접두를 쓴다.
                둘 다 없으면(엔진 없이 부른 entity_ref 등) scope · local 은 null 이다 -- 지어내지 않는다
    subjects    `"action": [그 실행의 행동 실체들]` -- tool 과 같은 꼴. 실체의 실행은 엔진이 기억한 것으로 고른다(접두로 고르면
                실행 `x` 가 실행 `x:y` 의 행동을 품는다)
    tool · agent · task · runtime 등 다른 실체의 출력은 그대로다. 칸 · 값의 뜻을 바꾸지 않고 더하는 고침이라 판본은 /2 그대로다

엔진 안(current · view · reg · cfg · metrics …)은 바뀔 수 있다. 밖은 이 넷만 본다:

    catalog(E)                 상태 정의: 실체 종류 · 값 집합 · 근거 종류 · 규칙 id/판본 · TTL · 뜻 · 돕는 결정
    read(E, entity, name, now) 상태 하나(값 · 유효성 · 신선도 · 근거 참조 · 시각). 없거나 모르는 상태면 UNKNOWN
    subjects(E, run_id)        실행 하나의 역할 -> 실체(agent · task · runtime · tool 들 · action 들) + scope(실행 id)
    as_of(E, run_id)           그 실행에서 본 가장 늦은 관측 시각과 시각 기준(unix_ms · monotonic_ms · None)
    entity_ref(entity[, E])    실체 id -> {type, scope, local} (action 은 엔진을 주어야 가른다)

돌려주는 것은 전부 JSON 으로 옮길 수 있는 기본 값의 새 사본이다 -- 받은 쪽이 고쳐도 엔진은 안 바뀐다.
원 텔레메트리 · 지표 값은 없다(근거는 지표 **id** 만). 판정기(verifier) · 참조 정책(policy) · 결정 문맥(decision)의 출력도 없다 --
이 계약은 "무엇이 참이라고 믿나" 만 내보낸다. LLM 제안(propose)은 상태가 아니므로 안 나온다.

뜻이 바뀌는 고침(칸 이름 · 값의 뜻 · 없앰)은 판본을 올린다(/2). 칸을 **더하는** 것은 같은 판본에서 한다.
읽는 쪽 예: cogito5170/DC 의 `SensorSource`. Sensor 는 그쪽을 import 하지 않는다.
"""
from __future__ import annotations

from .model import Basis, EntityType, Status
from .normalize import entity_id

CONTRACT = "llmsensor.state-export/2"
FIELDS = ("contract", "entity", "entity_ref", "name", "value", "status", "freshness", "age_ms", "basis", "rule_id",
          "rule_version", "config_version", "evidence_refs", "observed_at", "since", "time_base", "ttl_ms", "final")
TIME_BASES = ("unix_ms", "monotonic_ms", None)


def catalog(E) -> dict:
    rules = {}
    for name, r in sorted(E.reg.rules.items()):
        rules[name] = {"entity": r.entity.value, "values": list(r.values), "basis": r.basis.value, "rule_id": r.id,
                       "rule_version": r.version, "ttl_ms": E.cfg.ttl_ms.get(name), "meaning": r.meaning,
                       "decision": r.decision}
    return {"contract": CONTRACT, "config_version": E.cfg.version, "states": rules,
            "common_statuses": [s.value for s in Status], "bases": [b.value for b in Basis],
            "time_bases": list(TIME_BASES)}


def _action_run(E, entity: str, rest: str):
    """행동 실체의 실행 id -- 엔진이 기억한 것, 없으면 아는 실행 id 가운데 가장 긴 접두. 모르면 None."""
    run = E._ent_run.get(entity)
    if run is not None and rest.startswith(run + ":") and len(rest) > len(run) + 1:
        return run
    known = [r for r in E.ledgers if rest.startswith(r + ":") and len(rest) > len(r) + 1]
    return max(known, key=len) if known else None


def entity_ref(entity: str, E=None) -> dict:
    """엔진의 실체 id -> {type, scope, local} (BD-32). 도구: tool:<실행>:<도구>, 행동: action:<실행>:<command_id>,
    나머지: <유형>:<실행>. 행동은 엔진(E)이 있어야 가른다 -- 없거나 실행을 모르면 scope · local 이 null 이다."""
    kind, rest = entity.split(":", 1)
    if kind == EntityType.TOOL.value:
        scope, local = rest.rsplit(":", 1)
        return {"type": kind, "scope": scope, "local": local}
    if kind == EntityType.ACTION.value:
        run = _action_run(E, entity, rest) if E is not None else None
        return {"type": kind, "scope": run, "local": rest[len(run) + 1:] if run is not None else None}
    return {"type": kind, "scope": rest, "local": None}


def _time_base(E, entity: str):
    L = E.ledgers.get(entity_ref(entity, E)["scope"])
    return L.time_base if L else None


def read(E, entity: str, name: str, now=None) -> dict:
    rule = E.reg.rules.get(name)
    st = E.current.get((entity, name))
    if st is None:
        return {"contract": CONTRACT, "entity": entity, "entity_ref": entity_ref(entity, E), "name": name, "value": None,
                "status": Status.UNKNOWN.value, "freshness": "UNTIMED", "age_ms": None,
                "basis": rule.basis.value if rule else None, "rule_id": rule.id if rule else None,
                "rule_version": rule.version if rule else None, "config_version": E.cfg.version, "evidence_refs": [],
                "observed_at": None, "since": None, "time_base": _time_base(E, entity),
                "ttl_ms": E.cfg.ttl_ms.get(name), "final": False}
    sv = E.view(st, now)
    return {"contract": CONTRACT, "entity": entity, "entity_ref": entity_ref(entity, E), "name": name, "value": st.value,
            "status": sv.status.value, "freshness": sv.freshness.value, "age_ms": sv.age_ms, "basis": st.basis.value,
            "rule_id": st.rule_id, "rule_version": st.rule_version, "config_version": st.config_version,
            "evidence_refs": list(sv.evidence_refs), "observed_at": st.observed_at, "since": st.since,
            "time_base": _time_base(E, entity), "ttl_ms": E.cfg.ttl_ms.get(name), "final": bool(st.final)}


def subjects(E, run_id: str) -> dict:
    tools = sorted({e for (e, _n) in E.current if e.startswith(f"tool:{run_id}:")})
    actions = sorted({e for (e, _n) in E.current if e.startswith(f"{EntityType.ACTION.value}:") and E._ent_run.get(e) == run_id})
    return {"scope": run_id, "agent": entity_id(EntityType.AGENT, run_id), "task": entity_id(EntityType.TASK, run_id),
            "runtime": entity_id(EntityType.RUNTIME, run_id), "tool": tools, "action": actions}


def as_of(E, run_id: str) -> dict:
    L = E.ledgers.get(run_id)
    return {"contract": CONTRACT, "run_id": run_id, "at": L.last_at if L else None,
            "time_base": L.time_base if L else None}
