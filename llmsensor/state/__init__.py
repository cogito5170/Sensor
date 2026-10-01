"""의미 상태 층 -- 텔레메트리(무엇을 보았나)에서 상태(지금 무엇이 참이라고 믿나)를 결정론적으로 만든다.

    normalize.py   텔레메트리 레코드 · 공급자 usage -> 정준 관측(Observation, 층 1)
    metrics.py     관측 -> 파생 지표(Metric, 층 2)
    rules.py       지표 -> 의미 상태(State, 층 3) -- 규칙마다 id · 버전 · 근거 종류
    registry.py    정의 목록과 의존 그래프(들여다볼 수 있다)
    engine.py      상태 엔진: 받아들이기 · 이력 · 전이 · 흔들림 억제 · 신선도 · 질의 · 설명 · 결정 문맥
    config.py      운영자 설정(가정이 든 값은 전부 여기, 버전과 함께)

Telemetry = 무엇을 보았나 · State = 지금 무엇이 참이라고 믿나 · Model(registry) = 그 상태가 무엇을 뜻하나.
정책(무엇을 할까)은 여기 없다.
"""
from .model import (Level, Status, Basis, Freshness, Lifecycle, EntityType, Observation, Metric, Evidence, State,
                    Transition, Relationship, LifecycleEvent, Proposal, StateView)
from .config import StateConfig, DEFAULT_CONFIG
from .registry import REGISTRY
from .engine import StateEngine
from .normalize import from_telemetry, canonical_usage

__all__ = ["Level", "Status", "Basis", "Freshness", "Lifecycle", "EntityType", "Observation", "Metric", "Evidence",
           "State", "Transition", "Relationship", "LifecycleEvent", "Proposal", "StateView", "StateConfig",
           "DEFAULT_CONFIG", "REGISTRY", "StateEngine", "from_telemetry", "canonical_usage"]
