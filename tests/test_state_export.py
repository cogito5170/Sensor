"""내보내기 계약(llmsensor.state-export/2) -- 상태 층 밖(cogito5170/DC 등)이 기대는 꼴을 붙든다.

칸을 빼거나 이름 · 뜻을 바꾸면 여기가 빨개진다 -- 그러면 판본을 올려야 한다(/3). 소유: DC 세션(baseline BD-56).
"""
import json
import unittest

from llmsensor.state import REGISTRY, StateEngine, from_telemetry
from llmsensor.state.export import CONTRACT, FIELDS, entity_ref
from tests.test_state import RUN, end, mc, tc

A = f"agent:{RUN}"
RAW_VALUES = (1000, 100, 50, 20, 200000, 144000)     # 레코드에 넣은 원 측정값


def engine(with_end=True):
    recs = [mc(0, 100, cr=1000, win=200000), tc(0, 0, 110, err=True), mc(1, 200), tc(1, 1, 210, name="Read",
                                                                                   head="Read:#a")]
    return StateEngine().ingest_all(from_telemetry(recs + ([end()] if with_end else [])))


class Contract(unittest.TestCase):
    def test_v2_entity_ref_time_base_and_vocabularies(self):
        """/2 (CMD-D7): 실체 id 꼴 <유형>:<범위>:<지역>(BD-32) · 시각 기준(BD-33) · 근거 종류 8 개 · reason 없음."""
        from llmsensor.state.model import Basis
        E = engine()
        d = E.export_state(A, "execution_health")
        self.assertEqual(d["entity_ref"], {"type": "agent", "scope": RUN, "local": None})
        self.assertEqual(entity_ref(f"tool:{RUN}:Bash"), {"type": "tool", "scope": RUN, "local": "Bash"})
        self.assertEqual(d["time_base"], "monotonic_ms")
        self.assertNotIn("reason", d)
        c = E.state_catalog()
        self.assertEqual(c["bases"], [b.value for b in Basis])
        self.assertEqual(len(c["bases"]), 8)
        self.assertIn(d["time_base"], c["time_bases"])
        self.assertEqual(E.subjects(RUN)["scope"], RUN)
        for name in REGISTRY.rules:                       # 모든 상태의 근거 종류가 catalog 어휘 안에 있다
            self.assertIn(E.export_state(A, name)["basis"], c["bases"])
        self.assertIsNone(StateEngine().export_state(A, "execution_health")["time_base"])   # 모르는 실행은 null

    def test_version_and_fields_are_pinned(self):
        E = engine()
        self.assertEqual(E.EXPORT_CONTRACT, CONTRACT)
        self.assertEqual(CONTRACT, "llmsensor.state-export/2")
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



