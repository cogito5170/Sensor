"""resource-state-v2 (baseline BD-39, baseline#3 CMD-S3) -- 가짜 레코드로 조건 다섯을 하나씩 붙든다.

    (1) 예산 없음 -> NOT_APPLICABLE(UNKNOWN 아님)
    (2) 실행 중 비용 = 토큰 × 단가표(판본이 근거에 남는다). 실행 끝 보고가 오면 그것이 이긴다
    (3) 단가 없는 호출이 있으면 합은 모른다. 하지만 부분 합 ≥ 예산이면 BUDGET_EXHAUSTED -- 영구는 보고 비용 ≥ 예산일 때만(BD-64)
    (4) WITHIN_BUDGET 은 합이 완전할 때만
    (5) 판본 v3(BD-64 로 v2 에서 올림)
"""
import unittest

from llmsensor.sensing.cost import RESOURCE_V1, RESOURCE_V3, pricing
from llmsensor.state import DEFAULT_CONFIG, Status
from llmsensor.state.model import Freshness
from tests.test_sensing import engine, mc3
from tests.test_state import A, RUN, end, val

CALL = (10 * 1 + 50 * 5 + 1000 * 0.1 + 100 * 2) / 1e6        # mc3 기본 호출 하나의 값(haiku 단가, 손으로 씀) = $0.00056


def cfg(b):
    return DEFAULT_CONFIG.with_(cost_budget_usd=b)


def rs(E, now=None):
    return val(E, A, "resource_state", now)


def bounds(E):
    ms = [m for i, m in E.metrics.items() if i.startswith(f"{A}/cost_bounds@")]
    return max(ms, key=lambda m: int(m.id.rsplit("@", 1)[1])).value


class Version(unittest.TestCase):
    def test_v2_is_registered_and_v1_kept(self):
        self.assertEqual((RESOURCE_V3.id, RESOURCE_V3.version), ("resource-state-v3", 3))
        self.assertEqual(RESOURCE_V1.id, "resource-state-v1")
        self.assertEqual(rs(engine([mc3(0, 100)], cfg(1.0))).rule, "resource-state-v3")


class NoBudget(unittest.TestCase):
    def test_no_budget_is_not_applicable_not_unknown(self):
        for recs in ([mc3(0, 100)], [mc3(0, 100), end()], [mc3(0, 100, model="<synthetic>")]):
            v = rs(engine(recs))
            self.assertEqual((v.status, v.value), (Status.NOT_APPLICABLE, None))


class MidRun(unittest.TestCase):
    def test_within_budget_before_any_report(self):
        E = engine([mc3(0, 100), mc3(1, 200)], cfg(1.0))
        v = rs(E)
        self.assertEqual((v.status, v.value), (Status.INFERRED, "WITHIN_BUDGET"))
        b = bounds(E)
        self.assertAlmostEqual(b["total"], 2 * CALL, places=12)
        self.assertEqual((b["source"], b["pricing"]), ("estimate", pricing.VERSION))

    def test_estimate_exhaustion_mid_run_is_not_permanent(self):
        # BD-64: 단가표 추정만으로 선 소진은 영구가 아니다(증명은 단가가 정확하다는 전제 위에 있다)
        budget = 2.5 * CALL
        E = engine([mc3(i, 100 * (i + 1)) for i in range(3)], cfg(budget))
        v = rs(E)
        self.assertEqual(v.value, "BUDGET_EXHAUSTED")
        self.assertNotEqual(v.freshness, Freshness.PERMANENT)
        t = [x for x in E.transitions if x.name == "resource_state"]
        self.assertEqual([(x.previous, x.new) for x in t], [("WITHIN_BUDGET", "BUDGET_EXHAUSTED")])

    def test_reported_exhaustion_is_permanent(self):
        E = engine([mc3(0, 100), end(cost_usd=3 * CALL)], cfg(2 * CALL))
        v = rs(E)
        self.assertEqual((v.value, v.freshness), ("BUDGET_EXHAUSTED", Freshness.PERMANENT))

