"""llmsensor -- LLM 을 하나의 자율 시스템으로 보고 다는 센서들.

    관측(trace) -> 센서 다섯(Reading) -> 성능모형 잔차(residual) -> 증거 융합(Q) -> 판정기(Verdict)

토큰은 센서가 아니라 관측량이고, 성공은 센서 하나가 아니라 여러 증거에서 추정하는 잠재 상태다.
"""
# 하위 패키지 llmsensor.telemetry(센서 층)와 함수 telemetry(trace)가 같은 이름이다. 하위 패키지를 먼저
# 올려 두어야 아래 함수가 그 자리를 차지한다 -- 아니면 누가 나중에 llmsensor.telemetry.* 를 처음
# import 하는 순간 패키지 속성이 모듈로 덮여 `from llmsensor import telemetry` 가 import 순서에 따라 달라진다.
from . import telemetry as _telemetry_layer  # noqa: F401
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
