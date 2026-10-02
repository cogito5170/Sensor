"""L0 Telemetry(cogito5170/Telemetry) -- **필수 의존** (2026-10-02, CMD-T9 · BD-62). 원천 수집은 L0 가 한다.

    pip install "llmsensor"            # 의존성 l0-telemetry 를 함께 깐다
    pip install git+https://github.com/cogito5170/Telemetry   # 따로 깔 때

    require()                           L0 패키지(telemetry)를 돌려준다. 없으면 무엇을 깔지 말하는 ImportError
    available()                         require() 가 되나
    collect(source, path, run_id)       -> (꼴 v3 레코드들, "l0")   (prefer_l0 인자는 옛 호출을 위해 남겼다 -- 무시한다)
    records_from_ledger(path)           L0 원장(JSONL) -> 꼴 v3 레코드
    compare(source, path, run_id)       L0 경로의 **불변식** 확인 -- 꼴 v4 · 결정성 · State 정규화.
                                        원래 수집기를 지웠으므로 '같은가' 는 더 이상 두 수집기를 맞대지 않는다.
                                        지우기 전 출력과의 대조는 Telemetry eval/l0_check.py --verify (얼린 지문).

찾는 순서: 설치된 `telemetry`(SPEC 이 l0-telemetry/ 인 것만 -- 이름만 같은 다른 패키지는 아니다) ->
**소스 checkout 일 때만** 옆 `../Telemetry`(네 저장소를 통합 머리끼리 나란히 둔 배치). `LLMSENSOR_L0_SIBLING=0` 이면 옆을 안 본다.
"""
from __future__ import annotations

import importlib
import os
import secrets
import sys
from pathlib import Path

SOURCES = ("cc_jsonl", "cc_stream", "sweagent")
MISSING = ("L0 Telemetry 가 없다 -- Sensor 의 원천 수집은 cogito5170/Telemetry 가 한다(필수 의존). "
           "pip install git+https://github.com/cogito5170/Telemetry  (또는 저장소를 ../Telemetry 에 두고 소스에서 쓴다)")


def _ok(mod) -> bool:
    return str(getattr(mod, "SPEC", "")).startswith("l0-telemetry/")


def _sibling() -> "Path | None":
    """소스 checkout(옆에 pyproject.toml 이 있는 저장소)일 때만 ../Telemetry. 설치본(site-packages)에서는 None."""
    if os.environ.get("LLMSENSOR_L0_SIBLING") == "0":
        return None
    repo = Path(__file__).resolve().parents[2]
    sib = repo.parent / "Telemetry"
    if (repo / "pyproject.toml").is_file() and (sib / "telemetry" / "__init__.py").is_file():
        return sib
    return None


def require():
    try:
        t = importlib.import_module("telemetry")
    except ImportError:
        t = None
    if t is not None and _ok(t):
        return t
    if t is not None:
        raise ImportError(f"`telemetry` 라는 다른 패키지가 깔려 있다({getattr(t, '__file__', '?')}) -- " + MISSING)
    sib = _sibling()
    if sib is not None:
        sys.path.append(str(sib))
        sys.modules.pop("telemetry", None)
        t = importlib.import_module("telemetry")
        if _ok(t):
            return t
    raise ImportError(MISSING)


def available() -> bool:
    try:
        require()
        return True
    except ImportError:
        return False


def _events(source, path, run_id, hasher=None):
    require()
    from telemetry import collect as c
    fn = {"cc_jsonl": c.from_cc_jsonl, "cc_stream": c.from_cc_stream, "sweagent": c.from_sweagent}[source]
    return fn(path, run_id, hasher)


def collect(source: str, path, run_id: str, prefer_l0: bool = True) -> "tuple[list, str]":
    if source not in SOURCES:
        raise ValueError(f"모르는 원천 {source!r}")
    require()
    from telemetry.compat import to_sensor_records
    return to_sensor_records(_events(source, path, run_id)), "l0"


def records_from_ledger(path) -> "list[dict]":
    require()
    from telemetry import ledger
    from telemetry.compat import to_sensor_records
    return to_sensor_records(ledger.read(path))


def compare(source: str, path, run_id: str = "cmp") -> dict:
    """L0 경로의 불변식: 레코드가 모두 꼴 v4 를 통과 · 같은 열쇠로 두 번 지으면 같다 · State 정규화가 받는다.
    `same` 은 셋이 모두 참인가다(옛 이름 그대로 -- cli l0-check 가 이것으로 종료 코드를 정한다)."""
    if not available():
        return {"available": False}
    from telemetry.compat import to_sensor_records
    from telemetry.hashing import Hasher
    from .schema import check
    key = secrets.token_bytes(32)
    a = to_sensor_records(_events(source, path, run_id, Hasher(key)))
    b = to_sensor_records(_events(source, path, run_id, Hasher(key)))
    bad = [(r["kind"], e) for r in a for e in check(r)]
    try:
        from ..state.normalize import from_telemetry
        from_telemetry(a)
        state_ok, state_err = True, None
    except Exception as e:                       # noqa: BLE001 -- 무엇이 깨졌는지 보고한다
        state_ok, state_err = False, f"{type(e).__name__}: {e}"
    same = not bad and a == b and state_ok
    return {"available": True, "source": source, "against": "invariants", "native": None, "l0": len(a),
            "same": same, "schema_errors": bad[:5], "deterministic": a == b, "state_ingest": state_ok,
            "first_diff": None if same else {"record": "invariants", "fields": [x for x, ok in (
                ("schema", not bad), ("determinism", a == b), ("state", state_ok)) if not ok], "state_error": state_err}}
