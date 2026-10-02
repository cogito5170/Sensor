"""Execution 센싱 -- 실행이 어떻게 끝났나, 도구 결과, 시간 초과 · 중단.

기존 상태(execution_health · tool_execution_health · completion_state · progress_state)는 뜻 그대로 이 팩에 묶고,
새로 관측할 수 있게 된 것(꼴 v3 의 timed_out, 기존 interrupted)으로 **execution_interruption** 하나만 더한다.
과제의 합성 열거 execution_state(RUNNING · FAILED · TIMEOUT ...)는 만들지 않는다 -- docs/MS_SENSING_REVIEW.md C2.
"""
from ...state.model import Basis, EntityType, Status
from ...state.rules import HEALTH, Result, Rule, _health, _inf, _unk
from ...trace import ToolCall, retries
from .. import SensingPack
from .._base import M, R, _m, canon
from ...state.metrics import MetricDefinition
from ..l0 import TIMEOUTS_CANON

A, T = EntityType.AGENT, EntityType.TASK
NEW_CANON = {
    "tool.timed_out": ("tool_call", "timed_out", EntityType.TOOL, Basis.RUNTIME_DECLARED),
    "tool.interrupted": ("tool_call", "interrupted", EntityType.TOOL, Basis.OBSERVED),
    "run.num_turns": ("run", "num_turns", EntityType.TASK, Basis.OBSERVED),
}
# S2: 시간 초과의 처분은 L0 tool.end 에서 **직접** 읽는다(BD-80 · CMD-S16) -- l0.timeouts(llmsensor/sensing/l0.py)
NEW_CANON.update(TIMEOUTS_CANON)


def _flag(L, field):
    rows = [t for t in L.tools if t.get(field) is not None and t[field].value is not None]
    hit = [t for t in rows if t[field].value]
    return rows, hit


def m_tool_timeouts(L, ctx, Mx):
    rows, hit = _flag(L, "tool.timed_out")
    if not rows:
        return _m(ctx, "tool_timeouts", None, (), reason="시간 초과를 판정할 수 있는 도구 결과가 없다(Bash 문구만 안다)")
    disp, refs = {"backgrounded": 0, "killed": 0, "unknown": len(hit)}, []
    l0 = L.run.get("l0.timeouts")
    if l0 is not None and l0.value is not None:
        if l0.value["timeouts"] == len(hit):      # 두 길이 같은 시간 초과를 세었을 때만 L0 의 처분을 쓴다
            disp = {k: l0.value[k] for k in ("backgrounded", "killed", "unknown")}
            refs = [l0.id]
        else:
            disp["mismatch"] = {"records": len(hit), "l0": l0.value["timeouts"]}
    return _m(ctx, "tool_timeouts", {"timeouts": len(hit), "covered": len(rows), **disp},
              [t["tool.timed_out"].id for t in (hit or rows[-1:])] + refs, Basis.RUNTIME_DECLARED)


def m_tool_interruptions(L, ctx, Mx):
    rows, hit = _flag(L, "tool.interrupted")
    if not rows:
        return _m(ctx, "tool_interruptions", None, (), reason="중단 깃발을 본 도구 결과가 없다")
    return _m(ctx, "tool_interruptions", {"interrupted": len(hit), "covered": len(rows)},
              [t["tool.interrupted"].id for t in (hit or rows[-1:])])


def m_tool_retries(L, ctx, Mx):
    """오류 뒤 같은 겨냥(도구 이름 + 겨냥 해시)을 다시 부른 수 -- llmsensor.trace.retries 와 같은 정의."""
    rows = [t for t in L.tools if t.get("tool.is_error") is not None and t["tool.is_error"].value is not None]
    if not rows:
        return _m(ctx, "tool_retries", None, (), reason="결과를 본 도구 호출이 없다")
    calls = [ToolCall(t["tool.name"].value, {"command": t["tool.target"].value if t.get("tool.target") else ""},
                      not t["tool.is_error"].value) for t in rows]
    return _m(ctx, "tool_retries", retries(calls), [t["tool.is_error"].id for t in rows])


