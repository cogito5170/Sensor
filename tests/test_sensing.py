import unittest

from llmsensor.providers import ErrorKind, error
from llmsensor.sensing import BASELINE_ORDER, packs
from llmsensor.sensing._base import min_samples, percentile
from llmsensor.sensing.cost import RESOURCE_V1, RESOURCE_V3, pricing
from llmsensor.sensing.provider import RATE_LIMIT_V1, RATE_LIMIT_V2, RATE_LIMIT_V3
from llmsensor.sensing.quality import external_label_batch
from llmsensor.state import DEFAULT_CONFIG, REGISTRY, Basis, Status, StateEngine, from_telemetry
from llmsensor.state.config import Band
from llmsensor.state.rules import RULES
from llmsensor.telemetry.schema import record
from tests.test_state import RUN, A, R, T, end, mc, tc, val


def mc3(i, t, w1h=100, w5m=0, model="claude-haiku-4-5-20251001", **kw):
    r = mc(i, t, **kw)
    r.update(cache_creation_1h_input_tokens=w1h, cache_creation_5m_input_tokens=w5m, model=model)
    for k in ("cache_creation_1h_input_tokens", "cache_creation_5m_input_tokens", "model"):
        if r[k] is not None and k in r["unobserved"]:
            r["unobserved"].remove(k)
    return r


def engine(recs, cfg=DEFAULT_CONFIG):
    return StateEngine(cfg).ingest_all(from_telemetry(recs))


class Packs(unittest.TestCase):
    def test_baseline_rules_are_the_same_objects(self):
        old = {r.state: r for r in RULES}
        for n in BASELINE_ORDER:
            if n == "rate_limit_state":
                self.assertIs(REGISTRY.rules[n], RATE_LIMIT_V3)
            elif n == "resource_state":                          # baseline BD-39 로 판본을 올렸다(시험: tests/test_resource_v2.py)
                self.assertIs(REGISTRY.rules[n], RESOURCE_V3)
                self.assertIs(RESOURCE_V1, old[n])
            else:
                self.assertIs(REGISTRY.rules[n], old[n], n)      # 뜻 불변 -- 같은 객체
        self.assertEqual(list(REGISTRY.rules)[:len(BASELINE_ORDER)], list(BASELINE_ORDER))
        self.assertEqual({p.name for p in packs()}, {"token", "execution", "latency", "provider", "cost", "quality",
                                                      "liveness", "actions"})
        self.assertEqual(REGISTRY.check(), [])

    def test_every_rule_has_threshold_source(self):
        for r in REGISTRY.rules.values():
            self.assertNotIn(r.basis, (Basis.OBSERVED, Basis.ESTIMATE), r.id)


class RateLimitV2(unittest.TestCase):
    def test_v2_equals_v1_without_new_observations(self):
        for u in (0.3, 0.99, 1.0, None):
            kw = {"rate_limit_utilization": u} if u is not None else {"rate_limit_utilization": None}
            E = engine([mc(0, 100), end(**kw)])
            v2 = val(E, R, "rate_limit_state")
            Mx = {m.name: m for m in E.metrics.values() if m.entity_id == R}
            v1 = RATE_LIMIT_V1.fn(Mx, None, DEFAULT_CONFIG)
            self.assertEqual((v2.value, v2.status), (v1.value, v1.status), u)

    def test_declared_warning_and_429(self):
        E = engine([mc(0, 100), end(rate_limit_utilization=0.8, rate_limit_status="allowed_warning",
                                    rate_limit_threshold=0.75)])
        self.assertEqual(val(E, R, "rate_limit_state").value, "WARNING")
        E = engine([mc(0, 100), end(rate_limit_status="some_new_status")])
        v = val(E, R, "rate_limit_state")
        self.assertEqual(v.value, "AVAILABLE")
        self.assertIn("추측 안 함", v.reason)
        self.assertEqual(val(engine([mc(0, 100), end(api_error_status="429")]), R, "rate_limit_state").value, "LIMITED")
        self.assertEqual(val(engine([mc(0, 100), end(rate_limit_utilization=1.0)]), R, "rate_limit_state").value,
                         "EXHAUSTED")


