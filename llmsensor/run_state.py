"""L0 사건 -> Sensor 엔진 -> state-export, 한 번에 (baseline#3 CMD-S25 · BD-115 · BD-120).

    rs = from_l0(events)                 # L0 사건 목록, 또는 원장 경로(JSONL)
    rs.read("agent:<run>", "execution_health")      # state-export/2 read
    rs.subjects("<run>")                            # 역할 -> 실체
    rs.as_of("<run>") · rs.catalog() · rs.runs

같은 객체가 MS 런타임 VERIFY 의 `run_state` 이음매다(`.read(entity, state)` · `.subjects(run)` -- 오리 타입, MS 를 import 하지
않는다). Health `verify` 는 `subjects=rs.subjects(run)`, `reads=rs.read` 로 바로 받는다.

새 상태 · 규칙은 없다. 길은 eval/l1_on_l0.py 와 같다: 사건 -> 꼴 v3 레코드(Telemetry compat) + L0 묶기 -> 엔진 -> export.
돌려주는 것은 export 의 것 그대로다(JSON 으로 옮길 수 있는 새 사본).

**지금(now).** export `read` 는 `now` 를 받아 신선도를 잰다. 안 주면 그 실행에서 본 가장 늦은 관측 시각을 지금으로 쓴다 --
엔진은 시계를 읽지 않는다. MS 는 `read(entity, state)` 로만 부르므로, 판정 시각에 맞춘 신선도가 필요하면 만들 때
`clock=` (인자 없는 함수, 관측과 같은 시간 기준)을 준다. 사건은 한 번에 받는다 -- 더 받으려면 모든 사건으로 다시 만든다
(엔진은 레코드 id 로 멱등이라 자라는 레코드를 다시 받지 못한다).
"""
from __future__ import annotations

from pathlib import Path

from .state import DEFAULT_CONFIG, StateEngine, from_telemetry
from .state import export


class RunState:
    def __init__(self, engine: StateEngine, clock=None):
        self.engine, self.clock = engine, clock

    @property
    def runs(self) -> "list[str]":
        return sorted(self.engine.ledgers)

    def _now(self, now):
        return now if now is not None else (self.clock() if self.clock is not None else None)

    def read(self, entity: str, state: str, now=None) -> dict:
        return export.read(self.engine, entity, state, self._now(now))

    def subjects(self, run: str) -> dict:
        return export.subjects(self.engine, run)

    def as_of(self, run: str) -> dict:
        return export.as_of(self.engine, run)

    def catalog(self) -> dict:
        return export.catalog(self.engine)


def from_l0(events, config=DEFAULT_CONFIG, clock=None) -> RunState:
    """L0 사건 목록(또는 L0 원장 JSONL 경로) -> RunState. Telemetry(L0) 가 필요하다(필수 의존)."""
    from .telemetry.l0 import require
    require()
    from telemetry import ledger
    from telemetry.compat import to_sensor_records
    from .sensing.l0 import batches
    if isinstance(events, (str, Path)):
        events = ledger.read(events)
    events = list(events)
    E = StateEngine(config)
    E.ingest_all(from_telemetry(to_sensor_records(events)))
    E.ingest_all(batches(events))
    return RunState(E, clock)
