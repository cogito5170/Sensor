"""다섯 센서. 우선순위(진실에 가까운 순):

    ExternalOutcome > Execution > Constraint > Consistency > Behavior(토큰 통계)

토큰은 "LLM 이 어떻게 행동하나" 를, 외부 결과는 "실제로 성공했나" 를 잰다.
"""
from .execution import ExecutionSensor
from .constraint import ConstraintSensor, validate
from .consistency import ConsistencySensor, agreement
from .behavior import BehaviorSensor
from .outcome import ExternalOutcomeSensor

__all__ = ["ExecutionSensor", "ConstraintSensor", "validate", "ConsistencySensor", "agreement", "BehaviorSensor",
           "ExternalOutcomeSensor"]
