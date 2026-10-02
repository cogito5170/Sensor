"""execution-health-v3 (baseline#3 CMD-S19 · BD-84 · CMD-S22 · BD-89): 도구 호출이 **아직 없음**과 결과를 **볼 수 없음**을 가른다.

    (a) 그 실행의 사건(L0 사건 · 모델 호출)은 봤고 도구 레코드가 하나도 없다 -> NO_TOOL_RUN_YET (INFERRED, 근거 OBSERVED)
        -- 건강을 말하지 않는다. 근거 시각은 그 실행에서 가장 늦게 본 관측(BD-74)
    (b) 도구 레코드가 있는데 결과(is_error)를 못 본다  -> UNKNOWN (v2 와 같다 -- SWE-agent · 도는 중인 호출)
"""
import unittest

from llmsensor.sensing.execution import EXECUTION_HEALTH_V2, EXECUTION_HEALTH_V3
from llmsensor.state import REGISTRY, Basis, Status, StateEngine
from llmsensor.state.export import catalog
from llmsensor.sensing.l0 import batches
from tests.test_state import A, RUN, end, engine, mc, tc, val


def st(recs):
    return engine(recs).current[(A, "execution_health")]


def l0(seq, ty, at, run=RUN):
    return {"spec": "l0-telemetry/1", "id": f"{run}:{seq}", "type": ty, "run_id": run, "seq": seq, "source": "cc_stream",
            "at": at, "time_base": "monotonic_ms", "data": {}, "unobserved": [], "reported_null": []}


def with_l0(recs, evs):
    return engine(recs).ingest_all(batches(evs))


class Split(unittest.TestCase):
    def test_a_no_tool_yet(self):
        s = st([mc(0, 100), mc(1, 900)])
        self.assertEqual((s.value, s.status, s.basis), ("NO_TOOL_RUN_YET", Status.INFERRED, Basis.OBSERVED))
        self.assertEqual(s.rule_id, "execution-health-v3")
        self.assertTrue(s.status.usable)
        self.assertEqual(s.observed_at, 900)           # 없음의 주장 -- 가장 늦은 관측(BD-74)

    def test_b_unobservable_outcome_stays_unknown(self):
        s = st([mc(0, 100), tc(0, 0, 110, known=False)])
        self.assertEqual((s.value, s.status), (None, Status.UNKNOWN))
        self.assertIn("결과(is_error)를 못 봤다", s.reason)

    def test_b_with_many_calls_still_unknown(self):
        recs = [mc(0, 100)] + [tc(0, j, 110 + j, head=f"edit:{j}", known=False) for j in range(5)]
        self.assertEqual(st(recs).status, Status.UNKNOWN)

    def test_in_flight_call_is_not_no_tool_yet(self):
        # L0 compat 은 tool.start 로 tool_call 레코드를 짓고 tool.end 가 오면 is_error 를 채운다 -- 도는 중이면 is_error 가 없다
        s = st([mc(0, 100), tc(0, 0, 110, known=False)])
        self.assertNotEqual(s.value, "NO_TOOL_RUN_YET")

    def test_result_seen_is_not_no_tool_yet(self):
        self.assertEqual(st([mc(0, 100), tc(0, 0, 110)]).value, "NO_FAILURE_OBSERVED")
        self.assertEqual(st([mc(0, 100), tc(0, 0, 110, err=True)]).value, "UNRESOLVED_FAILURES")

    def test_seen_and_unseen_mixed_follows_v2(self):
        s = st([mc(0, 100), tc(0, 0, 110), tc(0, 1, 120, head="Bash:b", known=False)])
        self.assertEqual(s.value, "NO_FAILURE_OBSERVED")
        self.assertIn("못 본 호출 1 개 제외", s.reason)

    def test_nothing_observed_is_unknown(self):
        s = engine([end()]).current[(A, "execution_health")]       # 실행 요약만 -- 모델 호출이 없다
        self.assertEqual((s.value, s.status), (None, Status.UNKNOWN))
        self.assertIn("관측이 없다", s.reason)

    def test_moves_on_when_first_tool_arrives(self):
        E = engine([mc(0, 100), tc(0, 0, 110), mc(1, 200)])
        tr = [(t.previous, t.new) for t in E.transitions if t.entity_id == A and t.name == "execution_health"]
        self.assertEqual(tr, [("NO_TOOL_RUN_YET", "NO_FAILURE_OBSERVED")])


class AnyRunEvent(unittest.TestCase):
    """BD-89: '아직 없다' 의 조건은 모델 호출이 아니라 그 실행의 사건 ≥ 1 -- input.received · turn.start 도 시각 있는 관측이다."""

    def test_l0_event_before_any_model_call(self):
        E = with_l0([], [l0(1, "input.received", 40), l0(2, "turn.start", 50)])
        s = E.current[(A, "execution_health")]
        self.assertEqual((s.value, s.status, s.basis), ("NO_TOOL_RUN_YET", Status.INFERRED, Basis.OBSERVED))
        self.assertEqual(s.observed_at, 50)              # 가장 늦게 본 사건(BD-74)
        self.assertIn("turn.start", s.reason)

    def test_time_is_the_latest_of_calls_and_events(self):
        E = with_l0([mc(0, 100)], [l0(1, "turn.start", 50), l0(2, "heartbeat", 500)])
        self.assertEqual(E.current[(A, "execution_health")].observed_at, 500)
        E = with_l0([mc(0, 900)], [l0(1, "turn.start", 50)])
        self.assertEqual(E.current[(A, "execution_health")].observed_at, 900)

    def test_other_runs_events_do_not_count(self):
        E = with_l0([end()], [l0(1, "turn.start", 50, run="cc_stream:other")])
        s = E.current[(A, "execution_health")]
        self.assertEqual((s.value, s.status), (None, Status.UNKNOWN))

    def test_tool_record_still_wins(self):
        E = with_l0([mc(0, 100), tc(0, 0, 110, known=False)], [l0(1, "turn.start", 50)])
        self.assertEqual(E.current[(A, "execution_health")].status, Status.UNKNOWN)


class Contract(unittest.TestCase):
    def test_value_is_added_not_a_state(self):
        self.assertIs(REGISTRY.rules["execution_health"], EXECUTION_HEALTH_V3)
        self.assertEqual(EXECUTION_HEALTH_V3.values, EXECUTION_HEALTH_V2.values + ("NO_TOOL_RUN_YET",))
        self.assertLessEqual(len(REGISTRY.rules), 15)      # 상한 그대로 -- 값이 늘 뿐 상태가 늘지 않는다
        self.assertEqual(REGISTRY.rules["tool_execution_health"].id, "tool-execution-health-v2")   # 도구 실체는 그대로

    def test_catalog_carries_the_value(self):
        c = catalog(StateEngine())["states"]["execution_health"]
        self.assertIn("NO_TOOL_RUN_YET", c["values"])
        self.assertEqual((c["rule_id"], c["rule_version"]), ("execution-health-v3", 3))

    def test_query_view(self):
        E = engine([mc(0, 100)])
        v = val(E, A, "execution_health", now=100)
        self.assertEqual((v.value, v.status), ("NO_TOOL_RUN_YET", Status.INFERRED))


if __name__ == "__main__":
    unittest.main()
