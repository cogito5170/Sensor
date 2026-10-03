"""L0 사건 봉투 -> 관측 묶음. L1 의 묶기(binding)다 -- 판단하지 않고, 사건이 있었다는 것과 그 순서 · 시각 · 센 수만 옮긴다.

쓰는 팩: liveness(차례 경계 · 활동 · 박동) · actions(런타임 자신의 행동: 압축 · 백그라운드 이동 · 입력 빼기 · 권한 거부).

L0 패키지(cogito5170/Telemetry)를 import 하지 않는다. 봉투는 L0 꼴의 dict 다(`telemetry/event.py`):

    {"spec", "id": "<run_id>:<seq>", "type", "run_id", "seq", "source", "at", "time_base", "data", "unobserved", "reported_null"}

사건마다 묶음 하나(멱등 열쇠 = 사건 id). 관측 값은 {"seq", "at"}(+ last_event 에는 "type") 이다 -- 칸 값(data)은 싣지 않는다.
"""
from __future__ import annotations

import copy

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
# S4 창(CMD-S21): provider.rate_limit_window 는 같은 원천 줄의 provider.rate_limit 바로 뒤에 창마다 하나씩 온다(Telemetry CMD-T15).
#   l0.rate_limit_windows  마지막 provider.rate_limit 뒤에 선언된 창들 {창 이름: {utilization, resets_at_ms, seq, at, 못 본 칸}}.
#   새 provider.rate_limit 가 오면 앞 묶음을 비운다(창 없는 보고 뒤에 낡은 창이 남지 않게). 창을 고르지 않는다 -- 지표가 정한다
RATE_LIMIT_WINDOWS_CANON = {"l0.rate_limit_windows": ("l0", "provider.rate_limit_window", EntityType.TASK,
                                                      Basis.RUNTIME_DECLARED)}
WINDOW_KEYS = ("utilization", "resets_at_ms")
# S23: 도구 결과를 기다리는 중인가, 원천이 결과를 주지 않는가 -- tool.end 를 본 tool_index 들(시각과 무관하다: SWE-agent 는 시각이 없다)
TOOL_ENDS_CANON = {"l0.tool_ends": ("l0", "tool.end", EntityType.TASK, Basis.OBSERVED)}
# S6 · 실행 지표(CMD-S24 · BD-108): 실행기가 낸 action.dispatch / action.result 를 **직접** 읽는다(compat 은 넓히지 않는다 -- BD-80).
#   l0.action_dispatch · l0.action_result  사건 하나마다 관측 하나(근거 id · 시각이 행동마다 따로 선다 -- BD-57)
#   l0.actions      그 실행의 행동 시도 목록. 시도마다 action_ref · action_type · target · args_sig · 두 관측 id · is_error.
#                   같은 action_ref 를 **차례로** 다시 쓰면(같은 명령의 되풀이) 시도가 하나 더 선다. result 는 그 ref 의 열린 시도에 붙는다
#   l0.act:<ref>    실체 action:<실행>:<ref> 의 마지막 시도 -- S6 action_state 가 읽는다
ACT_PREFIX = "l0.act:"
ACTION_STATE_CANON = {
    "l0.action_dispatch": ("l0", "action.dispatch", EntityType.TASK, Basis.RUNTIME_DECLARED),
    "l0.action_result": ("l0", "action.result", EntityType.TASK, Basis.RUNTIME_DECLARED),
    "l0.actions": ("l0", "action.dispatch · action.result", EntityType.TASK, Basis.RUNTIME_DECLARED),
    ACT_PREFIX + "*": ("l0", "action.dispatch · action.result", EntityType.ACTION, Basis.RUNTIME_DECLARED),
}
NEW_CANON = {**LIVENESS_CANON, **ACTIONS_CANON, **DEPENDENCY_CANON, **TIMEOUTS_CANON, **RATE_LIMIT_CANON,
             **RATE_LIMIT_WINDOWS_CANON, **TOOL_ENDS_CANON, **ACTION_STATE_CANON}
