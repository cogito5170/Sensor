"""execution-health-v3 (baseline#3 CMD-S19 · BD-84): 도구 호출이 **아직 없음**과 결과를 **볼 수 없음**을 가른다.

    (a) 모델 호출은 봤고 도구 레코드가 하나도 없다     -> NO_TOOL_RUN_YET (INFERRED, 근거 OBSERVED) -- 건강을 말하지 않는다
    (b) 도구 레코드가 있는데 결과(is_error)를 못 본다  -> UNKNOWN (v2 와 같다 -- SWE-agent · 도는 중인 호출)
"""
import unittest

from llmsensor.sensing.execution import EXECUTION_HEALTH_V2, EXECUTION_HEALTH_V3
from llmsensor.state import REGISTRY, Basis, Status, StateEngine
from llmsensor.state.export import catalog
from tests.test_state import A, end, engine, mc, tc, val


def st(recs):
    return engine(recs).current[(A, "execution_health")]


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
        self.assertIn("볼 수 없다", s.reason)

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


class Contract(unittest.TestCase):
    def test_value_is_added_not_a_state(self):
        self.assertIs(REGISTRY.rules["execution_health"], EXECUTION_HEALTH_V3)
        self.assertEqual(EXECUTION_HEALTH_V3.values, EXECUTION_HEALTH_V2.values + ("NO_TOOL_RUN_YET",))
        self.assertLessEqual(len(REGISTRY.rules), 14)      # 상한 그대로 -- 값이 늘 뿐 상태가 늘지 않는다
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