class Execution(unittest.TestCase):
    def test_interruption(self):
        t = tc(0, 0, 110, err=True)
        t["timed_out"] = True
        t["unobserved"].remove("timed_out")
        self.assertEqual(val(engine([mc(0, 100), t]), A, "execution_interruption").value, "TIMEOUT_OBSERVED")
        ok = tc(0, 0, 110)
        ok["timed_out"] = False
        ok["unobserved"].remove("timed_out")
        v = val(engine([mc(0, 100), ok]), A, "execution_interruption")
        self.assertEqual(v.value, "NONE_OBSERVED")
        self.assertIn("못 본다", v.reason)
        self.assertEqual(val(engine([mc(0, 100), tc(0, 0, 110)]), A, "execution_interruption").status, Status.UNKNOWN)

    def test_timeout_is_not_a_run_failure(self):
        # t11 처럼: 도구는 시간 초과, 실행은 정상 종료 -- 두 상태가 따로 말한다(합성 열거를 만들지 않은 까닭)
        t = tc(0, 0, 110, err=True)
        t["timed_out"] = True
        t["unobserved"].remove("timed_out")
        E = engine([mc(0, 100), t, mc(1, 200, stop="end_turn"), end()])
        self.assertEqual(val(E, A, "execution_interruption").value, "TIMEOUT_OBSERVED")
        self.assertEqual(val(E, T, "completion_state").value, "ENDED_NORMALLY")

    def test_timeout_disposition(self):
        # S2: 처분 -- L0 tool.end.moved_to_background. 모두 같을 때만 그 처분, 섞였거나 모르면 TIMEOUT_OBSERVED(v2 와 같음)
        def to(i, t, moved):
            r = tc(0, i, t, head=f"Bash:{i}", err=moved is not True)
            r["timed_out"] = True
            r["unobserved"].remove("timed_out")
            if moved is not None:
                r["moved_to_background"] = moved           # 꼴 v3 에 아직 없는 칸 -- 정준 입력 계약만으로 시험한다
            return r
        cases = {(True,): "TIMEOUT_BACKGROUNDED", (False,): "TIMEOUT_KILLED", (True, True): "TIMEOUT_BACKGROUNDED",
                 (True, False): "TIMEOUT_OBSERVED", (True, None): "TIMEOUT_OBSERVED", (None,): "TIMEOUT_OBSERVED"}
        for moves, want in cases.items():
            recs = [mc(0, 100)] + [to(i, 110 + i, m) for i, m in enumerate(moves)]
            v = val(engine(recs), A, "execution_interruption")
            self.assertEqual(v.value, want, moves)
            self.assertIn("처분", v.reason)

    def test_retries_metric(self):
        E = engine([mc(0, 100), tc(0, 0, 110, err=True), mc(1, 200), tc(1, 1, 210), mc(2, 300), tc(2, 2, 310)])
        m = [m for m in E.metrics.values() if m.name == "tool_retries"][-1]
        self.assertEqual(m.value, 1)


class Latency(unittest.TestCase):
    def test_percentile_needs_samples(self):
        self.assertEqual((min_samples(0.5), min_samples(0.95), min_samples(0.99)), (2, 20, 100))
        self.assertIsNone(percentile(list(range(19)), 0.95))
        self.assertEqual(percentile(list(range(1, 21)), 0.95), 19)
        self.assertEqual(percentile([5, 1], 0.5), 1)

    def test_state_needs_slo(self):
        recs = [mc(i, 100 + 100 * i) for i in range(25)]
        self.assertEqual(val(engine(recs), A, "latency_state").status, Status.NOT_APPLICABLE)
        slo = {"metric": "call_latency", "percentile": "p95", "bands": (Band("ELEVATED", 8, 6), Band("DEGRADED", 20, 15))}
        cfg = DEFAULT_CONFIG.with_(version="l", latency_slo=slo)
        v = val(engine(recs, cfg), A, "latency_state")          # 호출 구간은 모두 10 ms
        self.assertEqual((v.value, v.basis), ("ELEVATED", Basis.OPERATOR_ASSUMED))
        self.assertEqual(val(engine(recs[:5], cfg), A, "latency_state").status, Status.UNKNOWN)   # 표본 5 < 20


class Cost(unittest.TestCase):
    def test_call_cost_matches_provider_table(self):
        E = engine([mc3(0, 100, inp=10, cr=1000, out=50, w1h=100, w5m=0)])
        m = [m for m in E.metrics.values() if m.name == "call_cost"][-1]
        self.assertAlmostEqual(m.value["total"], (10 * 1 + 50 * 5 + 1000 * 0.1 + 100 * 2) / 1e6)
        self.assertEqual(m.basis, Basis.PROVIDER_DECLARED)

    def test_unknown_model_or_missing_split_is_unknown(self):
        E = engine([mc3(0, 100, model="some-new-model")])
        m = [m for m in E.metrics.values() if m.name == "cost_estimate"][-1]
        self.assertEqual(m.status, Status.UNKNOWN)
        E = engine([mc(0, 100)])                                   # 5m/1h 나눔을 못 봤다
        m = [m for m in E.metrics.values() if m.name == "cost_estimate"][-1]
        self.assertEqual(m.status, Status.UNKNOWN)

    def test_estimate_error_uses_calls_up_to_report_time(self):
        calls = [mc3(0, 100, inp=10, cr=1000, out=50), mc3(1, 200, inp=10, cr=1000, out=50)]
        one = pricing.call_cost("claude-haiku-4-5", 10, 50, 1000, 0, 100)["total"]
        snap = end(cost_usd=one)
        snap["snapshot_at_ms"] = 150                                # 첫 호출 뒤의 스냅숏
        snap["unobserved"].remove("snapshot_at_ms")
        E = engine(calls + [snap])
        m = [m for m in E.metrics.values() if m.name == "cost_estimate_error"][-1]
        self.assertAlmostEqual(m.value, 0.0)

    def test_pricing_has_source_and_validation(self):
        self.assertIn("prompt-caching", pricing.SOURCE)
        for p in pricing.PRICES.values():
            self.assertTrue(p["validated"])
        self.assertIsNone(pricing.lookup("gpt-5"))


