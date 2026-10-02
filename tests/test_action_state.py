"""S6 action_state · 실행 지표의 action.* 읽기 (baseline#3 CMD-S24 · BD-108).

사건은 Telemetry 의 Recorder 로 짓는다 -- MS 실행기가 낼 꼴 그대로다(dispatch 만 · 쌍 · 오류 · is_error 못 봄).
"""
import itertools
import unittest

from llmsensor.telemetry.l0 import require

require()
from telemetry.compat import to_sensor_records  # noqa: E402
from telemetry.hashing import Hasher  # noqa: E402
from telemetry.ledger import MemorySink  # noqa: E402
from telemetry.recorder import Recorder  # noqa: E402

from llmsensor.sensing.l0 import batches  # noqa: E402
from llmsensor.state import REGISTRY, Status, StateEngine, from_telemetry  # noqa: E402
from llmsensor.state.model import Freshness, Lifecycle  # noqa: E402

RUN = "ms:r1"
KEY = b"k" * 32


def recorder(run=RUN):
    clock = itertools.count(1_790_000_000_000, 1000)
    mono = itertools.count(0, 10)
    sink = MemorySink()
    return Recorder(run, sink, source="inproc:ms", wall=lambda: next(clock), mono=lambda: next(mono),
                    hasher=Hasher(KEY)), sink


def engine(events):
    E = StateEngine()
    E.ingest_all(from_telemetry(to_sensor_records(events)))
    E.ingest_all(batches(events))
    return E


def state(E, ref, run=RUN):
    return E.current.get((f"action:{run}:{ref}", "action_state"))


def metric(E, name, run=RUN):
    ms = [m for i, m in E.metrics.items() if i.startswith(f"agent:{run}/{name}@")]
    return max(ms, key=lambda m: int(str(m.id.rsplit("@", 1)[1]).split("+")[0]))


class ActionState(unittest.TestCase):
    def test_pair_completed(self):
        rec, sink = recorder()
        with rec.action("RETURN", decision_ref="d1", action_ref="cmd-1", args={"x": 1}) as a:
            a.result(is_error=False, exit_code=0)
        s = state(engine(sink.events), "cmd-1")
        self.assertEqual((s.value, s.status), ("COMPLETED", Status.INFERRED))
        self.assertIn("효과를 판정한 것은 아니다", s.reason)

    def test_dispatch_only_started(self):
        rec, sink = recorder()
        with rec.action("RETURN", action_ref="cmd-1") as a:
            mid = list(sink.events)                       # 블록 안 -- action.result 전
            a.result(is_error=False)
        s = state(engine(mid), "cmd-1")
        self.assertEqual((s.value, s.status, s.basis.value), ("STARTED", Status.INFERRED, "OBSERVED"))

    def test_error_failed(self):
        rec, sink = recorder()
        with rec.action("RETRY", action_ref="cmd-2") as a:
            a.result(is_error=True, exit_code=2)
        self.assertEqual(state(engine(sink.events), "cmd-2").value, "FAILED")

    def test_exception_is_failed(self):
        rec, sink = recorder()
        with self.assertRaises(RuntimeError):
            with rec.action("RETRY", action_ref="cmd-3"):
                raise RuntimeError("x")
        self.assertEqual(state(engine(sink.events), "cmd-3").value, "FAILED")

    def test_is_error_unseen_unknown(self):
        rec, sink = recorder()
        with rec.action("RETURN", action_ref="cmd-4") as a:
            a.result(output="done")                        # is_error 를 넘기지 않았다 -- 못 봄
        s = state(engine(sink.events), "cmd-4")
        self.assertEqual((s.value, s.status), (None, Status.UNKNOWN))
        self.assertIn("is_error 를 못 봤다", s.reason)

    def test_result_without_dispatch_unknown(self):
        rec, sink = recorder()
        ev = rec.emit("action.result", action_ref="cmd-9", is_error=False)
        s = state(engine([ev]), "cmd-9")
        self.assertEqual(s.status, Status.UNKNOWN)
        self.assertIn("순서를 어긴", s.reason)

    def test_repeated_ref_follows_latest_attempt(self):
        rec, sink = recorder()
        for err in (True, False):
            with rec.action("RETURN", action_ref="cmd-5") as a:
                a.result(is_error=err)
        E = engine(sink.events)
        s = state(E, "cmd-5")
        self.assertEqual(s.value, "COMPLETED")
        self.assertEqual((metric(E, "tool_results").value, metric(E, "tool_outcome_pending").value), (2, 0))  # 결과는 제 시도에
        self.assertIn("시도 2", s.reason)
        self.assertFalse(s.final)

    def test_ref_with_colon_finds_its_run(self):
        # Recorder 가 짓는 ref 는 `<run_id>/a<n>` -- 실행 id 에 ':' 가 있으면 실체 id 에서 실행을 글자로 못 가른다
        run = "cc_stream:demo"
        rec, sink = recorder(run)
        with rec.action("RETURN") as a:
            a.result(is_error=False)
        E = engine(sink.events)
        ref = f"{run}/a0"
        self.assertEqual(state(E, ref, run).value, "COMPLETED")
        v = E.query(f"action:{run}:{ref}", ["action_state"])[0]
        self.assertEqual(v.freshness, Freshness.FRESH)                 # 지금 = 그 실행의 마지막 관측 -- 실행을 찾았다
        ev = E.tick({run: 1_790_000_000_000 + 3_600_000})
        self.assertTrue(any(e.event is Lifecycle.STALE and e.name == "action_state" for e in ev))

    def test_no_action_events_no_entity(self):
        rec, sink = recorder()
        rec.run_start()
        E = engine(sink.events)
        self.assertFalse([k for k in E.current if k[1] == "action_state"])

    def test_state_definition(self):
        d = REGISTRY.state_definition("action_state")
        self.assertEqual(set(d["allowed_values"]) - {"UNKNOWN", "NOT_APPLICABLE"}, {"STARTED", "COMPLETED", "FAILED"})


