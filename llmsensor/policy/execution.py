"""참조 실행 정책 -- 실행을 이어갈까 · 다시 할까 · 멈출까."""
from . import Decision, _pick

NAME = "reference-execution-v1"


def decide(ctx) -> Decision:
    assert ctx.purpose == "continue_or_stop"
    comp, health = ctx.value("completion_state"), ctx.value("execution_health")
    intr, budget = ctx.value("execution_interruption"), ctx.value("resource_state")
    q = ctx.value("quality_state")
    if comp in ("ENDED_NORMALLY", "ENDED_BY_LIMIT", "ENDED_WITH_ERROR"):
        if q == "FAILED" or comp != "ENDED_NORMALLY":
            return Decision(NAME, ctx.context_id, _pick(ctx, "ESCALATE"), f"끝남({comp}) · 외부 평가 {q}",
                            ("completion_state", "quality_state"))
        return Decision(NAME, ctx.context_id, None, f"끝남({comp}) -- 할 일 없음", ("completion_state",))
    if budget == "BUDGET_EXHAUSTED":
        return Decision(NAME, ctx.context_id, _pick(ctx, "STOP"), "예산 소진", ("resource_state",))
    if health == "UNRESOLVED_FAILURES":
        why = "풀리지 않은 도구 실패" + (" (시간 초과)" if intr == "TIMEOUT_OBSERVED" else "")
        return Decision(NAME, ctx.context_id, _pick(ctx, "RETRY", "ESCALATE"), why,
                        ("execution_health", "execution_interruption"))
    if comp is None:
        return Decision(NAME, ctx.context_id, _pick(ctx, "ESCALATE"), "실행 상태를 모른다", ("completion_state",))
    return Decision(NAME, ctx.context_id, _pick(ctx, "CONTINUE"), f"{comp} · 도구 {health}",
                    ("completion_state", "execution_health"))