def m_run_last_event(L, ctx, Mx):
    """그 실행에서 마지막으로 본 L0 사건(종류 · seq). 시각은 관측이 가진다. L0 묶기를 안 받았으면 None."""
    o = L.run.get("l0.last_event")
    if o is None or o.value is None:
        return _m(ctx, "run_last_event", None, (), reason="그 실행의 L0 사건을 받지 않았다")
    return _m(ctx, "run_last_event", {"type": o.value.get("type"), "seq": o.value.get("seq")}, [o.id])


def m_turns(L, ctx, Mx):
    o = L.run.get("run.num_turns")
    if o is None or o.value is None:
        return _m(ctx, "turns", None, (), reason="런타임이 회전 수를 보고하지 않았다")
    return _m(ctx, "turns", o.value, [o.id])


def r_interruption(Mx, prev, cfg):
    to, it = Mx["tool_timeouts"], Mx["tool_interruptions"]
    if to.value and to.value["timeouts"]:
        v = to.value
        n = v["timeouts"]
        # 처분이 모두 같을 때만 그 처분을 값으로 -- 섞였거나 하나라도 모르면 v2 와 같은 TIMEOUT_OBSERVED (짐작하지 않는다)
        val = ("TIMEOUT_BACKGROUNDED" if v.get("backgrounded") == n else "TIMEOUT_KILLED" if v.get("killed") == n
               else "TIMEOUT_OBSERVED")
        return _inf(val, f"도구 시간 초과 {n} 회 / 판정 가능 {v['covered']} -- 처분: 백그라운드 {v.get('backgrounded', 0)} · "
                         f"죽임 {v.get('killed', 0)} · 모름 {v.get('unknown', n)}",
                    ["tool_timeouts"], decided_by=to.inputs)          # 입력 = 시간 초과가 선 결과들(BD-57)
    if it.value and it.value["interrupted"]:
        return _inf("INTERRUPTED_OBSERVED", f"도구 중단 {it.value['interrupted']} 회(런타임 깃발)", ["tool_interruptions"],
                    decided_by=it.inputs)
    covered = [n for n, m in (("tool_timeouts", to), ("tool_interruptions", it)) if m.value]
    if covered:
        return _inf("NONE_OBSERVED", "판정 가능한 결과에서 시간 초과 · 중단 없음 -- 다른 도구의 시간 초과는 문구를 몰라 못 본다",
                    covered)
    return _unk("시간 초과 · 중단을 판정할 수 있는 도구 결과가 없다", ["tool_timeouts", "tool_interruptions"])


NEW_METRICS = (
    MetricDefinition("tool_timeouts", A, ("tool.timed_out", "l0.timeouts"), Basis.RUNTIME_DECLARED,
                     "런타임이 시간 초과를 선언한 도구 결과 수 / 판정 가능한 결과 수 · 그 처분(백그라운드 · 죽임 · 모름)", m_tool_timeouts),
    MetricDefinition("tool_interruptions", A, ("tool.interrupted",), Basis.OBSERVED,
                     "중단 깃발이 선 도구 결과 수 / 깃발을 본 결과 수", m_tool_interruptions),
    MetricDefinition("tool_retries", A, ("tool.is_error", "tool.target", "tool.name"), Basis.OBSERVED,
                     "오류 뒤 같은 겨냥 재호출 수", m_tool_retries),
    MetricDefinition("turns", T, ("run.num_turns",), Basis.OBSERVED, "런타임이 보고한 회전 수", m_turns),
    MetricDefinition("run_last_event", T, ("l0.last_event",), Basis.OBSERVED,
                     "그 실행에서 마지막으로 본 L0 사건(종류 · seq) -- '아직 없다' 의 근거 시각", m_run_last_event),
)
INTERRUPTION = Rule("execution-interruption-v3", 3, "execution_interruption", A, Basis.RUNTIME_DECLARED,
                    ("tool_timeouts", "tool_interruptions"),
                    ("TIMEOUT_BACKGROUNDED", "TIMEOUT_KILLED", "TIMEOUT_OBSERVED", "INTERRUPTED_OBSERVED", "NONE_OBSERVED"),
                    "런타임이 도구의 시간 초과 · 중단을 선언했나, 시간 초과를 어떻게 처분했나(백그라운드로 옮김 · 죽임 -- 모두 같을 때만, "
                    "아니면 TIMEOUT_OBSERVED). 지연 문턱이 아니라 런타임의 선언이다. 시간 초과 ≠ 실패",
                    "시간 제한을 늘릴까 · 배경으로 돌릴까", r_interruption, owner_layer="ASSESS")

