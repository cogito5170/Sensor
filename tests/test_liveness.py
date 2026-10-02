"""liveness_state -- 가짜 **L0 사건 봉투**로만 시험한다(L0 패키지 · 원천 파일을 읽지 않는다). baseline#3 CMD-S2 · BD-47.

L0 사건: input.received · turn.start · turn.end · turn.continued · source.closed · run.end · heartbeat (+ 그 밖의 어떤 사건이든 '활동').
평가 시각은 사건의 at(받을 때) 또는 advance(now)(다시 잴 때)다.
"""
import time
import unittest
from unittest import mock

from llmsensor.sensing.liveness import batches
from llmsensor.state import DEFAULT_CONFIG, Basis, Status, StateEngine, from_telemetry
from llmsensor.state.model import Freshness
from tests.test_state import end, val

RUN = "fake:live"
T = f"task:{RUN}"
CFG = DEFAULT_CONFIG.with_(liveness_timeout_ms=30_000)


def ev(type, seq, at, source="cc_stream", run=RUN, time_base="monotonic_ms"):
    """L0 봉투 꼴(data 는 liveness 가 안 읽으므로 비운다)."""
    return {"spec": "l0-telemetry/1", "id": f"{run}:{seq}", "type": type, "run_id": run, "seq": seq, "source": source,
            "at": at, "time_base": time_base, "data": {}, "unobserved": [], "reported_null": []}


def eng(events, cfg=DEFAULT_CONFIG, records=()):
    E = StateEngine(cfg)
    E.ingest_all(from_telemetry(list(records)))
    return E.ingest_all(batches(events))


def lv(E, now=None):
    return val(E, T, "liveness_state", now)


class NoGuessing(unittest.TestCase):
    def test_no_events_is_unknown(self):
        self.assertEqual(lv(eng([ev("llm.request", 0, 100)], CFG)).status, Status.UNKNOWN)

    def test_activity_without_turn_events_is_not_judged(self):
        # 공백이 사람을 기다린 것일 수 있다 -- 차례 경계를 모르면 멈췄다고 하지 않는다
        E = eng([ev("llm.request", 0, 0), ev("tool.end", 1, 10)], CFG)
        E.advance(RUN, 10_000_000)
        self.assertEqual(lv(E).status, Status.UNKNOWN)

    def test_cc_jsonl_without_any_turn_end_is_unknown(self):
        # Telemetry 보고: cc_jsonl 은 Stop 훅이 있을 때만 turn.end 를 낸다 -- 끝을 한 번도 못 봤으면 '열림' 이라 하지 않는다
        E = eng([ev("input.received", 0, 0, "cc_jsonl"), ev("turn.start", 1, 5, "cc_jsonl")], CFG)
        v = lv(E)
        self.assertEqual(v.status, Status.UNKNOWN)
        self.assertIn("근거가 없다", v.reason)

    def test_cc_jsonl_after_one_seen_turn_end_can_be_open(self):
        evs = [ev("input.received", 0, 0, "cc_jsonl"), ev("turn.start", 1, 5, "cc_jsonl"), ev("turn.end", 2, 10, "cc_jsonl"),
               ev("input.received", 3, 20, "cc_jsonl")]
        self.assertEqual(lv(eng(evs)).value, "IN_TURN")

    def test_closed_turn_is_awaiting_input_not_stalled(self):
        E = eng([ev("turn.start", 0, 0), ev("turn.end", 1, 900)], CFG)
        E.advance(RUN, 5 * 3600_000)                       # 재고: 사람을 기다린 5.5시간 공백
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("AWAITING_INPUT", Basis.OBSERVED))

    def test_turn_continued_does_not_close(self):
        E = eng([ev("turn.start", 0, 0), ev("turn.continued", 1, 10)])
        self.assertEqual(lv(E).value, "IN_TURN")

    def test_input_received_mid_turn_then_end_is_closed(self):
        E = eng([ev("turn.start", 0, 0), ev("input.received", 1, 5), ev("turn.end", 2, 10)])
        self.assertEqual(lv(E).value, "AWAITING_INPUT")

    def test_pending_input_opens_the_turn(self):
        # 입력을 받은 순간부터 열림 -- 받아 놓고 처리를 시작하지 않은 입력의 침묵도 잰다
        E = eng([ev("turn.start", 0, 0), ev("turn.end", 1, 10), ev("input.received", 2, 20)], CFG)
        self.assertEqual(lv(E).value, "ACTIVE")
        E.advance(RUN, 20 + 30_001)
        self.assertEqual(lv(E).value, "STALLED")

    def test_no_operator_timeout_never_active_or_stalled(self):
        E = eng([ev("turn.start", 0, 0)])
        for now in (1000, 10_000, 10_000_000):
            E.advance(RUN, now)
            self.assertEqual(lv(E).value, "IN_TURN")
        self.assertIn("설정되지 않아", lv(E).reason)

    def test_timeout_but_no_event_times_is_unknown(self):
        v = lv(eng([ev("turn.start", 0, None, "sweagent")], CFG))
        self.assertEqual(v.status, Status.UNKNOWN)

    def test_mixed_time_bases_are_not_subtracted(self):
        E = eng([ev("turn.start", 0, 900), ev("heartbeat", 1, 1_790_000_000_000, time_base="unix_ms")], CFG)
        self.assertEqual(lv(E).status, Status.UNKNOWN)
        self.assertIn("시간 기준이 섞였다", lv(E).reason)


