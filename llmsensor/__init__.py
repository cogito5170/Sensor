"""llmsensor -- LLM 을 하나의 자율 시스템으로 보고 다는 센서들.

    관측(trace) -> 센서 다섯(Reading) -> 성능모형 잔차(residual) -> 증거 융합(Q) -> 판정기(Verdict)

토큰은 센서가 아니라 관측량이고, 성공은 센서 하나가 아니라 여러 증거에서 추정하는 잠재 상태다.
"""
from .reading import Reading, OK, SUSPECT, FAULT, UNKNOWN
from .trace import Task, ToolCall, Recorder, from_claude_code, telemetry
from .sensors import (ExecutionSensor, ConstraintSensor, ConsistencySensor, BehaviorSensor,
                      ExternalOutcomeSensor, agreement)
from .model import PerformanceModel
from .residual import residuals
from .fusion import OutcomeModel
from .verifier import Verifier, ACCEPT, REJECT, RETRY, DEGRADE
from .pipeline import sense

__all__ = ["Reading", "OK", "SUSPECT", "FAULT", "UNKNOWN", "Task", "ToolCall", "Recorder", "from_claude_code",
           "telemetry", "ExecutionSensor", "ConstraintSensor", "ConsistencySensor", "BehaviorSensor",
           "ExternalOutcomeSensor", "agreement", "PerformanceModel", "residuals", "OutcomeModel", "Verifier",
           "ACCEPT", "REJECT", "RETRY", "DEGRADE", "sense"]
