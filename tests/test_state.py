import json
import unittest

from llmsensor.state import (DEFAULT_CONFIG, Basis, Freshness, Lifecycle, Status, StateEngine, canonical_usage,
                             from_telemetry, REGISTRY)
from llmsensor.state.config import Band
from llmsensor.state.rules import band
from llmsensor.telemetry.schema import record

RUN = "cc_stream:demo"


def mc(i, t, inp=10, cr=1000, cw=100, out=50, think=20, stop="tool_use", win=None, est=None, run=RUN):
    return record("model_call", run, "cc_stream", call_index=i, t_start_ms=t - 10, t_end_ms=t,
                  time_base="monotonic_ms", input_tokens=inp, cache_read_input_tokens=cr,
                  cache_creation_input_tokens=cw, output_tokens=out, thinking_tokens=think, stop_reason=stop,
                  tool_calls_per_message=1, output_text_chars=0, context_window=win, stream_thinking_estimate=est)


def tc(i, j, t, name="Bash", head="Bash:pytest", err=False, sig="s", run=RUN, src="cc_stream", known=True):
    return record("tool_call", run, src, call_index=i, tool_index=j, tool_name=name, tool_head=head, tool_sig=sig,
                  tool_input_chars=10, t_issued_ms=t - 5, t_result_ms=t, time_base="monotonic_ms",
                  is_error=err if known else None, tool_output_chars=3)


def end(run=RUN, **kw):
    base = dict(result_subtype="success", terminal_reason="completed", is_error=False, cost_usd=0.05,
                context_window=200000, autocompact_threshold=144000, rate_limit_utilization=0.5)
    base.update(kw)
    rn = [k for k, v in base.items() if v is None]
    if "api_error_status" not in kw:
        rn.append("api_error_status")
    return record("run", run, "cc_stream", reported_null=rn, **{k: v for k, v in base.items() if v is not None})


def engine(recs, cfg=DEFAULT_CONFIG):
    return StateEngine(cfg).ingest_all(from_telemetry(recs))


def val(E, ent, name, now=None):
    return E.query(ent, [name], now)[0]


A, T, R = f"agent:{RUN}", f"task:{RUN}", f"runtime:{RUN}"


class Unknown(unittest.TestCase):
    def test_no_tool_results_is_unknown_not_healthy(self):
        E = engine([mc(0, 100)])
        v = val(E, A, "execution_health")
        self.assertEqual((v.status, v.value), (Status.UNKNOWN, None))
        self.assertIn("증거도 없다", v.reason)

    def test_unobservable_outcome_is_unknown(self):
        E = engine([mc(0, 100), tc(0, 0, 110, known=False)])
        v = val(E, A, "execution_health")
        self.assertEqual(v.status, Status.UNKNOWN)
        self.assertIn("볼 수 없다", v.reason)

    def test_missing_field_not_filled_from_older_call(self):
        bad = mc(1, 200)
        bad["cache_creation_input_tokens"] = None
        bad["unobserved"].append("cache_creation_input_tokens")
        bad["context_window"] = 200000
        bad["unobserved"].remove("context_window")
        E = engine([mc(0, 100, win=200000), bad])          # 창은 안다 -- 모르는 것은 마지막 호출의 맥락뿐
        v = val(E, A, "context_pressure")
        self.assertEqual(v.status, Status.UNKNOWN)
        self.assertIn("메우지 않는다", v.reason)

    def test_reported_null_vs_absent(self):
        E = engine([mc(0, 100), end()])
        self.assertEqual(val(E, R, "runtime_reliability").value, "NO_FAILURE_OBSERVED")
        E2 = engine([end()])          # 호출도 없고 api_error_status 도 키가 없다
        r = end()
        r["reported_null"].remove("api_error_status")
        r["unobserved"].append("api_error_status")
        E2 = engine([r])
        self.assertEqual(val(E2, R, "runtime_reliability").status, Status.UNKNOWN)
        E5 = engine([end()])          # 호출 없이 '오류 보고 없음(보고된 null)' 만으로
        v = val(E5, R, "runtime_reliability")
        self.assertEqual(v.value, "NO_FAILURE_OBSERVED")
        self.assertIn("보고된 null", v.reason)
        E3 = engine([mc(0, 100), end(api_error_status="429")])
        self.assertEqual(val(E3, R, "runtime_reliability").value, "FAILURE_OBSERVED")
        E4 = engine([mc(0, 100, stop="max_tokens")])
        self.assertEqual(val(E4, R, "runtime_reliability").value, "FAILURE_OBSERVED")

    def test_query_undefined_is_unknown(self):
        E = engine([mc(0, 100)])
        self.assertEqual(val(E, A, "resource_state").status, Status.NOT_APPLICABLE)
        self.assertEqual(val(E, "agent:nope", "execution_health").status, Status.UNKNOWN)


