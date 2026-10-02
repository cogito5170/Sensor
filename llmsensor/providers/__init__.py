"""공급자 어댑터 -- 공급자마다 다른 usage · 오류 꼴을 **정준 꼴**로. 상위(상태 · 결정 문맥 · 정책)는 공급자 차이를 보지 않는다.

    usage(provider, usage_dict)               -> (정준 토큰 dict, 주석)       state.normalize.canonical_usage 와 같다
    error(provider, http_status, body, headers) -> CanonicalError

정준 오류 종류(ErrorKind)는 Google 의 google.rpc.Code(code.proto)의 HTTP 대응을 뼈대로 삼았다 -- 세 공급자 중 공개된
1 차 정의가 가장 촘촘하다. 표마다 출처가 있고, 출처 없는 대응은 넣지 않는다(UNKNOWN 으로 남긴다).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..state.normalize import canonical_usage


class ErrorKind(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"            # 한도 -- 다시 하면 될 수 있다
    OVERLOADED = "OVERLOADED"                # 공급자 과부하
    UNAVAILABLE = "UNAVAILABLE"              # 일시 불능 -- 그 호출만 다시
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"  # 시간 초과 -- **성공했을 수도 있다**(google.rpc 주석)
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    NOT_FOUND = "NOT_FOUND"
    BILLING = "BILLING"
    TOO_LARGE = "TOO_LARGE"
    SERVER_ERROR = "SERVER_ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"                      # 출처 있는 대응이 없다 -- 원래 값은 provider_code 에 남는다


@dataclass(frozen=True)
class CanonicalError:
    provider: str
    kind: ErrorKind
    http_status: "int | None"
    provider_code: "str | None"       # 공급자 고유 이름(rate_limit_error · RESOURCE_EXHAUSTED ...) -- 근거로만
    retry_after_ms: "float | None"    # 공급자가 선언한 대기(PROVIDER_DECLARED). 없으면 None
    source: str                       # 이 대응의 출처


def error(provider: str, http_status=None, body=None, headers=None) -> CanonicalError:
    from . import anthropic, gemini, openai
    mod = {"anthropic": anthropic, "gemini": gemini, "openai": openai}.get(provider)
    if mod is None:
        raise ValueError(f"모르는 공급자 {provider!r}")
    return mod.error(http_status, body or {}, {k.lower(): v for k, v in (headers or {}).items()})


def usage(provider: str, u: dict):
    return canonical_usage(provider, u)
