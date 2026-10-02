"""L0 사건 봉투 -> 관측 묶음. L1 의 묶기(binding)다 -- 판단하지 않고, 사건이 있었다는 것과 그 순서 · 시각 · 센 수만 옮긴다.

쓰는 팩: liveness(차례 경계 · 활동 · 박동) · actions(런타임 자신의 행동: 압축 · 백그라운드 이동 · 입력 빼기 · 권한 거부).

L0 패키지(cogito5170/Telemetry)를 import 하지 않는다. 봉투는 L0 꼴의 dict 다(`telemetry/event.py`):

    {"spec", "id": "<run_id>:<seq>", "type", "run_id", "seq", "source", "at", "time_base", "data", "unobserved", "reported_null"}

사건마다 묶음 하나(멱등 열쇠 = 사건 id). 관측 값은 {"seq", "at"}(+ last_event 에는 "type") 이다 -- 칸 값(data)은 싣지 않는다.
"""
from __future__ import annotations

from ..state.model import Basis, EntityType, Observation
from ..state.normalize import Batch, entity_id

T = EntityType.TASK
# L0 사건 종류 -> 정준 관측 이름, 근거
EVENT_OBS = {
    "input.received": ("l0.input_received", Basis.OBSERVED),
    "turn.start": ("l0.turn_start", Basis.OBSERVED),
    "turn.end": ("l0.turn_end", Basis.OBSERVED),
    "turn.continued": ("l0.turn_continued", Basis.OBSERVED),
    "source.closed": ("l0.source_closed", Basis.OBSERVED),
    "run.end": ("l0.run_end", Basis.OBSERVED),
    "heartbeat": ("l0.heartbeat", Basis.RUNTIME_DECLARED),
    "input.removed": ("l0.input_removed", Basis.OBSERVED),     # 줄에 선 입력을 런타임이 뺐다(absorbed_mid_turn ...) -- CMD-T5
}
# 정준 이름 표 -- 레지스트리의 의존 그래프와 검사용. 레코드 종류 "l0" 는 꼴 v3 레코드에 없으므로 from_telemetry 와 섞이지 않는다
NEW_CANON = {name: ("l0", typ, T, basis) for typ, (name, basis) in EVENT_OBS.items()}
NEW_CANON["l0.last_event"] = ("l0", "*", T, Basis.OBSERVED)
# 묶기가 세는 값: 아직 처리되지 않은 입력 수. input.received +1 · input.removed −1(0 아래로 안 감) · turn.start 가 소비(0).
# input.removed 는 어느 입력인지 가리키지 않는다 -- 그래서 짝을 짓지 않고 수로 센다. turn.start 는 줄에 선 입력을 모두 받는다고
# 본다(Claude Code 는 줄에 선 입력을 한 차례로 합친다 -- 이 가정이 틀리면 열림을 일찍 닫는다)
NEW_CANON["l0.pending_inputs"] = ("l0", "input.*", T, Basis.OBSERVED)
LIVENESS_CANON = dict(NEW_CANON)
# 런타임 자신의 행동(S5, BD-53): 실행마다 센 수와 마지막 압축의 전후 토큰. 값을 바꾸는 사건에서만 관측이 생긴다 --
# 관측이 없으면 '0 회' 가 아니라 '본 적 없음' 이다
ACTIONS_CANON = {"l0.runtime_actions": ("l0", "runtime.*", T, Basis.RUNTIME_DECLARED)}
# 의존 대상(S3, BD-54): 그 대상에 대한 **마지막 호출**의 결과와 지금까지의 수. 이름마다 관측 이름이 따로다(l0.dep:<이름>)
#   provider[.<이름>]  <- llm.response(성공) · llm.error(정준 error_code · http_status)
#   probe.<겨냥 해시>  <- dependency.probe(error_code · status_code)
# 결함 원인은 **선언된 것만**: 출처 있는 표로 옮긴 error_code, 또는 HTTP 상태 ≥ 400(RFC 9110 의 정의). 글을 해석하지 않는다
DEP_PREFIX = "l0.dep:"
DEPENDENCY_CANON = {DEP_PREFIX + "*": ("l0", "llm.* · dependency.probe", EntityType.DEPENDENCY, Basis.RUNTIME_DECLARED)}
# S2 · S4 가 L0 를 직접 읽는다(BD-80 · CMD-S16 -- compat 은 넓히지 않는다):
#   l0.timeouts    런타임이 시간 초과를 선언한 tool.end 의 수와 처분(moved_to_background: true 옮김 · false 죽임 · 없음 모름)
#   l0.rate_limit  마지막 provider.rate_limit 의 resets_at_ms · declared_status · limit_type · utilization + 원천이 안 준 칸 목록
TIMEOUTS_CANON = {"l0.timeouts": ("l0", "tool.end", EntityType.TASK, Basis.RUNTIME_DECLARED)}
RATE_LIMIT_CANON = {"l0.rate_limit": ("l0", "provider.rate_limit", EntityType.TASK, Basis.RUNTIME_DECLARED)}
RATE_LIMIT_KEYS = ("resets_at_ms", "declared_status", "limit_type", "utilization")
NEW_CANON = {**LIVENESS_CANON, **ACTIONS_CANON, **DEPENDENCY_CANON, **TIMEOUTS_CANON, **RATE_LIMIT_CANON}
# 차례 끝을 **늘** 내는 것으로 알려진 원천(Telemetry 보고 baseline#1: cc_stream 의 result). cc_jsonl 은 Stop 훅이 있을 때만이라 넣지 않는다
ENDS_ALWAYS = frozenset({"cc_stream"})