class Execution(unittest.TestCase):
    def test_unresolved_recovered_none(self):
        self.assertEqual(val(engine([mc(0, 100), tc(0, 0, 110, err=True)]), A, "execution_health").value,
                         "UNRESOLVED_FAILURES")
        E = engine([mc(0, 100), tc(0, 0, 110, err=True), mc(1, 200), tc(1, 1, 210, err=False)])
        self.assertEqual(val(E, A, "execution_health").value, "RECOVERED_FAILURES")
        self.assertEqual(val(engine([mc(0, 100), tc(0, 0, 110)]), A, "execution_health").value, "NO_FAILURE_OBSERVED")

    def test_tools_are_independent_entities(self):
        E = engine([mc(0, 100), tc(0, 0, 110, "Bash", "Bash:make", err=True), tc(0, 1, 111, "Read", "Read:#ab")])
        self.assertEqual(val(E, f"tool:{RUN}:Bash", "tool_execution_health").value, "UNRESOLVED_FAILURES")
        self.assertEqual(val(E, f"tool:{RUN}:Read", "tool_execution_health").value, "NO_FAILURE_OBSERVED")
        rel = {(r.subject, r.predicate, r.object) for r in E.relationships.values()}
        self.assertIn((A, "uses", f"tool:{RUN}:Bash"), rel)
        self.assertIn((T, "executed_by", A), rel)

    def test_min_consecutive_suppresses_flapping(self):
        cfg = DEFAULT_CONFIG.with_(version="t", min_consecutive={"execution_health": 2})
        recs = [mc(0, 100), tc(0, 0, 110, err=True), mc(1, 200), tc(1, 1, 210, err=False)]
        E = engine(recs, cfg)
        # 실패 직후 한 번의 성공으로는 아직 안 바뀐다(대기). 같은 판정이 한 번 더 와야 바뀐다
        self.assertEqual(val(E, A, "execution_health").value, "UNRESOLVED_FAILURES")
        E = engine(recs + [mc(2, 300)], cfg)
        self.assertEqual(val(E, A, "execution_health").value, "RECOVERED_FAILURES")


class Context(unittest.TestCase):
    def test_runtime_declared_boundaries(self):
        E = engine([mc(0, 100, cr=150000, win=200000), end()])
        self.assertEqual(val(E, A, "context_pressure").value, "ABOVE_COMPACTION_THRESHOLD")
        E = engine([mc(0, 100, cr=100000, win=200000), end()])
        self.assertEqual(val(E, A, "context_pressure").value, "BELOW_COMPACTION_THRESHOLD")
        E = engine([mc(0, 100, cr=210000, win=200000)])
        self.assertEqual(val(E, A, "context_pressure").value, "AT_CONTEXT_LIMIT")
        E = engine([mc(0, 100, cr=100000, win=200000)])        # 압축 문턱 선언 전
        self.assertEqual(val(E, A, "context_pressure").value, "BELOW_CONTEXT_LIMIT")
        self.assertEqual(val(engine([mc(0, 100)]), A, "context_pressure").status, Status.UNKNOWN)

    def test_override_is_marked_assumed(self):
        E = engine([mc(0, 100)], DEFAULT_CONFIG.with_(version="o", context_window_override=1_000_000))
        self.assertEqual(val(E, A, "context_pressure").value, "BELOW_CONTEXT_LIMIT")
        ex = E.explain(A, "context_pressure")
        win = [n for n in ex["evidence"] if n["name"] == "context_window"][0]
        self.assertEqual(win["basis"], "OPERATOR_ASSUMED")
        self.assertEqual(ex["config"]["assumptions"]["context_window_override"], 1_000_000)

    def test_estimate_superseded_by_final(self):
        E = engine([mc(0, 100, est=300)])
        m = [m for m in E.metrics.values() if m.name == "reasoning_estimate"][-1]
        self.assertEqual(m.status, Status.INVALID)
        r = mc(0, 100, est=300)
        r["thinking_tokens"] = None
        r["unobserved"].append("thinking_tokens")
        E = engine([r])
        m = [m for m in E.metrics.values() if m.name == "reasoning_estimate"][-1]
        self.assertEqual((m.status, m.basis), (Status.DERIVED, Basis.ESTIMATE))


