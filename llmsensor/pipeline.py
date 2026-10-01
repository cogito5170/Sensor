"""한 과업을 센서 다섯 -> 잔차 -> Q -> 판정까지 한 번에."""
from __future__ import annotations

from .fusion import OutcomeModel
from .residual import residuals
from .sensors import BehaviorSensor, ConsistencySensor, ConstraintSensor, ExecutionSensor
from .trace import Task, telemetry
from .verifier import Verifier


def sense(task: Task, model=None, constraint: "ConstraintSensor | None" = None, external=None, others=None,
          outcome_model: "OutcomeModel | None" = None, verifier: "Verifier | None" = None, attempt: int = 0,
          behavior: "BehaviorSensor | None" = None, execution: "ExecutionSensor | None" = None) -> dict:
    """external: ExternalOutcomeSensor(없으면 그 센서는 UNKNOWN 판독을 낸다).
    others: 같은 과업에 대한 다른 모형의 답들(교차 일치)."""
    from .reading import Reading, UNKNOWN
    readings = [
        (execution or ExecutionSensor()).read(task),
        (constraint or ConstraintSensor()).read(task),
        ConsistencySensor().read(task, others),
        (behavior or BehaviorSensor(model)).read(task),
        external.read(task) if external is not None else Reading("outcome", UNKNOWN, "외부 검증을 안 걸었다"),
    ]
    tel = telemetry(task)
    res = residuals(tel, model, task.cls, readings)
    exp = res["expected"]
    om = outcome_model or OutcomeModel()
    q = om.q(readings, exp.get("p_success"))
    v = (verifier or Verifier()).decide(readings, q["Q"], attempt, tel, exp)
    return {"cls": task.cls, "telemetry": tel, "readings": [r.to_dict() for r in readings], "residual": res,
            "fusion": q, "verdict": v.to_dict()}
