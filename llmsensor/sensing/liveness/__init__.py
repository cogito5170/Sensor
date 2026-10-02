"""Liveness 센싱 -- 대상이 **지금 움직이고 있나**(execution 은 '어떻게 끝났나', 이것은 '아직 도나').

입력 계약(docs/SENSOR_HEALTH_DESIGN.md §1, S1) -- 텔레메트리 계층이 `run` 레코드에 채운다. 원천 꼴은 여기서 모른다.

    terminal_seen     런타임의 종료 사건(결과 레코드)을 받았나                     OBSERVED
    transport_closed  원천의 흐름이 닫혔나(스트림 EOF · 프로세스 종료)             OBSERVED
    turn_open         차례가 열려 있나 -- 입력을 **받은 순간부터** 차례가 끝날 때까지 true
                      (받았는데 아직 처리 시작 전인 입력도 '열림' 이다. 그래야 그 침묵도 잴 수 있다)  OBSERVED
    activity_at_ms    이 실행에서 어떤 사건이든 마지막으로 온 시각                  OBSERVED
    heartbeat_at_ms   런타임이 '진행 중' 이라고 보낸 마지막 신호 시각              RUNTIME_DECLARED

시각은 레코드의 time_base 하나로 잰다. 두 시각의 time_base 가 다르면 빼지 않는다(UNKNOWN). advance(now) 의 now 도 같은 기준이어야 한다.

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

T = EntityType.TASK
NEW_CANON = {
    "run.terminal_seen": ("run", "terminal_seen", T, Basis.OBSERVED),
    "run.transport_closed": ("run", "transport_closed", T, Basis.OBSERVED),
    "run.turn_open": ("run", "turn_open", T, Basis.OBSERVED),
    "run.activity_at_ms": ("run", "activity_at_ms", T, Basis.OBSERVED),
    "run.heartbeat_at_ms": ("run", "heartbeat_at_ms", T, Basis.RUNTIME_DECLARED),
}


def _flag(L, key):
    o = L.run.get(key)
    return (None, None) if o is None or o.value is None else (o.value, o)


def m_stream_end(L, ctx, Mx):
    """끝 신호 둘 -- 종료 사건을 받았나, 흐름이 닫혔나. 둘 다 못 봤으면 None."""
    (ts, o1), (tc, o2) = _flag(L, "run.terminal_seen"), _flag(L, "run.transport_closed")
    if o1 is None and o2 is None:
        return _m(ctx, "stream_end", None, (), reason="종료 사건 · 흐름 닫힘을 관측하지 못했다")
    return _m(ctx, "stream_end", {"terminal_seen": ts, "transport_closed": tc}, [o.id for o in (o1, o2) if o])


def m_turn_open(L, ctx, Mx):
    v, o = _flag(L, "run.turn_open")
    if o is None:
        return _m(ctx, "turn_open", None, (), reason="차례가 열려 있는지 관측하지 못했다")
    return _m(ctx, "turn_open", bool(v), [o.id])


def m_silence(L, ctx, Mx):
    """평가 시각 − 마지막 활동(사건 또는 런타임 heartbeat 중 늦은 것). 엔진은 시계를 읽지 않는다 -- now 는 ctx 에서."""
    obs = [o for o in (L.run.get("run.activity_at_ms"), L.run.get("run.heartbeat_at_ms"))
           if o is not None and o.value is not None]
    if not obs:
        return _m(ctx, "silence_ms", None, (), reason="활동 시각을 관측하지 못했다")
    if len({o.time_base for o in obs}) > 1:
        return _m(ctx, "silence_ms", None, [o.id for o in obs],
                  reason=f"활동 · heartbeat 시각의 시간 기준이 다르다 {sorted(str(o.time_base) for o in obs)} -- 빼지 않는다")
    now = ctx.get("now")
    if now is None:
        return _m(ctx, "silence_ms", None, [o.id for o in obs], reason="평가 시각이 없다")
    last = max(obs, key=lambda o: (o.value, o.field))
    s = now - last.value
    if s < 0:
        return _m(ctx, "silence_ms", None, [o.id for o in obs], reason=f"평가 시각 {now} 이 마지막 활동 {last.value} 보다 이르다")
    src = "heartbeat" if last.field == "run.heartbeat_at_ms" else "activity"
    return _m(ctx, "silence_ms", {"ms": s, "last": src}, [o.id for o in obs],
              Basis.RUNTIME_DECLARED if src == "heartbeat" else Basis.OBSERVED)


def _res(v, reason, ev, basis=None, final=False):
    return Result(v, Status.INFERRED, reason, tuple(ev), final, basis)


def r_liveness(M, prev, cfg):
    end, term, turn, sil = M["stream_end"].value or {}, M["termination"], M["turn_open"], M["silence_ms"]
    if end.get("terminal_seen") is True:
        return _res("ENDED", "런타임의 종료 사건을 받았다", ["stream_end"], Basis.OBSERVED, final=True)
    declared = {k: v for k, v in (term.value or {}).items() if v is not None}
    if declared:          # 종료 칸이 전부 null 로 보고된 요약은 종료 선언이 아니다
        return _res("ENDED", f"런타임이 종료를 선언했다 {declared}", ["termination"], Basis.RUNTIME_DECLARED, final=True)
    if end.get("transport_closed") is True:
        return _res("ENDED_WITHOUT_TERMINAL", "흐름이 닫혔는데 런타임이 끝났다고 말하지 않았다 -- 정의로 결함",
                    ["stream_end"], Basis.DEFINITIONAL)
    if turn.value is None:
        return _unk("차례가 열려 있는지 모른다 -- 공백이 사람을 기다린 것일 수 있어 판정하지 않는다: " + turn.reason,
                    ["turn_open"])
    if turn.value is False:
        return _res("AWAITING_INPUT", "차례가 닫혀 있다 -- 멈춘 것이 아니라 다음 입력을 기다린다", ["turn_open"],
                    Basis.OBSERVED)
    timeout = cfg.liveness_timeout_ms
    if timeout is None:
        return _res("IN_TURN", "차례가 열려 있다. 무음 문턱(liveness_timeout_ms)이 설정되지 않아 멈춤 여부는 판정하지 않는다",
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
    MetricDefinition("stream_end", T, ("run.terminal_seen", "run.transport_closed"), Basis.OBSERVED,
                     "종료 사건을 받았나 · 흐름이 닫혔나", m_stream_end),
    MetricDefinition("turn_open", T, ("run.turn_open",), Basis.OBSERVED, "차례가 열려 있나(입력 수신 ~ 차례 끝)", m_turn_open),
    MetricDefinition("silence_ms", T, ("run.activity_at_ms", "run.heartbeat_at_ms"), Basis.OBSERVED,
                     "평가 시각 − 마지막 활동(사건 또는 런타임 heartbeat)", m_silence),
)
LIVENESS = Rule("liveness-state-v1", 1, "liveness_state", T, Basis.DEFINITIONAL,
                ("stream_end", "termination", "turn_open", "silence_ms"),
                ("ENDED", "ENDED_WITHOUT_TERMINAL", "AWAITING_INPUT", "IN_TURN", "ACTIVE", "STALLED"),
                "대상이 아직 움직이나. 끝남 · 끝 신호 없이 닫힘 · 입력 대기 · 차례 중은 문턱 없이, ACTIVE · STALLED 는 "
                "운영자 무음 문턱이 있을 때만(값마다 근거가 따로 남는다). DEAD 는 내지 않는다",
                "기다릴까 · 끊고 다시 띄울까", r_liveness, clock_values=("ACTIVE", "STALLED"))

PACK = SensingPack("liveness", "대상이 지금 움직이고 있나 -- 끝났나 · 입력을 기다리나 · 차례 중 멈췄나(멈춤은 운영자 문턱이 있을 때만)",
                   NEW_CANON, NEW_METRICS, (LIVENESS,))
