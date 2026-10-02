"""L0 사건 봉투 -> liveness 관측 묶음. L1 의 묶기(binding)다 -- 판단하지 않고, 사건이 있었다는 것과 그 순서 · 시각만 옮긴다.

L0 패키지(cogito5170/Telemetry)를 import 하지 않는다. 봉투는 L0 꼴의 dict 다(`telemetry/event.py`):

    {"spec", "id": "<run_id>:<seq>", "type", "run_id", "seq", "source", "at", "time_base", "data", "unobserved", "reported_null"}

사건마다 묶음 하나(멱등 열쇠 = 사건 id). 관측 값은 {"seq", "at"}(+ last_event 에는 "type") 이다 -- 칸 값(data)은 싣지 않는다.
"""
from __future__ import annotations

from ...state.model import Basis, EntityType, Observation
from ...state.normalize import Batch, entity_id

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
# 차례 끝을 **늘** 내는 것으로 알려진 원천(Telemetry 보고 baseline#1: cc_stream 의 result). cc_jsonl 은 Stop 훅이 있을 때만이라 넣지 않는다
ENDS_ALWAYS = frozenset({"cc_stream"})


def batches(events) -> "list[Batch]":
    """L0 사건들 -> 실행마다 원천 순서(seq)대로의 묶음. 모르는 종류의 사건도 '마지막 활동' 으로는 센다."""
    out, pending = [], {}
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
        out.append(Batch(f"l0:{rid}", run, "run", at, tb, src, obs))
    return out
