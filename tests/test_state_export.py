"""내보내기 계약(llmsensor.state-export/1) -- 상태 층 밖(cogito5170/DC 등)이 기대는 꼴을 붙든다.

칸을 빼거나 이름 · 뜻을 바꾸면 여기가 빨개진다 -- 그러면 판본을 올려야 한다(/2).
"""
import json
import unittest

from llmsensor.state import REGISTRY, StateEngine, from_telemetry
from llmsensor.state.export import CONTRACT, FIELDS
from tests.test_state import RUN, end, mc, tc

A = f"agent:{RUN}"
RAW_VALUES = (1000, 100, 50, 20, 200000, 144000)     # 레코드에 넣은 원 측정값


def engine(with_end=True):
    recs = [mc(0, 100, cr=1000, win=200000), tc(0, 0, 110, err=True), mc(1, 200), tc(1, 1, 210, name="Read",
                                                                                   head="Read:#a")]
    return StateEngine().ingest_all(from_telemetry(recs + ([end()] if with_end else [])))


class Contract(unittest.TestCase):
    def test_version_and_fields_are_pinned(self):
        E = engine()
        self.assertEqual(E.EXPORT_CONTRACT, CONTRACT)
        self.assertEqual(CONTRACT, "llmsensor.state-export/1")
        for name in REGISTRY.rules:
            for ent in (A, f"task:{RUN}", f"runtime:{RUN}"):
                d = E.export_state(ent, name)
                self.assertEqual(tuple(d), FIELDS, f"{ent} {name}")
                json.dumps(d)

    def test_catalog_matches_registry(self):
        c = engine().state_catalog()
        self.assertEqual(c["contract"], CONTRACT)
        self.assertEqual(set(c["states"]), set(REGISTRY.rules))
        r = REGISTRY.rules["execution_health"]
        self.assertEqual(c["states"]["execution_health"]["values"], list(r.values))
        self.assertIn("UNKNOWN", c["common_statuses"])

    def test_missing_or_undefined_state_is_unknown_not_guessed(self):
        E = StateEngine()
        d = E.export_state(A, "execution_health")
        self.assertEqual((d["value"], d["status"], d["evidence_refs"]), (None, "UNKNOWN", []))
        d = E.export_state(A, "no_such_state")
        self.assertEqual((d["status"], d["rule_id"]), ("UNKNOWN", None))

    def test_evidence_is_ids_not_raw_values(self):
        E = engine()
        for name in REGISTRY.rules:
            d = E.export_state(A, name)
            for ref in d["evidence_refs"]:
                self.assertIsInstance(ref, str)
                self.assertIn(ref, E.metrics)          # 지표 id -- explain() 으로 관측까지 펼 수 있다
            self.assertNotIn("observations", d)
            self.assertNotIn("metrics", d)
        blob = json.dumps({n: E.export_state(A, n)["value"] for n in REGISTRY.rules})
        for raw in RAW_VALUES:
            self.assertNotIn(str(raw), blob)

    def test_staleness_and_final_pass_through(self):
        E = engine()
        late = E.as_of(RUN)["at"] + 45 * 60_000
        self.assertEqual(E.export_state(A, "execution_health", now=late)["status"], "STALE")
        self.assertTrue(E.export_state(f"task:{RUN}", "completion_state", now=late)["final"])

    def test_copies_not_views(self):
        E = engine()
        d = E.export_state(A, "execution_health")
        d["value"], d["evidence_refs"][:] = "HACKED", []
        again = E.export_state(A, "execution_health")
        self.assertNotEqual(again["value"], "HACKED")
        self.assertTrue(again["evidence_refs"])

    def test_llm_proposal_never_exported(self):
        E = engine()
        before = E.export_state(A, "execution_health")
        E.propose(A, "execution_health", "FAILING", "llm", "생각에 실패 중")
        self.assertEqual(E.export_state(A, "execution_health"), before)

    def test_subjects_and_as_of(self):
        E = engine()
        s = E.subjects(RUN)
        self.assertEqual(s["agent"], A)
        self.assertEqual(s["tool"], [f"tool:{RUN}:Bash", f"tool:{RUN}:Read"])
        a = E.as_of(RUN)
        self.assertEqual((a["time_base"], a["at"] is not None), ("monotonic_ms", True))
        self.assertIsNone(E.as_of("nope")["at"])

    def test_export_module_reads_no_decision_or_verdict(self):
        import ast
        import inspect
        from llmsensor.state import export
        mods = {n.module for n in ast.walk(ast.parse(inspect.getsource(export))) if isinstance(n, ast.ImportFrom)}
        self.assertFalse([m for m in mods if m and any(k in m for k in ("decision", "policy", "verifier", "fusion"))])


if __name__ == "__main__":
    unittest.main()
