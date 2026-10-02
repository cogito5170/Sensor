"""Gemini(Google) -- 출처: googleapis/googleapis google/rpc/code.proto(상태 이름 · HTTP 대응),
google/rpc/error_details.proto(RetryInfo.retry_delay), aip-dev AIP-193(오류 꼴의 status 문자열)."""
from . import CanonicalError, ErrorKind as K

SOURCE = "google/rpc/code.proto + error_details.proto RetryInfo + AIP-193"
BY_RPC = {"INVALID_ARGUMENT": K.INVALID_REQUEST, "FAILED_PRECONDITION": K.INVALID_REQUEST, "OUT_OF_RANGE": K.INVALID_REQUEST,
          "UNAUTHENTICATED": K.AUTH, "PERMISSION_DENIED": K.PERMISSION, "NOT_FOUND": K.NOT_FOUND,
          "RESOURCE_EXHAUSTED": K.RATE_LIMITED, "UNAVAILABLE": K.UNAVAILABLE, "DEADLINE_EXCEEDED": K.DEADLINE_EXCEEDED,
          "INTERNAL": K.SERVER_ERROR, "UNKNOWN": K.SERVER_ERROR, "DATA_LOSS": K.SERVER_ERROR, "CANCELLED": K.CANCELLED}
BY_STATUS = {400: K.INVALID_REQUEST, 401: K.AUTH, 403: K.PERMISSION, 404: K.NOT_FOUND, 429: K.RATE_LIMITED,
             499: K.CANCELLED, 500: K.SERVER_ERROR, 503: K.UNAVAILABLE, 504: K.DEADLINE_EXCEEDED}


def _duration_ms(s):
    """google.protobuf.Duration 의 JSON 꼴 '30s' · '1.5s'."""
    if isinstance(s, str) and s.endswith("s"):
        try:
            return float(s[:-1]) * 1000
        except ValueError:
            return None
    return None


def error(status, body, headers) -> CanonicalError:
    err = body.get("error") or {} if isinstance(body, dict) else {}
    rpc = err.get("status")
    kind = BY_RPC.get(rpc) or BY_STATUS.get(status or err.get("code"), K.UNKNOWN)
    ra = None
    for d in err.get("details") or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("google.rpc.RetryInfo"):
            ra = _duration_ms(d.get("retryDelay"))
    return CanonicalError("gemini", kind, status or err.get("code"), rpc, ra, SOURCE)