class Quality(unittest.TestCase):
    def test_external_label_only(self):
        E = engine([mc(0, 100), end()])
        self.assertEqual(val(E, T, "quality_state").status, Status.UNKNOWN)
        E.ingest(external_label_batch(RUN, True, "hidden tests", "x1"))
        v = val(E, T, "quality_state")
        self.assertEqual((v.value, v.basis), ("PASSED", Basis.EXTERNAL_LABEL))
        E2 = engine([mc(0, 100)])
        E2.ingest(external_label_batch(RUN, False, "hidden tests", "x1"))
        self.assertEqual(val(E2, T, "quality_state").value, "FAILED")


class Providers(unittest.TestCase):
    def test_errors_normalize(self):
        a = error("anthropic", 429, {"error": {"type": "rate_limit_error"}}, {"Retry-After": "12"})
        g = error("gemini", 429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"}]}})
        o = error("openai", 429)
        self.assertEqual({a.kind, g.kind, o.kind}, {ErrorKind.RATE_LIMITED})
        self.assertEqual((a.retry_after_ms, g.retry_after_ms, o.retry_after_ms), (12000.0, 30000.0, None))
        self.assertEqual(error("anthropic", 529).kind, ErrorKind.OVERLOADED)
        self.assertEqual(error("gemini", 504).kind, ErrorKind.DEADLINE_EXCEEDED)
        self.assertEqual(error("openai", 503).kind, ErrorKind.UNKNOWN)          # 출처 없는 대응은 하지 않는다
        self.assertEqual(error("anthropic", 418).kind, ErrorKind.UNKNOWN)
        with self.assertRaises(ValueError):
            error("mystery", 429)


if __name__ == "__main__":
    unittest.main()


class OwnerLayer(unittest.TestCase):
    def test_assess_marks_follow_bd35_bd52(self):
        # 이름 · 값은 그대로, 소유 층 표시만 -- BD-35(건강 성격 넷) + BD-52(liveness). 나머지는 상태 층(None)
        marked = {n for n, r in REGISTRY.rules.items() if r.owner_layer == "ASSESS"}
        self.assertEqual(marked, {"execution_health", "tool_execution_health", "execution_interruption",
                                  "runtime_reliability", "liveness_state"})
        self.assertEqual({r.owner_layer for n, r in REGISTRY.rules.items() if n not in marked}, {None})
        self.assertEqual(REGISTRY.state_definition("liveness_state")["owner_layer"], "ASSESS")


class Quota(unittest.TestCase):
    """S4 -- 한도 여유(계정 범위 값). 소진 예측은 하지 않는다."""

    def _m(self, E, name):
        ms = [m for i, m in E.metrics.items() if i.startswith(f"{R}/{name}@")]
        return max(ms, key=lambda m: int(str(m.id.rsplit("@", 1)[1]).split("+")[0]))

    def test_rejected_is_limited_in_v3_not_guessed_in_v2(self):
        E = engine([mc(0, 100), end(rate_limit_status="rejected", rate_limit_utilization=None)])
        self.assertEqual(val(E, R, "rate_limit_state").value, "LIMITED")
        Mx = {m.name: m for m in E.metrics.values() if m.entity_id == R}
        self.assertIn("추측 안 함", RATE_LIMIT_V2.fn(Mx, None, DEFAULT_CONFIG).reason)

    def test_headroom_is_one_minus_declared_utilization(self):
        E = engine([mc(0, 100), end(rate_limit_utilization=0.72)])
        self.assertEqual(self._m(E, "quota_headroom").value, 0.28)
        E = engine([mc(0, 100), end(rate_limit_utilization=None)])
        self.assertIsNone(self._m(E, "quota_headroom").value)

    def test_time_to_reset_only_on_unix_time(self):
        def recs(tb):
            m, e = mc(0, 1_790_884_000_000), end()
            m["time_base"] = tb
            e["rate_limit_resets_at_ms"] = 1_790_884_800_000          # 꼴 v3 에 아직 없는 칸 -- 정준 입력 계약만으로
            return [m, e]
        E = engine(recs("unix_ms"))
        self.assertEqual(self._m(E, "quota_time_to_reset_ms").value, 800_000)
        v = self._m(engine(recs("monotonic_ms")), "quota_time_to_reset_ms")
        self.assertIsNone(v.value)
        self.assertIn("unix ms 가 아니다", v.reason)
