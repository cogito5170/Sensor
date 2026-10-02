import os
import sys
import tempfile
import unittest

from llmsensor import (BehaviorSensor, ConsistencySensor, ConstraintSensor, ExecutionSensor, ExternalOutcomeSensor,
                       FAULT, OK, SUSPECT, UNKNOWN, PerformanceModel, ToolCall, agreement, from_claude_code, telemetry)
from llmsensor.sensors.consistency import claims_success, numbers
from llmsensor.trace import call_head, retries
from tests.helpers import bash, task, write_session


class Trace(unittest.TestCase):
    def test_claude_code_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, [
                ("sys", "<system-reminder>무시</system-reminder>"),        # 첫 과업 전 · 시스템 주입
                ("user", "시험을 고쳐라"),
                ("tool", "Bash", {"command": "pytest -q"}, False, "1 failed"),
                ("tool", "Edit", {"file_path": "a.py"}, True, "ok"),
                ("tool", "Bash", {"command": "pytest -q"}, True, "3 passed"),
                ("text", "고쳤습니다. 모두 통과."),
                ("sys", "<task-notification>x</task-notification>"),      # 과업 경계가 아니다
                ("side", "하위 에이전트의 말"),                               # 경계가 아니다
                ("user", "둘째 일"),
                ("text", "네"),
            ])
            ts = from_claude_code(p)
        self.assertEqual(len(ts), 2)
        a, b = ts
        self.assertEqual(a.prompt, "시험을 고쳐라")
        self.assertEqual([c.ok for c in a.calls], [False, True, True])
        self.assertEqual(a.calls[0].output, "1 failed")
        self.assertEqual(a.answer, "고쳤습니다. 모두 통과.")
        # 쪼개진 호출은 한 턴: 도구 3 + 글 1 = 4 턴, 글 턴의 usage 는 마지막 조각(120)
        self.assertEqual(len(a.turns), 4)
        self.assertEqual(a.tokens, 3 * 1510 + 120)
        self.assertEqual(telemetry(a)["R"], 1)
        self.assertGreater(a.latency, 0)
        self.assertEqual((b.prompt, b.answer, len(b.calls)), ("둘째 일", "네", 0))

    def test_answer_is_text_after_last_tool(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, [("user", "u"), ("text", "먼저 보겠습니다"),
                              ("tool", "Bash", {"command": "ls"}, True, ""), ("text", "끝")])
            self.assertEqual(from_claude_code(p)[0].answer, "끝")

    def test_call_head_and_retries(self):
        self.assertEqual(call_head(bash("cd /x && FOO=1 python3 -m pytest -q")), "Bash:pytest")
        self.assertEqual(call_head(bash("timeout 30 make test")), "Bash:make")
        self.assertEqual(call_head(ToolCall("Edit", {"file_path": "a.py"})), "Edit:a.py")
        calls = [bash("pytest", False), bash("pytest -x", False), bash("pytest", True), bash("pytest", True)]
        self.assertEqual(retries(calls), 2)      # 실패 뒤 두 번 · 성공 뒤의 것은 재시도가 아니다


class Execution(unittest.TestCase):
    s = ExecutionSensor()

    def test_unresolved_fault_vs_resolved_ok(self):
        self.assertEqual(self.s.read(task([bash("make", False)])).status, FAULT)
        self.assertEqual(self.s.read(task([bash("make", False), bash("make", True)])).status, OK)

    def test_explore_failures_not_counted(self):
        r = self.s.read(task([bash("grep -r foo .", False), bash("make", True)]))
        self.assertEqual(r.status, OK)
        self.assertEqual(self.s.read(task([bash("grep foo", False)])).status, UNKNOWN)

    def test_no_calls_unknown_and_missing_result_suspect(self):
        self.assertEqual(self.s.read(task()).status, UNKNOWN)
        self.assertEqual(self.s.read(task([bash("make", None)])).status, SUSPECT)

    def test_check_files(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "a.txt")
            open(real, "w").close()
            calls = [ToolCall("Write", {"file_path": real}, True), ToolCall("Write", {"file_path": real + "x"}, True)]
            self.assertEqual(ExecutionSensor(check_files=True).read(task(calls)).status, FAULT)
            self.assertEqual(ExecutionSensor(check_files=True).read(task(calls[:1])).status, OK)


