"""CMD-S25 (BD-115 · BD-120): L0 사건 -> 엔진 -> state-export 편의 함수 · MS `run_state` 어댑터.

    대조       from_l0 의 출력 = 엔진 · export 를 하나씩 부른 결과(사건 목록 · 원장 경로 둘 다)
    VERIFY     `$run.agent` 사후조건을 이 어댑터로 Health `verify` 가 판정한다 -- VERIFIED · NOT_VERIFIED
               (health · action 이 옆 저장소 ../health · ../action 에 있을 때만. 없으면 건너뛴다 -- 선택 의존)
"""
import importlib
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path

from llmsensor.run_state import RunState, from_l0
from llmsensor.telemetry.l0 import require

require()
from telemetry import ledger  # noqa: E402
from telemetry.compat import to_sensor_records  # noqa: E402
from telemetry.hashing import Hasher  # noqa: E402
from telemetry.ledger import MemorySink  # noqa: E402
from telemetry.recorder import Recorder  # noqa: E402

from llmsensor.sensing.l0 import batches  # noqa: E402
from llmsensor.state import StateEngine, export, from_telemetry  # noqa: E402

RUN = "ms:r1"
T0 = 1_790_000_000_000          # 명령 발행(unix_ms)
WIN = 60_000


def recorder(start):
    clock = itertools.count(start, 1000)
    mono = itertools.count(0, 10)
    sink = MemorySink()
    return Recorder(RUN, sink, source="inproc:ms", wall=lambda: next(clock), mono=lambda: next(mono),
                    hasher=Hasher(b"k" * 32)), sink


def events(errors, start=T0 + 1_000):
    """같은 겨냥(Bash pytest)을 errors 의 차례대로 실행한 실행 하나 + 행동 하나."""
    rec, sink = recorder(start)
    for i, err in enumerate(errors):
        rec.llm_response(i, "anthropic", usage={"input_tokens": 1, "output_tokens": 1})
        with rec.tool("Bash", {"command": "pytest -x"}, call_index=i) as t:
            t.result(is_error=err)
    with rec.action("RETURN", action_ref="cmd-1", args={}) as a:
        a.result(is_error=False)
    return sink.events


def manual(evs):
    E = StateEngine()
    E.ingest_all(from_telemetry(to_sensor_records(evs)))
    E.ingest_all(batches(evs))
    return E


class SameAsByHand(unittest.TestCase):
    def _same(self, rs, evs):
        E = manual(evs)
        self.assertEqual(rs.runs, [RUN])
        self.assertEqual(sorted(rs.engine.current), sorted(E.current))
        for (ent, name) in E.current:
            self.assertEqual(rs.read(ent, name), export.read(E, ent, name), (ent, name))
        self.assertEqual(rs.read(f"agent:{RUN}", "no_such_state"), export.read(E, f"agent:{RUN}", "no_such_state"))
        self.assertEqual(rs.subjects(RUN), export.subjects(E, RUN))
        self.assertEqual(rs.as_of(RUN), export.as_of(E, RUN))
        self.assertEqual(rs.catalog(), export.catalog(E))

    def test_events(self):
        evs = events([True, False])
        self._same(from_l0(evs), evs)

    def test_ledger_path(self):
        evs = events([True])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l0.jsonl"
            ledger.write(p, evs)
            self._same(from_l0(p), evs)
            self._same(from_l0(str(p)), evs)

    def test_subjects_carry_action_and_scope(self):
        s = from_l0(events([False])).subjects(RUN)
        self.assertEqual((s["scope"], s["agent"], s["action"]), (RUN, f"agent:{RUN}", [f"action:{RUN}:cmd-1"]))

    def test_clock_is_used_only_when_now_is_not_given(self):
        rs = from_l0(events([False]), clock=lambda: T0 + 3_600_000)
        a = rs.read(f"agent:{RUN}", "execution_health")
        self.assertEqual(a["freshness"], "STALE")                            # TTL 10 분을 넘긴 시계
        b = rs.read(f"agent:{RUN}", "execution_health", now=T0 + 10_000)
        self.assertEqual(b["freshness"], "FRESH")
        self.assertEqual(RunState(rs.engine).read(f"agent:{RUN}", "execution_health")["freshness"], "FRESH")


