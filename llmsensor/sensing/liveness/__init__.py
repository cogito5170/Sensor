"""Liveness 센싱 -- 대상이 **지금 움직이고 있나**(execution 은 '어떻게 끝났나', 이것은 '아직 도나'). 소유 층: ASSESS(BD-52).

입력은 **L0 사건**이다(BD-47: 이름은 L0 가 정하고, Sensor 는 그 사건에서 계산한다 -- baseline#3 CMD-S2).
`l0.batches(events)` 가 L0 사건 봉투를 관측 묶음으로 옮기고, 아래 지표가 다섯 가지 뜻을 **측정**한다:

    종료 사건을 받았나        <- run.end
    원천의 흐름이 닫혔나      <- source.closed (닫힘 줄이 있을 때만 -- 파일 끝은 닫힘이 아니다)
    차례가 열려 있나          <- 돌고 있는 차례(turn.start 뒤 turn.end 없음, 원천 순서 seq) 또는 처리하지 않은 입력
                                 (input.received − input.removed, turn.start 가 소비). 입력을 **받은 순간부터** 열림.
                                 turn.continued(훅이 끝을 막음)는 닫지 않는다
    마지막 활동 시각          <- 모든 사건의 at
    런타임 진행 신호          <- heartbeat

**차례 끝을 낸다는 근거가 없는 원천에서는 '열려 있다' 고 하지 않는다.** cc_jsonl 은 Stop 훅이 있는 세션에서만 turn.end 를
낸다(Telemetry 보고) -- 그 실행에서 turn.end 를 한 번이라도 봤거나, 원천이 늘 끝을 내는 것으로 알려졌을 때(cc_stream 의
result)만 열림을 판정한다. 아니면 UNKNOWN.

시각은 사건의 time_base 하나로 잰다. 두 시각의 기준이 다르면 빼지 않는다(UNKNOWN). advance(now) 의 now 도 같은 기준이어야 한다.

이 팩이 **하지 않는 것**:
    DEAD   기록이 끊긴 것만으로는 '대상이 죽음' 과 '수집이 죽음' 을 가를 수 없다 -- 기록 밖 채널이 필요하다
    ALIVE  ACTIVE 와 같은 말을 문턱 없이 하게 된다
    문턱   무음 문턱은 운영자 설정(liveness_timeout_ms)뿐. 관측된 heartbeat 간격(재고: 30초)은 선언이 아니라 쓰지 않는다
"""
from ...state.metrics import MetricDefinition
from ...state.model import Basis, EntityType, Status
from ...state.rules import Result, Rule, _unk
from .. import SensingPack
from .._base import _m
from .l0 import ENDS_ALWAYS, NEW_CANON, batches  # noqa: F401  (batches: L0 사건 -> 관측 묶음)

T = EntityType.TASK


def _ev(L, name):
    o = L.run.get(name)
    return None if o is None or o.value is None else o


def m_stream_end(L, ctx, Mx):
    """끝 신호 둘 -- 종료 사건(run.end)을 받았나, 흐름이 닫혔나(source.closed). 못 받았으면 None(받지 않음 ≠ 아니다)."""
    e, c = _ev(L, "l0.run_end"), _ev(L, "l0.source_closed")
    if e is None and c is None:
        return _m(ctx, "stream_end", None, (), reason="종료 사건 · 흐름 닫힘 사건을 받지 않았다")
    return _m(ctx, "stream_end", {"terminal_seen": True if e else None, "transport_closed": True if c else None},
              [o.id for o in (e, c) if o])


def m_turn_open(L, ctx, Mx):
    """차례가 열려 있나 = 차례가 돌고 있다(turn.start 뒤 turn.end 없음) 또는 받아 놓고 처리하지 않은 입력이 있다."""
    start, end, pend = _ev(L, "l0.turn_start"), _ev(L, "l0.turn_end"), _ev(L, "l0.pending_inputs")
    if start is None and end is None and pend is None:
        return _m(ctx, "turn_open", None, (), reason="차례 경계 사건을 받지 않았다")
    running = start is not None and (end is None or start.value["seq"] > end.value["seq"])
    waiting = pend is not None and pend.value["n"] > 0
    refs = [o.id for o in (start, end, pend) if o]
    if not running and not waiting:
        return _m(ctx, "turn_open", False, refs, reason="돌고 있는 차례도, 처리하지 않은 입력도 없다")
    src = (start or pend).source
    if end is None and src not in ENDS_ALWAYS:
        return _m(ctx, "turn_open", None, refs,
                  reason=f"{src} 이 차례 끝을 낸다는 근거가 없다(이 실행에서 turn.end 를 한 번도 못 봤다 -- "
                         "cc_jsonl 은 Stop 훅이 있을 때만 낸다). 열려 있다고 짐작하지 않는다")
    why = "차례가 돌고 있다" if running else f"처리하지 않은 입력 {pend.value['n']} 개"
    return _m(ctx, "turn_open", True, refs, reason=why)


