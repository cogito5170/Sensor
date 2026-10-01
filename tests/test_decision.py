import json
import os
import subprocess
import sys
import tempfile
import unittest

from llmsensor import (ACCEPT, DEGRADE, REJECT, RETRY, FAULT, OK, SUSPECT, UNKNOWN, ConstraintSensor,
                       ExternalOutcomeSensor, OutcomeModel, Reading, Verifier, residuals, sense, telemetry)
from tests.helpers import bash, task, write_session
from tests.test_sensors import _model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def R(sensor, status, **detail):
    return Reading(sensor, status, f"{sensor} {status}", detail=detail)


def five(outcome=UNKNOWN, execution=UNKNOWN, constraint=UNKNOWN, consistency=UNKNOWN, behavior=UNKNOWN,
         claim=UNKNOWN, loop=UNKNOWN):
    return [R("execution", execution), R("constraint", constraint),
            R("consistency", consistency, claim={"status": claim}), R("behavior", behavior, loop={"status": loop}),
            R("outcome", outcome)]


class Fusion(unittest.TestCase):
    om = OutcomeModel()

    def test_unknown_is_zero_evidence(self):
        q = self.om.q(five(), prior=0.3)
        self.assertAlmostEqual(q["Q"], 0.3)
        self.assertEqual(q["evidence"], 0)
        self.assertFalse(q["calibrated"])

    def test_hierarchy(self):
        # 같은 OK 라도 외부 결과가 가장 세고 행동이 가장 약하다
        qs = {s: self.om.q(five(**{s: OK}))["Q"] for s in ("outcome", "execution", "consistency", "behavior")}
        self.assertGreater(qs["outcome"], qs["execution"])
        self.assertGreater(qs["execution"], qs["consistency"])
        self.assertGreater(qs["consistency"], qs["behavior"])
        # 외부 결과 FAULT 는 나머지가 다 OK 여도 Q 를 반 밑으로
        q = self.om.q(five(outcome=FAULT, execution=OK, constraint=OK, consistency=OK, behavior=OK))["Q"]
        self.assertLess(q, 0.5)

    def test_calibrate(self):
        ex = [(five(execution=OK), True)] * 8 + [(five(execution=FAULT), True)] * 2 \
            + [(five(execution=FAULT), False)] * 8 + [(five(execution=OK), False)] * 2
        m = OutcomeModel().calibrate(ex)
        self.assertTrue(m.calibrated)
        self.assertGreater(m.lr["execution"][OK], 1)
        self.assertLess(m.lr["execution"][FAULT], 1)
        self.assertAlmostEqual(m.lr["behavior"][OK], 1.0)        # 늘 UNKNOWN 이던 센서는 증거가 안 된다
        self.assertEqual(OutcomeModel.from_dict(m.to_dict()).lr, m.lr)
        with self.assertRaises(ValueError):
            OutcomeModel().calibrate([(five(), True)])

    def test_calibrate_unseen_status_is_neutral_with_unequal_classes(self):
        # 부류 크기가 다를 때(성공 3 : 실패 12) 한 번도 안 나온 상태가 LR 1 이어야 한다 -- Laplace 판은 (12+4)/(3+4)
        ex = [(five(execution=OK), True)] * 3 + [(five(execution=FAULT), False)] * 12
        m = OutcomeModel().calibrate(ex)
        for s in ("outcome", "constraint", "behavior"):
            for st in (OK, SUSPECT, FAULT):
                self.assertEqual(m.lr[s][st], 1.0, (s, st))
        self.assertEqual(m.lr["execution"][SUSPECT], 1.0)
        self.assertGreater(m.lr["execution"][OK], 1)
        self.assertLess(m.lr["execution"][FAULT], 1)
        # 드문 상태는 1 쪽으로 줄어든다: 성공 1 번만 본 FAULT 가 무한대 증거가 되지 않는다
        ex2 = ex + [(five(consistency=FAULT), True)]
        self.assertLess(OutcomeModel().calibrate(ex2).lr["consistency"][FAULT], 5)


class Verdicts(unittest.TestCase):
    v = Verifier()

    def d(self, rs, attempt=0):
        return self.v.decide(rs, OutcomeModel().q(rs)["Q"], attempt)

    def test_rule1_hard_fault(self):
        rs = five(outcome=FAULT, execution=OK)
        self.assertEqual((self.d(rs).action, self.d(rs).rule), (RETRY, 1))
        self.assertEqual(self.d(rs, attempt=2).action, REJECT)
        self.assertEqual(self.d(five(constraint=FAULT, outcome=UNKNOWN)).action, RETRY)

    def test_rule2_outcome_ok_wins_over_cost(self):
        v = self.d(five(outcome=OK, behavior=FAULT, loop=FAULT))
        self.assertEqual((v.action, v.rule), (ACCEPT, 2))
        self.assertTrue(any("비용" in r for r in v.reasons))
        self.assertTrue(v.policy["terminate_on_repeat"])

    def test_rule3_false_success(self):
        v = self.d(five(execution=OK, consistency=FAULT, claim=FAULT))
        self.assertEqual((v.action, v.rule), (RETRY, 3))

    def test_rule4_behavior_degrades(self):
        v = self.d(five(execution=OK, behavior=FAULT))
        self.assertEqual((v.action, v.rule, v.policy["route"]), (DEGRADE, 4, "escalate"))

    def test_rule5_vs_rule6_tokens_alone_never_accept(self):
        # 실행 OK + 행동 OK 로 Q 를 올려도 결과 근거가 없으면 받지 않는다
        rs = five(execution=OK, behavior=OK, consistency=OK)
        q = 0.95
        v = self.v.decide(rs, q)
        self.assertEqual((v.action, v.rule), (DEGRADE, 6))
        rs2 = five(execution=OK, consistency=OK, claim=OK)
        self.assertEqual(self.v.decide(rs2, q).action, ACCEPT)
        self.assertEqual(self.v.decide(five(constraint=OK), q).action, ACCEPT)

    def test_rule7_and_8(self):
        self.assertEqual(self.v.decide(five(execution=FAULT), 0.1).rule, 7)
        self.assertEqual(self.v.decide(five(execution=SUSPECT), 0.5).action, DEGRADE)