_HEALTH_V2 = _health("")


def r_execution_health_v3(Mx, prev, cfg):
    """v2 + 도구 호출이 **아직 없음**을 따로 낸다(BD-84). 결과를 못 본 호출이 있으면(SWE-agent) v2 와 같이 UNKNOWN.
    '아직 없다' 를 말하려면 그 실행의 사건이 하나라도 있어야 한다(BD-89): L0 사건, 또는 L0 에서 온 모델 호출 레코드."""
    res, unobs, act, last = Mx["tool_results"], Mx["tool_outcome_unobservable"], Mx["activity"], Mx["run_last_event"]
    if res.value == 0 and unobs.value == 0:          # 둘 다 0 = 도구 레코드(tool.start)가 하나도 없다 -- 도는 중인 호출도 없다
        calls = act.value["model_calls"] if act.value else 0
        if not calls and last.value is None:
            return _unk("그 실행의 사건을 하나도 못 봤다 -- '아직 없다' 를 말할 관측이 없다", ["tool_results", "run_last_event"])
        seen = [x for x, ok in ((f"모델 호출 {calls} 개", calls), (f"L0 사건(마지막 {last.value['type']})" if last.value
                                                                  else "", last.value is not None)) if ok]
        # 없음의 주장이라 그 실행에서 가장 늦게 본 관측의 시각을 쓴다(BD-74): decided_by 를 비우면 엔진이 근거 가운데 가장 늦은 시각을 쓴다
        return Result("NO_TOOL_RUN_YET", Status.INFERRED,
                      f"{' · '.join(seen)} 를 봤고 도구 호출은 아직 없다 -- 건강을 말하는 값이 아니다",
                      ("tool_results", "tool_outcome_unobservable", "activity", "run_last_event"), basis=Basis.OBSERVED)
    return _HEALTH_V2(Mx, prev, cfg)


EXECUTION_HEALTH_V3 = Rule("execution-health-v3", 3, "execution_health", A, Basis.DEFINITIONAL,
                           ("tool_results", "tool_outcome_unobservable", "tool_targets", "tool_failure_rate", "activity",
                            "run_last_event"),
                           HEALTH + ("NO_TOOL_RUN_YET",),
                           "도구 실행 결과에 풀리지 않은 실패가 있나. 겨냥마다 마지막 결과로 본다(실패율 문턱이 아니다). "
                           "그 실행의 사건(L0 사건 · 모델 호출)은 봤는데 도구 호출이 아직 없으면 NO_TOOL_RUN_YET -- 건강을 말하지 않는다. "
                           "도구 호출이 있는데 결과를 볼 수 없으면 UNKNOWN(v2 와 같다)",
                           "다시 시도할까 · 사람에게 올릴까", r_execution_health_v3, owner_layer="ASSESS")
EXECUTION_HEALTH_V2 = R["execution_health"]     # 회귀 시험용으로 남긴다

PACK = SensingPack(
    "execution", "실행이 어떻게 끝났나 · 도구 결과에 풀리지 않은 실패 · 시간 초과 · 중단이 있었나",
    {**canon("tool.name", "tool.target", "tool.signature", "tool.is_error", "tool.output_chars", "call.stop_reason",
             "run.terminal_reason", "run.result_subtype", "run.is_error"), **NEW_CANON},
    tuple(M[n] for n in ("tool_results", "tool_outcome_unobservable", "tool_errors", "tool_failure_rate", "tool_targets",
                         "identical_call_max", "termination", "activity")) + NEW_METRICS,
    (EXECUTION_HEALTH_V3, R["tool_execution_health"], R["completion_state"], R["progress_state"], INTERRUPTION))
