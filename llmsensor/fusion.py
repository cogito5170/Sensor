"""성과모형 M_O -- 센서 증거를 Q = P(success | 증거) 하나로.

로그 오즈 융합(naive Bayes):

    logit(Q) = logit(prior) + Σ_sensor log LR(sensor, status)

prior 는 성능모형의 그 부류 성공률(없으면 0.5). UNKNOWN 은 LR = 1 -- 증거 0.

**기본 LR 은 잰 값이 아니다.** 우선순위(외부 결과 > 실행 > 제약 > 일관성 > 행동)를 따르게 손으로 둔 사전값이다.
라벨 붙은 이력으로 `calibrate()` 하기 전의 Q 는 확률이 아니라 순서 점수로 읽어라 -- `calibrated` 가 그것을 말한다.
또 센서들은 독립이 아니다(실행 센서와 외부 결과 센서가 같은 시험을 볼 수 있다) -- naive Bayes 는 그때 과신한다.
"""
from __future__ import annotations

import math

from .reading import OK, SUSPECT, FAULT, UNKNOWN

DEFAULT_LR = {
    "outcome":     {OK: 19.0, SUSPECT: 0.5, FAULT: 0.03},
    "execution":   {OK: 2.0,  SUSPECT: 0.7, FAULT: 0.2},
    "constraint":  {OK: 2.0,  SUSPECT: 0.6, FAULT: 0.1},
    "consistency": {OK: 1.5,  SUSPECT: 0.5, FAULT: 0.15},
    "behavior":    {OK: 1.2,  SUSPECT: 0.7, FAULT: 0.4},
}


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


class OutcomeModel:
    def __init__(self, lr: "dict | None" = None):
        self.lr = {k: dict(v) for k, v in (lr or DEFAULT_LR).items()}
        self.calibrated = False
        self.n_calib = 0

    def q(self, readings, prior: "float | None" = None) -> dict:
        p0 = 0.5 if prior is None else prior
        lo = _logit(p0)
        contrib = {}
        for r in readings:
            lr = 1.0 if r.status == UNKNOWN else self.lr.get(r.sensor, {}).get(r.status, 1.0)
            contrib[r.sensor] = math.log(lr)
            lo += math.log(lr)
        return {"Q": 1 / (1 + math.exp(-lo)), "prior": p0, "log_lr": contrib, "calibrated": self.calibrated,
                "evidence": sum(r.status != UNKNOWN for r in readings)}

    def calibrate(self, examples, alpha: float = 10.0) -> "OutcomeModel":
        """examples: (readings, success: bool) 의 목록. LR = P(status | 성공) / P(status | 실패).

        m-추정으로 다듬는다: P(st | 부류) = (c + alpha·m) / (n + alpha), m = 두 부류를 합친 그 상태의 비율.
        드문 상태의 LR 은 1 쪽으로 준다(얼마나 주는지는 부류 크기에 달렸고 상한은 없다). **한 번도 안 나온 상태는
        LR = 1** 이다(증거 없음).
        (첫 판은 Laplace 였다 -- 안 나온 상태의 LR 이 1 이 아니라 '부류 크기의 비' 가 되는 버그. 2026-10-01
        SWE-bench Lite 분석에서 늘 UNKNOWN 인 센서가 LR 2.7 을 받는 것으로 드러났다.)
        한쪽 라벨만 있으면 LR 을 못 잰다 -- ValueError."""
        pos = [r for r, y in examples if y]
        neg = [r for r, y in examples if not y]
        if not pos or not neg:
            raise ValueError("성공 · 실패 라벨이 둘 다 있어야 LR 을 잰다")
        sensors = {x.sensor for rs, _ in examples for x in rs}

        def counts(group, s):
            c = {st: 0 for st in (OK, SUSPECT, FAULT, UNKNOWN)}
            for rs in group:
                for x in rs:
                    if x.sensor == s:
                        c[x.status] += 1
            return c

        for s in sensors:
            cp, cn = counts(pos, s), counts(neg, s)
            npos, nneg = sum(cp.values()), sum(cn.values())
            lr = {}
            for st in (OK, SUSPECT, FAULT):
                tot = cp[st] + cn[st]
                if tot == 0 or npos == 0 or nneg == 0:
                    lr[st] = 1.0
                    continue
                m = tot / (npos + nneg)
                lr[st] = ((cp[st] + alpha * m) / (npos + alpha)) / ((cn[st] + alpha * m) / (nneg + alpha))
            self.lr[s] = lr
        self.calibrated, self.n_calib = True, len(examples)
        return self

    def to_dict(self) -> dict:
        return {"lr": self.lr, "calibrated": self.calibrated, "n_calib": self.n_calib}

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeModel":
        m = cls(d["lr"])
        m.calibrated, m.n_calib = d.get("calibrated", False), d.get("n_calib", 0)
        return m