class ActionEntity(unittest.TestCase):
    """/2 에 더함 (baseline CMD-D16 · BD-108 · BD-110): 실행기의 행동 실체 action:<실행>:<command_id>.
    사건은 Telemetry Recorder 로 짓는다 -- 실행 id · command_id 에 `:` 가 든 경우와, 한 실행 id 가 다른 실행 id 의 접두인 경우까지."""

    RUNS = ("cc_stream:demo", "cc_stream")          # 둘째는 첫째의 접두 -- 접두로 고르면 섞인다

    @classmethod
    def setUpClass(cls):
        import itertools
        from llmsensor.telemetry.l0 import require
        require()
        from telemetry.compat import to_sensor_records
        from telemetry.hashing import Hasher
        from telemetry.ledger import MemorySink
        from telemetry.recorder import Recorder
        from llmsensor.sensing.l0 import batches
        events = []
        for run in cls.RUNS:
            clock, mono, sink = itertools.count(1_790_000_000_000, 1000), itertools.count(0, 10), MemorySink()
            rec = Recorder(run, sink, source="inproc:ms", wall=lambda c=clock: next(c), mono=lambda m=mono: next(m),
                           hasher=Hasher(b"k" * 32))
            with rec.action("RETURN", decision_ref="d1", action_ref="sha:ab:12") as a:     # command_id 에 ':'
                a.result(is_error=False, exit_code=0)
            with rec.action("RETRY") as a:                                                 # 기본 ref <실행>/a<n>
                a.result(is_error=True, exit_code=2)
            if run == "cc_stream":          # id 가 action:cc_stream:demo:z -- 가장 긴 접두로는 실행 cc_stream:demo 로 잘못 간다
                with rec.action("RETURN", action_ref="demo:z") as a:
                    a.result(is_error=False, exit_code=0)
            events += sink.events
        cls.E = StateEngine()
        cls.E.ingest_all(from_telemetry(to_sensor_records(events)))
        cls.E.ingest_all(batches(events))

    def actions(self, run):
        return sorted(e for (e, n) in self.E.current if n == "action_state" and self.E._ent_run.get(e) == run)

    def test_read_splits_run_and_command_id(self):
        for run in self.RUNS:
            ents = self.actions(run)
            self.assertEqual(len(ents), 3 if run == "cc_stream" else 2, run)
            for ent in ents:
                d = self.E.export_state(ent, "action_state")
                ref = d["entity_ref"]
                self.assertEqual((ref["type"], ref["scope"]), ("action", run), ent)
                self.assertEqual(f"action:{ref['scope']}:{ref['local']}", ent)
                self.assertIn(ref["local"], ("sha:ab:12", f"{run}/a0", "demo:z"))
                self.assertEqual(d["time_base"], self.E.as_of(run)["time_base"])          # 실행을 찾았다
                self.assertIsNotNone(d["time_base"])
                self.assertEqual(tuple(d), FIELDS)
                self.assertIn(d["value"], ("COMPLETED", "FAILED"))

    def test_engine_memory_beats_the_longest_prefix(self):
        ref = self.E.export_state("action:cc_stream:demo:z", "action_state")["entity_ref"]
        self.assertEqual((ref["scope"], ref["local"]), ("cc_stream", "demo:z"))
        self.assertIn("action:cc_stream:demo:z", self.E.subjects("cc_stream")["action"])
        self.assertNotIn("action:cc_stream:demo:z", self.E.subjects("cc_stream:demo")["action"])

    def test_subjects_hold_only_that_runs_actions(self):
        for run in self.RUNS:
            s = self.E.subjects(run)
            self.assertEqual(s["action"], self.actions(run))
            self.assertTrue(all(self.E.export_state(e, "action_state")["entity_ref"]["scope"] == run for e in s["action"]))
        self.assertEqual(StateEngine().subjects("nope")["action"], [])

    def test_unseen_action_in_a_known_run_and_no_engine(self):
        ref = self.E.export_state("action:cc_stream:demo:cmd-9", "action_state")["entity_ref"]
        self.assertEqual((ref["scope"], ref["local"]), ("cc_stream:demo", "cmd-9"))      # 가장 긴 아는 실행 id
        self.assertEqual(entity_ref("action:cc_stream:demo:cmd-9"),                        # 엔진 없이는 가르지 않는다
                         {"type": "action", "scope": None, "local": None})
        ref = self.E.export_state("action:nowhere:cmd-1", "action_state")["entity_ref"]
        self.assertEqual((ref["scope"], ref["local"]), (None, None))

    def test_other_entities_unchanged(self):
        """대조: tool · agent · task · runtime 의 entity_ref 는 엔진이 있든 없든 예전 그대로다."""
        for ent, want in ((f"tool:{RUN}:Bash", {"type": "tool", "scope": RUN, "local": "Bash"}),
                          ("tool:cc_stream:demo:Bash", {"type": "tool", "scope": "cc_stream:demo", "local": "Bash"}),
                          (A, {"type": "agent", "scope": RUN, "local": None}),
                          ("task:cc_stream:demo", {"type": "task", "scope": "cc_stream:demo", "local": None}),
                          ("runtime:cc_stream:demo", {"type": "runtime", "scope": "cc_stream:demo", "local": None})):
            self.assertEqual(entity_ref(ent), want, ent)
            self.assertEqual(entity_ref(ent, self.E), want, ent)
        s = self.E.subjects("cc_stream:demo")
        self.assertEqual((s["scope"], s["agent"], s["task"], s["runtime"]),
                         ("cc_stream:demo", "agent:cc_stream:demo", "task:cc_stream:demo", "runtime:cc_stream:demo"))


if __name__ == "__main__":
    unittest.main()
