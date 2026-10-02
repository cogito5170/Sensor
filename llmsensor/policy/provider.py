"""참조 Provider Policy -- 공급자 신뢰 · 요금 한도 범주로 공급자를 어떻게 할지."""
from . import Decision, _pick

NAME = "reference-provider-v1"


def decide(ctx) -> Decision:
    assert ctx.purpose == "select_provider"
    rl, rel = ctx.value("rate_limit_state"), ctx.value("runtime_reliability")
    used = ("rate_limit_state", "runtime_reliability")
    if rl in ("LIMITED", "EXHAUSTED") or rel == "FAILURE_OBSERVED":
        a = _pick(ctx, "SWITCH_PROVIDER", "WAIT")
        return Decision(NAME, ctx.context_id, a, f"요금 한도 {rl} · 신뢰 {rel}", used)
    if rl is None and rel is None:
        return Decision(NAME, ctx.context_id, _pick(ctx, "STAY_PROVIDER"),
                        "둘 다 모른다 -- 모르는 것으로 공급자를 바꾸지 않는다", used)
    return Decision(NAME, ctx.context_id, _pick(ctx, "STAY_PROVIDER"), f"요금 한도 {rl} · 신뢰 {rel}", used)