class Task(unittest.TestCase):
    def test_completion(self):
        self.assertEqual(val(engine([mc(0, 100)]), T, "completion_state").value, "RUNNING")
        E = engine([mc(0, 100), end()])
        v = val(E, T, "completion_state")
        self.assertEqual((v.value, v.freshness), ("ENDED_NORMALLY", Freshness.PERMANENT))
        self.assertIn("성공", v.reason)
        E = engine([mc(0, 100), end(result_subtype="error_max_turns", terminal_reason="max_turns", is_error=True)])
        self.assertEqual(val(E, T, "completion_state").value, "ENDED_BY_LIMIT")
        E = engine([mc(0, 100), end(result_subtype="weird", terminal_reason="weird", is_error=False)])
        self.assertEqual(val(E, T, "completion_state").status, Status.UNKNOWN)

    def test_final_state_is_not_reevaluated(self):
        E = engine([mc(0, 100), end()])
        n = len([e for e in E.lifecycle if e.name == "completion_state"])
        E.ingest_all(from_telemetry([mc(5, 900)]))          # 끝난 뒤 늦게 온 관측
        self.assertEqual(len([e for e in E.lifecycle if e.name == "completion_state"]), n)
        self.assertEqual(val(E, T, "completion_state").value, "ENDED_NORMALLY")

    def test_progress_needs_configured_threshold(self):
        recs = [mc(0, 100)] + [tc(0, j, 110 + j, sig="same") for j in range(4)]
        self.assertEqual(val(engine(recs), T, "progress_state").status, Status.UNKNOWN)
        cfg = DEFAULT_CONFIG.with_(version="s", stall_repeat_threshold=3)
        self.assertEqual(val(engine(recs, cfg), T, "progress_state").value, "STALLED")
        self.assertEqual(val(engine(recs[:2], cfg), T, "progress_state").value, "NO_STALL_DETECTED")
        self.assertEqual(val(engine(recs + [end()], cfg), T, "progress_state").status, Status.NOT_APPLICABLE)


class Resource(unittest.TestCase):
    def test_budget(self):
        self.assertEqual(val(engine([mc(0, 100), end()]), A, "resource_state").status, Status.NOT_APPLICABLE)
        cfg = DEFAULT_CONFIG.with_(version="b", cost_budget_usd=0.10)
        self.assertEqual(val(engine([mc(0, 100)], cfg), A, "resource_state").status, Status.UNKNOWN)
        self.assertEqual(val(engine([mc(0, 100), end(cost_usd=0.07)], cfg), A, "resource_state").value,
                         "WITHIN_BUDGET")
        self.assertEqual(val(engine([mc(0, 100), end(cost_usd=0.12)], cfg), A, "resource_state").value,
                         "BUDGET_EXHAUSTED")

    def test_bands_with_hysteresis(self):
        bands = (Band("MEDIUM", 0.5, 0.45), Band("HIGH", 0.75, 0.7))
        seq, prev = [], None
        for x in (0.4, 0.76, 0.72, 0.74, 0.69, 0.47, 0.44):
            prev = band(x, bands, prev)
            seq.append(prev)
        self.assertEqual(seq, ["LOW", "HIGH", "HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW"])
        self.assertEqual(band(0.72, bands, None), "MEDIUM")          # 이전 값이 없으면 enter 로만
        with self.assertRaises(ValueError):
            Band("X", 0.5, 0.6)

    def test_pressure_needs_bands(self):
        cfg = DEFAULT_CONFIG.with_(version="p", cost_budget_usd=0.10,
                                   resource_bands=(Band("MEDIUM", 0.5, 0.45), Band("HIGH", 0.75, 0.7)))
        v = val(engine([mc(0, 100), end(cost_usd=0.07)], cfg), A, "resource_pressure")
        self.assertEqual((v.value, v.basis), ("MEDIUM", Basis.OPERATOR_ASSUMED))


