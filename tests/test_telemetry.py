import json
import os
import tempfile
import unittest

from llmsensor.telemetry.catalog import CALL_VARS, CATALOG, RUN_VARS
from llmsensor.telemetry.collect import Hasher, from_cc_jsonl, from_cc_stream, from_sweagent
from llmsensor.telemetry.derive import by_run, calls, run_summary
from llmsensor.telemetry.schema import check, observed, record
from tests.helpers import write_session


class Schema(unittest.TestCase):
    def test_unobserved_is_explicit(self):
        r = record("model_call", "r", "sweagent", call_index=0, output_text_chars=5)
        self.assertIsNone(r["input_tokens"])
        self.assertIn("input_tokens", r["unobserved"])
        self.assertNotIn("output_text_chars", r["unobserved"])
        self.assertEqual(check(r), [])
        r["unobserved"].remove("input_tokens")              # 거짓말: null 인데 어느 목록에도 없다
        self.assertTrue(any("정확히 하나" in e for e in check(r)))
        with self.assertRaises(KeyError):
            record("run", "r", "cc_stream", invented_field=1)

    def test_reported_null_is_not_unobserved(self):
        r = record("run", "r", "cc_stream", reported_null=["api_error_status"], cost_usd=0.1)
        self.assertIsNone(r["api_error_status"])
        self.assertEqual(r["reported_null"], ["api_error_status"])
        self.assertNotIn("api_error_status", r["unobserved"])
        self.assertIn("ttft_ms", r["unobserved"])
        self.assertTrue(observed(r, "api_error_status"))
        self.assertFalse(observed(r, "ttft_ms"))
        self.assertEqual(check(r), [])
        r["unobserved"].append("api_error_status")         # 두 목록 모두 -- 거짓
        self.assertTrue(check(r))
        with self.assertRaises(ValueError):
            record("run", "r", "cc_stream", reported_null=["cost_usd"], cost_usd=1.0)

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
                                 "api_error_status": None,
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
        self.assertIn("api_error_status", run["reported_null"])     # 원천이 null 로 줬다 = 오류 보고 없음
        self.assertIn("ttft_ms", run["unobserved"])                  # 키가 없었다 = 못 봄
        self.assertEqual(t["tool_head"], "Bash:ls")                  # 맨 프로그램 이름은 평문


class Privacy(unittest.TestCase):
    def _session(self, d):
        p = os.path.join(d, "s.jsonl")
        write_session(p, [("user", "go"),
                          ("tool", "Read", {"file_path": "/home/alice/secret/plan.txt"}, True, "x"),
                          ("tool", "WebSearch", {"query": "acquisition target confidential"}, True, "x"),
                          ("tool", "Bash", {"command": "./deploy.sh --prod"}, False, "x"),
                          ("tool", "Bash", {"command": "cd /srv/app && python3 -m pytest -q"}, True, "x"),
                          ("tool", "Read", {"file_path": "/home/alice/secret/plan.txt"}, True, "x"),
                          ("text", "done")])
        return p

    def test_targets_are_hashed(self):
        with tempfile.TemporaryDirectory() as d:
            recs = from_cc_jsonl(self._session(d), "x", Hasher(b"k1"))
        dump = json.dumps(recs)
        for leak in ("alice", "secret", "plan.txt", "acquisition", "confidential", "deploy.sh", "/srv/app"):
            self.assertNotIn(leak, dump)
        heads = [r["tool_head"] for r in recs if r["kind"] == "tool_call"]
        self.assertTrue(heads[0].startswith("Read:#") and heads[1].startswith("WebSearch:#"))
        self.assertTrue(heads[2].startswith("Bash:#"))              # ./deploy.sh 는 경로 -- 해시
        self.assertEqual(heads[3], "Bash:pytest")                   # 맨 프로그램 이름은 평문
        self.assertEqual(heads[0], heads[4])                        # 같은 겨냥 = 같은 해시 -> 반복 · 재시도를 셀 수 있다
        s = run_summary(by_run(recs)["x"])
        self.assertEqual(s["identical_call_repeats"], 2)

    def test_key_controls_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._session(d)
            a = [r["tool_head"] for r in from_cc_jsonl(p, "x", Hasher(b"k1")) if r["kind"] == "tool_call"]
            b = [r["tool_head"] for r in from_cc_jsonl(p, "x", Hasher(b"k2")) if r["kind"] == "tool_call"]
        self.assertNotEqual(a[0], b[0])                             # 열쇠를 모르면 사전 대입으로 못 맞춘다
        self.assertEqual(a[3], b[3])                                # 평문 프로그램 이름은 그대로

    def test_default_key_is_random_unless_env(self):
        """열쇠가 고정이면 코드를 가진 누구나 사전 대입으로 해시를 되찾는다 -- 기본은 무작위여야 한다."""
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLMSENSOR_HASH_KEY", None)
            self.assertNotEqual(Hasher()("/etc/passwd"), Hasher()("/etc/passwd"))
        with mock.patch.dict(os.environ, {"LLMSENSOR_HASH_KEY": "shared"}):
            self.assertEqual(Hasher()("/etc/passwd"), Hasher()("/etc/passwd"))

    def test_sweagent_tool_name_path_hashed(self):
        import gzip
        traj = {"trajectory": [{"action": "/tmp/private/run.sh --x", "observation": "", "response": ""},
                               {"action": "python reproduce.py", "observation": "", "response": ""}],
                "info": {"exit_status": None, "model_stats": {"tokens_sent": 5}}}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.traj.gz")
            with gzip.open(p, "wt") as f:
                json.dump(traj, f)
            recs = from_sweagent(p, "s", Hasher(b"k"))
        self.assertNotIn("private", json.dumps(recs))
        tc = [r for r in recs if r["kind"] == "tool_call"]
        self.assertEqual(tc[1]["tool_name"], "python")
        run = [r for r in recs if r["kind"] == "run"][0]
        self.assertIn("terminal_reason", run["reported_null"])
        self.assertIn("api_calls", run["unobserved"])

    def test_committed_records_have_no_paths_or_queries(self):
        """커밋한 레코드에 경로 · 검색어가 평문으로 남아 있으면 빨갛다."""
        import gzip
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(root, "eval", "results", "sensor_layer_records.jsonl.gz")
        if not os.path.exists(p):
            self.skipTest("레코드 없음")
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                for k in ("tool_head", "tool_name"):
                    v = r.get(k)
                    if v is None:
                        continue
                    target = v.split(":", 1)[1] if ":" in v else ""
                    self.assertTrue(target == "" or target.startswith("#") or re.match(
                        r"^[A-Za-z][A-Za-z0-9_.+-]*$", target), (k, v))
                    self.assertNotIn("/", v, (k, v))
                self.assertEqual(r.get("schema_version", 2), 2)


if __name__ == "__main__":
    unittest.main()