class Stall(unittest.TestCase):
    def test_active_then_stalled_by_operator_timeout(self):
        E = eng([ev("turn.start", 0, 900)], CFG)
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("ACTIVE", Basis.OPERATOR_ASSUMED))
        E.advance(RUN, 900 + 30_001)
        self.assertEqual((lv(E).value, lv(E).basis), ("STALLED", Basis.OPERATOR_ASSUMED))
        t = [x for x in E.transitions if x.name == "liveness_state"][-1]
        self.assertEqual((t.previous, t.new), ("ACTIVE", "STALLED"))

    def test_exactly_at_timeout_is_still_active(self):
        E = eng([ev("turn.start", 0, 900)], CFG)
        E.advance(RUN, 900 + 30_000)
        self.assertEqual(lv(E).value, "ACTIVE")

    def test_runtime_heartbeat_counts_as_activity(self):
        # 재고 t11: 오래 도는 도구 -- 다른 사건은 없지만 런타임이 30초마다 진행 중이라고 알렸다
        E = eng([ev("turn.start", 0, 0), ev("tool.start", 1, 10), ev("heartbeat", 2, 95_000)], CFG)
        E.advance(RUN, 100_000)
        v = lv(E)
        self.assertEqual(v.value, "ACTIVE")
        self.assertIn("heartbeat", v.reason)
        fields = {E.observations[i].field for i in E.observation_ids(T, "liveness_state")}
        self.assertIn("l0.heartbeat", fields)

    def test_any_event_is_activity(self):
        E = eng([ev("turn.start", 0, 0), ev("llm.response", 1, 95_000)], CFG)
        E.advance(RUN, 100_000)
        self.assertEqual(lv(E).value, "ACTIVE")

    def test_new_activity_recovers_from_stall(self):
        E = eng([ev("turn.start", 0, 900)], CFG)
        E.advance(RUN, 100_000)
        self.assertEqual(lv(E).value, "STALLED")
        E.ingest(batches([ev("tool.end", 1, 120_000)])[0])
        self.assertEqual(lv(E).value, "ACTIVE")

    def test_min_consecutive_suppresses_single_stall(self):
        E = eng([ev("turn.start", 0, 900)], CFG.with_(min_consecutive={"liveness_state": 2}))
        E.advance(RUN, 100_000)
        self.assertEqual(lv(E, 100_000).value, "ACTIVE")
        E.advance(RUN, 100_001)
        self.assertEqual(lv(E).value, "STALLED")


class Ending(unittest.TestCase):
    def test_run_end_is_ended_and_final(self):
        E = eng([ev("turn.start", 0, 0), ev("run.end", 1, 10)], CFG)
        E.advance(RUN, 10_000_000)
        v = lv(E)
        self.assertEqual((v.value, v.basis, v.freshness), ("ENDED", Basis.OBSERVED, Freshness.PERMANENT))

    def test_runtime_termination_declaration_is_ended(self):
        v = lv(eng([], records=[end(run=RUN)]))
        self.assertEqual((v.value, v.basis), ("ENDED", Basis.RUNTIME_DECLARED))

    def test_all_null_termination_is_not_an_end(self):
        E = eng([ev("turn.start", 0, 900)], CFG,
                records=[end(run=RUN, terminal_reason=None, result_subtype=None, is_error=None)])
        self.assertNotEqual(lv(E).value, "ENDED")

    def test_closed_without_terminal_then_late_run_end(self):
        E = eng([ev("turn.start", 0, 0), ev("source.closed", 1, 10)], CFG)
        v = lv(E)
        self.assertEqual((v.value, v.basis), ("ENDED_WITHOUT_TERMINAL", Basis.DEFINITIONAL))
        self.assertNotEqual(v.freshness, Freshness.PERMANENT)          # 늦게 온 종료 사건이 고칠 수 있게
        E.ingest(batches([ev("run.end", 2, 20)])[0])
        self.assertEqual(lv(E).value, "ENDED")


class Clock(unittest.TestCase):
    def test_active_is_stale_when_queried_later_without_advance(self):
        E = eng([ev("turn.start", 0, 1000)], CFG)
        self.assertEqual(lv(E, 1000).status, Status.INFERRED)
        v = lv(E, 1001)                                    # ACTIVE 는 평가 순간의 판정이다
        self.assertEqual((v.status, v.freshness), (Status.STALE, Freshness.STALE))
        E.advance(RUN, 1001)
        self.assertEqual(lv(E, 1001).status, Status.INFERRED)

    def test_observation_facts_are_not_clock_stale(self):
        E = eng([ev("turn.start", 0, 0), ev("turn.end", 1, 1000)], CFG)
        self.assertEqual(lv(E, 1001).status, Status.INFERRED)   # AWAITING_INPUT 은 관측 사실 -- 일반 TTL 만 따른다

    def test_advance_rejects_time_going_backwards(self):
        E = eng([ev("turn.start", 0, 1000)], CFG)
        with self.assertRaises(ValueError):
            E.advance(RUN, 999)
        self.assertFalse(E.advance("nope", 5000))

    def test_idempotent_by_event_id(self):
        E = eng([ev("turn.start", 0, 0)], CFG)
        self.assertFalse(E.ingest(batches([ev("turn.start", 0, 0)])[0]))

    def test_deterministic_and_reads_no_clock(self):
        evs = [ev("turn.start", 0, 900), ev("heartbeat", 1, 950)]

        def run():
            E = eng(evs, CFG)
            for now in (5000, 40_000, 90_000):
                E.advance(RUN, now)
            return E.snapshot()
        with mock.patch.object(time, "time", side_effect=AssertionError("시계를 읽었다")), \
                mock.patch.object(time, "monotonic", side_effect=AssertionError("시계를 읽었다")):
            a, b = run(), run()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