# 차례 끝을 **늘** 내는 것으로 알려진 원천(Telemetry 보고 baseline#1: cc_stream 의 result). cc_jsonl 은 Stop 훅이 있을 때만이라 넣지 않는다
ENDS_ALWAYS = frozenset({"cc_stream"})


class Binder:
    """L0 묶기를 이어서 한다(CMD-SEN1) -- 실행마다 쌓는 것(대기 입력 수 · 런타임 행동 · 의존 대상 · 시간 초과 · 한도 창 · 끝난 도구 ·
    행동 시도)을 들고 있어, 새 사건만 먹이면 된다. `batches(events)` 는 새 Binder 에 차례대로 먹인 것과 같다.
    상태는 실행마다 따로라 `snapshot(run)` / `restore(run, s)` 로 실행 하나를 되감을 수 있다(깊은 사본)."""

    def __init__(self):
        self.state: dict = {}

    def _st(self, run):
        st = self.state.get(run)
        if st is None:
            st = self.state[run] = {"pending": 0, "acts": {}, "deps": {}, "tos": None, "wins": {}, "ends": set(),
                                    "attempts": []}
        return st

    def snapshot(self, run):
        return copy.deepcopy(self.state.get(run))

    def restore(self, run, snap):
        if snap is None:
            self.state.pop(run, None)
        else:
            self.state[run] = copy.deepcopy(snap)

    def feed(self, ev) -> Batch:
        run, rid, at, tb, src = ev["run_id"], ev["id"], ev.get("at"), ev.get("time_base"), ev["source"]
        st = self._st(run)
        ent = entity_id(T, run)
        val = {"seq": ev["seq"], "at": at}
        obs = [Observation(f"{rid}#l0.last_event", ent, "l0.last_event", dict(val, type=ev["type"]), False, at, tb, src,
                           Basis.OBSERVED)]
        hit = EVENT_OBS.get(ev["type"])
        if hit:
            name, basis = hit
            obs.append(Observation(f"{rid}#{name}", ent, name, dict(val), False, at, tb, src, basis))
        if ev["type"] in ("input.received", "input.removed", "turn.start"):
            n = st["pending"]
            n = n + 1 if ev["type"] == "input.received" else max(0, n - 1) if ev["type"] == "input.removed" else 0
            st["pending"] = n
            obs.append(Observation(f"{rid}#l0.pending_inputs", ent, "l0.pending_inputs", dict(val, n=n), False, at, tb,
                                   src, Basis.OBSERVED))
        a = _action(st["acts"], ev)
        if a is not None:
            obs.append(Observation(f"{rid}#l0.runtime_actions", ent, "l0.runtime_actions", dict(a, **val), False, at, tb,
                                   src, Basis.RUNTIME_DECLARED))
        data = ev.get("data") or {}
        if ev["type"] == "tool.end" and data.get("tool_index") is not None:
            e = st["ends"]
            e.add(data["tool_index"])
            obs.append(Observation(f"{rid}#l0.tool_ends", ent, "l0.tool_ends", dict(val, indices=sorted(e)), False, at, tb,
                                   src, Basis.OBSERVED))
        if ev["type"] == "tool.end" and data.get("timed_out") is True:
            if st["tos"] is None:
                st["tos"] = {"timeouts": 0, "backgrounded": 0, "killed": 0, "unknown": 0}
            c = st["tos"]
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
            if st["wins"]:                                   # 앞 보고의 창 묶음을 비운다 -- 이 보고의 창은 뒤에 온다
                st["wins"] = {}
                obs.append(Observation(f"{rid}#l0.rate_limit_windows", ent, "l0.rate_limit_windows",
                                       dict(val, windows={}, rate_limit_seq=ev["seq"]), False, at, tb, src,
                                       Basis.RUNTIME_DECLARED))
        if ev["type"] == "provider.rate_limit_window" and data.get("window_name") is not None:
            w = {k: data.get(k) for k in WINDOW_KEYS}
            w.update(seq=ev["seq"], at=at, unobserved=sorted(k for k in ev.get("unobserved", ()) if k in WINDOW_KEYS),
                     reported_null=sorted(k for k in ev.get("reported_null", ()) if k in WINDOW_KEYS))
            cur = dict(st["wins"] or {})
            cur[str(data["window_name"])] = w
            st["wins"] = cur
            obs.append(Observation(f"{rid}#l0.rate_limit_windows", ent, "l0.rate_limit_windows", dict(val, windows=cur),
                                   False, at, tb, src, Basis.RUNTIME_DECLARED))
        if ev["type"] in ("action.dispatch", "action.result") and data.get("action_ref") is not None:
            obs += _executor_action(st["attempts"], ev, rid, run, ent, val, at, tb, src)
        d = _dependency(st["deps"], ev)
        if d is not None:
            name, v = d
            obs.append(Observation(f"{rid}#{DEP_PREFIX}{name}", entity_id(EntityType.DEPENDENCY, run, name), DEP_PREFIX + name,
                                   dict(v, **val), False, at, tb, src, Basis.RUNTIME_DECLARED))
        return Batch(f"l0:{rid}", run, "run", at, tb, src, obs)