class Constraint(unittest.TestCase):
    schema = {"type": "object", "required": ["name", "score"], "additionalProperties": False,
              "properties": {"name": {"type": "string", "minLength": 1},
                             "score": {"type": "number", "minimum": 0, "maximum": 1},
                             "tags": {"type": "array", "items": {"enum": ["a", "b"]}}}}

    def test_schema(self):
        s = ConstraintSensor(self.schema)
        self.assertEqual(s.read('결과:\n```json\n{"name": "x", "score": 0.5, "tags": ["a"]}\n```').status, OK)
        bad = s.read('{"name": "", "score": 2, "tags": ["c"], "extra": 1}')
        self.assertEqual(bad.status, FAULT)
        self.assertEqual(len(bad.detail["violations"]), 4)
        self.assertEqual(s.read("JSON 없음").status, FAULT)
        self.assertEqual(s.read('{"score": 0.1}').status, FAULT)       # 필수 필드

    def test_unknown_paths(self):
        self.assertEqual(ConstraintSensor().read("아무거나").status, UNKNOWN)
        self.assertEqual(ConstraintSensor({"oneOf": []}).read("{}").status, UNKNOWN)

        def boom(a):
            raise RuntimeError
        self.assertEqual(ConstraintSensor(predicates=[("터짐", boom)]).read("x").status, UNKNOWN)

    def test_regex_and_length(self):
        s = ConstraintSensor(must=[r"^## 요약"], must_not=[r"TODO"], max_chars=50)
        self.assertEqual(s.read("## 요약\n좋다").status, OK)
        self.assertEqual(s.read("## 요약\nTODO").status, FAULT)
        self.assertEqual(s.read("요약 없음").status, FAULT)
        self.assertEqual(s.read("## 요약\n" + "가" * 60).status, FAULT)


class Consistency(unittest.TestCase):
    s = ConsistencySensor()

    def test_false_success(self):
        t = task([bash("pytest -q", True), bash("pytest -q", False, "1 failed")], "모든 테스트를 통과했습니다.")
        r = self.s.read(t)
        self.assertEqual(r.status, FAULT)
        self.assertEqual(r.detail["claim"]["status"], FAULT)

    def test_unverified_and_verified_claims(self):
        self.assertEqual(self.s.claim(task([bash("ls")], "고쳤습니다.")).status, SUSPECT)
        self.assertEqual(self.s.claim(task([bash("make test", True)], "Fixed. All tests pass.")).status, OK)

    def test_admission_is_not_a_claim(self):
        t = task([bash("pytest", False)], "테스트 하나가 아직 실패합니다.")
        self.assertEqual(self.s.claim(t).status, UNKNOWN)
        self.assertIs(claims_success("통과하지 못했습니다"), False)
        self.assertIs(claims_success("실패하던 것을 고쳤습니다\n모두 통과"), True)
        self.assertIsNone(claims_success("파일을 읽어 보겠습니다"))
        self.assertIs(claims_success("에러 없이 통과했습니다."), True)
        self.assertIs(claims_success("Done: 12 passed, 0 failed."), True)
        self.assertIs(claims_success("The build did not pass."), False)
        self.assertIs(claims_success("고쳤습니다.\n다만 lint 는 실패합니다."), False)

    def test_numbers(self):
        t = task([bash("wc", True, "total 12,345 lines, ratio 0.875")], "총 12,345줄이고 비율은 0.875 입니다.")
        self.assertEqual(self.s.numbers(t).status, OK)
        t2 = task([bash("wc", True, "total 10")], "정확도 93.4% 이고 지연은 128ms, 처리량 4,410")
        self.assertEqual(self.s.numbers(t2).status, SUSPECT)
        self.assertEqual(self.s.numbers(task(answer="네")).status, UNKNOWN)
        self.assertNotIn("123", numbers("see foo.py:123"))

    def test_agreement(self):
        self.assertAlmostEqual(agreement(["a b c", "a b c"]), 1.0)
        self.assertLess(agreement(["a b c", "x y z"]), 0.1)
        self.assertIsNone(agreement(["a"]))
        self.assertEqual(agreement(["답 42", "그래서 42"], key=lambda s: s.split()[-1]), 1.0)
        self.assertEqual(self.s.read(task(answer="파리는 프랑스 수도"), others=["베를린 맞다"]).status, SUSPECT)


def _model(n=20, T=10_000, spread=0.1, R=0):
    import math
    recs = [{"cls": "edit", "T": T * math.exp(spread * ((i % 5) - 2)), "R": R, "L": 5, "E": 0, "latency": 30,
             "success": i % 4 != 0} for i in range(n)]
    return PerformanceModel().fit(recs)


