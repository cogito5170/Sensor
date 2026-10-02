"""Dependency 센싱(S3, BD-54) -- 결함이 **어디서** 났나(격리). 소유 층: ASSESS.

실체 `dependency:<실행>:<이름>` 마다 따로 선다(도구마다 서는 tool_execution_health 처럼). 이름은 L0 묶기가 정한다
(llmsensor/sensing/l0.py: provider[.<이름>] · probe.<겨냥 해시>).

    FAULT_DECLARED      그 대상에 대한 마지막 호출이 **선언된** 원인으로 실패했다(정준 error_code · HTTP ≥ 400)
    NO_FAULT_DECLARED   마지막 호출이 성공했다 -- **HEALTHY 가 아니다.** 앞선 결함 수는 이유에 남는다
    UNKNOWN             그 대상에 대한 호출을 본 적이 없다(실체가 서지 않는다)

값을 정하는 근거는 마지막 호출 하나다 -- 그래서 근거 시각도 그 호출의 시각이다(BD-57 과 맞다).
원인을 해석하지 않는다: Bash stderr 의 글에서 '네트워크 같다' 를 읽지 않는다. 구조화되지 않은 실패는 tool_execution_health 에만 남는다.
비핵심 의존성의 결함을 위에서 degraded 로 읽을지는 정책 · 설정의 일이다(Health Endpoint Monitoring). 센서는 핵심 여부를 모른다.
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType
from ...state.rules import Result, Rule, _unk
from ...state.model import Status
from .. import SensingPack
from .._base import _m
from ..l0 import DEP_PREFIX, DEPENDENCY_CANON

D = EntityType.DEPENDENCY


def subjects(L) -> "list[str]":
    return sorted(k[len(DEP_PREFIX):] for k in L.run if k.startswith(DEP_PREFIX))


def _outcome(name):
    def fn(L, ctx, Mx):
        o = L.run.get(DEP_PREFIX + name) if name else None
        if o is None or o.value is None:
            return _m(ctx, "dependency_outcome", None, (), reason="이 의존 대상에 대한 호출을 본 적이 없다")
        v = {k: o.value[k] for k in ("ok", "cause", "calls", "faults")}
        return _m(ctx, "dependency_outcome", v, [o.id], Basis.RUNTIME_DECLARED)
    return fn


def subject_metrics(name):
    return [MetricDefinition("dependency_outcome", D, (DEP_PREFIX + "*",), Basis.RUNTIME_DECLARED,
                             "의존 대상에 대한 마지막 호출의 결과(ok · 선언된 원인)와 호출 · 결함 수", _outcome(name))]


def r_dependency(M, prev, cfg):
    o = M["dependency_outcome"]
    if o.value is None:
        return _unk(o.reason, ["dependency_outcome"])
    v = o.value
    if not v["ok"]:
        return Result("FAULT_DECLARED", Status.INFERRED, f"마지막 호출이 선언된 원인 {v['cause']} 로 실패 "
                      f"(결함 {v['faults']}/{v['calls']})", ("dependency_outcome",))
    return Result("NO_FAULT_DECLARED", Status.INFERRED,
                  f"마지막 호출 성공 -- 건강이 증명된 것은 아니다(앞선 결함 {v['faults']}/{v['calls']})", ("dependency_outcome",),
                  basis=Basis.OBSERVED)


NEW_METRICS = (subject_metrics(None)[0],)       # 정의(레지스트리 · 의존 그래프용). 값은 실체마다 따로 계산한다
DEPENDENCY_FAULT = Rule("dependency-fault-v1", 1, "dependency_fault", D, Basis.RUNTIME_DECLARED, ("dependency_outcome",),
                        ("FAULT_DECLARED", "NO_FAULT_DECLARED"),
                        "의존 대상 하나에 대한 마지막 호출이 선언된 원인으로 실패했나. NO_FAULT_DECLARED 는 HEALTHY 가 아니다",
                        "다른 대상으로 돌릴까 · 그 대상을 쓰는 행동을 미룰까", r_dependency, owner_layer="ASSESS",
                        subjects=subjects, subject_metrics=subject_metrics)

PACK = SensingPack("dependency", "결함이 어디서 났나 -- 의존 대상(공급자 · 외부 서비스)마다, 선언된 원인만",
                   DEPENDENCY_CANON, NEW_METRICS, (DEPENDENCY_FAULT,))