def batches(events) -> "list[Batch]":
    """L0 사건들 -> 실행마다 원천 순서(seq)대로의 묶음. 모르는 종류의 사건도 '마지막 활동' 으로는 센다."""
    b = Binder()
    return [b.feed(ev) for ev in sorted(events, key=lambda e: (e["run_id"], e["seq"]))]


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


def _executor_action(attempts, ev, rid, run, ent, val, at, tb, src):
    """행동 사건 하나 -> 관측들. attempts(그 실행의 시도 목록)를 고친다. 칸 값은 이름 · 해시 · 선언된 결과만 -- 글은 없다."""
    d, ref = ev.get("data") or {}, str(ev["data"]["action_ref"])
    if ev["type"] == "action.dispatch":
        name = "l0.action_dispatch"
        a = {"ref": ref, "action_type": d.get("action_type"), "target": d.get("target"), "args_sig": d.get("args_sig"),
             "dispatch": f"{rid}#{name}", "result": None, "is_error": None, "seq": ev["seq"]}
        attempts.append(a)
        v = {k: d.get(k) for k in ("action_type", "target", "args_sig", "decision_ref")}
    else:
        name = "l0.action_result"
        a = next((x for x in reversed(attempts) if x["ref"] == ref and x["result"] is None), None)
        if a is None:                       # dispatch 없이 온 결과 -- 순서를 어겼다. 시도로 세우되 dispatch 가 없다고 적는다
            a = {"ref": ref, "action_type": None, "target": None, "args_sig": None, "dispatch": None, "seq": ev["seq"]}
            attempts.append(a)
        a.update(result=f"{rid}#{name}", is_error=d.get("is_error"),
                 is_error_unobserved="is_error" in (ev.get("unobserved") or ()))
        v = {k: d.get(k) for k in ("is_error", "exit_code", "status_code", "exception", "output_chars", "elapsed_ms")}
    last = dict(a, attempts=sum(x["ref"] == ref for x in attempts))
    return [Observation(f"{rid}#{name}", ent, name, dict(val, action_ref=ref, **v), False, at, tb, src, Basis.RUNTIME_DECLARED),
            Observation(f"{rid}#l0.actions", ent, "l0.actions", dict(val, attempts=[dict(x) for x in attempts]), False, at,
                        tb, src, Basis.RUNTIME_DECLARED),
            Observation(f"{rid}#{ACT_PREFIX}{ref}", entity_id(EntityType.ACTION, run, ref), ACT_PREFIX + ref, dict(val, **last),
                        False, at, tb, src, Basis.RUNTIME_DECLARED)]


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
