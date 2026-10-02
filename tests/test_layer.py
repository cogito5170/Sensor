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


class OptionalL0(unittest.TestCase):

    def test_falls_back_without_l0(self):
        with mock.patch.dict(sys.modules, {"telemetry": None}), tempfile.TemporaryDirectory() as d:
            self.assertFalse(l0.available())
            recs, backend = l0.collect("cc_jsonl", _session(d), "x")
            self.assertEqual(backend, "native")
            self.assertTrue(recs)
            self.assertEqual(l0.compare("cc_jsonl", _session(d)), {"available": False})
            with self.assertRaises(ImportError):
                l0.records_from_ledger(os.path.join(d, "none.jsonl"))

    def test_impostor_named_telemetry_is_not_l0(self):
        with mock.patch.dict(sys.modules, {"telemetry": types.ModuleType("telemetry")}):
            self.assertFalse(l0.available())


@unittest.skipUnless((TELEMETRY / "telemetry").is_dir(), "옆에 ../Telemetry 가 없다")
class WithL0(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(TELEMETRY) not in sys.path:
            sys.path.insert(0, str(TELEMETRY))

    def test_prefers_l0_and_matches_native(self):
        self.assertTrue(l0.available())
        with tempfile.TemporaryDirectory() as d:
            p = _session(d)
            _, backend = l0.collect("cc_jsonl", p, "x")
            self.assertEqual(backend, "l0")
            _, backend = l0.collect("cc_jsonl", p, "x", prefer_l0=False)
            self.assertEqual(backend, "native")
            r = l0.compare("cc_jsonl", p)
            self.assertTrue(r["same"], r)

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
