"""S4 창 (baseline#3 CMD-S21): provider.rate_limit_window 를 L0 묶기로 읽는다. 창을 임의로 고르지 않는다.

    quota_headroom (v2)          선언된 창 가운데 가장 작은 여유. 창 사용률을 하나라도 못 봤으면 모름. 창이 없으면 v1 그대로
    quota_time_to_reset_ms (v2)  그 여유를 정한 창이 다시 차기까지(같은 여유가 여럿이면 가장 늦은 것). 창이 없으면 v1 그대로
    quota_resets_at_ms           그 창의 선언된 재설정 시각(unix ms) 그대로 -- 평가 시각이 필요 없다(BD-90)
    quota_windows                창마다 여유 · 재설정 시각 · 남은 시간 -- 고르지 않는다
"""
import unittest

from llmsensor.sensing.l0 import batches
from llmsensor.sensing.provider import NEW_METRICS
from llmsensor.state import REGISTRY
from tests.test_state import RUN, end, engine, mc

R = f"runtime:{RUN}"
AT = 1_790_884_000_000          # unix ms
A5, A7 = AT + 3_600_000, AT + 86_400_000


def ev(seq, ty, data, tb="unix_ms", unobserved=(), reported_null=()):
    return {"spec": "l0-telemetry/1", "id": f"{RUN}:{seq}", "type": ty, "run_id": RUN, "seq": seq, "source": "cc_stream",
            "at": AT, "time_base": tb, "data": data, "unobserved": list(unobserved), "reported_null": list(reported_null)}


def rl(seq, u=0.8, tb="unix_ms", resets=A7):
    return ev(seq, "provider.rate_limit", {"utilization": u, "declared_status": "allowed_warning",
                                           "limit_type": "seven_day", "resets_at_ms": resets}, tb)


def win(seq, name, u, resets, tb="unix_ms", **kw):
    d = {"window_name": name, "resets_at_ms": resets}
    if u is not None:
        d["utilization"] = u
    return ev(seq, "provider.rate_limit_window", d, tb, **kw)


def m(E, name):
    ms = [x for i, x in E.metrics.items() if i.startswith(f"{R}/{name}@")]
    return max(ms, key=lambda x: int(str(x.id.rsplit("@", 1)[1]).split("+")[0]))


def run(evs, recs=()):
    return engine(list(recs)).ingest_all(batches(evs))


class TwoWindows(unittest.TestCase):
    def test_smallest_headroom_not_the_first_window(self):
        E = run([rl(1), win(2, "five_hour", 0.7, A5), win(3, "seven_day", 0.8, A7)])
        h = m(E, "quota_headroom")
        self.assertEqual(h.value, 0.2)
        self.assertIn("seven_day", h.reason)
        self.assertNotIn("five_hour", h.reason)
        self.assertIn("사건 seq 3", h.reason)             # 값을 정한 창의 근거(BD-57)
        t = m(E, "quota_time_to_reset_ms")
        self.assertEqual(t.value, A7 - AT)
        self.assertIn("seven_day", t.reason)

    def test_smallest_headroom_not_the_last_window(self):
        E = run([rl(1), win(2, "seven_day", 0.8, A7), win(3, "five_hour", 0.7, A5)])
        self.assertEqual(m(E, "quota_headroom").value, 0.2)
        self.assertEqual(m(E, "quota_time_to_reset_ms").value, A7 - AT)

    def test_windows_metric_keeps_every_window(self):
        E = run([rl(1), win(2, "five_hour", 0.7, A5), win(3, "seven_day", 0.8, A7)])
        w = m(E, "quota_windows").value
        self.assertEqual(set(w), {"five_hour", "seven_day"})
        self.assertEqual(w["five_hour"], {"headroom": 0.3, "resets_at_ms": A5, "time_to_reset_ms": A5 - AT})
        self.assertEqual(w["seven_day"]["headroom"], 0.2)

    def test_tie_names_both_and_waits_for_the_later_reset(self):
        E = run([rl(1), win(2, "five_hour", 0.8, A5), win(3, "seven_day", 0.8, A7)])
        h = m(E, "quota_headroom")
        self.assertEqual(h.value, 0.2)
        self.assertIn("five_hour", h.reason)
        self.assertIn("seven_day", h.reason)
        self.assertEqual(m(E, "quota_time_to_reset_ms").value, A7 - AT)   # 둘 다 차야 가장 작은 여유가 오른다

    def test_unseen_window_utilization_is_unknown(self):
        E = run([rl(1), win(2, "five_hour", None, A5, unobserved=["utilization"]), win(3, "seven_day", 0.8, A7)])
        h = m(E, "quota_headroom")
        self.assertIsNone(h.value)
        self.assertIn("five_hour", h.reason)
        self.assertIsNone(m(E, "quota_time_to_reset_ms").value)
        self.assertIsNone(m(E, "quota_windows").value["five_hour"]["headroom"])

    def test_monotonic_time_base_gives_no_time_to_reset(self):
        E = run([rl(1, tb="monotonic_ms"), win(2, "five_hour", 0.7, A5, "monotonic_ms"),
                 win(3, "seven_day", 0.8, A7, "monotonic_ms")])
        self.assertEqual(m(E, "quota_headroom").value, 0.2)              # 여유는 시각이 필요 없다
        t = m(E, "quota_time_to_reset_ms")
        self.assertIsNone(t.value)
        self.assertIn("unix ms 가 아니다", t.reason)
        w = m(E, "quota_windows").value["seven_day"]
        self.assertEqual((w["resets_at_ms"], w["time_to_reset_ms"]), (A7, None))   # 선언된 시각은 그대로 싣는다


