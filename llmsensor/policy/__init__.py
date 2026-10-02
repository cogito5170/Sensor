"""참조 정책 -- **MS 정책이 아니다.** 이 저장소에 MS 정책 런타임이 없어서(docs/MS_SENSING_REVIEW.md), 결정 문맥이 실제로
결정을 바꾸는지 재려고 지은 최소 결정론 정책이다. 입력은 DecisionContext 뿐이다(상태 저장소 · 텔레메트리를 보지 않는다).

    context.py   manage_context   -> KEEP_CONTEXT · REDUCE_CONTEXT · COMPACT_CONTEXT
    provider.py  select_provider  -> STAY_PROVIDER · SWITCH_PROVIDER · WAIT
    execution.py continue_or_stop -> CONTINUE · RETRY · STOP · ESCALATE

규칙의 문턱은 없다 -- 상태의 범주 값만 본다. 쓸 수 없는 상태(UNKNOWN · STALE)를 어떻게 다룰지는 **정책이 명시적으로** 정한다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    policy: str
    context_id: str
    action: str
    reason: str
    used: tuple          # 결정에 쓴 상태 이름


def _pick(ctx, *prefs):
    """선호 순서대로, 문맥이 가능하다고 한 첫 행동. 하나도 없으면 None."""
    return next((a for a in prefs if a in ctx.available_actions), None)
