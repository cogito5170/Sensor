"""Provider 센싱 -- 공급자 · 요금 한도 · 오류. 공급자를 **고르는 것은 정책의 일**이다.

- runtime_reliability(v1, 뜻 그대로) 가 과제의 provider_health 다. HEALTHY 는 쓰지 않는다(관측 없음 ≠ 건강, 리뷰 C4).
- rate_limit_state 를 **v2** 로 넓힌다: 런타임이 선언한 경고(`allowed_warning` + surpassedThreshold)는 WARNING,
  API 오류 429(google.rpc RESOURCE_EXHAUSTED 의 HTTP 대응 · Anthropic rate_limit_error)는 LIMITED. 둘 다 없는 레코드에서는
  v1 과 출력이 **같다**(시험이 붙든다).
- 공급자별 오류 꼴(HTTP 상태 · google.rpc 상태 문자열 · retry-after)은 llmsensor/providers 의 어댑터가 정준 꼴로 바꾼다.
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType
from ...state.rules import Rule, _inf, _unk, r_rate_limit
from .. import SensingPack
from .._base import M, R, _m, canon
from ..l0 import RATE_LIMIT_CANON

RT = EntityType.RUNTIME
NEW_CANON = {
    "runtime.rate_limit_status": ("run", "rate_limit_status", RT, Basis.RUNTIME_DECLARED),
    "runtime.rate_limit_threshold": ("run", "rate_limit_threshold", RT, Basis.RUNTIME_DECLARED),
}
# S4: 한도 창이 다시 차는 시각은 L0 provider.rate_limit 에서 **직접** 읽는다(BD-80 · CMD-S16) -- l0.rate_limit
NEW_CANON.update(RATE_LIMIT_CANON)
# 런타임 상태 문자열 -> 값. **이 수집에서 본 값만** 넣었다. 모르는 문자열은 추측하지 않는다
DECLARED_STATUS = {"allowed_warning": "WARNING"}
# v3: 'rejected' 를 실데이터에서 봤다(이 세션의 5 시간 한도 거절, 2026-10-01 20:45 -- 재고 D2 · L0 provider.rate_limit)
DECLARED_STATUS_V3 = {**DECLARED_STATUS, "rejected": "LIMITED"}
LIMIT_ERRORS = {"429", "RATE_LIMITED"}   # HTTP 429 · 어댑터의 정준 종류. HTTP 429 = google.rpc.Code RESOURCE_EXHAUSTED(code.proto) = Anthropic rate_limit_error


def m_declared(L, ctx, Mx):
    s, t = L.run.get("runtime.rate_limit_status"), L.run.get("runtime.rate_limit_threshold")
    if s is None or s.value is None:
        return _m(ctx, "rate_limit_declared", None, (), reason="런타임이 요금 한도 상태 문자열을 주지 않았다")
    return _m(ctx, "rate_limit_declared", {"status": s.value, "threshold": t.value if t else None},
              [o.id for o in (s, t) if o is not None], Basis.RUNTIME_DECLARED)


def _rate_limit(table):
    return lambda Mx, prev, cfg: r_rate_limit_v2(Mx, prev, cfg, table)


def m_quota_headroom(L, ctx, Mx):
    """1 − 런타임이 선언한 사용률. **계정** 범위 값이다(BD-32) -- 이 실행이 소모한 것이 아니다. 소진 예측은 하지 않는다:
    사용률이 0.01 단위로 양자화돼 있고 계정 전체의 소모라 이 실행의 속도가 아니다(재고)."""
    u = L.run.get("runtime.rate_limit_utilization")
    if u is None or u.value is None:
        return _m(ctx, "quota_headroom", None, (), reason="런타임이 한도 사용률을 주지 않았다")
    return _m(ctx, "quota_headroom", round(1 - u.value, 6), [u.id], Basis.RUNTIME_DECLARED)


def m_quota_time_to_reset(L, ctx, Mx):
    r = L.run.get("l0.rate_limit")
    if r is None or r.value is None:
        return _m(ctx, "quota_time_to_reset_ms", None, (), reason="L0 provider.rate_limit 사건을 받지 않았다")
    t = r.value.get("resets_at_ms")
    if t is None:
        # L0 원장의 말을 옮긴다 -- 원천을 직접 본 것이 아니다(실측: 원천 줄에 resetsAt 가 있는데 L0 가 unobserved 로 적은 일이 있었다)
        why = ("L0 원장이 '원천이 주지 않음(unobserved)' 으로 적었다" if "resets_at_ms" in r.value.get("unobserved", ())
               else "L0 사건에 그 칸이 비었다")
        return _m(ctx, "quota_time_to_reset_ms", None, [r.id], reason="한도 창이 다시 차는 시각이 없다 -- " + why)
    now = ctx.get("now")
    if now is None or r.time_base != "unix_ms":
        return _m(ctx, "quota_time_to_reset_ms", None, [r.id],
                  reason=f"평가 시각이 unix ms 가 아니다(time_base={r.time_base}) -- 다시 차는 시각(unix ms)에서 빼지 않는다")
    return _m(ctx, "quota_time_to_reset_ms", max(0, t - now), [r.id], Basis.RUNTIME_DECLARED)


def r_rate_limit_v2(Mx, prev, cfg, table=DECLARED_STATUS):
    api, dec, u = Mx["api_error"], Mx["rate_limit_declared"], Mx["rate_limit_utilization"]
    if api.value and api.value["reported"] and str(api.value["value"]) in LIMIT_ERRORS:
        return _inf("LIMITED", f"API 오류 {api.value['value']} -- 요청이 한도로 거절됐다", ["api_error"])
    if u.value is not None and u.value >= 1:
        return _inf("EXHAUSTED", f"사용률 {u.value} ≥ 1", ["rate_limit_utilization"])
    if dec.value is not None:
        hit = table.get(dec.value["status"])
        if hit:
            return _inf(hit, f"런타임 선언 {dec.value['status']!r} (사용률 {u.value} ≥ 런타임 문턱 {dec.value['threshold']})",
                        ["rate_limit_declared", "rate_limit_utilization"])
        base = r_rate_limit(Mx, prev, cfg)
        return type(base)(base.value, base.status, base.reason + f" · 표에 없는 런타임 상태 {dec.value['status']!r} -- 추측 안 함",
                          base.evidence + ("rate_limit_declared",), base.final)
    return r_rate_limit(Mx, prev, cfg)     # v1 과 같은 길


NEW_METRICS = (MetricDefinition("rate_limit_declared", RT, ("runtime.rate_limit_status", "runtime.rate_limit_threshold"),
                                Basis.RUNTIME_DECLARED, "런타임이 선언한 요금 한도 상태와 그 문턱", m_declared),
               MetricDefinition("quota_headroom", RT, ("runtime.rate_limit_utilization",), Basis.RUNTIME_DECLARED,
                                "1 − 선언된 한도 사용률(계정 범위 -- 이 실행의 소모가 아니다)", m_quota_headroom),
               MetricDefinition("quota_time_to_reset_ms", RT, ("l0.rate_limit",), Basis.RUNTIME_DECLARED,
                                "선언된 한도 창이 다시 차기까지(평가 시각이 unix ms 일 때만)", m_quota_time_to_reset))
RATE_LIMIT_V2 = Rule("rate-limit-state-v2", 2, "rate_limit_state", RT, Basis.RUNTIME_DECLARED,
                     ("rate_limit_utilization", "rate_limit_declared", "api_error"),
                     ("AVAILABLE", "WARNING", "LIMITED", "EXHAUSTED"),
                     "요금 한도: 429 로 거절됨(LIMITED) · 사용률 ≥ 1(EXHAUSTED) · 런타임이 경고를 선언(WARNING) · 그 밖(AVAILABLE). "
                     "v1(AVAILABLE · EXHAUSTED)의 확장 -- 새 관측이 없으면 v1 과 같다", "늦출까 · 공급자를 바꿀까", r_rate_limit_v2)
RATE_LIMIT_V3 = Rule("rate-limit-state-v3", 3, "rate_limit_state", RT, Basis.RUNTIME_DECLARED,
                     ("rate_limit_utilization", "rate_limit_declared", "api_error"),
                     ("AVAILABLE", "WARNING", "LIMITED", "EXHAUSTED"),
                     "v2 + 런타임이 선언한 거절('rejected')도 LIMITED. 그 밖은 v2 와 같다", "늦출까 · 공급자를 바꿀까",
                     _rate_limit(DECLARED_STATUS_V3))
RATE_LIMIT_V1 = R["rate_limit_state"]       # 회귀 시험용으로 남긴다

PACK = SensingPack(
    "provider", "공급자가 요청을 받아 주나 -- API 오류 · 한도에 잘린 생성 · 요금 한도",
    {**canon("runtime.api_error_status", "runtime.rate_limit_utilization", "runtime.model"), **NEW_CANON},
    tuple(M[n] for n in ("stop_reasons", "api_error", "rate_limit_utilization")) + NEW_METRICS,
    (RATE_LIMIT_V3, R["runtime_reliability"]))