class Time(unittest.TestCase):
    def test_stale_after_ttl_and_tick(self):
        E = engine([mc(0, 100), tc(0, 0, 110)])
        self.assertEqual(val(E, A, "execution_health").freshness, Freshness.FRESH)
        later = 110 + DEFAULT_CONFIG.ttl_ms["execution_health"] + 1
        v = val(E, A, "execution_health", now=later)
        self.assertEqual((v.status, v.freshness, v.value), (Status.STALE, Freshness.STALE, "NO_FAILURE_OBSERVED"))
        ev = E.tick({RUN: later})
        self.assertTrue(any(e.event is Lifecycle.STALE and e.name == "execution_health" for e in ev))
        self.assertEqual(E.tick({RUN: later}), [])                    # 같은 낡음을 두 번 남기지 않는다

    def test_untimed(self):
        r = record("model_call", "sweagent:x", "sweagent", call_index=0, output_text_chars=1, tool_calls_per_message=1)
        t = record("tool_call", "sweagent:x", "sweagent", call_index=0, tool_index=0, tool_name="edit",
                   tool_head="edit", tool_sig="z", tool_output_chars=1)
        E = engine([r, t])
        v = val(E, "agent:sweagent:x", "execution_health")
        self.assertEqual((v.status, v.freshness), (Status.UNKNOWN, Freshness.UNTIMED))

    def test_lifecycle_and_transitions(self):
        E = engine([mc(0, 100), tc(0, 0, 110), mc(1, 200), tc(1, 1, 210, err=True), mc(2, 300)])
        evs = [e.event for e in E.lifecycle if e.entity_id == A and e.name == "execution_health"]
        self.assertEqual(evs[0], Lifecycle.CREATE)
        self.assertIn(Lifecycle.RECOVER, evs)       # UNKNOWN -> NO_FAILURE_OBSERVED
        self.assertIn(Lifecycle.UPDATE, evs)        # NO_FAILURE -> UNRESOLVED
        self.assertIn(Lifecycle.REFRESH, evs)
        tr = [t for t in E.transitions if t.entity_id == A and t.name == "execution_health"]
        self.assertEqual([(t.previous, t.new) for t in tr],
                         [(None, "NO_FAILURE_OBSERVED"), ("NO_FAILURE_OBSERVED", "UNRESOLVED_FAILURES")])
        self.assertTrue(all(t.evidence and t.at is not None for t in tr))

    def test_invalidate(self):
        E = engine([mc(0, 100), tc(0, 0, 110)])
        E.invalidate(A, "execution_health", "도구 기록이 손상됨", at=120)
        v = val(E, A, "execution_health")
        self.assertEqual(v.status, Status.INVALID)
        self.assertTrue(any(e.event is Lifecycle.INVALIDATE for e in E.lifecycle))


class Provenance(unittest.TestCase):
    def test_chain_reaches_observations(self):
        E = engine([mc(0, 100, cr=150000, win=200000), tc(0, 0, 110, err=True), end()])
        for (ent, name), st in E.current.items():
            if st.status.usable:
                ids = E.observation_ids(ent, name)
                self.assertTrue(ids, (ent, name))
                self.assertTrue(ids <= set(E.observations), (ent, name))
        ex = E.explain(A, "execution_health")
        self.assertEqual(ex["rule"]["id"], "execution-health-v1")
        self.assertEqual(ex["state"]["config_version"], "default-v1")

    def test_proposal_never_becomes_state(self):
        E = engine([mc(0, 100), tc(0, 0, 110)])
        before = E.snapshot()
        E.propose(A, "execution_health", "FAILING", "llm", "I think the runtime is failing")
        self.assertEqual(E.snapshot(), before)
        self.assertEqual(val(E, A, "execution_health").value, "NO_FAILURE_OBSERVED")
        self.assertEqual(len(E.proposals), 1)


