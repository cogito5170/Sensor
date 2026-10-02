import dataclasses
import json
import unittest

from llmsensor.decision.context import PURPOSES, ContextBuilder, ContextStore
from llmsensor.policy import context as cpol, execution as epol, provider as ppol
from llmsensor.state import DEFAULT_CONFIG, StateEngine, from_telemetry
from tests.test_state import RUN, end, mc, tc

CAP = {"compaction": True, "providers": 2}


def build(recs, purpose, cfg=DEFAULT_CONFIG, **kw):
    E = StateEngine(cfg).ingest_all(from_telemetry(recs))
    return E, ContextBuilder(E).build(RUN, purpose, **kw)


class Projection(unittest.TestCase):
    def test_purpose_selects_only_needed_states(self):
        recs = [mc(0, 100, cr=150000, win=200000), tc(0, 0, 110, err=True), end()]
        _, c = build(recs, "select_provider", capabilities=CAP)
        self.assertEqual({s.name for s in c.states}, {"runtime_reliability", "rate_limit_state"})
        _, c = build(recs, "manage_context", capabilities=CAP)
        self.assertIn("context_pressure", {s.name for s in c.states})
        self.assertNotIn("rate_limit_state", {s.name for s in c.states})
        self.assertEqual(dict(c.omitted), {})

    def test_no_raw_telemetry_or_reason_text(self):
        _, c = build([mc(0, 100, cr=150000, win=200000), tc(0, 0, 110, err=True)], "optimize_llm_request",
                     capabilities=CAP)
        body = json.dumps([dataclasses.asdict(s) for s in c.states], ensure_ascii=False)
        for raw in ("tokens.", "cache_read", "150000", "맥락", "observation"):
            self.assertNotIn(raw, body)
        for s in c.states:
            self.assertTrue(s.rule_id and s.rule_version)

    def test_frozen_and_unaffected_by_later_state(self):
        E, c = build([mc(0, 100), tc(0, 0, 110, err=True)], "continue_or_stop", capabilities=CAP)
        before = (c.context_id, c.states, c.explain())
        E.ingest_all(from_telemetry([mc(1, 200), tc(1, 1, 210), end()]))
        self.assertEqual((c.context_id, c.states, c.explain()), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.validity = "VALID"
        c2 = ContextBuilder(E).build(RUN, "continue_or_stop", capabilities=CAP)
        self.assertNotEqual(c2.context_id, c.context_id)          # 새 상태에서 만든 것은 다르다

    def test_deterministic_id(self):
        recs = [mc(0, 100), tc(0, 0, 110)]
        _, a = build(recs, "manage_context", capabilities=CAP)
        _, b = build(recs, "manage_context", capabilities=CAP)
        _, d = build(recs, "continue_or_stop", capabilities=CAP)
        self.assertEqual(a.context_id, b.context_id)
        self.assertNotEqual(a.context_id, d.context_id)


class Validity(unittest.TestCase):
    def test_stale_is_not_usable_unless_allowed(self):
        recs = [mc(0, 100, cr=150000, win=200000), end()]
        later = 100 + DEFAULT_CONFIG.ttl_ms["context_pressure"] + 1
        _, c = build(recs, "manage_context", now=later, capabilities=CAP)
        s = c.get("context_pressure")
        self.assertEqual((s.status, s.usable, c.validity), ("STALE", False, "DEGRADED"))
        self.assertIsNone(c.value("context_pressure"))
        self.assertEqual(c.value("context_pressure", allow_stale=True), "ABOVE_COMPACTION_THRESHOLD")
        _, c2 = build(recs, "manage_context", now=later, capabilities=CAP, allow_stale=("context_pressure",))
        self.assertTrue(c2.get("context_pressure").usable and c2.get("context_pressure").stale_allowed)
        self.assertEqual(c2.validity, "VALID")

    def test_unknown_required_degrades(self):
        _, c = build([mc(0, 100)], "manage_context", capabilities=CAP)      # 창도 문턱도 없음
        self.assertEqual((c.get("context_pressure").status, c.validity), ("UNKNOWN", "DEGRADED"))

    def test_constraints_pass_through_and_reject_objectives(self):
        _, c = build([mc(0, 100)], "select_provider", constraints={"max_cost_usd": 0.1, "max_latency_ms": 5000})
        self.assertEqual(dict(c.constraints), {"max_cost_usd": 0.1, "max_latency_ms": 5000})
        with self.assertRaises(ValueError):
            build([mc(0, 100)], "select_provider", constraints={"minimize": "cost"})
        with self.assertRaises(TypeError):
            build([mc(0, 100)], "select_provider", constraints={"max_cost_usd": "cheap"})
        with self.assertRaises(KeyError):
            build([mc(0, 100)], "make_coffee")


class Actions(unittest.TestCase):
    def test_actions_are_facts_not_choices(self):
        recs = [mc(0, 100), end()]
        _, c = build(recs, "select_provider", capabilities={"providers": 1})
        self.assertNotIn("SWITCH_PROVIDER", c.available_actions)
        _, c = build(recs, "manage_context", capabilities={})
        self.assertNotIn("COMPACT_CONTEXT", c.available_actions)
        _, c = build(recs, "continue_or_stop", capabilities=CAP)                # 끝난 실행
        self.assertEqual(c.available_actions, ("ESCALATE",))
        _, c = build([mc(0, 100)], "continue_or_stop", capabilities=CAP)
        self.assertEqual(set(c.available_actions), {"CONTINUE", "RETRY", "STOP", "ESCALATE"})

    def test_explain_reaches_observations(self):
        E, c = build([mc(0, 100), tc(0, 0, 110, err=True)], "continue_or_stop", capabilities=CAP)
        S = ContextStore()
        S.put(c)
        chain = S.explain(c.context_id)["chains"]["execution_health"]
        obs = json.dumps(chain)
        self.assertIn("#tool.is_error", obs)
        self.assertEqual(chain["rule"]["id"], "execution-health-v1")


class Policies(unittest.TestCase):
    def test_context_policy(self):
        _, c = build([mc(0, 100, cr=150000, win=200000), end()], "manage_context", capabilities=CAP)
        self.assertEqual(cpol.decide(c).action, "COMPACT_CONTEXT")
        _, c = build([mc(0, 100, cr=150000, win=200000), end()], "manage_context", capabilities={})
        self.assertEqual(cpol.decide(c).action, "REDUCE_CONTEXT")             # 압축이 불가능하면
        _, c = build([mc(0, 100)], "manage_context", capabilities=CAP)
        d = cpol.decide(c)
        self.assertEqual(d.action, "KEEP_CONTEXT")
        self.assertIn("모른다", d.reason)

    def test_provider_policy(self):
        _, c = build([mc(0, 100), end(api_error_status="429")], "select_provider", capabilities=CAP)
        self.assertEqual(ppol.decide(c).action, "SWITCH_PROVIDER")
        _, c = build([mc(0, 100), end(api_error_status="429")], "select_provider", capabilities={"providers": 1})
        self.assertEqual(ppol.decide(c).action, "WAIT")
        _, c = build([mc(0, 100), end()], "select_provider", capabilities=CAP)
        self.assertEqual(ppol.decide(c).action, "STAY_PROVIDER")

    def test_execution_policy(self):
        _, c = build([mc(0, 100), tc(0, 0, 110, err=True)], "continue_or_stop", capabilities=CAP)
        self.assertEqual(epol.decide(c).action, "RETRY")
        _, c = build([mc(0, 100), tc(0, 0, 110)], "continue_or_stop", capabilities=CAP)
        self.assertEqual(epol.decide(c).action, "CONTINUE")

    def test_policies_only_choose_available_actions_and_are_reproducible(self):
        cases = [[mc(0, 100)], [mc(0, 100, cr=150000, win=200000), tc(0, 0, 110, err=True)],
                 [mc(0, 100), end(api_error_status="429")], [mc(0, 100), end()]]
        for recs in cases:
            for cap in (CAP, {}, {"providers": 1}):
                for purpose, pol in (("manage_context", cpol), ("select_provider", ppol),
                                     ("continue_or_stop", epol)):
                    _, c = build(recs, purpose, capabilities=cap)
                    d1, d2 = pol.decide(c), pol.decide(c)
                    self.assertEqual(d1, d2)
                    self.assertTrue(d1.action is None or d1.action in c.available_actions, (purpose, d1))
                    self.assertTrue(set(d1.used) <= {s.name for s in c.states} | {n.state for n in
                                                                                  PURPOSES[purpose].needs})


if __name__ == "__main__":
    unittest.main()
