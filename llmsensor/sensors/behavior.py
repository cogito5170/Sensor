"""행동 센서 -- 토큰 팽창 · 붕괴 · 재시도 팽창 · 도구 고리 · 지연.

**이 센서는 '성공했나' 를 재지 않는다.** '평소처럼 행동하나' 를 잰다. 그래서 융합에서 가장 약한 증거로 들어가고,
판정기는 이것만으로 ACCEPT 하지 않는다.

  loop      같은 (호출, 출력) 이 loop_k 번 -- 새 관측 없이 맴돈다 -> FAULT
            ABAB 진동이 loop_k 바퀴 -> FAULT
            같은 호출(출력은 달라도)이 2*loop_k 번 -> SUSPECT (폴링일 수도 있다)
  tokens    성능모형이 있어야 한다. log T 의 강건 z(중앙값 · MAD). z > z_fault 팽창 FAULT, < -z_fault 붕괴 SUSPECT
  retry     성능모형이 있으면 R 의 강건 z, 없으면 절대 문턱
  latency   성능모형이 있을 때만
  budget    max_tokens 를 넘으면 FAULT

모형이 없으면 tokens · latency 는 UNKNOWN 이다 -- 기준 없이 '많다' 고 하지 않는다.
"""
from __future__ import annotations

import hashlib

from ..reading import Reading, OK, SUSPECT, FAULT, UNKNOWN, worst
from ..trace import Task, call_sig, telemetry


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode()).hexdigest()[:12]


def oscillation(sigs: "list[str]") -> int:
    """가장 긴 ABAB.. 구간의 바퀴 수(AB 한 쌍이 한 바퀴)."""
    best = run = 0
    for i in range(2, len(sigs)):
        if sigs[i] == sigs[i - 2] and sigs[i] != sigs[i - 1]:
            run = run + 1 if run else 3
            best = max(best, run)
        else:
            run = 0
    return best // 2


class BehaviorSensor:
    name = "behavior"

    def __init__(self, model=None, z_fault: float = 3.5, z_suspect: float = 2.5, loop_k: int = 3,
                 retry_suspect: int = 3, retry_fault: int = 5, max_tokens: "int | None" = None):
        self.model, self.z_fault, self.z_suspect, self.loop_k = model, z_fault, z_suspect, loop_k
        self.retry_suspect, self.retry_fault, self.max_tokens = retry_suspect, retry_fault, max_tokens

    def loop(self, task: Task) -> Reading:
        if not task.calls:
            return Reading("behavior.loop", UNKNOWN, "도구 호출이 없다")
        sigs = [call_sig(c) for c in task.calls]
        same_obs: dict = {}
        same: dict = {}
        for c, s in zip(task.calls, sigs):
            k = (s, _h(c.output))
            same_obs[k] = same_obs.get(k, 0) + 1
            same[s] = same.get(s, 0) + 1
        stuck, rep, osc = max(same_obs.values()), max(same.values()), oscillation(sigs)
        det = {"max_same_call_same_output": stuck, "max_same_call": rep, "oscillation_cycles": osc}
        if stuck >= self.loop_k:
            return Reading("behavior.loop", FAULT, f"같은 호출이 같은 출력으로 {stuck} 번 -- 새 관측 없이 맴돈다",
                           float(stuck), det)
        if osc >= self.loop_k:
            return Reading("behavior.loop", FAULT, f"두 호출 사이 진동 {osc} 바퀴", float(osc), det)
        if rep >= 2 * self.loop_k:
            return Reading("behavior.loop", SUSPECT, f"같은 호출 {rep} 번(출력은 달랐다 -- 폴링일 수도)",
                           float(rep), det)
        return Reading("behavior.loop", OK, "고리 없음", 0.0, det)

    def _z(self, task, key, x, label, high_fault=True) -> Reading:
        z = self.model.z(task.cls, key, x)
        nm = f"behavior.{label}"
        if z is None:
            return Reading(nm, UNKNOWN, f"{task.cls!r} 부류의 기준이 없다")
        det = {"z": z, "value": x, "expected": self.model.expect(task.cls).get(key)}
        if z > self.z_fault:
            return Reading(nm, FAULT if high_fault else SUSPECT, f"{label} 팽창 z={z:.1f}", z, det)
        if z < -self.z_fault:
            return Reading(nm, SUSPECT, f"{label} 붕괴 z={z:.1f} -- 일찍 포기했을 수 있다", z, det)
        if abs(z) > self.z_suspect:
            return Reading(nm, SUSPECT, f"{label} 문턱 근처 z={z:.1f}", z, det)
        return Reading(nm, OK, f"{label} 평소대로 z={z:.1f}", z, det)

    def read(self, task: Task) -> Reading:
        tel = telemetry(task)
        subs = [self.loop(task)]
        if self.model is not None and tel["T"] > 0:
            subs.append(self._z(task, "T", tel["T"], "tokens"))
        else:
            subs.append(Reading("behavior.tokens", UNKNOWN, "성능모형이 없거나 토큰 기록이 없다"))
        if self.model is not None:
            subs.append(self._z(task, "R", tel["R"], "retry"))
        else:
            r = tel["R"]
            st = FAULT if r >= self.retry_fault else SUSPECT if r >= self.retry_suspect else OK
            subs.append(Reading("behavior.retry", st, f"재시도 {r}", float(r), {"R": r}))
        if self.model is not None and tel["latency"]:
            subs.append(self._z(task, "latency", tel["latency"], "latency", high_fault=False))
        if self.max_tokens is not None and tel["T"]:
            over = tel["T"] > self.max_tokens
            subs.append(Reading("behavior.budget", FAULT if over else OK,
                                f"토큰 {tel['T']:,} {'>' if over else '<='} 예산 {self.max_tokens:,}",
                                tel["T"] / self.max_tokens))
        st = worst(subs)
        bad = [s for s in subs if s.status == st and st != UNKNOWN]
        return Reading(self.name, st, " · ".join(s.why for s in bad) if bad else "평가할 것이 없다", None,
                       {s.sensor.split(".")[1]: s.to_dict() for s in subs} | {"telemetry": tel})
