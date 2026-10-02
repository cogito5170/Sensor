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
from ..l0 import RATE_LIMIT_CANON, RATE_LIMIT_WINDOWS_CANON

RT = EntityType.RUNTIME
NEW_CANON = {
    "runtime.rate_limit_status": ("run", "rate_limit_status", RT, Basis.RUNTIME_DECLARED),
    "runtime.rate_limit_threshold": ("run", "rate_limit_threshold", RT, Basis.RUNTIME_DECLARED),
}
# S4: 한도 창이 다시 차는 시각은 L0 provider.rate_limit 에서 **직접** 읽는다(BD-80 · CMD-S16) -- l0.rate_limit
NEW_CANON.update(RATE_LIMIT_CANON)
# S4 창(CMD-S21): 런타임이 창마다 따로 준 사용률 · 재설정 시각 -- l0.rate_limit_windows
NEW_CANON.update(RATE_LIMIT_WINDOWS_CANON)
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


def _windows(L):
    """(창 관측, {이름: 창}) -- 마지막 provider.rate_limit 뒤에 선언된 창. 없으면 (None, {})."""
    w = L.run.get("l0.rate_limit_windows")
    if w is None or w.value is None or not w.value.get("windows"):
        return None, {}
    return w, w.value["windows"]


def _binding(ws):
    """가장 작은 여유를 정한 창들(이름 차례) -- 모든 창의 사용률을 봤을 때만. 못 본 창이 있으면 (None, 그 창들)."""
    blind = sorted(n for n, x in ws.items() if not isinstance(x.get("utilization"), (int, float)))
    if blind:
        return None, blind
    lo = min(1 - x["utilization"] for x in ws.values())
    return round(lo, 6), sorted(n for n, x in ws.items() if round(1 - x["utilization"], 6) == round(lo, 6))


def _cite(ws, names):
    return " · ".join(f"{n}(사용률 {ws[n]['utilization']}, 사건 seq {ws[n]['seq']})" for n in names)


def m_quota_windows(L, ctx, Mx):
    """창마다: 여유(1 − 사용률) · 선언된 재설정 시각(unix ms) · 남은 시간(평가 시각이 unix ms 일 때만). 창을 고르지 않는다."""
    w, ws = _windows(L)
    if w is None:
        return _m(ctx, "quota_windows", None, (), reason="런타임이 창별 한도(provider.rate_limit_window)를 주지 않았다")
    now = ctx.get("now")
    out = {}
    for n, x in ws.items():
        u, r = x.get("utilization"), x.get("resets_at_ms")
        out[n] = {"headroom": round(1 - u, 6) if isinstance(u, (int, float)) else None, "resets_at_ms": r,
                  "time_to_reset_ms": max(0, r - now) if (r is not None and now is not None and w.time_base == "unix_ms")
                  else None}
    return _m(ctx, "quota_windows", out, [w.id], Basis.RUNTIME_DECLARED)


def m_quota_headroom(L, ctx, Mx):
    """v2 (CMD-S21): 창이 선언됐으면 **선언된 창 가운데 가장 작은 여유**, 그 값을 정한 창을 이유에 남긴다. 창의 사용률을 하나라도
    못 봤으면 모름(나머지 가운데 최소는 참 최소의 상한일 뿐이다). 창이 없으면 v1 그대로: 1 − 런타임이 선언한 사용률.
    **계정** 범위 값이다(BD-32) -- 이 실행이 소모한 것이 아니다. 소진 예측은 하지 않는다(사용률이 0.01 단위 · 계정 전체의 소모)."""
    w, ws = _windows(L)
    if w is not None:
        lo, names = _binding(ws)
        if lo is None:
            return _m(ctx, "quota_headroom", None, [w.id],
                      reason=f"창 {', '.join(names)} 의 사용률을 못 봤다 -- 가장 작은 여유를 정할 수 없다")
        return _m(ctx, "quota_headroom", lo, [w.id], Basis.RUNTIME_DECLARED,
                  reason=f"선언된 창 {len(ws)} 개 가운데 가장 작은 여유 -- {_cite(ws, names)}")
    u = L.run.get("runtime.rate_limit_utilization")
    if u is None or u.value is None:
        return _m(ctx, "quota_headroom", None, (), reason="런타임이 한도 사용률을 주지 않았다")
    return _m(ctx, "quota_headroom", round(1 - u.value, 6), [u.id], Basis.RUNTIME_DECLARED)


