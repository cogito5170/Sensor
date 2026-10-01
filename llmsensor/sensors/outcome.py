"""외부 결과 센서 -- 단위 시험 · 컴파일러 · 시뮬레이션 · DB 조회. 가장 진실에 가까운 센서.

명령(cmd)을 돌려 종료 코드를 보거나, 함수 fn(task) -> True/False/None 을 부른다.

    종료 0 / True          OK
    종료 != 0 / False      FAULT
    못 돌림(없는 명령 · 시간 초과 · fn 이 None 이나 예외)   UNKNOWN  -- 못 잰 것을 실패로도 성공으로도 안 센다
"""
from __future__ import annotations

import shlex
import subprocess
import time

from ..reading import Reading, OK, FAULT, UNKNOWN


class ExternalOutcomeSensor:
    name = "outcome"

    def __init__(self, cmd=None, fn=None, cwd=None, timeout: float = 600, env=None):
        if (cmd is None) == (fn is None):
            raise ValueError("cmd 와 fn 중 정확히 하나")
        self.cmd = shlex.split(cmd) if isinstance(cmd, str) else cmd
        self.fn, self.cwd, self.timeout, self.env = fn, cwd, timeout, env

    def read(self, task=None) -> Reading:
        if self.fn is not None:
            try:
                r = self.fn(task)
            except Exception as ex:
                return Reading(self.name, UNKNOWN, f"검증 함수가 터졌다: {type(ex).__name__}: {ex}")
            if r is None:
                return Reading(self.name, UNKNOWN, "검증 함수가 판정을 안 냈다")
            return Reading(self.name, OK if r else FAULT, "외부 검증 통과" if r else "외부 검증 실패", float(bool(r)))
        t0 = time.time()
        try:
            p = subprocess.run(self.cmd, cwd=self.cwd, env=self.env, capture_output=True, text=True,
                               timeout=self.timeout)
        except FileNotFoundError:
            return Reading(self.name, UNKNOWN, f"명령이 없다: {self.cmd[0]}")
        except subprocess.TimeoutExpired:
            return Reading(self.name, UNKNOWN, f"{self.timeout}s 안에 안 끝났다")
        det = {"returncode": p.returncode, "seconds": round(time.time() - t0, 3),
               "tail": (p.stdout + p.stderr)[-400:]}
        if p.returncode == 0:
            return Reading(self.name, OK, f"`{' '.join(self.cmd)}` 종료 0", 1.0, det)
        return Reading(self.name, FAULT, f"`{' '.join(self.cmd)}` 종료 {p.returncode}", 0.0, det)
