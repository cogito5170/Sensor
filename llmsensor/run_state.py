"""L0 사건 -> Sensor 엔진 -> state-export, 한 번에 (baseline#3 CMD-S25 · BD-115 · BD-120) · 이어 받기 (CMD-SEN1 · BD-257).

    rs = from_l0(events)                 # L0 사건 목록, 또는 원장 경로(JSONL)
    rs.read("agent:<run>", "execution_health")      # state-export/2 read
    rs.subjects("<run>")                            # 역할 -> 실체
    rs.as_of("<run>") · rs.catalog() · rs.runs
    rs.extend(more_events)               # 새 사건만 넣는다 -- 전체를 다시 짓지 않는다

같은 객체가 MS 런타임 VERIFY 의 `run_state` 이음매다(`.read(entity, state)` · `.subjects(run)` -- 오리 타입, MS 를 import 하지
않는다). Health `verify` 는 `subjects=rs.subjects(run)`, `reads=rs.read` 로 바로 받는다.

새 상태 · 규칙은 없다. 길은 eval/l1_on_l0.py 와 같다: 사건 -> 꼴 v3 레코드(Telemetry compat) + L0 묶기 -> 엔진 -> export.
돌려주는 것은 export 의 것 그대로다(JSON 으로 옮길 수 있는 새 사본).

**지금(now).** export `read` 는 `now` 를 받아 신선도를 잰다. 안 주면 그 실행에서 본 가장 늦은 관측 시각을 지금으로 쓴다 --
엔진은 시계를 읽지 않는다. MS 는 `read(entity, state)` 로만 부르므로, 판정 시각에 맞춘 신선도가 필요하면 만들 때
`clock=` (인자 없는 함수, 관측과 같은 시간 기준)을 준다.

**이어 받기(extend, CMD-SEN1).** 훅처럼 도구 호출마다 상태를 다시 읽는 쪽이 세션 길이에 비례해 느려지지 않게 한다.

- 사건은 id 로 합친다. 새 id 는 더하고, 본 id 가 **내용이 바뀌어** 다시 오면(끝나지 않은 마지막 llm.response) 갈아 끼운다.
  그러니 매번 전체 사건 목록을 넘겨도, 새 사건만 넘겨도 된다.
- 합친 사건 전체로 레코드 · L0 묶음을 다시 짓는다(Telemetry compat · L0 묶기 -- 가볍다). 엔진에는 **새 묶음만 넣고**,
  **자란 묶음**(같은 record_id, 다른 내용 -- 뒤에 온 도구 결과가 tool_call 에 붙음, 실행 요약에 칸이 늚)은 갈아 끼운다
  (`StateEngine.replace`). 같은 묶음은 건너뛴다.
- 그다음 바뀐 실행마다 **한 번** 평가한다. 평가 시각은 전체를 다시 지었을 때 그 실행의 마지막 평가 시각(그 실행의 마지막 묶음)이다.
- 결과 -- 값 · 유효성 · 근거 시각(observed_at)은 전체를 다시 지은 것과 같다(시험: tests/test_run_state_extend.py, 무작위
  사건 흐름을 무작위로 자른다). 같지 않은 것: 전이 · 생애 사건 · `since` · 지표 id 의 seq 는 평가 횟수를 따른다 --
  묶음마다 평가하지 않으므로 그 사이의 이력이 없다.
- **그렇게 같으려면 규칙이 이력에 기대지 않아야 한다.** 기본 설정은 그렇다(끝난 값의 잠금은 줄지 않는 근거에서만 선다).
  운영자가 이력에 기대는 손잡이(`min_consecutive` 흔들림 억제 · `resource_bands` · `latency_slo` 띠)를 주면 이어 받기가
  같은 값을 보장하지 못하므로, extend 는 **전체를 다시 짓는다**(느리지만 맞다). `last_extend["mode"]` 가 무엇을 했는지 말한다.
- 이미 본 레코드가 새 판에서 사라지면(꼴이 바뀜) 역시 전체를 다시 짓는다 -- 엔진은 받은 것을 지우지 못한다.

**한 번 평가(evaluate="once").** `from_l0(..., evaluate="once")` 는 묶음마다가 아니라 다 넣은 뒤 실행마다 한 번 평가한다 --
처음 짓기를 제곱에서 선형으로 낮춘다. 값 · 유효성 · 근거 시각은 기본("each")과 같고(같은 조건), 이력만 없다. 기본은 "each" 다
(전이 · 생애 사건을 묶음마다 남기는 지금 그대로).
"""
from __future__ import annotations