def _declared_reset(L):
    """(선언된 재설정 시각 unix ms | None, 근거 관측, 이유, 그 관측). 창이 선언됐으면 가장 작은 여유를 정한 창의 것(여럿이 같으면
    가장 늦은 것 -- 그래야 가장 작은 여유가 오른다). 창이 없으면 마지막 provider.rate_limit 의 것."""
    w, ws = _windows(L)
    if w is not None:
        lo, names = _binding(ws)
        if lo is None:
            return None, [w.id], f"창 {', '.join(names)} 의 사용률을 못 봤다 -- 어느 창이 여유를 정하는지 모른다", w
        rs = [ws[n].get("resets_at_ms") for n in names]
        if any(r is None for r in rs):
            return None, [w.id], f"여유를 정한 창({', '.join(names)})의 재설정 시각이 없다", w
        return max(rs), [w.id], f"가장 작은 여유를 정한 창 -- {_cite(ws, names)}", w
    r = L.run.get("l0.rate_limit")
    if r is None or r.value is None:
        return None, [], "L0 provider.rate_limit 사건을 받지 않았다", None
    t = r.value.get("resets_at_ms")
    if t is None:
        # L0 원장의 말을 옮긴다 -- 원천을 직접 본 것이 아니다(실측: 원천 줄에 resetsAt 가 있는데 L0 가 unobserved 로 적은 일이 있었다)
        why = ("L0 원장이 '원천이 주지 않음(unobserved)' 으로 적었다" if "resets_at_ms" in r.value.get("unobserved", ())
               else "L0 사건에 그 칸이 비었다")
        return None, [r.id], "한도 창이 다시 차는 시각이 없다 -- " + why, r
    return t, [r.id], "", r


def m_quota_resets_at(L, ctx, Mx):
    """BD-90: 선언된 재설정 시각(unix ms) **그대로**. 평가 시각이 필요 없다 -- 남은 시간은 unix now 를 가진 쪽이 계산한다.
    시간 기준이 monotonic 인 원천(cc_stream)에서도 값이 선다."""
    t, refs, why, _ = _declared_reset(L)
    if t is None:
        return _m(ctx, "quota_resets_at_ms", None, refs, reason=why)
    return _m(ctx, "quota_resets_at_ms", t, refs, Basis.RUNTIME_DECLARED, reason=why)


def m_quota_time_to_reset(L, ctx, Mx):
    """v2 (CMD-S21): quota_resets_at_ms 와 같은 창(들)이 다시 차기까지. 평가 시각이 unix ms 일 때만(BD-33 -- 시간 기준을 섞지 않는다)."""
    t, refs, why, o = _declared_reset(L)
    if t is None:
        return _m(ctx, "quota_time_to_reset_ms", None, refs, reason=why)
    now = ctx.get("now")
    if now is None or o.time_base != "unix_ms":
        return _m(ctx, "quota_time_to_reset_ms", None, refs,
                  reason=f"평가 시각이 unix ms 가 아니다(time_base={o.time_base}) -- 다시 차는 시각(unix ms)에서 빼지 않는다")
    return _m(ctx, "quota_time_to_reset_ms", max(0, t - now), refs, Basis.RUNTIME_DECLARED, reason=why)


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
               MetricDefinition("quota_headroom", RT, ("runtime.rate_limit_utilization", "l0.rate_limit_windows"),
                                Basis.RUNTIME_DECLARED,
                                "선언된 창 가운데 가장 작은 여유(창이 없으면 1 − 선언된 한도 사용률). 계정 범위 -- 이 실행의 소모가 아니다",
                                m_quota_headroom, version=2),
               MetricDefinition("quota_time_to_reset_ms", RT, ("l0.rate_limit", "l0.rate_limit_windows"),
                                Basis.RUNTIME_DECLARED,
                                "가장 작은 여유를 정한 창이 다시 차기까지(창이 없으면 선언된 한도 창). 평가 시각이 unix ms 일 때만",
                                m_quota_time_to_reset, version=2),
               MetricDefinition("quota_resets_at_ms", RT, ("l0.rate_limit", "l0.rate_limit_windows"), Basis.RUNTIME_DECLARED,
                                "가장 작은 여유를 정한 창(창이 없으면 선언된 한도 창)의 선언된 재설정 시각(unix ms) 그대로 -- "
                                "평가 시각이 필요 없다(BD-90)", m_quota_resets_at),
               MetricDefinition("quota_windows", RT, ("l0.rate_limit_windows",), Basis.RUNTIME_DECLARED,
                                "창마다 여유 · 선언된 재설정 시각 · 남은 시간 -- 창을 고르지 않는다", m_quota_windows))
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
