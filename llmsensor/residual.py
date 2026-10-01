"""잔차 -- 예측(M_P)과 관측의 차. NASA analytical redundancy 의 residual generation 을 그대로 옮긴다.

    r_T = (T_actual - T_expected) / T_expected     상대 토큰 잔차
    z_T = 로그 눈금 강건 z
    r_R = R_actual - R_expected                    재시도 초과
    r_E = E_actual - E_expected                    오류 초과
    r_V = 1 if 검증 실패 else 0                    (외부 결과 · 마지막 검증 · 제약 중 하나라도 FAULT)

    R_sys = w_T·max(0, z_T)/z_ref + w_R·max(0, r_R) + w_E·max(0, r_E) + w_V·r_V

R_sys 는 **순위 점수**다. 단위가 다른 것을 무게로 더했을 뿐이고 문턱은 재서 정한 것이 아니다.
기대값이 없는 항은 0 이 아니라 빠지고(`missing` 에 적힌다), 빠진 항이 있다는 것이 결과에 남는다.
"""
from __future__ import annotations

from .reading import FAULT

WEIGHTS = {"T": 1.0, "R": 1.0, "E": 1.0, "V": 2.0}


def residuals(tel: dict, model=None, cls: str = "default", readings=None, weights=None, z_ref: float = 3.5) -> dict:
    w = dict(WEIGHTS, **(weights or {}))
    exp = model.expect(cls) if model is not None else {}
    out: dict = {"expected": exp, "missing": []}
    parts = {}
    if exp.get("T"):
        out["r_T"] = (tel["T"] - exp["T"]) / exp["T"]
        out["z_T"] = model.z(cls, "T", tel["T"])
        parts["T"] = max(0.0, out["z_T"]) / z_ref
    else:
        out["missing"].append("T")
    for k in ("R", "E"):
        if k in exp:
            out[f"r_{k}"] = tel[k] - exp[k]
            parts[k] = max(0.0, out[f"r_{k}"])
        else:
            out["missing"].append(k)
    if readings is not None:
        bad = [r.sensor for r in readings if r.sensor in ("outcome", "constraint") and r.status == FAULT]
        cl = [r for r in readings if r.sensor == "consistency"]
        if cl and cl[0].detail.get("claim", {}).get("status") == FAULT:
            bad.append("consistency.claim")
        out["r_V"] = 1.0 if bad else 0.0
        out["r_V_from"] = bad
        parts["V"] = out["r_V"]
    else:
        out["missing"].append("V")
    out["R_sys"] = sum(w[k] * v for k, v in parts.items())
    out["parts"] = parts
    return out
