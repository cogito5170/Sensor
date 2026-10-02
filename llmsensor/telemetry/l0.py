"""L0 Telemetry(cogito5170/Telemetry) -- **선택 의존**. 깔려 있으면 원천을 그쪽 수집기로 L0 사건 원장에 적고, 그 원장에서
꼴 v3 레코드를 되지어(`telemetry.compat.to_sensor_records`) 이 저장소의 State 층에 넘긴다. 없으면 지금 수집기(collect.py)를 쓴다.

    pip install "llmsensor[l0]"        또는  pip install git+https://github.com/cogito5170/Telemetry

    available()                         L0 패키지가 있나 (이름만 같은 다른 `telemetry` 는 아니다 -- SPEC 으로 가린다)
    collect(source, path, run_id)       -> (레코드들, "l0" | "native")
    records_from_ledger(path)           L0 원장(JSONL) -> 꼴 v3 레코드. L0 가 없으면 ImportError
    compare(source, path, run_id)       두 길이 같은 레코드를 내나 -- 실데이터에서 계속 같으면 필수 의존으로 바꾼다(Telemetry docs 9 절)

L0 는 판단하지 않는다. 이 모듈도 판단하지 않는다 -- 꼴을 옮길 뿐이다.
"""
from __future__ import annotations

import importlib
import secrets

from . import collect as native

SOURCES = ("cc_jsonl", "cc_stream", "sweagent")
_NATIVE = {"cc_jsonl": native.from_cc_jsonl, "cc_stream": native.from_cc_stream, "sweagent": native.from_sweagent}


def _l0():
    try:
        t = importlib.import_module("telemetry")
    except ImportError:
        return None
    return t if str(getattr(t, "SPEC", "")).startswith("l0-telemetry/") else None


def available() -> bool:
    return _l0() is not None


def _l0_events(source, path, run_id, key=None):
    from telemetry import collect as c
    from telemetry.hashing import Hasher
    fn = {"cc_jsonl": c.from_cc_jsonl, "cc_stream": c.from_cc_stream, "sweagent": c.from_sweagent}[source]
    return fn(path, run_id, Hasher(key) if key is not None else None)


def collect(source: str, path, run_id: str, prefer_l0: bool = True) -> "tuple[list, str]":
    if source not in SOURCES:
        raise ValueError(f"모르는 원천 {source!r}")
    if prefer_l0 and available():
        from telemetry.compat import to_sensor_records
        return to_sensor_records(_l0_events(source, path, run_id)), "l0"
    return _NATIVE[source](path, run_id), "native"


def records_from_ledger(path) -> "list[dict]":
    if not available():
        raise ImportError("L0 Telemetry 가 없다 -- pip install git+https://github.com/cogito5170/Telemetry")
    from telemetry import ledger
    from telemetry.compat import to_sensor_records
    return to_sensor_records(ledger.read(path))


def compare(source: str, path, run_id: str = "cmp") -> dict:
    """같은 열쇠로 두 길을 돌려 레코드를 맞댄다. 다르면 첫 차이를 낸다(값은 칸 이름과 함께 그대로)."""
    if not available():
        return {"available": False}
    from telemetry.compat import to_sensor_records
    key = secrets.token_bytes(32)
    ours = _NATIVE[source](path, run_id, native.Hasher(key))
    theirs = to_sensor_records(_l0_events(source, path, run_id, key))

    def k(r):
        return (r["kind"], r["tool_index"] if r["kind"] == "tool_call" else r.get("call_index", -1))
    a, b = sorted(ours, key=k), sorted(theirs, key=k)
    out = {"available": True, "source": source, "native": len(a), "l0": len(b), "same": a == b, "first_diff": None}
    if not out["same"]:
        for x, y in zip(a, b):
            if x != y:
                out["first_diff"] = {"record": k(x), "fields": sorted(f for f in set(x) | set(y) if x.get(f) != y.get(f))}
                break
        else:
            out["first_diff"] = {"record": "count", "fields": []}
    return out