class Residual(unittest.TestCase):
    def test_missing_without_model(self):
        r = residuals({"T": 100, "R": 0, "E": 0}, None)
        self.assertEqual(sorted(r["missing"]), ["E", "R", "T", "V"])
        self.assertEqual(r["R_sys"], 0)

    def test_with_model(self):
        m = _model()
        rs = five(outcome=FAULT)
        r = residuals({"T": 40_000, "R": 3, "E": 2}, m, "edit", rs)
        self.assertAlmostEqual(r["r_T"], 3.0, places=3)
        self.assertEqual((r["r_R"], r["r_E"], r["r_V"]), (3, 2, 1.0))
        self.assertGreater(r["R_sys"], 2 * 1.0 + 3 + 2)        # V 무게 2 + R + E + T 몫
        quiet = residuals({"T": 10_000, "R": 0, "E": 0}, m, "edit", five(outcome=OK))
        self.assertLess(quiet["R_sys"], 0.1)


class Pipeline(unittest.TestCase):
    def test_false_success_end_to_end(self):
        t = task([bash("pytest -q", False, "1 failed")], "모든 테스트를 통과했습니다.")
        rep = sense(t)
        st = {r["sensor"]: r["status"] for r in rep["readings"]}
        self.assertEqual((st["execution"], st["consistency"], st["outcome"]), (FAULT, FAULT, UNKNOWN))
        self.assertIn(rep["verdict"]["action"], (RETRY, REJECT))

    def test_external_and_constraint_accept(self):
        t = task([bash("make test", True)], '{"ok": true}')
        rep = sense(t, constraint=ConstraintSensor({"type": "object", "required": ["ok"]}),
                    external=ExternalOutcomeSensor(fn=lambda _: True))
        self.assertEqual(rep["verdict"]["action"], ACCEPT)
        self.assertGreater(rep["fusion"]["Q"], 0.9)

    def test_same_task_different_evidence_changes_verdict(self):
        # 사소한 설명 죽이기: 판정이 상수를 돌려주는 것이 아님을 -- 증거 하나만 바꿔 판정이 바뀌는지 본다
        t = task([bash("make test", True)], "완료")
        a = sense(t, external=ExternalOutcomeSensor(fn=lambda _: True))["verdict"]["action"]
        b = sense(t, external=ExternalOutcomeSensor(fn=lambda _: False))["verdict"]["action"]
        c = sense(t)["verdict"]["action"]
        self.assertEqual((a, b), (ACCEPT, RETRY))
        # 외부 검증 없이 추적 안의 검증 하나만으로는 보정 전 LR 로 Q≈0.78 -- 받지 않고 외부 검증으로 올린다
        self.assertEqual(c, DEGRADE)


class CLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "llmsensor", *args], cwd=ROOT, capture_output=True, text=True)

    def test_read_fit_check(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            write_session(p, [("user", "비밀스러운 질문 ZZQX"),
                              ("tool", "Bash", {"command": "pytest -q"}, False, "1 failed"),
                              ("text", "모든 테스트를 통과했습니다.")] * 6)
            r = self.run_cli("read", p)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("과업 6", r.stdout)
            self.assertIn("false success", r.stdout)
            self.assertNotIn("ZZQX", r.stdout)                  # 글은 내보내지 않는다
            m = os.path.join(d, "m.json")
            r = self.run_cli("fit", p, "-o", m)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self.run_cli("read", p, "--model", m, "--json")
            rep = json.loads(r.stdout)
            self.assertEqual(rep[0]["readings"][3]["detail"]["tokens"]["status"], OK)
        self.assertEqual(self.run_cli("check", "--", sys.executable, "-c", "pass").returncode, 0)
        self.assertEqual(self.run_cli("check", "--", sys.executable, "-c", "raise SystemExit(4)").returncode, 1)
        self.assertEqual(self.run_cli("check", "--", "no-such-cmd-xyz").returncode, 2)


class Telemetry(unittest.TestCase):
    def test_vector(self):
        t = task([bash("make", False), bash("make", True), bash("x", None)], tokens=(10, 20))
        self.assertEqual(telemetry(t), {"T": 30, "T_out": 0, "turns": 2, "L": 3, "E": 1, "R": 1, "latency": 10.0,
                                        "missing_results": 1})


if __name__ == "__main__":
    unittest.main()
