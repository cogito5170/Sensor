"""S23 (baseline#3 CMD-S23): 결과를 못 본 도구 호출의 UNKNOWN 이유를 가른다. 값은 그대로 UNKNOWN.

    기다리는 중     L0 를 받았고 그 tool_index 의 tool.end 가 아직 없다         근거 tool_outcome_pending
    원천이 안 줌    tool.end 는 왔는데 is_error 가 없다(SWE-agent)             근거 tool_outcome_unobservable
    모른다          L0 를 받지 않았다(레코드만)                                근거 tool_outcome_unobservable

가르는 열쇠는 tool.end 를 **봤는가**다. t_result_ms(시각)로 가르면 시각이 없는 SWE-agent 가 모두 '기다리는 중' 이 된다.
"""
import unittest

from llmsensor.sensing.l0 import batches
from llmsensor.state import Status
from llmsensor.state.engine import TOOL_RULE
from llmsensor.telemetry.schema import record
from tests.test_state import A, RUN, engine, mc, tc


def l0(seq, ty, data=None, at=None):
    return {"spec": "l0-telemetry/1", "id": f"{RUN}:{seq}", "type": ty, "run_id": RUN, "seq": seq, "source": "cc_stream",
            "at": at, "time_base": "monotonic_ms" if at is not None else None, "data": data or {}, "unobserved": [],
            "reported_null": []}


def tcx(j, at=110, **kw):
    r = tc(0, j, at, known=False, head=f"Bash:{j}", **kw)
    return r


def run(recs, evs):
    return engine(recs).ingest_all(batches(evs))


def health(E, ent=A, name="execution_health"):
    return E.current[(ent, name)]


def pend(E):
    ms = [m for i, m in E.metrics.items() if i.startswith(f"{A}/tool_outcome_pending@")]
    return max(ms, key=lambda m: int(str(m.id.rsplit("@", 1)[1]).split("+")[0]))


class Split(unittest.TestCase):
    def test_waiting_when_no_tool_end_yet(self):
        E = run([mc(0, 100), tcx(0)], [l0(1, "turn.start", at=50), l0(2, "tool.start", {"tool_index": 0}, at=105)])
        s = health(E)
        self.assertEqual((s.value, s.status), (None, Status.UNKNOWN))
        self.assertIn("기다리는 중", s.reason)
        self.assertEqual([e.name for e in s.evidence], ["tool_outcome_pending"])
        self.assertEqual(pend(E).value, 1)

    def test_source_does_not_give_when_tool_end_came(self):
        E = run([mc(0, 100), tcx(0)], [l0(1, "tool.start", {"tool_index": 0}), l0(2, "tool.end", {"tool_index": 0})])
        s = health(E)
        self.assertEqual(s.status, Status.UNKNOWN)
        self.assertIn("원천이 주지 않는다", s.reason)
        self.assertEqual([e.name for e in s.evidence], ["tool_outcome_unobservable"])
        self.assertEqual(pend(E).value, 0)

    def test_untimed_source_is_not_waiting(self):
        # SWE-agent 꼴: 시각이 없다(at=None) -- 그래도 tool.end 를 봤으니 원천 한계다
        sw = "sweagent:x"
        recs = [record("model_call", sw, "sweagent", call_index=0, output_text_chars=1, tool_calls_per_message=2)]
        recs += [record("tool_call", sw, "sweagent", call_index=0, tool_index=j, tool_name="edit", tool_head=f"edit:{j}",
                        tool_sig="z", tool_output_chars=1) for j in (0, 1)]
        evs = [dict(l0(j + 1, "tool.end", {"tool_index": j}), run_id=sw, id=f"{sw}:{j + 1}", source="sweagent")
               for j in (0, 1)]
        s = engine(recs).ingest_all(batches(evs)).current[(f"agent:{sw}", "execution_health")]
        self.assertEqual(s.status, Status.UNKNOWN)
        self.assertIn("원천이 주지 않는다", s.reason)

    def test_mixed(self):
        E = run([mc(0, 100), tcx(0), tcx(1)], [l0(1, "tool.end", {"tool_index": 0}, at=111)])
        s = health(E)
        self.assertIn("기다리는 호출 1 개", s.reason)
        self.assertIn("주지 않은 호출 1 개", s.reason)
        self.assertEqual({e.name for e in s.evidence}, {"tool_outcome_pending", "tool_outcome_unobservable"})

    def test_records_only_says_it_cannot_tell(self):
        s = health(engine([mc(0, 100), tcx(0)]))
        self.assertIn("모른다", s.reason)
        self.assertNotIn("기다리는 중", s.reason)
        self.assertNotIn("원천이 주지 않는다", s.reason)

    def test_tool_entity_gets_the_same_split(self):
        E = run([mc(0, 100), tcx(0)], [l0(1, "turn.start", at=50)])
        s = E.current[(f"tool:{RUN}:Bash", TOOL_RULE)]
        self.assertIn("기다리는 중", s.reason)

    def test_seen_results_are_not_counted(self):
        E = run([mc(0, 100), tc(0, 0, 110), tcx(1)], [l0(1, "turn.start", at=50)])
        self.assertEqual(pend(E).value, 1)
        self.assertEqual(health(E).value, "NO_FAILURE_OBSERVED")


if __name__ == "__main__":
    unittest.main()