class ExecutionMetrics(unittest.TestCase):
    """실행(agent) 실체의 기존 지표가 action.* 도 센다 -- 새 상태는 없다(BD-79)."""

    def test_counts(self):
        rec, sink = recorder()
        rec.llm_response(0, "anthropic", usage={"input_tokens": 1, "output_tokens": 1})
        with rec.action("RETURN", action_ref="a", args={"k": 1}) as a:
            a.result(is_error=False)
        with rec.action("RETRY", action_ref="b", args={"k": 2}) as a:
            a.result(is_error=True)
        with rec.action("RETURN", action_ref="c") as a:
            mid = list(sink.events)
            a.result(is_error=False)
        E = engine(mid)
        self.assertEqual(metric(E, "tool_results").value, 2)
        self.assertEqual(metric(E, "tool_errors").value, 1)
        self.assertEqual(metric(E, "tool_outcome_unobservable").value, 1)
        self.assertEqual(metric(E, "tool_outcome_pending").value, 1)
        h = E.current[(f"agent:{RUN}", "execution_health")]
        self.assertEqual(h.value, "UNRESOLVED_FAILURES")
        self.assertNotIn(f"tool:{RUN}:RETURN", {k[0] for k in E.current})       # 도구 실체는 세우지 않는다

    def test_action_only_run_is_not_no_tool_run_yet(self):
        rec, sink = recorder()
        with rec.action("RETURN", action_ref="a") as a:
            a.result(is_error=False)
        self.assertEqual(E_health(sink.events).value, "NO_FAILURE_OBSERVED")

    def test_unresolved_failure_keeps_its_own_time(self):
        rec, sink = recorder()
        with rec.action("FETCH", action_ref="a", target="x") as a:
            a.result(is_error=True)
        fail_at = sink.events[-1]["at"]
        for i in range(3):
            with rec.action("RUN", action_ref=f"b{i}", target=f"y{i}") as a:
                a.result(is_error=False)
        h = E_health(sink.events)
        self.assertEqual((h.value, h.observed_at), ("UNRESOLVED_FAILURES", fail_at))     # BD-57


def E_health(events):
    return engine(events).current[(f"agent:{RUN}", "execution_health")]


class SameRunTwoWays(unittest.TestCase):
    """대조 시험: 같은 실행을 tool.* 로 낸 것과 action.* 로 낸 것 -- execution_health · identical_call_max 가 같다."""

    STEPS = [("Bash", "pytest", {"command": "pytest -x"}, True), ("Bash", "pytest", {"command": "pytest -x"}, False),
             ("Bash", "ls", {"command": "ls"}, False), ("Bash", "ls", {"command": "ls"}, False),
             ("Edit", "f.py", {"file_path": "f.py"}, True)]

    def _tool(self, steps):
        rec, sink = recorder()
        for i, (name, _, inp, err) in enumerate(steps):
            rec.llm_response(i, "anthropic", usage={"input_tokens": 1, "output_tokens": 1})
            with rec.tool(name, inp, call_index=i) as t:
                t.result(is_error=err)
        return engine(sink.events)

    def _action(self, steps):
        rec, sink = recorder()
        for i, (name, target, inp, err) in enumerate(steps):
            rec.llm_response(i, "anthropic", usage={"input_tokens": 1, "output_tokens": 1})
            with rec.action(name, action_ref=f"cmd-{i}", target=target, args=inp) as a:
                a.result(is_error=err)
        return engine(sink.events)

    def _cmp(self, steps):
        a, b = self._tool(steps), self._action(steps)
        ha, hb = (E.current[(f"agent:{RUN}", "execution_health")] for E in (a, b))
        self.assertEqual((ha.value, ha.status), (hb.value, hb.status))
        self.assertEqual(metric(a, "identical_call_max").value, metric(b, "identical_call_max").value)
        return ha.value, metric(a, "identical_call_max").value

    def test_unresolved(self):
        self.assertEqual(self._cmp(self.STEPS), ("UNRESOLVED_FAILURES", 2))

    def test_recovered(self):
        self.assertEqual(self._cmp(self.STEPS[:4]), ("RECOVERED_FAILURES", 2))

    def test_clean(self):
        self.assertEqual(self._cmp(self.STEPS[2:4]), ("NO_FAILURE_OBSERVED", 2))


if __name__ == "__main__":
    unittest.main()
