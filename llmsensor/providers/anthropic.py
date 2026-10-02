"""Anthropic -- 출처: claude-api 스킬 shared/error-codes.md (상태 표 · 'retry-after: Seconds to wait before retrying')."""
from . import CanonicalError, ErrorKind as K

SOURCE = "claude-api skill shared/error-codes.md"
BY_TYPE = {"invalid_request_error": K.INVALID_REQUEST, "authentication_error": K.AUTH, "billing_error": K.BILLING,
           "permission_error": K.PERMISSION, "not_found_error": K.NOT_FOUND, "request_too_large": K.TOO_LARGE,
           "rate_limit_error": K.RATE_LIMITED, "api_error": K.SERVER_ERROR, "overloaded_error": K.OVERLOADED}
BY_STATUS = {400: K.INVALID_REQUEST, 401: K.AUTH, 402: K.BILLING, 403: K.PERMISSION, 404: K.NOT_FOUND,
             413: K.TOO_LARGE, 429: K.RATE_LIMITED, 500: K.SERVER_ERROR, 529: K.OVERLOADED}


def error(status, body, headers) -> CanonicalError:
    typ = ((body.get("error") or {}).get("type")) if isinstance(body, dict) else None
    kind = BY_TYPE.get(typ) or BY_STATUS.get(status, K.UNKNOWN)
    ra = headers.get("retry-after")
    try:
        ra_ms = float(ra) * 1000 if ra is not None else None
    except ValueError:
        ra_ms = None                       # HTTP 날짜 꼴 등 -- 문서에 '초' 로만 적혀 있어 추측하지 않는다
    return CanonicalError("anthropic", kind, status, typ, ra_ms, SOURCE)