class Unpriced(unittest.TestCase):
    def test_synthetic_call_makes_total_unknown(self):
        # 재고 D3: 런타임이 합성한 오류 메시지(<synthetic>) -- 단가가 없다. 세션 전체가 None 이 되지 않고 '합을 모름' 이 된다
        E = engine([mc3(0, 100), mc3(1, 200, model="<synthetic>", out=0, cr=0, cw=0, w1h=0)], cfg(1.0))
        v = rs(E)
        self.assertEqual(v.status, Status.UNKNOWN)
        self.assertIn("단가 없는 호출 1", v.reason)
        self.assertEqual(bounds(E)["unpriced_calls"], 1)

    def test_partial_sum_proves_exhaustion(self):
        # 단가 없는 호출이 **먼저** 온다 -- 소진은 처음부터 '합을 모르는' 채로 부분 합만으로 증명돼야 한다
        recs = [mc3(0, 100, model="<synthetic>")] + [mc3(i, 100 * (i + 1)) for i in range(1, 4)]
        E = engine(recs[:3], cfg(2.5 * CALL))
        self.assertEqual(rs(E).status, Status.UNKNOWN)              # 부분 합 2·CALL < 예산
        E = engine(recs, cfg(2.5 * CALL))
        self.assertEqual(rs(E).value, "BUDGET_EXHAUSTED")           # 부분 합 3·CALL ≥ 예산 -- 단가 없는 호출이 있어도
        self.assertEqual(bounds(E)["unpriced_calls"], 1)

    def test_unknown_model_is_not_priced_as_another(self):
        E = engine([mc3(0, 100, model="gpt-x")], cfg(1.0))
        self.assertEqual(rs(E).status, Status.UNKNOWN)


class ReportWins(unittest.TestCase):
    def test_end_of_run_report_wins_over_estimate(self):
        # 덮는 보고가 오면 합은 보고다 -- 추정(CALL)과 달라도
        E = engine([mc3(0, 100), end(cost_usd=1.5 * CALL)], cfg(2 * CALL))
        b = bounds(E)
        self.assertEqual((rs(E).value, b["source"], b["total"]), ("WITHIN_BUDGET", "reported", 1.5 * CALL))
        # 추정은 예산 안인데 보고가 예산을 넘으면 소진
        E = engine([mc3(0, 100), end(cost_usd=3 * CALL)], cfg(2 * CALL))
        self.assertEqual(rs(E).value, "BUDGET_EXHAUSTED")

    def test_lower_covering_report_overturns_estimate_exhaustion(self):
        # BD-64: 보고가 이긴다. 추정 소진(단가표 과대)을 더 낮은 덮는 보고가 뒤집고, 그 어긋남을 이유에 남긴다
        E = engine([mc3(i, 100 * (i + 1)) for i in range(3)] + [end(cost_usd=CALL)], cfg(2.5 * CALL))
        v = rs(E)
        self.assertEqual((v.value, bounds(E)["source"]), ("WITHIN_BUDGET", "reported"))
        self.assertIn("과대 의심", v.reason)
        t = [(x.previous, x.new) for x in E.transitions if x.name == "resource_state"]
        self.assertEqual(t[-1], ("BUDGET_EXHAUSTED", "WITHIN_BUDGET"))

    def test_report_alone_counts_when_calls_unpriced(self):
        E = engine([mc3(0, 100, model="gpt-x"), end(cost_usd=0.3)], cfg(1.0))
        self.assertEqual(rs(E).value, "WITHIN_BUDGET")
        E = engine([mc3(0, 100, model="gpt-x"), end(cost_usd=1.3)], cfg(1.0))
        self.assertEqual(rs(E).value, "BUDGET_EXHAUSTED")

    def test_snapshot_report_covers_only_earlier_calls(self):
        # 중간 스냅숏(Claude Code cost-state): 스냅숏 뒤 호출이 단가 없으면 합을 모른다
        snap = end(cost_usd=CALL, snapshot_at_ms=150, result_subtype=None, terminal_reason=None, is_error=None)
        E = engine([mc3(0, 100), mc3(1, 200, model="gpt-x"), snap], cfg(1.0))
        self.assertFalse(bounds(E)["reported_covers_all"])
        self.assertEqual(rs(E).status, Status.UNKNOWN)
        E = engine([mc3(0, 100), snap], cfg(1.0))
        self.assertTrue(bounds(E)["reported_covers_all"])
        self.assertEqual((rs(E).value, bounds(E)["source"]), ("WITHIN_BUDGET", "reported"))


class SameAsV1WhenTotalIsKnown(unittest.TestCase):
    def test_final_values_match_v1_with_full_report(self):
        import copy
        from llmsensor.state import StateEngine, from_telemetry
        from llmsensor.state.registry import REGISTRY
        reg = copy.copy(REGISTRY)
        reg.rules = dict(REGISTRY.rules, resource_state=RESOURCE_V1)
        for b in (0.01, 0.05, 1.0):
            recs = [mc3(0, 100), mc3(1, 200), end(cost_usd=0.04)]
            v2 = rs(engine(recs, cfg(b))).value
            v1 = rs(StateEngine(cfg(b), reg).ingest_all(from_telemetry(recs))).value
            self.assertEqual(v1, v2, b)


if __name__ == "__main__":
    unittest.main()