class ResetsAt(unittest.TestCase):
    """BD-90: 남은 시간 대신 선언된 재설정 시각 그대로 -- monotonic 원천(cc_stream)에서도 선다."""

    def test_binding_window_reset(self):
        E = run([rl(1), win(2, "five_hour", 0.7, A5), win(3, "seven_day", 0.8, A7)])
        r = m(E, "quota_resets_at_ms")
        self.assertEqual(r.value, A7)
        self.assertIn("seven_day", r.reason)

    def test_tie_takes_the_later_reset(self):
        E = run([rl(1), win(2, "five_hour", 0.8, A5), win(3, "seven_day", 0.8, A7)])
        self.assertEqual(m(E, "quota_resets_at_ms").value, A7)

    def test_monotonic_source_still_has_the_declared_time(self):
        E = run([rl(1, tb="monotonic_ms"), win(2, "five_hour", 0.7, A5, "monotonic_ms"),
                 win(3, "seven_day", 0.8, A7, "monotonic_ms")])
        self.assertEqual(m(E, "quota_resets_at_ms").value, A7)
        self.assertIsNone(m(E, "quota_time_to_reset_ms").value)
        E = run([rl(1, tb="monotonic_ms", resets=AT + 800_000)])          # 창 없음 -- v1 길
        self.assertEqual(m(E, "quota_resets_at_ms").value, AT + 800_000)

    def test_unknown_when_binding_is_unknown_or_unobserved(self):
        E = run([rl(1), win(2, "five_hour", None, A5, unobserved=["utilization"]), win(3, "seven_day", 0.8, A7)])
        self.assertIsNone(m(E, "quota_resets_at_ms").value)
        E = run([ev(1, "provider.rate_limit", {"utilization": 0.8}, unobserved=["resets_at_ms"])])
        r = m(E, "quota_resets_at_ms")
        self.assertIsNone(r.value)
        self.assertIn("unobserved", r.reason)

    def test_agrees_with_time_to_reset_on_unix(self):
        E = run([rl(1), win(2, "five_hour", 0.7, A5), win(3, "seven_day", 0.8, A7)])
        self.assertEqual(m(E, "quota_resets_at_ms").value - AT, m(E, "quota_time_to_reset_ms").value)


class NoWindows(unittest.TestCase):
    def test_headroom_same_as_v1(self):
        E = engine([mc(0, 100), end(rate_limit_utilization=0.72)])
        self.assertEqual(m(E, "quota_headroom").value, 0.28)
        self.assertIsNone(m(E, "quota_windows").value)

    def test_time_to_reset_same_as_v1(self):
        E = run([rl(1, resets=AT + 800_000)])
        self.assertEqual(m(E, "quota_time_to_reset_ms").value, 800_000)
        self.assertIsNone(m(E, "quota_windows").value)

    def test_report_without_windows_clears_stale_windows(self):
        # 창이 있던 보고 뒤에 창 없는 보고가 오면, 앞 창은 낡았다 -- v1 길(그 보고의 값)로 돌아간다
        E = run([rl(1), win(2, "five_hour", 0.95, A5), win(3, "seven_day", 0.8, A7), rl(4, resets=AT + 800_000)],
                [mc(0, 100), end(rate_limit_utilization=0.5)])
        self.assertIsNone(m(E, "quota_windows").value)
        self.assertEqual(m(E, "quota_headroom").value, 0.5)
        self.assertEqual(m(E, "quota_time_to_reset_ms").value, 800_000)

    def test_next_report_replaces_windows(self):
        E = run([rl(1), win(2, "five_hour", 0.95, A5), rl(3), win(4, "seven_day", 0.8, A7)])
        self.assertEqual(set(m(E, "quota_windows").value), {"seven_day"})
        self.assertEqual(m(E, "quota_headroom").value, 0.2)


class Contract(unittest.TestCase):
    def test_versions(self):
        v = {d.name: d.version for d in NEW_METRICS}
        self.assertEqual((v["quota_headroom"], v["quota_time_to_reset_ms"], v["quota_windows"]), (2, 2, 1))
        self.assertIs(REGISTRY.metrics["quota_headroom"].fn, next(d for d in NEW_METRICS if d.name == "quota_headroom").fn)

    def test_state_count_unchanged(self):
        self.assertLessEqual(len(REGISTRY.rules), 15)      # 지표만 늘었다


if __name__ == "__main__":
    unittest.main()
