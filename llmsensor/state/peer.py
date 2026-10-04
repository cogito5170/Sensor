"""동료 세션의 메시지를 상태 층의 관측으로 받는다 -- CMD-NET2 · POL-3 (NETWORK.md 2.3 · 3.1).

메시지는 '세션 j 가 X 를 보냈다'는 관측된 사실(informs) + X(관측 참조 또는 의견)로 들어온다.
동료가 상태를 직접 쓰지 못한다: 값은 이 노드의 규칙만 바꾼다. 여기 함수는 State.value 를 한 번도 쓰지 않는다.
"""
from __future__ import annotations

from .model import EntityType

INFORMS = "informs"
CONTRADICTS = "contradicts"


def session_id(sid: str) -> str:
    p = EntityType.SESSION.value + ":"
    return sid if sid.startswith(p) else p + sid


def receive_message(E, sender: str, receiver: str, msg_id: str, at=None) -> bool:
    """session -> session `informs`(basis observed, 근거 = L0 msg_id). 같은 msg_id 는 한 번만 센다. 새로 기록했으면 True."""
    r = E.relationships.get((session_id(sender), INFORMS, session_id(receiver)))
    if r is not None and msg_id in r.evidence:
        return False
    E._relate(session_id(sender), INFORMS, session_id(receiver), at, msg_id)
    return True


def observe_peer(E, sender: str, ent: str, name: str, value, evidence_id: str, at=None) -> str:
    """같은 StateRef 에 대한 동료의 관측. 반환: 'duplicate' | 'consistent' | 'contradicts' | 'no_state'.
    값이 다르고 근거가 다르면 `contradicts` 관계를 남기고 불확실로 표시한다. 값은 덮어쓰지 않는다.
    같은 근거 id 가 여러 동료를 거쳐 와도 한 번만 센다."""
    key = (ent, name, evidence_id)
    seen = E.peer_evidence.get(key)
    if seen is not None:
        seen.add(session_id(sender))
        return "duplicate"
    E.peer_evidence[key] = {session_id(sender)}
    st = E.current.get((ent, name))
    if st is None:
        return "no_state"
    local = [e.ref for e in st.evidence]
    if evidence_id in local or value == st.value:
        return "consistent"
    E._relate(evidence_id, CONTRADICTS, local[0] if local else f"state:{ent}/{name}", at, evidence_id)
    E.uncertain.setdefault((ent, name), set()).add(evidence_id)
    return "contradicts"


def propose_peer(E, sender: str, ent: str, name: str, suggested, rationale: str = "", at=None):
    """동료의 의견 -- Proposal(author=session:<j>)로 보관만 한다. 상태는 그대로."""
    return E.propose(ent, name, suggested, session_id(sender), rationale, at)


def is_uncertain(E, ent: str, name: str) -> bool:
    return (ent, name) in E.uncertain