def m_silence(L, ctx, Mx):
    """평가 시각 − 마지막 활동(어떤 사건이든 또는 heartbeat 중 늦은 것). 엔진은 시계를 읽지 않는다 -- now 는 ctx 에서."""
    obs = [o for o in (_ev(L, "l0.last_event"), _ev(L, "l0.heartbeat")) if o and o.value.get("at") is not None]
    if not obs:
        return _m(ctx, "silence_ms", None, (), reason="시각이 있는 사건을 받지 않았다")
    # 차례 경계 사건의 시각 기준까지 견준다 -- 마지막 사건이 heartbeat 하나뿐이면 '활동' 과 '박동' 이 같은 사건이라 섞임이 안 보인다
    turn = [o for o in (_ev(L, n) for n in ("l0.input_received", "l0.turn_start", "l0.turn_end"))
            if o and o.value.get("at") is not None]
    bases = {o.time_base for o in obs + turn}
    if len(bases) > 1:
        return _m(ctx, "silence_ms", None, [o.id for o in obs + turn],
                  reason=f"사건 시각의 시간 기준이 섞였다 {sorted(str(b) for b in bases)} -- 빼지 않는다")
    now = ctx.get("now")
    if now is None:
        return _m(ctx, "silence_ms", None, [o.id for o in obs], reason="평가 시각이 없다")
    last = max(obs, key=lambda o: (o.value["at"], o.field))
    s = now - last.value["at"]
    if s < 0:
        return _m(ctx, "silence_ms", None, [o.id for o in obs],
                  reason=f"평가 시각 {now} 이 마지막 활동 {last.value['at']} 보다 이르다")
    src = "heartbeat" if last.field == "l0.heartbeat" else last.value.get("type", "event")
    return _m(ctx, "silence_ms", {"ms": s, "last": src}, [o.id for o in obs],
              Basis.RUNTIME_DECLARED if src == "heartbeat" else Basis.OBSERVED)


def _res(v, reason, ev, basis=None, final=False):
    return Result(v, Status.INFERRED, reason, tuple(ev), final, basis)


def r_liveness(M, prev, cfg):
    end, term, turn, sil = M["stream_end"].value or {}, M["termination"], M["turn_open"], M["silence_ms"]
    if end.get("terminal_seen") is True:
        return _res("ENDED", "런타임의 종료 사건(run.end)을 받았다", ["stream_end"], Basis.OBSERVED, final=True)
    declared = {k: v for k, v in (term.value or {}).items() if v is not None}
    if declared:          # 종료 칸이 전부 null 로 보고된 요약은 종료 선언이 아니다
        return _res("ENDED", f"런타임이 종료를 선언했다 {declared}", ["termination"], Basis.RUNTIME_DECLARED, final=True)
    if end.get("transport_closed") is True:
        return _res("ENDED_WITHOUT_TERMINAL", "흐름이 닫혔는데(source.closed) 런타임이 끝났다고 말하지 않았다 -- 정의로 결함",
                    ["stream_end"], Basis.DEFINITIONAL)
    if turn.value is None:
        return _unk("차례가 열려 있는지 모른다 -- 공백이 사람을 기다린 것일 수 있어 판정하지 않는다: " + turn.reason,
                    ["turn_open"])
    if turn.value is False:
        return _res("AWAITING_INPUT", "차례가 닫혀 있다 -- 멈춘 것이 아니라 다음 입력을 기다린다", ["turn_open"],
                    Basis.OBSERVED)
    timeout = cfg.liveness_timeout_ms
    if timeout is None:
        return _res("IN_TURN", f"차례가 열려 있다({turn.reason}). 무음 문턱(liveness_timeout_ms)이 설정되지 않아 멈춤 여부는 "
                    "판정하지 않는다",
                    ["turn_open"], Basis.OBSERVED)
    if sil.value is None:
        return _unk("차례가 열려 있는데 무음을 잴 수 없다: " + sil.reason, ["turn_open", "silence_ms"])
    s = sil.value["ms"]
    if s > timeout:
        return _res("STALLED", f"차례가 열린 채 {s:,} ms 동안 사건 없음(마지막: {sil.value['last']}) > 설정 {timeout:,} ms",
                    ["turn_open", "silence_ms"], Basis.OPERATOR_ASSUMED)
    return _res("ACTIVE", f"마지막 {sil.value['last']} 뒤 {s:,} ms ≤ 설정 {timeout:,} ms -- 평가 시각의 판정",
                ["turn_open", "silence_ms"], Basis.OPERATOR_ASSUMED)


NEW_METRICS = (
    MetricDefinition("stream_end", T, ("l0.run_end", "l0.source_closed"), Basis.OBSERVED,
                     "종료 사건(run.end)을 받았나 · 흐름이 닫혔나(source.closed)", m_stream_end),
    MetricDefinition("turn_open", T, ("l0.turn_start", "l0.turn_end", "l0.pending_inputs"), Basis.OBSERVED,
                     "차례가 열려 있나(입력 받음 ~ 차례 끝, 원천 순서로). 끝을 낸다는 근거 없는 원천에서는 None", m_turn_open),
    MetricDefinition("silence_ms", T, ("l0.last_event", "l0.heartbeat", "l0.input_received", "l0.turn_start", "l0.turn_end"),
                     Basis.OBSERVED,
                     "평가 시각 − 마지막 활동(어떤 사건 또는 런타임 heartbeat)", m_silence),
)
LIVENESS = Rule("liveness-state-v2", 2, "liveness_state", T, Basis.DEFINITIONAL,
                ("stream_end", "termination", "turn_open", "silence_ms"),
                ("ENDED", "ENDED_WITHOUT_TERMINAL", "AWAITING_INPUT", "IN_TURN", "ACTIVE", "STALLED"),
                "대상이 아직 움직이나 -- L0 차례 경계 사건에서. 끝남 · 끝 신호 없이 닫힘 · 입력 대기 · 차례 중은 문턱 없이, "
                "ACTIVE · STALLED 는 운영자 무음 문턱이 있을 때만(값마다 근거가 따로 남는다). DEAD 는 내지 않는다",
                "기다릴까 · 끊고 다시 띄울까", r_liveness, clock_values=("ACTIVE", "STALLED"), owner_layer="ASSESS")

PACK = SensingPack("liveness", "대상이 지금 움직이고 있나 -- 끝났나 · 입력을 기다리나 · 차례 중 멈췄나(멈춤은 운영자 문턱이 있을 때만)",
                   NEW_CANON, NEW_METRICS, (LIVENESS,))
