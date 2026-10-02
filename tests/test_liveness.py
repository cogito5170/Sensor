"""S1 liveness_state -- 가짜 정준 관측으로만 시험한다(원천 · 텔레메트리 꼴을 읽지 않는다).

입력은 run 레코드의 칸 다섯(terminal_seen · transport_closed · turn_open · activity_at_ms · heartbeat_at_ms)이고,
평가 시각은 레코드의 snapshot_at_ms(받을 때) 또는 advance(now)(다시 잴 때)다.
"""
import time
import unittest
from unittest import mock

from llmsensor.state import DEFAULT_CONFIG, Basis, Status, StateEngine, from_telemetry
from llmsensor.state.model import Freshness, Lifecycle
from tests.test_state import end, val

RUN = "fake:live"
T = f"task:{RUN}"
CFG = DEFAULT_CONFIG.with_(liveness_timeout_ms=30_000)


def live(at, run=RUN, time_base="monotonic_ms", reported_null=(), **f):
    """liveness 입력만 든 run 레코드. 칸이 없으면 못 본 것, reported_null 이면 원천이 null 이라고 한 것."""
    r = {"kind": "run", "run_id": run, "source": "fake", "time_base": time_base, "snapshot_at_ms": at,
         "reported_null": list(reported_null)}
    r.update(f)
    for k in reported_null:
        r[k] = None
    return r


def eng(recs, cfg=DEFAULT_CONFIG):
    return StateEngine(cfg).ingest_all(from_telemetry(recs))


def lv(E, now=None):
    return val(E, T, "liveness_state", now)


class NoGuessing(unittest.TestCase):
    def test_no_inputs_is_unknown(self):
        v = lv(eng([live(1000)], CFG))
        self.assertEqual((v.status, v.value), (Status.UNKNOWN, None))

    def test_unknown_turn_is_not_judged_even_with_long_silence(self):
        # 공백이 사람을 기다린 것일 수 있다 -- 차례를 모르면 멈췄다고 하지 않는다
        E = eng([live(1000, activity_at_ms=0)], CFG)
        self.assertEqual(lv(E).status, Status.UNKNOWN)
        E.advance(RUN, 10_000_000)
        self.assertEqual(lv(E).status, Status.UNKNOWN)

    def test_reported_null_turn_is_unknown_not_awaiting(self):
        v = lv(eng([live(1000, activity_at_ms=0, reported_null=["turn_open"])], CFG))
        self.assertEqual(v.status, Status.UNKNOWN)

    def test_closed_turn_is_awaiting_input_not_stalled(self):
        E = eng([live(1000, turn_open=False, activity_at_ms=0)], CFG)
        E.advance(RUN, 5 * 3600_000)                       # 재고: 사람을 기다린 5.5시간 공백
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("AWAITING_INPUT", Basis.OBSERVED))

    def test_no_operator_timeout_never_active_or_stalled(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=0)])
        for now in (1000, 10_000, 10_000_000):
            E.advance(RUN, now)
            self.assertEqual(lv(E).value, "IN_TURN")
        self.assertIn("설정되지 않아", lv(E).reason)

    def test_timeout_but_no_activity_time_is_unknown(self):
        v = lv(eng([live(1000, turn_open=True)], CFG))
        self.assertEqual(v.status, Status.UNKNOWN)
        self.assertIn("무음을 잴 수 없다", v.reason)

    def test_now_before_activity_is_unknown(self):
        v = lv(eng([live(1000, turn_open=True, activity_at_ms=5000)], CFG))
        self.assertEqual(v.status, Status.UNKNOWN)
        self.assertIn("이르다", v.reason)

    def test_mixed_time_bases_are_not_subtracted(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900),
                 live(1000, time_base="epoch_ms", heartbeat_at_ms=1_790_000_000_000)], CFG)
        self.assertEqual(lv(E).status, Status.UNKNOWN)
        self.assertIn("시간 기준이 다르다", lv(E).reason)