def _siblings():
    root = Path(__file__).resolve().parents[1].parent
    paths = [os.environ.get("LLMSENSOR_HEALTH_PATH", str(root / "health")),
             os.environ.get("LLMSENSOR_ACTION_PATH", str(root / "action"))]
    for p in paths:
        if Path(p).is_dir() and p not in sys.path:
            sys.path.append(p)
    try:
        h, a = importlib.import_module("health"), importlib.import_module("action")
    except ImportError:
        return None
    return (h, a) if getattr(h, "SCHEMA", None) == "verification-record/1" and hasattr(a, "ActionCommand") else None


HA = _siblings()
POST = ({"entity": "$run.agent", "pred": ["execution_health", "!=", "UNRESOLVED_FAILURES"]},)


@unittest.skipUnless(HA, "옆에 health · action 이 없다(../health · ../action, LLMSENSOR_HEALTH_PATH · LLMSENSOR_ACTION_PATH)")
class HealthVerify(unittest.TestCase):
    """MS Verifier 가 하는 그대로: subjects = run_state.subjects(run), reads = run_state.read."""

    def verdict(self, rs, at):
        health, action = HA
        cmd = action.ActionCommand(intent_id="int-0123456789abcdef", decision_ref="dec-1", action="retry_tool",
                                   target=f"tool:{RUN}:Bash", args={}, issued_at=T0, deadline=None)
        return health.verify(cmd, run=RUN, subjects=rs.subjects(RUN), spec="retry_tool@1", postcondition=POST,
                             window_ms=WIN, reads=rs.read, evaluated_at=at)

    def test_verified(self):
        rs = from_l0(events([True, False]), clock=lambda: T0 + 20_000)      # 실패 뒤 회복 -> RECOVERED_FAILURES
        self.assertEqual(rs.read(f"agent:{RUN}", "execution_health")["value"], "RECOVERED_FAILURES")
        r = self.verdict(rs, T0 + 20_000)
        self.assertEqual((r.result, r.reason), ("VERIFIED", "MET"))
        self.assertEqual(r.evidence[0]["entity"], f"agent:{RUN}")
        self.assertEqual(r.evidence[0]["time_base"], "unix_ms")

    def test_not_verified_at_close(self):
        end = T0 + WIN + 1
        rs = from_l0(events([True]), clock=lambda: end)                     # 미해결 실패
        self.assertEqual(rs.read(f"agent:{RUN}", "execution_health")["value"], "UNRESOLVED_FAILURES")
        r = self.verdict(rs, end)
        self.assertEqual((r.result, r.reason), ("NOT_VERIFIED", "UNMET_AT_CLOSE"))

    def test_pending_while_open(self):
        rs = from_l0(events([True]), clock=lambda: T0 + 20_000)
        self.assertEqual(self.verdict(rs, T0 + 20_000).result, "PENDING")

    def test_observation_before_command_is_not_evidence(self):
        rs = from_l0(events([False], start=T0 - 30_000), clock=lambda: T0 + WIN + 1)
        r = self.verdict(rs, T0 + WIN + 1)
        self.assertEqual((r.result, r.reason), ("UNKNOWN", "NO_POST_OBSERVATION"))

    def test_stale_read_is_not_usable(self):
        late = T0 + WIN + 3_600_000
        rs = from_l0(events([False]), clock=lambda: late)
        r = self.verdict(rs, late)
        self.assertEqual((r.result, r.reason), ("UNKNOWN", "NOT_USABLE"))


if __name__ == "__main__":
    unittest.main()
