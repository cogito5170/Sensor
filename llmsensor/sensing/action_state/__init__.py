"""S6 action_state (CMD-S24 · BD-108) -- 실행기가 실행한 행동 하나가 어떻게 됐나. 소유 층 표시는 아직 없다(baseline 결정 대기).

실체 `action:<실행>:<command_id>` 마다 따로 선다(BD-32 · BD-99 -- action_ref = 실행기의 command_id). 입력은 L0 의
`action.dispatch` · `action.result` 뿐이다(llmsensor/sensing/l0.py 의 l0.act:<ref>). 값은 그 ref 의 **마지막 시도**로 정한다:

    STARTED     dispatch 만 있다(결과를 기다린다)
    COMPLETED   result 가 왔고 is_error = false
    FAILED      result 가 왔고 is_error = true
    UNKNOWN     result 는 왔는데 is_error 를 못 봤다 · dispatch 없이 result 만 왔다(순서를 어긴 기록)

PROPOSED · ACCEPTED · CANCELLED 는 내지 않는다 -- L0 에 그 사건이 없다(결정 원장의 일, docs/SENSOR_HEALTH_DESIGN.md S6).
COMPLETED 는 **행동이 오류 없이 끝났다**는 실행기의 선언이다. 행동이 효과를 냈는지(좋아졌나)는 판정하지 않는다.
같은 command_id 를 차례로 다시 쓰면(되풀이) 값은 새 시도를 따른다 -- 그래서 끝난 값도 final 이 아니다.
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType, Status
from ...state.rules import Result, Rule, _unk
from .. import SensingPack
from .._base import _m
from ..l0 import ACT_PREFIX, ACTION_STATE_CANON

AC = EntityType.ACTION


def subjects(L) -> "list[str]":
    return sorted(k[len(ACT_PREFIX):] for k in L.run if k.startswith(ACT_PREFIX))


def _outcome(ref):
    def fn(L, ctx, Mx):
        o = L.run.get(ACT_PREFIX + ref) if ref else None
        if o is None or o.value is None:
            return _m(ctx, "action_outcome", None, (), reason="이 행동의 사건을 본 적이 없다")
        v = o.value
        out = {"dispatched": v["dispatch"] is not None, "result": v["result"] is not None, "is_error": v["is_error"],
               "action_type": v["action_type"], "attempts": v["attempts"]}
        refs = [x for x in (v["result"], v["dispatch"]) if x is not None]     # 값을 정한 사건: 결과가 있으면 결과, 없으면 dispatch
        return _m(ctx, "action_outcome", out, refs[:1], Basis.RUNTIME_DECLARED)
    return fn


def subject_metrics(ref):
    return [MetricDefinition("action_outcome", AC, (ACT_PREFIX + "*",), Basis.RUNTIME_DECLARED,
                             "행동 하나의 마지막 시도: dispatch 를 봤나 · result 를 봤나 · is_error · 시도 수", _outcome(ref))]


def r_action_state(M, prev, cfg):
    o = M["action_outcome"]
    if o.value is None:
        return _unk(o.reason, ["action_outcome"])
    v = o.value
    tail = f" ({v['action_type']}, 시도 {v['attempts']})" if v["action_type"] else f" (시도 {v['attempts']})"
    if not v["dispatched"]:
        return _unk("dispatch 없이 result 만 왔다 -- 순서를 어긴 기록" + tail, ["action_outcome"])
    if not v["result"]:
        return Result("STARTED", Status.INFERRED, "실행기가 행동을 보냈고 결과를 아직 받지 않았다" + tail, ("action_outcome",),
                      basis=Basis.OBSERVED)
    if v["is_error"] is None:
        return _unk("결과는 왔는데 is_error 를 못 봤다 -- 끝났는지만 안다" + tail, ["action_outcome"])
    if v["is_error"]:
        return Result("FAILED", Status.INFERRED, "실행기가 행동의 오류를 선언했다" + tail, ("action_outcome",))
    return Result("COMPLETED", Status.INFERRED, "실행기가 행동이 오류 없이 끝났다고 선언했다 -- 효과를 판정한 것은 아니다" + tail,
                  ("action_outcome",))


NEW_METRICS = (subject_metrics(None)[0],)       # 정의(레지스트리 · 의존 그래프용). 값은 실체마다 따로 계산한다
ACTION_STATE = Rule("action-state-v1", 1, "action_state", AC, Basis.RUNTIME_DECLARED, ("action_outcome",),
                    ("STARTED", "COMPLETED", "FAILED"),
                    "실행기가 실행한 행동 하나(command_id)가 어떻게 됐나: 보냄 · 오류 없이 끝남 · 오류로 끝남. "
                    "효과(좋아졌나)는 판정하지 않는다",
                    "다시 시도할까 · 다른 행동으로 바꿀까 · 사람에게 올릴까", r_action_state,
                    subjects=subjects, subject_metrics=subject_metrics)

PACK = SensingPack("action_state", "실행기가 실행한 행동이 어떻게 됐나 -- 행동(command_id)마다, 실행기가 선언한 결과만",
                   ACTION_STATE_CANON, NEW_METRICS, (ACTION_STATE,))
