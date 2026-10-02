"""원천 -> 꼴 v3 레코드. **수집은 L0 Telemetry 가 한다** (2026-10-02, CMD-T9 · BD-62 -- 수집기가 두 벌이면 결함을 두 번 고쳐야 했다).

이 모듈은 이음매다. 같은 이름 · 같은 서명을 남겨, 부르는 쪽(Sensor eval/health_inventory.py · DC examples/sensor_session.py 등)이
고치지 않아도 돈다. 안에서 L0 수집기(telemetry.collect)로 사건을 짓고 telemetry.compat.to_sensor_records 로 꼴 v3 레코드를 돌려준다.

    from_cc_jsonl(path, run_id, hasher=None)    Claude Code 세션 JSONL
    from_cc_stream(path, run_id, hasher=None)   {"_t", "line"} 캡처(claude -p stream-json)
    from_sweagent(path, run_id, hasher=None)    SWE-agent .traj(.gz)
    Hasher · TIMEOUT_TEXT · PROGRAM              L0 의 것을 그대로(같은 열쇠면 같은 해시)

수집 규칙(겨냥 해시 · D1 시간 초과 · D2 API 오류 줄 · 원천 순서 …)의 원본은 cogito5170/Telemetry `telemetry/collect/`.
L0 가 없으면 import 할 때 ImportError -- 무엇을 깔지 말한다(llmsensor.telemetry.l0.require).

지우기 전 이 저장소 수집기의 출력은 Telemetry `tests/golden/*.json`(시험 고정 자료)과 `eval/results/l0_check_corpus.json`
의 `v3_digest`(실기록)로 얼려 두었다. 이음매가 그 출력과 같은지는 그쪽 시험 · `eval/l0_check.py --verify` 가 본다.
"""
from __future__ import annotations

from .l0 import require

require()

from telemetry.collect import TIMEOUT_TEXT  # noqa: E402,F401
from telemetry.compat import to_sensor_records  # noqa: E402
from telemetry.hashing import PROGRAM, Hasher, default_hasher  # noqa: E402,F401
from telemetry import collect as _l0  # noqa: E402


def from_cc_jsonl(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    return to_sensor_records(_l0.from_cc_jsonl(path, run_id, hasher))


def from_cc_stream(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    return to_sensor_records(_l0.from_cc_stream(path, run_id, hasher))


def from_sweagent(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    return to_sensor_records(_l0.from_sweagent(path, run_id, hasher))
