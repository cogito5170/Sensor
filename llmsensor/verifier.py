"""판정기 -- LLM 이 자기 성공을 판정하지 않는다. 결정론적 규칙이 한다.

    ACCEPT   받는다
    REJECT   버린다(재시도 다 씀)
    RETRY    다시 시킨다(같은 경로)
    DEGRADE  이 경로로는 결론을 못 낸다 -- 더 강한 검증 · 다른 모형 · 사람으로 올리거나 예산을 줄인다

규칙(위에서부터 처음 맞는 것):

  1. 하드 실패: 외부 결과 FAULT 또는 제약 FAULT            -> RETRY (attempt < max_retries) / REJECT
  2. 외부 결과 OK 이고 Q >= accept_q                         -> ACCEPT (행동 FAULT 는 비용 경고로만 붙는다)
  3. 일관성 FAULT(false success)                             -> RETRY / REJECT
  4. 행동 FAULT(고리 · 팽창 · 예산)                          -> DEGRADE
  5. Q >= accept_q 이고 **근거 있음**                        -> ACCEPT
  6. Q >= accept_q 인데 근거 없음                            -> DEGRADE
  7. Q <= reject_q                                           -> RETRY / REJECT
  8. 나머지(불확실)                                          -> DEGRADE

근거 있음 = 외부 결과 OK · 제약 OK · 일관성의 claim OK(마지막 검증 성공) 중 하나.
**토큰 · 실행 성공만으로는 ACCEPT 하지 않는다** -- 둘 다 '행동' 의 증거이지 '결과' 의 증거가 아니다.

판정마다 `policy` 에 다음 실행을 위한 정책 제안(예산 · 재시도 한도 · 경로)을 붙인다. 가중치를 바꾸는 것이 아니라
정책을 바꾸는 것이 먼저다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .reading import OK, FAULT

ACCEPT, REJECT, RETRY, DEGRADE = "ACCEPT", "REJECT", "RETRY", "DEGRADE"


@dataclass
class Verdict:
    action: str
    rule: int
    reasons: list = field(default_factory=list)
    policy: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Verifier:
    def __init__(self, accept_q: float = 0.8, reject_q: float = 0.2, max_retries: int = 2):
        self.accept_q, self.reject_q, self.max_retries = accept_q, reject_q, max_retries

    def _again(self, attempt, rule, reasons, policy) -> Verdict:
        if attempt < self.max_retries:
            return Verdict(RETRY, rule, reasons, policy)
        return Verdict(REJECT, rule, reasons + [f"재시도 {attempt}/{self.max_retries} 다 씀"], policy)

    def decide(self, readings, q: float, attempt: int = 0, telemetry: "dict | None" = None,
               expected: "dict | None" = None) -> Verdict:
        by = {r.sensor: r for r in readings}
        st = {k: r.status for k, r in by.items()}
        claim = by.get("consistency").detail.get("claim", {}).get("status") if "consistency" in by else None
        loop = by.get("behavior").detail.get("loop", {}).get("status") if "behavior" in by else None
        policy: dict = {}
        if telemetry and expected and expected.get("T"):
            # 다음 예산 = 이 부류 기대 토큰의 3 배. 팽창한 실행이 예산을 끌어올리지 않게 관측값이 아니라 기대값에서
            policy["token_budget"] = int(3 * expected["T"])
        if loop == FAULT:
            policy["terminate_on_repeat"] = True
        bad_beh = st.get("behavior") == FAULT
        if bad_beh:
            policy.setdefault("retry_limit", max(0, self.max_retries - 1))

        hard = [k for k in ("outcome", "constraint") if st.get(k) == FAULT]
        if hard:
            return self._again(attempt, 1, [f"{k}: {by[k].why}" for k in hard], policy)
        if st.get("outcome") == OK and q >= self.accept_q:
            rs = [f"outcome: {by['outcome'].why}"]
            if bad_beh:
                rs.append(f"비용 경고 -- behavior: {by['behavior'].why}")
            return Verdict(ACCEPT, 2, rs, policy)
        if st.get("consistency") == FAULT:
            return self._again(attempt, 3, [f"consistency: {by['consistency'].why}"], policy)
        if bad_beh:
            policy["route"] = "escalate"
            return Verdict(DEGRADE, 4, [f"behavior: {by['behavior'].why}"], policy)
        grounded = st.get("outcome") == OK or st.get("constraint") == OK or claim == OK
        if q >= self.accept_q:
            if grounded:
                return Verdict(ACCEPT, 5, [f"Q={q:.2f} >= {self.accept_q} · 결과 근거 있음"], policy)
            policy["route"] = "verify"
            return Verdict(DEGRADE, 6, [f"Q={q:.2f} 이지만 결과 근거가 없다(토큰 · 실행 성공뿐) -- 외부 검증으로"],
                           policy)
        if q <= self.reject_q:
            return self._again(attempt, 7, [f"Q={q:.2f} <= {self.reject_q}"], policy)
        policy["route"] = "verify"
        return Verdict(DEGRADE, 8, [f"Q={q:.2f} 불확실"], policy)
