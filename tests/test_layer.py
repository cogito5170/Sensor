"""L0 / L1 경계 -- (1) 문턱 있는 판독은 telemetry/derive 가 아니라 sensing 에 있다, (2) L0 Telemetry 는 선택 의존이다."""
import gzip
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

from llmsensor.sensing.token.events import token_events
from llmsensor.telemetry import l0
from llmsensor.telemetry.collect import from_cc_jsonl
from llmsensor.telemetry.derive import by_run, calls
from tests.helpers import write_session

ROOT = pathlib.Path(__file__).resolve().parents[1]
TELEMETRY = ROOT.parent / "Telemetry"
RECORDS = ROOT / "eval" / "results" / "sensor_layer_records.jsonl.gz"
# 옮기기 전(llmsensor/telemetry/derive.py 안) 출력의 지문 -- 실데이터 313 실행 · 9538 호출
BEFORE_MOVE = "631a0d000ed2b62f17f1f4c552548b6fad4a67052c132f4df67d807fc37f84e4"


class TokenReadingsMoved(unittest.TestCase):
    def test_derive_holds_arithmetic_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, [("user", "go"), ("text", "a"), ("text", "b"), ("text", "c"), ("text", "d"), ("text", "e")])
            rows = calls(by_run(from_cc_jsonl(p, "x"))["x"])
        for r in rows:
            self.assertFalse({"token_burst", "token_stagnation", "token_oscillation"} & set(r))

    @unittest.skipUnless(RECORDS.exists(), "실데이터 레코드가 없다")
    def test_same_readings_as_before_the_move(self):
        recs = [json.loads(x) for x in gzip.open(RECORDS, "rt", encoding="utf-8")]
        runs = by_run(recs)
        rows = [(rid, e["step_index"], e["token_burst"], e["token_stagnation"], e["token_oscillation"])
                for rid in sorted(runs) for e in token_events(calls(runs[rid]))]
        self.assertEqual(len(rows), 9538)
        self.assertEqual(hashlib.sha256(json.dumps(rows).encode()).hexdigest(), BEFORE_MOVE)

    def test_burst_semantics(self):
        rows = [{"run_id": "r", "step_index": i, "output_tokens": o, "context_growth": None, "context_tokens": None}
                for i, o in enumerate([10, 10, 10, 41, 40, None])]
        ev = token_events(rows)
        self.assertEqual([e["token_burst"] for e in ev], [None, None, None, True, False, None])   # 앞 3 호출은 판정 안 함


def _session(d):
    p = os.path.join(d, "s.jsonl")
    write_session(p, [("user", "go"), ("tool", "Bash", {"command": "make"}, False, "err"),
                      ("tool", "Read", {"file_path": "/a/b"}, True, "ok"), ("text", "done")])
    return p


class CollectorDefectsFixed(unittest.TestCase):
    """D1 · D2 (docs/MS_HEALTH_INVENTORY.md §1) -- L0 수집기와 같은 규칙. 고치기 전에는 이 시험이 빨갛다."""

    def _recs(self, rows):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for x in rows:
                    f.write(json.dumps(x) + "\n")
            return from_cc_jsonl(p, "x")

    def test_d1_timeout_structured_first_and_no_quoted_phrase(self):
        def tool(i, ok, out, tur):
            return [{"type": "assistant", "timestamp": f"2026-10-02T00:00:{i:02d}Z", "message": {
                        "id": f"m{i}", "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash",
                                                    "input": {"command": "x"}}]}},
                    {"type": "user", "timestamp": f"2026-10-02T00:00:{i + 1:02d}Z", "toolUseResult": tur, "message": {
                        "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "is_error": not ok,
                                     "content": out}]}}]
        recs = self._recs(tool(0, True, "log: Command timed out after 2m", {}) +
                          tool(2, True, "moved to the background", {"timedOutAfterMs": 600000, "backgroundTaskId": "b"}) +
                          tool(4, False, "Exit code 143\nCommand timed out after 2m 0.0s", {}))
        self.assertEqual([r["timed_out"] for r in recs if r["kind"] == "tool_call"], [False, True, True])

    def test_d2_api_error_line_is_not_a_model_call(self):
        recs = self._recs([
            {"type": "assistant", "timestamp": "2026-10-02T00:00:01Z", "message": {
                "id": "m1", "model": "claude-x", "usage": {"input_tokens": 1, "output_tokens": 1}, "content": []}},
            {"type": "assistant", "timestamp": "2026-10-02T00:00:02Z", "isApiErrorMessage": True, "apiErrorStatus": 429,
             "error": "rate_limit", "quotaLimits": {"status": "rejected"},
             "message": {"id": "e1", "model": "<synthetic>", "usage": {"input_tokens": 0, "output_tokens": 0}}},
            {"type": "assistant", "timestamp": "2026-10-02T00:00:03Z", "message": {
                "id": "s1", "model": "<synthetic>", "usage": {}, "content": []}}])
        self.assertEqual([r["model"] for r in recs if r["kind"] == "model_call"], ["claude-x"])
        run = [r for r in recs if r["kind"] == "run"][0]
        self.assertEqual((run["api_error_status"], run["rate_limit_status"]), ("429", "rejected"))


