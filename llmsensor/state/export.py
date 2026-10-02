"""상태 내보내기 계약 -- 상태 층 **밖**(Decision Context · 정책 · 다른 저장소)이 이 엔진을 읽는 유일한 길.

    CONTRACT = "llmsensor.state-export/1"

엔진 안(current · view · reg · cfg · metrics …)은 바뀔 수 있다. 밖은 이 넷만 본다:

    catalog(E)                 상태 정의: 실체 종류 · 값 집합 · 근거 종류 · 규칙 id/판본 · TTL · 뜻 · 돕는 결정
    read(E, entity, name, now) 상태 하나(값 · 유효성 · 신선도 · 근거 참조 · 시각). 없거나 모르는 상태면 UNKNOWN
    subjects(E, run_id)        실행 하나의 역할 -> 실체(agent · task · runtime · tool 들)
    as_of(E, run_id)           그 실행에서 본 가장 늦은 관측 시각과 시각 기준(unix_ms · monotonic_ms · None)

돌려주는 것은 전부 JSON 으로 옮길 수 있는 기본 값의 새 사본이다 -- 받은 쪽이 고쳐도 엔진은 안 바뀐다.
원 텔레메트리 · 지표 값은 없다(근거는 지표 **id** 만). 판정기(verifier) · 참조 정책(policy) · 결정 문맥(decision)의 출력도 없다 --
이 계약은 "무엇이 참이라고 믿나" 만 내보낸다. LLM 제안(propose)은 상태가 아니므로 안 나온다.

뜻이 바뀌는 고침(칸 이름 · 값의 뜻 · 없앰)은 판본을 올린다(/2). 칸을 **더하는** 것은 같은 판본에서 한다.
읽는 쪽 예: cogito5170/DC 의 `SensorSource`. Sensor 는 그쪽을 import 하지 않는다.
"""
from __future__ import annotations

from .model import EntityType, Status
from .normalize import entity_id

CONTRACT = "llmsensor.state-export/1"
FIELDS = ("contract", "entity", "name", "value", "status", "freshness", "age_ms", "basis", "rule_id", "rule_version",
          "config_version", "evidence_refs", "reason", "observed_at", "since", "ttl_ms", "final")


def catalog(E) -> dict:
    rules = {}
    for name, r in sorted(E.reg.rules.items()):
        rules[name] = {"entity": r.entity.value, "values": list(r.values), "basis": r.basis.value, "rule_id": r.id,
                       "rule_version": r.version, "ttl_ms": E.cfg.ttl_ms.get(name), "meaning": r.meaning,
                       "decision": r.decision}
    return {"contract": CONTRACT, "config_version": E.cfg.version, "states": rules,
            "common_statuses": [s.value for s in Status]}


def read(E, entity: str, name: str, now=None) -> dict:
    rule = E.reg.rules.get(name)
    st = E.current.get((entity, name))
    if st is None:
        return {"contract": CONTRACT, "entity": entity, "name": name, "value": None, "status": Status.UNKNOWN.value,
                "freshness": "UNTIMED", "age_ms": None, "basis": rule.basis.value if rule else None,
                "rule_id": rule.id if rule else None, "rule_version": rule.version if rule else None,
                "config_version": E.cfg.version, "evidence_refs": [],
                "reason": "아직 계산되지 않았다" if rule else "정의되지 않은 상태",
                "observed_at": None, "since": None, "ttl_ms": E.cfg.ttl_ms.get(name), "final": False}
    sv = E.view(st, now)
    return {"contract": CONTRACT, "entity": entity, "name": name, "value": st.value, "status": sv.status.value,
            "freshness": sv.freshness.value, "age_ms": sv.age_ms, "basis": st.basis.value, "rule_id": st.rule_id,
            "rule_version": st.rule_version, "config_version": st.config_version,
            "evidence_refs": list(sv.evidence_refs), "reason": st.reason, "observed_at": st.observed_at,
            "since": st.since, "ttl_ms": E.cfg.ttl_ms.get(name), "final": bool(st.final)}


def subjects(E, run_id: str) -> dict:
    tools = sorted({e for (e, _n) in E.current if e.startswith(f"tool:{run_id}:")})
    return {"agent": entity_id(EntityType.AGENT, run_id), "task": entity_id(EntityType.TASK, run_id),
            "runtime": entity_id(EntityType.RUNTIME, run_id), "tool": tools}


def as_of(E, run_id: str) -> dict:
    L = E.ledgers.get(run_id)
    return {"contract": CONTRACT, "run_id": run_id, "at": L.last_at if L else None,
            "time_base": L.time_base if L else None}
