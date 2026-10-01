import json
import os
import tempfile
import unittest

from llmsensor.telemetry.catalog import CALL_VARS, CATALOG, RUN_VARS
from llmsensor.telemetry.collect import from_cc_jsonl, from_cc_stream
from llmsensor.telemetry.derive import by_run, calls, run_summary
from llmsensor.telemetry.schema import check, record
from tests.helpers import write_session


class Schema(unittest.TestCase):
    def test_unobserved_is_explicit(self):
        r = record("model_call", "r", "sweagent", call_index=0, output_text_chars=5)
        self.assertIsNone(r["input_tokens"])
        self.assertIn("input_tokens", r["unobserved"])
        self.assertNotIn("output_text_chars", r["unobserved"])
        self.assertEqual(check(r), [])
        r["input_tokens"] = None
        r["unobserved"].remove("input_tokens")              # 거짓말: null 인데 관측했다고
        self.assertTrue(any("불일치" in e for e in check(r)))
        with self.assertRaises(KeyError):
            record("run", "r", "cc_stream", invented_field=1)

    def test_catalog_shape(self):
        self.assertGreaterEqual(len(CATALOG), 20)
        names = {s["name"] for s in CATALOG}
        for s in CATALOG:
            self.assertIn(s["type"], (1, 2))
            if s["type"] == 2:
                self.assertTrue(s["derived_from"], s["name"])
        for v in CALL_VARS + RUN_VARS:
            self.assertTrue(v in names or v in ("step_index", "tool_errors", "tokens_sent", "tokens_received",
                                                "model_calls", "mean_tool_output_chars"), v)


class Collect(unittest.TestCase):
    def test_cc_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, [("user", "go"), ("tool", "Bash", {"command": "make"}, False, "err"),
                              ("tool", "Bash", {"command": "make"}, True, "ok"), ("text", "done")])
            recs = from_cc_jsonl(p, "x")
        self.assertEqual([check(r) for r in recs], [[]] * len(recs))
        mc = [r for r in recs if r["kind"] == "model_call"]
        tc = [r for r in recs if r["kind"] == "tool_call"]
        self.assertEqual(len(mc), 3)
        self.assertEqual([t["is_error"] for t in tc], [True, False])
        self.assertEqual(mc[2]["output_tokens"], 20)          # 쪼개진 호출: 마지막 usage
        self.assertIn("thinking_tokens", mc[0]["unobserved"])  # 필드가 없으면 0 이 아니라 null
        c = calls(by_run(recs)["x"])
        self.assertEqual(c[0]["tool_errors"], 1)
        # 시험 세션은 cache_creation_input_tokens 를 안 준다 -> 맥락 크기는 0 으로 메우지 않고 None
        self.assertIsNone(c[0]["context_tokens"])
        self.assertIsNone(c[1]["context_growth"])
        self.assertIsNotNone(c[0]["tool_latency_ms"])
        s = run_summary(by_run(recs)["x"])
        self.assertEqual((s["tool_error_rate"], s["retry_count"], s["identical_call_repeats"]), (0.5, 1, 2))

    def test_cc_stream(self):
        lines = [
            {"_t": 0, "line": {"type": "system", "subtype": "init"}},
            {"_t": 100, "line": {"type": "stream_event", "event": {"type": "message_start", "message": {
                "id": "m1", "model": "h", "usage": {"input_tokens": 10, "output_tokens": 1}}}}},
            {"_t": 150, "line": {"type": "stream_event", "event": {"type": "content_block_delta"}}},
            {"_t": 180, "line": {"type": "stream_event", "event": {"type": "content_block_delta"}}},
            {"_t": 190, "line": {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 42}},
            {"_t": 200, "line": {"type": "stream_event", "event": {"type": "message_delta", "delta": {
                "stop_reason": "tool_use"}, "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
                                                      "cache_creation_input_tokens": 0, "output_tokens": 30,
                                                      "output_tokens_details": {"thinking_tokens": 12}}}}},
            {"_t": 210, "line": {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}}},
            {"_t": 400, "line": {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "boom", "is_error": True}]}}},
            {"_t": 500, "line": {"type": "result", "subtype": "success", "duration_ms": 500, "num_turns": 1,
                                 "modelUsage": {"h": {"contextWindow": 200000, "maxOutputTokens": 32000}},
                                 "usage": {"input_tokens": 10, "output_tokens": 30}}},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.stream.jsonl")
            with open(p, "w") as f:
                for x in lines:
                    f.write(json.dumps(x) + "\n")
            recs = from_cc_stream(p, "s")
        self.assertEqual([check(r) for r in recs], [[]] * len(recs))
        m = [r for r in recs if r["kind"] == "model_call"][0]
        self.assertEqual((m["output_tokens"], m["thinking_tokens"], m["stream_chunks"], m["first_chunk_ms"],
                          m["stream_thinking_estimate"], m["stop_reason"], m["context_window"]),
                         (30, 12, 2, 50, 42, "tool_use", 200000))
        t = [r for r in recs if r["kind"] == "tool_call"][0]
        self.assertEqual((t["is_error"], t["t_result_ms"] - t["t_issued_ms"]), (True, 190))
        run = [r for r in recs if r["kind"] == "run"][0]
        self.assertEqual((run["context_window"], run["reported_output_tokens"]), (200000, 30))


if __name__ == "__main__":
    unittest.main()
