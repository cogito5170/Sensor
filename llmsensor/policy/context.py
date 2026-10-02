"""참조 Context Policy -- 맥락 압력 범주로 맥락을 어떻게 할지. LLM 에게 무엇을 보일지(LLM Context)도 이 층의 일이다."""
from . import Decision, _pick

NAME = "reference-context-v1"


def decide(ctx) -> Decision:
    assert ctx.purpose == "manage_context"
    p = ctx.value("context_pressure")
    if p is None:
        return Decision(NAME, ctx.context_id, _pick(ctx, "KEEP_CONTEXT"),
                        "맥락 압력을 모른다(또는 낡았다) -- 모르는 것으로 맥락을 줄이지 않는다", ("context_pressure",))
    if p == "AT_CONTEXT_LIMIT":
        return Decision(NAME, ctx.context_id, _pick(ctx, "REDUCE_CONTEXT"), "창에 닿았다", ("context_pressure",))
    if p == "ABOVE_COMPACTION_THRESHOLD":
        return Decision(NAME, ctx.context_id, _pick(ctx, "COMPACT_CONTEXT", "REDUCE_CONTEXT"),
                        "런타임 압축 문턱을 넘었다", ("context_pressure",))
    return Decision(NAME, ctx.context_id, _pick(ctx, "KEEP_CONTEXT"), f"맥락 압력 {p}", ("context_pressure",))