def batches(events) -> "list[Batch]":
    """L0 사건들 -> 실행마다 원천 순서(seq)대로의 묶음. 모르는 종류의 사건도 '마지막 활동' 으로는 센다."""
    out, pending, acts, deps, tos = [], {}, {}, {}, {}
    for ev in sorted(events, key=lambda e: (e["run_id"], e["seq"])):
        run, rid, at, tb, src = ev["run_id"], ev["id"], ev.get("at"), ev.get("time_base"), ev["source"]
        ent = entity_id(T, run)
        val = {"seq": ev["seq"], "at": at}
        obs = [Observation(f"{rid}#l0.last_event", ent, "l0.last_event", dict(val, type=ev["type"]), False, at, tb, src,
                           Basis.OBSERVED)]
        hit = EVENT_OBS.get(ev["type"])
        if hit:
            name, basis = hit
            obs.append(Observation(f"{rid}#{name}", ent, name, dict(val), False, at, tb, src, basis))
        if ev["type"] in ("input.received", "input.removed", "turn.start"):
            n = pending.get(run, 0)
            n = n + 1 if ev["type"] == "input.received" else max(0, n - 1) if ev["type"] == "input.removed" else 0
            pending[run] = n
            obs.append(Observation(f"{rid}#l0.pending_inputs", ent, "l0.pending_inputs", dict(val, n=n), False, at, tb,
                                   src, Basis.OBSERVED))
        a = _action(acts.setdefault(run, {}), ev)
        if a is not None:
            obs.append(Observation(f"{rid}#l0.runtime_actions", ent, "l0.runtime_actions", dict(a, **val), False, at, tb,
                                   src, Basis.RUNTIME_DECLARED))
        data = ev.get("data") or {}
        if ev["type"] == "tool.end" and data.get("timed_out") is True:
            c = tos.setdefault(run, {"timeouts": 0, "backgrounded": 0, "killed": 0, "unknown": 0})
            m = data.get("moved_to_background")
            c["timeouts"] += 1
            c["unknown" if m is None else "backgrounded" if m else "killed"] += 1
            obs.append(Observation(f"{rid}#l0.timeouts", ent, "l0.timeouts", dict(c, **val), False, at, tb, src,
                                   Basis.RUNTIME_DECLARED))
        if ev["type"] == "provider.rate_limit":
            v = {k: data.get(k) for k in RATE_LIMIT_KEYS}
            v["unobserved"] = sorted(k for k in ev.get("unobserved", ()) if k in RATE_LIMIT_KEYS)
            obs.append(Observation(f"{rid}#l0.rate_limit", ent, "l0.rate_limit", dict(v, **val), False, at, tb, src,
                                   Basis.RUNTIME_DECLARED))
        d = _dependency(deps.setdefault(run, {}), ev)
        if d is not None:
            name, v = d
            obs.append(Observation(f"{rid}#{DEP_PREFIX}{name}", entity_id(EntityType.DEPENDENCY, run, name), DEP_PREFIX + name,
                                   dict(v, **val), False, at, tb, src, Basis.RUNTIME_DECLARED))
        out.append(Batch(f"l0:{rid}", run, "run", at, tb, src, obs))
    return out


def _action(c, ev):
    """런타임 행동 수를 고친다. 바뀌었으면 사본을, 아니면 None. 칸 값은 수 · 토큰 · 런타임이 붙인 이름만 옮긴다.
    **본 종류만** 싣는다 -- 0 으로 미리 채우면 다른 사건(권한 거부 보고) 하나가 '압축 0 회' 를 지어낸다."""
    d, t = ev.get("data") or {}, ev["type"]
    if t == "runtime.compaction":
        c["compaction"] = c.get("compaction", 0) + 1
        c["last_compaction"] = {k: d.get(k) for k in ("trigger", "pre_tokens", "post_tokens", "duration_ms")}
    elif t == "tool.end" and d.get("moved_to_background") is True:
        c["tool_backgrounded"] = c.get("tool_backgrounded", 0) + 1
    elif t == "input.removed":
        c["input_removed"] = c.get("input_removed", 0) + 1
        c["last_removed_reason"] = d.get("reason")
    elif t == "run.end" and d.get("permission_denials") is not None:
        c["permission_denials"] = d["permission_denials"]
    else:
        return None
    return dict(c)


def _dependency(c, ev):
    """(이름, 그 대상의 지금 값) 또는 None. 값 = 마지막 호출의 결과(ok · 원인)와 수. 원인은 선언된 것만."""
    d, t = ev.get("data") or {}, ev["type"]
    if t in ("llm.response", "llm.error"):
        name = "provider" + (f".{d['provider']}" if d.get("provider") else "")
        cause = None
        if t == "llm.error":
            cause = {k: d.get(k) for k in ("error_code", "http_status") if d.get(k) is not None} or {"error": "llm.error"}
    elif t == "dependency.probe" and d.get("target"):
        name = "probe." + str(d["target"]).lstrip("#")
        sc, ec = d.get("status_code"), d.get("error_code")
        cause = {k: v for k, v in (("error_code", ec), ("status_code", sc)) if v is not None} \
            if ec is not None or (sc is not None and sc >= 400) else None
    else:
        return None
    s = c.setdefault(name, {"calls": 0, "faults": 0})
    s["calls"] += 1
    s["faults"] += cause is not None
    return name, {"ok": cause is None, "cause": cause, "calls": s["calls"], "faults": s["faults"]}
