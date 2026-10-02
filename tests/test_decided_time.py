"""BD-57 · BD-63 (baseline#3 CMD-S8): 집계 상태의 근거 시각 = 그 값을 **정한** 근거의 시각, 여럿이면 가장 이른 것.

baseline#5 Q4 의 실제 사례를 줄인 꼴: 오래전 한 도구(WebFetch)의 실패가 미해결로 남아 있는데, 다른 도구의 새 결과가 계속
들어와 집계가 신선해 보였다. 값을 정하지 않은 새 근거가 낡은 결론을 신선하게 보이게 하면 STALE 판정이 틀린다.
"""
import unittest

from llmsensor.state import DEFAULT_CONFIG, Status
from llmsensor.state.model import Freshness
from tests.test_state import A, RUN, mc, tc, val
from tests.test_state import engine as eng

HOUR = 3600_000
TTL = DEFAULT_CONFIG.ttl_ms["execution_health"]


class Aggregate(unittest.TestCase):
    def test_unresolved_failure_keeps_its_own_time(self):
        recs = [mc(0, 100), tc(0, 0, 100, name="WebFetch", head="WebFetch:x", err=True)]
        for i in range(1, 8):                                   # 7 시간 동안 다른 도구가 계속 성공
            recs += [mc(i, 100 + i * HOUR), tc(i, i, 100 + i * HOUR, name="Bash", head=f"Bash:{i}")]
        E = eng(recs)
        st = E.current[(A, "execution_health")]
        self.assertEqual(st.value, "UNRESOLVED_FAILURES")
        self.assertEqual(st.observed_at, 100)                   # 실패의 시각 -- 마지막 성공의 시각이 아니다
        v = val(E, A, "execution_health", now=100 + 7 * HOUR)
        self.assertEqual((v.freshness, v.status), (Freshness.STALE, Status.STALE))

    def test_earliest_of_several_deciding_failures(self):
        recs = [mc(0, 100), tc(0, 0, 100, head="Bash:a", err=True), mc(1, 5000), tc(1, 1, 5000, head="Bash:b", err=True),
                mc(2, 9000), tc(2, 2, 9000, head="Bash:c")]
        st = eng(recs).current[(A, "execution_health")]
        self.assertEqual((st.value, st.observed_at), ("UNRESOLVED_FAILURES", 100))

    def test_recovered_takes_the_recovery_time(self):
        recs = [mc(0, 100), tc(0, 0, 100, head="Bash:a", err=True), mc(1, 5000), tc(1, 1, 5000, head="Bash:a"),
                mc(2, 9000), tc(2, 2, 9000, head="Bash:z")]
        st = eng(recs).current[(A, "execution_health")]
        self.assertEqual((st.value, st.observed_at), ("RECOVERED_FAILURES", 5000))

    def test_no_failure_stays_as_fresh_as_latest_result(self):
        # '실패 없음' 은 결과마다 다시 확인된다 -- 그대로 가장 늦은 결과(baseline 에 해석을 물었다)
        recs = [mc(0, 100), tc(0, 0, 100, head="Bash:a"), mc(1, 9000), tc(1, 1, 9000, head="Bash:b")]
        st = eng(recs).current[(A, "execution_health")]
        self.assertEqual((st.value, st.observed_at), ("NO_FAILURE_OBSERVED", 9000))

    def test_tool_entity_follows_the_same_rule(self):
        recs = [mc(0, 100), tc(0, 0, 100, name="WebFetch", head="WebFetch:x", err=True),
                mc(1, 100 + HOUR), tc(1, 1, 100 + HOUR, name="WebFetch", head="WebFetch:y")]
        st = eng(recs).current[(f"tool:{RUN}:WebFetch", "tool_execution_health")]
        self.assertEqual((st.value, st.observed_at), ("UNRESOLVED_FAILURES", 100))


if __name__ == "__main__":
    unittest.main()
