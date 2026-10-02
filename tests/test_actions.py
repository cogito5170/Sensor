"""S5 runtime_actions -- 런타임 자신의 행동. 가짜 L0 사건 봉투로만 시험한다."""
import unittest

from llmsensor.sensing.l0 import batches
from llmsensor.state import StateEngine

RUN = "fake:act"
T = f"task:{RUN}"


def ev(type, seq, at=None, **data):
    return {"spec": "l0-telemetry/1", "id": f"{RUN}:{seq}", "type": type, "run_id": RUN, "seq": seq, "source": "cc_jsonl",
            "at": at, "time_base": "unix_ms", "data": data, "unobserved": [], "reported_null": []}


def metric(events):
    E = StateEngine().ingest_all(batches(events))
    ms = [m for i, m in E.metrics.items() if i.startswith(f"{T}/runtime_actions@")]
    return max(ms, key=lambda m: int(str(m.id.rsplit("@", 1)[1]).split("+")[0]))


class RuntimeActions(unittest.TestCase):
    def test_no_action_events_is_none_not_zero(self):
        m = metric([ev("turn.start", 0, 1), ev("llm.response", 1, 2), ev("tool.end", 2, 3, moved_to_background=None)])
        self.assertIsNone(m.value)
        self.assertIn("일어나지 않았다는 뜻이 아니다", m.reason)

    def test_counts_and_last_compaction(self):
        m = metric([ev("runtime.compaction", 0, 1, trigger="auto", pre_tokens=783484, post_tokens=7209, duration_ms=69703),
                    ev("tool.end", 1, 2, moved_to_background=True), ev("tool.end", 2, 3, moved_to_background=False),
                    ev("input.removed", 3, 4, reason="absorbed_mid_turn"), ev("run.end", 4, 5, permission_denials=0)])
        v = m.value
        self.assertEqual((v["compaction"], v["tool_backgrounded"], v["input_removed"], v["permission_denials"]), (1, 1, 1, 0))
        self.assertEqual(v["last_compaction"], {"trigger": "auto", "pre_tokens": 783484, "post_tokens": 7209,
                                                "duration_ms": 69703})
        self.assertEqual(v["last_removed_reason"], "absorbed_mid_turn")
        self.assertNotIn("seq", v)

    def test_one_kind_reported_does_not_invent_zeros_for_others(self):
        # 실데이터 t11 에서 났던 섞임: 권한 거부 0 이 보고되자 '압축 0 회' 가 함께 실렸다 -- 본 종류만 싣는다
        v = metric([ev("run.end", 0, 1, permission_denials=0)]).value
        self.assertEqual(v, {"permission_denials": 0})

    def test_model_written_summary_is_not_an_action(self):
        self.assertIsNone(metric([ev("post_turn_summary", 0, 1)]).value)


if __name__ == "__main__":
    unittest.main()
