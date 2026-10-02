"""토큰 사건형 판독 -- 문턱이 있는 해석이라 **L1(Sensor)** 의 일이다. 2026-10-02 에 llmsensor/telemetry/derive.py 에서 옮겼다
(L0 Telemetry 는 판단하지 않는다 -- cogito5170/Telemetry docs/TELEMETRY.md 7 절). 정의는 바꾸지 않았다(catalog 의 정의 그대로,
시험이 eval/results/sensor_layer_records.jsonl.gz 실데이터 9538 호출에서 옮기기 전 출력과 같음을 붙든다).

입력은 derive.calls() 의 호출 단위 행(산술 파생까지)이다. 출력은 호출마다:

    token_burst        output_tokens > 그때까지 그 실행의 중앙값 × BURST_FACTOR (앞 호출 BURST_MIN_HISTORY 개 뒤부터)
    token_stagnation   context_growth 가 STAGNATION_CALLS 호출 연속 |Δ| < STAGNATION_FRACTION × context_tokens
    token_oscillation  창 OSCILLATION_WINDOW 호출 안 Δoutput_tokens 의 부호가 바뀐 횟수

**문턱은 정한 것이지 잰 것이 아니다**(catalog: "문턱 4 는 정한 것이지 잰 것이 아니다"). 판단할 수 없으면 None.
"""
from __future__ import annotations

BURST_FACTOR = 4
BURST_MIN_HISTORY = 3
STAGNATION_FRACTION = 0.01
STAGNATION_CALLS = 3
OSCILLATION_WINDOW = 6


def token_events(rows) -> "list[dict]":
    out, hist = [], []
    for r in rows:
        o = r["output_tokens"]
        burst = None
        if o is not None:
            med = sorted(hist)[len(hist) // 2] if hist else None
            burst = (o > BURST_FACTOR * med) if med and len(hist) >= BURST_MIN_HISTORY else None
            hist.append(o)
        out.append({"run_id": r["run_id"], "step_index": r["step_index"], "token_burst": burst})
    for i, d in enumerate(out):
        g = [rows[j]["context_growth"] for j in range(max(1, i - STAGNATION_CALLS + 1), i + 1)]
        c = rows[i]["context_tokens"]
        d["token_stagnation"] = (all(x is not None and abs(x) < STAGNATION_FRACTION * c for x in g)
                                 if i >= STAGNATION_CALLS and c else None)
        w = [rows[j]["output_tokens"] for j in range(max(0, i - OSCILLATION_WINDOW + 1), i + 1)]
        dif = [b - a for a, b in zip(w, w[1:]) if a is not None and b is not None]
        d["token_oscillation"] = sum(1 for a, b in zip(dif, dif[1:]) if a * b < 0) if len(dif) >= 2 else None
    return out
