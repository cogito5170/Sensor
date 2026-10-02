"""OpenAI -- **1 차 문서를 읽지 못했다**(platform.openai.com 막힘). 다른 두 공급자의 1 차 자료가 같은 뜻으로 쓰는
HTTP 429 만 RATE_LIMITED 로 옮기고, 나머지는 UNKNOWN(원래 값은 남긴다). 헤더(x-ratelimit-*)는 해석하지 않는다."""
from . import CanonicalError, ErrorKind as K

SOURCE = "HTTP 429 only (OpenAI docs not read -- U); same meaning in google/rpc/code.proto and Anthropic error-codes.md"


def error(status, body, headers) -> CanonicalError:
    code = ((body.get("error") or {}).get("type")) if isinstance(body, dict) else None
    return CanonicalError("openai", K.RATE_LIMITED if status == 429 else K.UNKNOWN, status, code, None, SOURCE)
