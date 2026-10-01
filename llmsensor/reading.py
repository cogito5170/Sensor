"""센서 판독 하나.

네 값이다. **UNKNOWN 은 OK 가 아니다** -- 센서가 평가를 못 했다는 뜻이고, 융합에서 증거 0(LR=1)으로,
판정기에서는 '증거 없음' 으로 다룬다. "로그가 없으니 실패가 없다" 의 길을 막는다.

    OK       평가했고 성공 쪽 증거
    SUSPECT  평가했고 약한 실패 쪽 증거(증거 없는 주장 · 문턱 근처)
    FAULT    평가했고 실패 쪽 증거
    UNKNOWN  평가하지 못했다
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

OK, SUSPECT, FAULT, UNKNOWN = "OK", "SUSPECT", "FAULT", "UNKNOWN"
STATUSES = (OK, SUSPECT, FAULT, UNKNOWN)


@dataclass
class Reading:
    sensor: str                 # execution | constraint | consistency | behavior | outcome
    status: str
    why: str = ""
    value: "float | None" = None   # 센서마다 뜻이 다른 연속값(실패 비율 · 강건 z 등). 없으면 None
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"status {self.status!r} not in {STATUSES}")

    def to_dict(self) -> dict:
        return asdict(self)


def worst(readings: "list[Reading]") -> str:
    """한 센서가 여러 하위 판독을 낼 때 합치는 규칙: FAULT > SUSPECT > OK > UNKNOWN.
    하나라도 평가됐으면 UNKNOWN 이 아니다."""
    st = {r.status for r in readings}
    for s in (FAULT, SUSPECT, OK):
        if s in st:
            return s
    return UNKNOWN
