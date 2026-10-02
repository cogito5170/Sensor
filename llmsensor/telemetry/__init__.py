"""센서 층 -- LLM 실행에서 바깥에서 볼 수 있는 값을 원천에서 꺼내 하나의 텔레메트리 꼴로.

    catalog.py   후보 센서 목록 · 형(직접/파생) · 원천별 가용성 근거
    schema.py    텔레메트리 레코드 꼴(model_call · tool_call · run) -- JSON Schema
    collect.py   원천 -> 레코드: Claude Code JSONL · claude -p stream-json · SWE-agent .traj -- **L0 수집기 위의 이음매**(CMD-T9)
    derive.py    레코드 -> 파생 텔레메트리(레코드만 본다 · 산술만. 문턱 있는 판독은 sensing/token/events.py)
    l0.py        L0 Telemetry(cogito5170/Telemetry) **필수 의존** -- 찾기 · 원장 읽기 · 불변식 확인

**Telemetry ≠ State.** 여기에는 해석(압박 · 혼란 · 수렴 안 함)이 없다. 관측값과 그 산술만 있다.
"""
