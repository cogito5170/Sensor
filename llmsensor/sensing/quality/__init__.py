"""Quality -- **인터페이스만.** 품질 점수를 만들지 않는다. 외부 평가(숨은 시험 · 사람 판정)의 라벨이 들어오면 그대로 옮긴다.

    batch = external_label_batch(run_id, passed=True, evaluator="swe-bench-lite hidden tests", label_id="...")
    engine.ingest(batch)

라벨이 없으면 quality_state = UNKNOWN. 지금 이 저장소에 있는 외부 라벨은 SWE-bench Lite 판정(287 실행)뿐이다.
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType, Observation
from ...state.normalize import Batch, entity_id
from ...state.rules import Rule, _inf, _unk
from .. import SensingPack
from .._base import _m

T = EntityType.TASK
NEW_CANON = {"task.external_outcome": ("external", "outcome", T, Basis.EXTERNAL_LABEL)}


def external_label_batch(run_id: str, passed: "bool | None", evaluator: str, label_id: str, at=None) -> Batch:
    rid = f"{run_id}/external/{label_id}"
    obs = [Observation(id=f"{rid}#task.external_outcome", entity_id=entity_id(T, run_id), field="task.external_outcome",
                       value=None if passed is None else {"passed": bool(passed), "evaluator": evaluator},
                       reported_null=passed is None, observed_at=at, time_base=None, source=f"external:{evaluator}",
                       basis=Basis.EXTERNAL_LABEL)]
    return Batch(rid, run_id, "external", at, None, f"external:{evaluator}", obs)


def m_outcome(L, ctx, Mx):
    o = L.external.get("task.external_outcome")
    if o is None or o.value is None:
        return _m(ctx, "external_outcome", None, (), Basis.EXTERNAL_LABEL, reason="외부 평가 라벨이 없다")
    return _m(ctx, "external_outcome", o.value, [o.id], Basis.EXTERNAL_LABEL)


def r_quality(Mx, prev, cfg):
    o = Mx["external_outcome"]
    if o.value is None:
        return _unk("외부 평가가 없다 -- 품질 점수를 만들지 않는다", ["external_outcome"])
    return _inf("PASSED" if o.value["passed"] else "FAILED", f"외부 평가 {o.value['evaluator']!r}", ["external_outcome"],
                final=True)


NEW_METRICS = (MetricDefinition("external_outcome", T, ("task.external_outcome",), Basis.EXTERNAL_LABEL,
                                "외부 평가 라벨(그대로)", m_outcome),)
QUALITY = Rule("quality-state-v1", 1, "quality_state", T, Basis.EXTERNAL_LABEL, ("external_outcome",),
               ("PASSED", "FAILED"), "외부 평가가 과업을 통과로 판정했나. 라벨이 없으면 UNKNOWN -- 점수를 지어내지 않는다",
               "결과를 받아들일까 · 사람에게 올릴까", r_quality)

PACK = SensingPack("quality", "외부 평가가 과업을 통과로 판정했나(라벨이 있을 때만)", NEW_CANON, NEW_METRICS, (QUALITY,))
