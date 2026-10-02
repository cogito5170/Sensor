"""S3 dependency_fault (BD-54) -- 가짜 L0 사건 봉투로만. 의존 대상마다 실체, 마지막 호출의 결과, 선언된 원인만."""
import unittest

from llmsensor.sensing.l0 import batches
from llmsensor.state import Basis, Status, StateEngine
from llmsensor.state.registry import REGISTRY

RUN = "fake:dep"


def ev(type, seq, at, **data):
    return {"spec": "l0-telemetry/1", "id": f"{RUN}:{seq}", "type": type, "run_id": RUN, "seq": seq, "source": "inproc:t",
            "at": at, "time_base": "unix_ms", "data": data, "unobserved": [], "reported_null": []}


def state(events, name="provider"):
    E = StateEngine().ingest_all(batches(events))
    return E, E.current.get((f"dependency:{RUN}:{name}", "dependency_fault"))


class DependencyFault(unittest.TestCase):
    def test_last_call_failed_with_declared_cause(self):
        E, st = state([ev("llm.response", 0, 100), ev("llm.error", 1, 200, error_code="RATE_LIMITED", http_status=429)])
        self.assertEqual((st.value, st.basis, st.observed_at), ("FAULT_DECLARED", Basis.RUNTIME_DECLARED, 200))
        self.assertIn("RATE_LIMITED", st.reason)

    def test_recovered_is_no_fault_declared_not_healthy(self):
        E, st = state([ev("llm.error", 0, 100, error_code="RATE_LIMITED"), ev("llm.response", 1, 200)])
        self.assertEqual((st.value, st.basis), ("NO_FAULT_DECLARED", Basis.OBSERVED))
        self.assertIn("1/2", st.reason)
        self.assertNotIn("HEALTHY", REGISTRY.rules["dependency_fault"].values)

    def test_no_calls_no_entity(self):
        E, st = state([ev("turn.start", 0, 100), ev("tool.end", 1, 200, is_error=True)])
        self.assertIsNone(st)
        self.assertEqual(E.query(f"dependency:{RUN}:provider", ["dependency_fault"])[0].status, Status.UNKNOWN)

    def test_probe_http_status_and_isolation(self):
        evs = [ev("dependency.probe", 0, 100, target="#aa", status_code=503), ev("dependency.probe", 1, 110, target="#bb",
               status_code=200), ev("llm.response", 2, 120)]
        E = StateEngine().ingest_all(batches(evs))
        get = lambda n: E.current[(f"dependency:{RUN}:{n}", "dependency_fault")].value  # noqa: E731
        self.assertEqual((get("probe.aa"), get("probe.bb"), get("provider")),
                         ("FAULT_DECLARED", "NO_FAULT_DECLARED", "NO_FAULT_DECLARED"))

    def test_probe_without_declared_cause_is_not_a_fault(self):
        E, st = state([ev("dependency.probe", 0, 100, target="#cc", status_code=302)], "probe.cc")
        self.assertEqual(st.value, "NO_FAULT_DECLARED")

    def test_owner_layer_assess(self):
        self.assertEqual(REGISTRY.rules["dependency_fault"].owner_layer, "ASSESS")


if __name__ == "__main__":
    unittest.main()


class Freshness(unittest.TestCase):
    def test_dependency_entity_finds_its_run_clock(self):
        # 실행 id 에 ':' 가 있어도 의존 대상 실체가 자기 실행의 '지금' 을 찾는다(앞 판은 UNTIMED 였다)
        evs = [dict(ev("llm.response", 0, 100), run_id="a:b", id="a:b:0"), dict(ev("turn.start", 1, 700_000), run_id="a:b", id="a:b:1")]
        E = StateEngine().ingest_all(batches(evs))
        v = E.query("dependency:a:b:provider", ["dependency_fault"])[0]
        self.assertEqual(v.freshness.value, "STALE")          # 마지막 호출(100) 뒤 TTL 10 분을 넘긴 시각(700,000)
