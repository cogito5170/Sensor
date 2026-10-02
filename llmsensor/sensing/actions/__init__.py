"""Actions 센싱(S5) -- 런타임이 **스스로** 한 행동과 그 결과. 우리 정책의 행동이 아니다(그것은 Action 저장소의 실행기, BD-25).

    압축(runtime.compaction)       횟수 · 마지막 압축의 trigger · 전후 토큰 · 걸린 시간 -- context_pressure 의 실패 영역이 실제로
                                   일어났다는 직접 증거(재고: 이 세션 02:58, 783,484 -> 7,209)
    백그라운드 이동(tool.end)       시간 한도를 넘은 명령을 죽이지 않고 옮겼다(S2 의 처분과 같은 사건 -- 여기서는 횟수만)
    입력 빼기(input.removed)        줄에 선 입력을 런타임이 뺐다(absorbed_mid_turn ...)
    권한 거부(run.end)              실행 끝에 런타임이 보고한 수

지표만 둔다(상태 없음). **사건이 없으면 None** -- '0 회' 가 아니라 '본 적 없음' 이다. 모형이 쓴 요약(post_turn_summary 등)은
관측이 아니라 판단이므로 받지 않는다.
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType
from .. import SensingPack
from .._base import _m
from ..l0 import ACTIONS_CANON

T = EntityType.TASK


def m_runtime_actions(L, ctx, Mx):
    o = L.run.get("l0.runtime_actions")
    if o is None or o.value is None:
        return _m(ctx, "runtime_actions", None, (), reason="런타임 행동 사건을 받지 않았다 -- 일어나지 않았다는 뜻이 아니다")
    v = {k: x for k, x in o.value.items() if k not in ("seq", "at")}
    return _m(ctx, "runtime_actions", v, [o.id], Basis.RUNTIME_DECLARED)


NEW_METRICS = (
    MetricDefinition("runtime_actions", T, ("l0.runtime_actions",), Basis.RUNTIME_DECLARED,
                     "런타임 자신의 행동 수(압축 · 백그라운드 이동 · 입력 빼기 · 권한 거부) · 마지막 압축 전후 토큰", m_runtime_actions),
)

PACK = SensingPack("actions", "런타임이 스스로 무엇을 했나 -- 압축 · 백그라운드 이동 · 입력 빼기 · 권한 거부(지표만)",
                   ACTIONS_CANON, NEW_METRICS, ())