from pathlib import Path

from .state import DEFAULT_CONFIG, StateEngine, from_telemetry
from .state import export


def _history_free(cfg) -> bool:
    """규칙 값이 평가 이력(앞 값 · 연속 횟수)에 기대지 않는 설정인가."""
    return not cfg.min_consecutive and cfg.resource_bands is None and cfg.latency_slo is None


def _last_by_run(bs) -> dict:
    """실행마다 마지막 묶음 -- 그 차례에서 그 실행의 마지막 평가를 일으키는 묶음."""
    last = {}
    for b in bs:
        last[b.run_id] = b
    return last


class RunState:
    def __init__(self, engine: StateEngine, clock=None):
        from .sensing.l0 import Binder
        self.engine, self.clock = engine, clock
        self._events: dict = {}          # 사건 id -> 사건 (처음 본 차례를 지킨다)
        self._raw: dict = {}             # record_id -> (compat 레코드, 묶음 시각) -- 바뀐 레코드만 다시 짓는다
        self._binder = Binder()          # L0 묶기 -- 실행마다 먹인 데까지의 상태
        self._fed: dict = {}             # 실행 -> 먹인 마지막 사건 seq
        self._snap: dict = {}            # 실행 -> (마지막 사건 seq, 그 사건을 먹이기 전 상태) -- 끝나지 않은 마지막 응답이 바뀔 때
        self.last_extend: "dict | None" = None

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

    # ---------------- 짓기 · 이어 받기 ----------------
    def _merge(self, events) -> dict:
        """사건을 id 로 합친다. 실행마다 **처음 바뀐(또는 새) 사건의 seq** 를 돌려준다 -- L0 묶음은 그 실행의 그 seq 까지의
        사건으로만 정해지므로(llmsensor/sensing/l0.Binder 는 실행마다 seq 차례로 쌓는다) 그 앞의 묶음은 그대로다."""
        first: dict = {}
        for ev in events:
            old = self._events.get(ev["id"])
            if old != ev:
                self._events[ev["id"]] = ev
                r = ev["run_id"]
                first[r] = ev["seq"] if r not in first else min(first[r], ev["seq"])
        return first

    def _records(self, only_changed: bool) -> "tuple[list, set]":
        """compat 레코드 -> 레코드 묶음(바뀐 것만, 또는 전부)과 이번에 본 record_id 들. compat 은 전체를 한 번 훑는다(가볍다)."""
        from telemetry.compat import to_sensor_records
        seen, raw = set(), {}

        def keep(rid, rec, at):
            seen.add(rid)
            raw[rid] = (rec, at)
            return not only_changed or self._raw.get(rid) != (rec, at)

        bs = list(from_telemetry(to_sensor_records(list(self._events.values())), keep))
        self._raw.update(raw)
        return bs, seen

    def _l0(self, first: "dict | None") -> list:
        """L0 묶음 -- first 가 None 이면 모든 실행을 처음부터, 아니면 바뀐 실행만 바뀐 자리부터 먹인다."""
        by_run: dict = {}
        for ev in self._events.values():
            if first is None or ev["run_id"] in first:
                by_run.setdefault(ev["run_id"], []).append(ev)
        out = []
        for run in sorted(by_run):
            evs = sorted(by_run[run], key=lambda e: e["seq"])
            start = None                                      # None = 처음부터
            if first is not None and run in self._fed:
                if first[run] > self._fed[run]:              # 뒤에 붙었다
                    start = first[run]
                elif run in self._snap and first[run] >= self._snap[run][0]:
                    self._binder.restore(run, self._snap[run][1])   # 끝나지 않은 마지막 사건이 바뀌었다 -- 그 앞으로 되감는다
                    start = self._snap[run][0]
            if start is None:
                self._binder.restore(run, None)
                todo = evs
            else:
                todo = [e for e in evs if e["seq"] >= start]
            for k, ev in enumerate(todo):
                if k == len(todo) - 1:
                    self._snap[run] = (ev["seq"], self._binder.snapshot(run))
                out.append(self._binder.feed(ev))
            if todo:
                self._fed[run] = todo[-1]["seq"]
        return out

    def _rebuild(self, evaluate: str):
        from .sensing.l0 import Binder
        self._raw, self._binder, self._fed, self._snap = {}, Binder(), {}, {}
        recs, _ = self._records(only_changed=False)
        l0 = self._l0(None)
        E = StateEngine(self.engine.cfg, self.engine.reg)
        if evaluate == "each":
            E.ingest_all(recs + l0)
        else:
            self._phases(E, recs, l0)
        self.engine = E
        return recs + l0

    def _phases(self, E, recs, l0) -> "tuple[int, int, set]":
        """두 차례로 넣고 차례마다 실행을 한 번 평가한다 -- 전체를 다시 지을 때의 차례(레코드 모두, 그다음 L0 묶음)와 같다.
        끝난 값의 잠금(완료 · liveness ENDED)은 레코드 차례의 평가에서 서므로, 그 차례를 지켜야 근거 시각까지 같다.
        받은 적 있는 record_id 는 갈아 끼우고(자란 레코드), 처음이면 넣는다."""
        new = replaced = 0
        touched: set = set()
        for phase in (recs, l0):
            hit = set()
            for b in phase:
                L = E.ledgers.get(b.run_id)
                if L is not None and b.record_id in L.seen:
                    E.replace(b, evaluate=False)
                    replaced += 1
                else:
                    E.ingest(b, evaluate=False)
                    new += 1
                hit.add(b.run_id)
            touched |= hit
            last = _last_by_run(phase)
            for run in sorted(touched if phase is l0 else hit):
                b = last.get(run) or _last_by_run(recs + l0)[run]
                E.evaluate_run(run, b.at, b.record_id)
        return new, replaced, touched

    def extend(self, events) -> "RunState":
        """새 사건을 넣는다(본 사건이 섞여 와도 된다). 값 · 유효성 · 근거 시각은 전체를 다시 지은 것과 같다(위 설명의 조건에서)."""
        if isinstance(events, (str, Path)):
            from telemetry import ledger
            events = ledger.read(events)
        first = self._merge(list(events))
        if not first:
            self.last_extend = {"mode": "unchanged", "new": 0, "replaced": 0, "runs": []}
            return self
        if not _history_free(self.engine.cfg):
            bs = self._rebuild("each")
            self.last_extend = {"mode": "rebuild:history_config", "new": len(bs), "replaced": 0,
                                "runs": sorted({b.run_id for b in bs})}
            return self
        known = set(self._raw)
        recs, seen = self._records(only_changed=True)
        if known - seen:                                      # 본 레코드가 사라졌다(꼴이 바뀜) -- 엔진은 지우지 못한다
            bs = self._rebuild("once")
            self.last_extend = {"mode": "rebuild:record_vanished", "new": len(bs), "replaced": 0,
                                "runs": sorted({b.run_id for b in bs})}
            return self
        l0 = self._l0(first)
        new, replaced, touched = self._phases(self.engine, recs, l0)
        self.last_extend = {"mode": "incremental", "new": new, "replaced": replaced, "runs": sorted(touched)}
        return self


def from_l0(events, config=DEFAULT_CONFIG, clock=None, evaluate: str = "each") -> RunState:
    """L0 사건 목록(또는 L0 원장 JSONL 경로) -> RunState. Telemetry(L0) 가 필요하다(필수 의존).
    evaluate: "each"(기본 -- 묶음마다 평가, 이력을 남긴다) | "once"(실행마다 한 번 -- 선형, 값은 같다)."""
    from .telemetry.l0 import require
    require()
    from telemetry import ledger
    if evaluate not in ("each", "once"):
        raise ValueError(f"evaluate 는 'each' 나 'once' 다 ({evaluate!r})")
    if isinstance(events, (str, Path)):
        events = ledger.read(events)
    rs = RunState(StateEngine(config), clock)
    rs._merge(list(events))
    rs._rebuild(evaluate if _history_free(config) else "each")
    return rs