class Behavior(unittest.TestCase):
    def test_stuck_loop(self):
        r = BehaviorSensor().read(task([bash("cat x", True, "same")] * 3))
        self.assertEqual(r.detail["loop"]["status"], FAULT)

    def test_polling_is_only_suspect(self):
        r = BehaviorSensor().loop(task([bash("kill -0 1", True, f"t{i}") for i in range(6)]))
        self.assertEqual(r.status, SUSPECT)

    def test_oscillation(self):
        calls = [bash("a", True, str(i)) if i % 2 == 0 else bash("b", True, str(i)) for i in range(6)]
        self.assertEqual(BehaviorSensor().loop(task(calls)).status, FAULT)
        self.assertEqual(BehaviorSensor().loop(task(calls[:3])).status, OK)

    def test_tokens_need_a_model(self):
        r = BehaviorSensor().read(task([bash("make")], tokens=(10**7,)))
        self.assertEqual(r.detail["tokens"]["status"], UNKNOWN)

    def test_inflation_and_collapse(self):
        m = _model()
        s = BehaviorSensor(m)
        self.assertEqual(s.read(task([bash("make")], tokens=(10_000,), cls="edit")).detail["tokens"]["status"], OK)
        self.assertEqual(s.read(task([bash("make")], tokens=(80_000,), cls="edit")).detail["tokens"]["status"], FAULT)
        self.assertEqual(s.read(task([bash("make")], tokens=(1_000,), cls="edit")).detail["tokens"]["status"],
                         SUSPECT)

    def test_absolute_retry_and_budget(self):
        calls = [bash("make", False)] * 1 + [bash(f"make -j{i}", False, str(i)) for i in range(5)]
        r = BehaviorSensor(max_tokens=500).read(task(calls, tokens=(1000,)))
        self.assertEqual(r.detail["retry"]["status"], FAULT)
        self.assertEqual(r.detail["budget"]["status"], FAULT)


class Outcome(unittest.TestCase):
    def test_real_commands(self):
        py = sys.executable
        self.assertEqual(ExternalOutcomeSensor([py, "-c", "pass"]).read().status, OK)
        r = ExternalOutcomeSensor([py, "-c", "import sys; print('boom'); sys.exit(3)"]).read()
        self.assertEqual((r.status, r.detail["returncode"]), (FAULT, 3))
        self.assertIn("boom", r.detail["tail"])

    def test_cannot_measure_is_unknown(self):
        self.assertEqual(ExternalOutcomeSensor(["no-such-cmd-xyz"]).read().status, UNKNOWN)
        r = ExternalOutcomeSensor([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3).read()
        self.assertEqual(r.status, UNKNOWN)
        self.assertEqual(ExternalOutcomeSensor(fn=lambda t: None).read().status, UNKNOWN)
        self.assertEqual(ExternalOutcomeSensor(fn=lambda t: False).read().status, FAULT)
        with self.assertRaises(ValueError):
            ExternalOutcomeSensor()


class Model(unittest.TestCase):
    def test_fit_fallback_roundtrip(self):
        m = _model()
        e = m.expect("edit")
        self.assertAlmostEqual(e["T"], 10_000, delta=1)
        self.assertAlmostEqual(e["p_success"], (15 + 1) / (20 + 2))
        self.assertEqual(m.expect("unseen")["n"], 20)              # '*' 로 물러남
        self.assertEqual(PerformanceModel(min_n=50).fit([{"T": 1}]).expect("x"), {})
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.json")
            m.save(p)
            self.assertEqual(PerformanceModel.load(p).expect("edit"), e)

    def test_mad_floor(self):
        m = PerformanceModel(min_n=1).fit([{"T": 1000, "R": 0}] * 5)  # MAD 0
        self.assertAlmostEqual(m.z("default", "T", 1000 * 2.718281828), 10.0, places=3)


if __name__ == "__main__":
    unittest.main()


class TelemetryName(unittest.TestCase):
    """함수 telemetry 와 하위 패키지 llmsensor.telemetry 가 이름을 나눠 쓴다 -- import 순서에 따라 바뀌면 안 된다."""

    def test_function_survives_subpackage_import(self):
        import llmsensor
        from llmsensor.telemetry import collect, derive, schema  # noqa: F401 -- 하위 모듈을 처음 올리는 쪽
        self.assertTrue(callable(llmsensor.telemetry))
        from llmsensor import telemetry as t
        self.assertIs(t, llmsensor.trace.telemetry)
