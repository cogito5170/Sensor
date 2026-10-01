"""성능모형 M_P -- 과업 부류마다 '평소에는 이렇다'.

    M_P(cls) -> 기대 T · R · L · latency · P(success)

이력(텔레메트리 + 있으면 성공 라벨)에서 **강건 통계**로 짓는다: 중앙값과 MAD(×1.4826). 토큰과 지연은 로그 눈금이다
(곱셈적으로 퍼지므로). 성공률은 Beta(1,1) 사전 위의 사후 평균이다.

부류의 표본이 min_n 보다 적으면 전체('*')로 물러난다. 전체도 min_n 보다 적으면 None(=기준 없음).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

KEYS = ("T", "R", "L", "E", "latency")
LOG = {"T", "latency"}
# MAD 바닥 -- 이력이 다 같은 값이면 MAD 가 0 이 되어 z 가 무한대로 튄다. 로그 눈금 0.1 ≈ 10%.
FLOOR = {"T": 0.1, "latency": 0.1, "R": 1.0, "L": 1.0, "E": 1.0}


def _med(xs):
    s = sorted(xs)
    n = len(s)
    return None if n == 0 else s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    m = _med(xs)
    return {"median": m, "mad": 1.4826 * _med([abs(x - m) for x in xs]), "n": len(xs)}


class PerformanceModel:
    def __init__(self, min_n: int = 5):
        self.min_n = min_n
        self.classes: dict = {}

    @staticmethod
    def _tx(key, x):
        if x is None:
            return None
        return math.log(max(float(x), 1.0)) if key in LOG else float(x)

    def fit(self, records: "list[dict]") -> "PerformanceModel":
        """records: {"cls", "T", "R", "L", "E", "latency", "success"(True/False/None)} 의 목록."""
        groups: dict = {"*": []}
        for r in records:
            groups.setdefault(r.get("cls", "default"), []).append(r)
            groups["*"].append(r)
        self.classes = {}
        for cls, rs in groups.items():
            c = {"n": len(rs)}
            for k in KEYS:
                c[k] = _stats([self._tx(k, r.get(k)) for r in rs])
            lab = [r["success"] for r in rs if r.get("success") is not None]
            c["success"] = {"k": sum(bool(x) for x in lab), "n": len(lab)}
            self.classes[cls] = c
        return self

    def fit_tasks(self, tasks, labels=None) -> "PerformanceModel":
        from .trace import telemetry
        labels = labels or [None] * len(tasks)
        return self.fit([dict(telemetry(t), cls=t.cls, success=y) for t, y in zip(tasks, labels)])

    def _cls(self, cls):
        for c in (cls, "*"):
            if c in self.classes and self.classes[c]["n"] >= self.min_n:
                return self.classes[c]
        return None

    def expect(self, cls: str) -> dict:
        c = self._cls(cls)
        if c is None:
            return {}
        out = {"n": c["n"]}
        for k in KEYS:
            s = c.get(k)
            if s:
                out[k] = math.exp(s["median"]) if k in LOG else s["median"]
        s = c["success"]
        out["p_success"] = (s["k"] + 1) / (s["n"] + 2) if s["n"] else None
        return out

    def z(self, cls: str, key: str, x) -> "float | None":
        c = self._cls(cls)
        s = c.get(key) if c else None
        if s is None or x is None:
            return None
        return (self._tx(key, x) - s["median"]) / max(s["mad"], FLOOR[key])

    def to_dict(self) -> dict:
        return {"min_n": self.min_n, "classes": self.classes}

    @classmethod
    def from_dict(cls, d: dict) -> "PerformanceModel":
        m = cls(d.get("min_n", 5))
        m.classes = d["classes"]
        return m

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "PerformanceModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