class Determinism(unittest.TestCase):
    def test_same_input_same_state_any_order(self):
        recs = [mc(0, 100), tc(0, 0, 110, err=True), mc(1, 200), tc(1, 1, 210), end(),
                mc(0, 50, run="cc_stream:other"), end(run="cc_stream:other")]
        a = engine(recs).snapshot()
        b = engine(list(reversed(recs))).snapshot()
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))


class Idempotent(unittest.TestCase):
    def test_duplicate_batch_is_ignored(self):
        recs = [mc(0, 100), tc(0, 0, 110, err=True)]
        E = engine(recs)
        snap = E.snapshot()
        self.assertFalse(any(E.ingest(b) for b in from_telemetry(recs)))     # 재전송
        self.assertEqual(E.snapshot(), snap)
        E2 = engine([mc(0, 100, stop="end_turn")])
        E2.ingest_all(from_telemetry([mc(0, 100, stop="end_turn")]))
        m = [m for m in E2.metrics.values() if m.name == "stop_reasons"][-1]
        self.assertEqual(m.value["observed"], 1)


class DecisionContext(unittest.TestCase):
    def test_minimal_and_semantic_only(self):
        E = engine([mc(0, 100, cr=150000, win=200000), tc(0, 0, 110, err=True)])
        d = E.decision_context(RUN)
        s = json.dumps(d, ensure_ascii=False)
        for raw in ("cache_read", "input_tokens", "tokens.", "tool_targets", "observation"):
            self.assertNotIn(raw, s)
        self.assertEqual(d["execution"]["health"]["value"], "UNRESOLVED_FAILURES")
        self.assertIn("task.progress=UNKNOWN", d["uncertain"])
        self.assertIn("resources.budget", d["not_applicable"])
        self.assertNotIn("budget", d["resources"])


class Providers(unittest.TestCase):
    def test_same_meaning_across_providers(self):
        a, _ = canonical_usage("anthropic", {"input_tokens": 100, "cache_read_input_tokens": 900,
                                             "cache_creation_input_tokens": 0, "output_tokens": 50,
                                             "output_tokens_details": {"thinking_tokens": 20}})
        o, on = canonical_usage("openai", {"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 900},
                                           "completion_tokens": 50,
                                           "completion_tokens_details": {"reasoning_tokens": 20}})
        g, gn = canonical_usage("gemini", {"prompt_token_count": 1000, "cached_content_token_count": 900,
                                           "candidates_token_count": 30, "thoughts_token_count": 20})
        for k in ("tokens.input_uncached", "tokens.cache_read", "tokens.output", "tokens.reasoning"):
            self.assertEqual(a[k], o[k], k)
            self.assertEqual(a[k], g[k], k)
        self.assertNotIn("tokens.cache_write", g)                    # 못 본 칸은 넣지 않는다
        self.assertTrue(on and gn)
        with self.assertRaises(ValueError):
            canonical_usage("mystery", {})


class Registry(unittest.TestCase):
    def test_definitions_are_consistent(self):
        self.assertEqual(REGISTRY.check(), [])
        for r in REGISTRY.rules.values():
            self.assertTrue(r.meaning and r.decision and r.id.endswith(f"-v{r.version}"))
            # 문턱 출처는 과제가 허용한 넷(런타임 · 공급자 · 운영자 · 검증 실험) + 정의상 + 외부 라벨뿐
            self.assertIn(r.basis, (Basis.DEFINITIONAL, Basis.RUNTIME_DECLARED, Basis.OPERATOR_ASSUMED,
                                    Basis.PROVIDER_DECLARED, Basis.VALIDATED_EXPERIMENT, Basis.EXTERNAL_LABEL))
            d = REGISTRY.state_definition(r.state, DEFAULT_CONFIG)
            self.assertIn("UNKNOWN", d["allowed_values"])
        self.assertGreaterEqual(len(REGISTRY.candidates), 10)
        names = set(REGISTRY.rules)
        self.assertLessEqual(len(names), 12)                          # 상태는 적어야 한다(압축)


if __name__ == "__main__":
    unittest.main()