class Stall(unittest.TestCase):
    def test_active_then_stalled_by_operator_timeout(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900)], CFG)
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("ACTIVE", Basis.OPERATOR_ASSUMED))
        E.advance(RUN, 900 + 30_001)
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("STALLED", Basis.OPERATOR_ASSUMED))
        t = [x for x in E.transitions if x.name == "liveness_state"][-1]
        self.assertEqual((t.previous, t.new), ("ACTIVE", "STALLED"))

    def test_exactly_at_timeout_is_still_active(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900)], CFG)
        E.advance(RUN, 900 + 30_000)
        self.assertEqual(lv(E).value, "ACTIVE")

    def test_runtime_heartbeat_counts_as_activity(self):
        # 재고 t11: 오래 도는 도구 -- 사건은 없지만 런타임이 30초마다 진행 중이라고 알렸다
        E = eng([live(100_000, turn_open=True, activity_at_ms=0, heartbeat_at_ms=95_000)], CFG)
        v = lv(E)
        self.assertEqual(v.value, "ACTIVE")
        self.assertIn("heartbeat", v.reason)
        fields = {E.observations[i].field for i in E.observation_ids(T, "liveness_state")}
        self.assertIn("run.heartbeat_at_ms", fields)

    def test_new_activity_recovers_from_stall(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900)], CFG)
        E.advance(RUN, 100_000)
        self.assertEqual(lv(E).value, "STALLED")
        E.ingest(from_telemetry([live(1000, turn_open=True, activity_at_ms=900),
                                 live(120_000, turn_open=True, activity_at_ms=119_000)])[1])
        self.assertEqual(lv(E).value, "ACTIVE")

    def test_min_consecutive_suppresses_single_stall(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900)], CFG.with_(min_consecutive={"liveness_state": 2}))
        E.advance(RUN, 100_000)
        self.assertEqual(lv(E, 100_000).value, "ACTIVE")
        E.advance(RUN, 100_001)
        self.assertEqual(lv(E).value, "STALLED")


class Ending(unittest.TestCase):
    def test_terminal_seen_is_ended_and_final(self):
        E = eng([live(1000, terminal_seen=True, turn_open=True, activity_at_ms=0)], CFG)
        E.advance(RUN, 10_000_000)
        v = lv(E)
        self.assertEqual((v.value, v.basis, v.freshness), ("ENDED", Basis.OBSERVED, Freshness.PERMANENT))

    def test_runtime_termination_declaration_is_ended(self):
        E = eng([end(run=RUN)])
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("ENDED", Basis.RUNTIME_DECLARED))

    def test_closed_without_terminal_then_late_terminal(self):
        E = eng([live(1000, transport_closed=True, terminal_seen=False)], CFG)
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("ENDED_WITHOUT_TERMINAL", Basis.DEFINITIONAL))
        self.assertNotEqual(v.freshness, Freshness.PERMANENT)          # 늦게 온 종료 사건이 고칠 수 있게
        E.ingest(from_telemetry([live(1000), live(2000, terminal_seen=True)])[1])
        self.assertEqual(lv(E).value, "ENDED")


class Clock(unittest.TestCase):
    def test_active_is_stale_when_queried_later_without_advance(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900)], CFG)
        self.assertEqual(lv(E, 1000).status, Status.INFERRED)
        v = lv(E, 1001)                                    # ACTIVE 는 평가 순간의 판정이다
        self.assertEqual((v.status, v.freshness), (Status.STALE, Freshness.STALE))
        self.assertFalse(v.status.usable)
        E.advance(RUN, 1001)
        self.assertEqual(lv(E, 1001).status, Status.INFERRED)

    def test_observation_facts_are_not_clock_stale(self):
        E = eng([live(1000, turn_open=False)], CFG)
        self.assertEqual(lv(E, 1001).status, Status.INFERRED)   # AWAITING_INPUT 은 관측 사실 -- 일반 TTL 만 따른다

    def test_advance_rejects_time_going_backwards(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900)], CFG)
        with self.assertRaises(ValueError):
            E.advance(RUN, 999)
        self.assertFalse(E.advance("nope", 5000))

    def test_advance_touches_only_clock_rules(self):
        E = eng([live(1000, turn_open=True, activity_at_ms=900), end(run=RUN, terminal_reason=None,
                                                                       result_subtype=None, is_error=None)], CFG)
        before = [(x.entity_id, x.name) for x in E.lifecycle]
        E.advance(RUN, 50_000)
        after = [(x.entity_id, x.name) for x in E.lifecycle][len(before):]
        self.assertTrue(after)
        self.assertEqual({n for _, n in after}, {"liveness_state"})

    def test_all_null_termination_is_not_an_end(self):
        # 종료 칸이 전부 reported_null 인 요약 -- 'termination' 지표는 값(전부 None)을 내지만 종료 선언이 아니다
        E = eng([live(1000, turn_open=True, activity_at_ms=900),
                 end(run=RUN, terminal_reason=None, result_subtype=None, is_error=None)], CFG)
        self.assertNotEqual(lv(E).value, "ENDED")
        self.assertEqual(lv(E).status, Status.UNKNOWN)          # 시각 없는 요약 -- 평가 시각이 없다
        E.advance(RUN, 1000)
        self.assertEqual(lv(E).value, "ACTIVE")

    def test_deterministic_and_reads_no_clock(self):
        recs = [live(1000, turn_open=True, activity_at_ms=900), live(1000, heartbeat_at_ms=950)]

        def run():
            E = eng(recs, CFG)
            for now in (5000, 40_000, 90_000):
                E.advance(RUN, now)
            return E.snapshot()
        with mock.patch.object(time, "time", side_effect=AssertionError("시계를 읽었다")), \
                mock.patch.object(time, "monotonic", side_effect=AssertionError("시계를 읽었다")):
            a, b = run(), run()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