class RequiredL0(unittest.TestCase):
    """CMD-T9: L0 Telemetry 는 필수 의존이다. 없으면 수집을 부를 때 분명한 ImportError -- 상태 층만 쓰는 import 는 깨지지 않는다."""

    def test_missing_l0_is_a_clear_error(self):
        import subprocess
        prog = ("import llmsensor, llmsensor.state\n"                      # 수집을 안 쓰는 쪽은 그대로 돈다
                "from llmsensor.telemetry import l0\n"
                "assert not l0.available()\n"
                "try:\n"
                "    import llmsensor.telemetry.collect\n"
                "except ImportError as e:\n"
                "    print('IMPORT-ERROR', e)\n")
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, PYTHONPATH=str(ROOT), LLMSENSOR_L0_SIBLING="0")
            p = subprocess.run([sys.executable, "-c", prog], cwd=d, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("IMPORT-ERROR", p.stdout)
        self.assertIn("cogito5170/Telemetry", p.stdout)                  # 무엇을 깔지 말한다

    def test_impostor_named_telemetry_is_refused(self):
        with mock.patch.dict(sys.modules, {"telemetry": types.ModuleType("telemetry")}):
            self.assertFalse(l0.available())
            with self.assertRaises(ImportError) as cm:
                l0.require()
            self.assertIn("다른 패키지", str(cm.exception))


@unittest.skipUnless((TELEMETRY / "telemetry").is_dir(), "옆에 ../Telemetry 가 없다")
class WithL0(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(TELEMETRY) not in sys.path:
            sys.path.insert(0, str(TELEMETRY))

    def test_collect_is_l0_and_invariants_hold(self):
        self.assertTrue(l0.available())
        with tempfile.TemporaryDirectory() as d:
            p = _session(d)
            for prefer in (True, False):                                  # 옛 인자는 남았지만 길은 하나다
                recs, backend = l0.collect("cc_jsonl", p, "x", prefer_l0=prefer)
                self.assertEqual(backend, "l0")
            self.assertEqual(recs, from_cc_jsonl(p, "x"))               # 이음매 == l0.collect
            r = l0.compare("cc_jsonl", p)
        self.assertTrue(r["same"], r)
        self.assertEqual((r["against"], r["native"], r["deterministic"], r["state_ingest"]),
                         ("invariants", None, True, True))

    def test_inproc_ledger_passes_v4_schema(self):
        """CMD-T3: 프로세스 안 계측 원장(source = inproc:<이름>)도 꼴 v4 를 통과한다. 이름 없는 inproc 는 아니다."""
        from llmsensor.telemetry.schema import check, record
        from telemetry import MemorySink, Recorder
        from telemetry.compat import to_sensor_records
        sink = MemorySink()
        rec = Recorder("r1", sink, source="inproc:ms")
        rec.run_start(model="m", provider="sim")
        with rec.llm_call(0, "sim") as c:
            c.response(usage={"input_tokens": 10, "output_tokens": 2}, usage_format="otel", finish_reason="stop")
        with rec.tool("throttle", {"target": "srv07"}, call_index=0) as t:
            t.result(is_error=False, output="ok")
        rec.run_end(terminal_reason="executed", decision_ref="dec-1")
        recs = to_sensor_records(sink.events)
        self.assertEqual({r["source"] for r in recs}, {"inproc:ms"})
        self.assertEqual([check(r) for r in recs], [[]] * len(recs))
        self.assertTrue(check(record("run", "r", "inproc:")))
        self.assertTrue(check(record("run", "r", "inproc:ms; rm")))

    def test_ledger_to_state(self):
        """L0 원장 -> 꼴 v3 -> State 정규화 묶음."""
        from llmsensor.state.normalize import from_telemetry
        from telemetry import ledger
        from telemetry.collect import from_cc_jsonl as l0_collect
        with tempfile.TemporaryDirectory() as d:
            p = _session(d)
            lp = os.path.join(d, "ledger.jsonl")
            ledger.write(lp, l0_collect(p, "x"))
            batches = from_telemetry(l0.records_from_ledger(lp))
        fields = {o.field for b in batches for o in b.observations}
        self.assertLessEqual({"tokens.output", "tool.is_error", "tool.name"}, fields)


if __name__ == "__main__":
    unittest.main()
