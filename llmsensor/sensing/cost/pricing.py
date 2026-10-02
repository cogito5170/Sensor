"""공급자 단가표(PROVIDER_DECLARED) -- 출처와 확인을 함께 둔다.

출처: claude-api 스킬(2.1.287)의 모형 표(cached 2026-09-25)와 shared/prompt-caching.md
      ("Cache reads cost ~0.1× base input price ... 0.05× on Claude Opus 5.5 ($0.20/MTok) ...
        Cache writes cost 1.25× for 5-minute TTL, 2× for 1-hour TTL").
확인(VALIDATED_EXPERIMENT, 2026-10-02):
  claude-haiku-4-5  claude -p 12 실행 -- 호출별 토큰 × 단가의 합이 런타임 total_cost_usd 와 상대오차 ≤ 2e-16(12/12)
  claude-opus-5-5   이 세션의 cost-state 스냅숏 -- 앞 27 호출의 합 $3.337149 = 런타임 costUSD $3.3371494
생각 토큰은 output_tokens 에 들어 있고 출력 단가로 청구되는 것으로 계산했다 -- 위 확인이 그 가정을 받친다.
표에 없는 모형은 비용을 계산하지 않는다(UNKNOWN) -- 짐작하지 않는다.
"""
from __future__ import annotations

SOURCE = "claude-api skill 2.1.287 models table (cached 2026-09-25) + shared/prompt-caching.md multipliers"
# 단가표 판본 -- 비용 근거가 어느 표에서 나왔는지 상태까지 따라간다(BD-39 조건 1). 값 · 모형을 바꾸면 올린다
VERSION = "anthropic-2026-09-25/1"

# $/MTok
PRICES = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write_5m": 1.25,
                         "cache_write_1h": 2.00, "validated": "claude -p 12 runs, exact (2026-10-02)"},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write_5m": 5.00,
                        "cache_write_1h": 8.00, "validated": "cost-state snapshot of this session, exact (2026-10-02)"},
}
ALIASES = {"claude-haiku-4-5-20251001": "claude-haiku-4-5"}   # models.md: Haiku 4.5 의 날짜 붙은 id


def lookup(model: "str | None") -> "tuple[str, dict] | None":
    if not model:
        return None
    m = ALIASES.get(model, model)
    return (m, PRICES[m]) if m in PRICES else None


def call_cost(model, inp, out, cread, w5m, w1h) -> "dict | None":
    """한 호출의 비용 성분($). 칸 하나라도 없으면 None."""
    hit = lookup(model)
    if hit is None or any(v is None for v in (inp, out, cread, w5m, w1h)):
        return None
    _, p = hit
    parts = {"input": inp * p["input"], "output": out * p["output"], "cache_read": cread * p["cache_read"],
             "cache_write": w5m * p["cache_write_5m"] + w1h * p["cache_write_1h"]}
    parts = {k: v / 1e6 for k, v in parts.items()}
    parts["total"] = sum(parts.values())
    return parts
