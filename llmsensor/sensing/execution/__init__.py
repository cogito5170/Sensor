"""Execution 센싱 -- 실행이 어떻게 끝났나, 도구 결과, 시간 초과 · 중단.

기존 상태(execution_health · tool_execution_health · completion_state · progress_state)는 뜻 그대로 이 팩에 묶고,
새로 관측할 수 있게 된 것(꼴 v3 의 timed_out, 기존 interrupted)으로 **execution_interruption** 하나만 더한다.
과제의 합성 열거 execution_state(RUNNING · FAILED · TIMEOUT ...)는 만들지 않는다 -- docs/MS_SENSING_REVIEW.md C2.
"""
from ...state.model import Basis, EntityType
from ...state.rules import Rule, _inf, _unk
from ...trace import ToolCall, retries
from .. import SensingPack
from .._base import M, R, _m, canon
from ...state.metrics import MetricDefinition

A, T = EntityType.AGENT, EntityType.TASK
NEW_CANON = {
    "tool.timed_out": ("tool_call", "timed_out", EntityType.TOOL, Basis.RUNTIME_DECLARED),
    "tool.interrupted": ("tool_call", "interrupted", EntityType.TOOL, Basis.OBSERVED),
    "run.num_turns": ("run", "num_turns", EntityType.TASK, Basis.OBSERVED),
}


def _flag(L, field):
    rows = [t for t in L.tools if t.get(field) is not None and t[field].value is not None]
    hit = [t for t in rows if t[field].value]
    return rows, hit


def m_tool_timeouts(L, ctx, Mx):
    rows, hit = _flag(L, "tool.timed_out")
    if not rows:
        return _m(ctx, "tool_timeouts", None, (), reason="시간 초과를 판정할 수 있는 도구 결과가 없다(Bash 문구만 안다)")
    return _m(ctx, "tool_timeouts", {"timeouts": len(hit), "covered": len(rows)},
              [t["tool.timed_out"].id for t in (hit or rows[-1:])], Basis.RUNTIME_DECLARED)


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


def m_turns(L, ctx, Mx):
    o = L.run.get("run.num_turns")
    if o is None or o.value is None:
        return _m(ctx, "turns", None, (), reason="런타임이 회전 수를 보고하지 않았다")
    return _m(ctx, "turns", o.value, [o.id])


def r_interruption(Mx, prev, cfg):
    to, it = Mx["tool_timeouts"], Mx["tool_interruptions"]
    if to.value and to.value["timeouts"]:
        return _inf("TIMEOUT_OBSERVED", f"도구 시간 초과 {to.value['timeouts']} 회(런타임 문구) / 판정 가능 {to.value['covered']}",
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
    MetricDefinition("tool_timeouts", A, ("tool.timed_out",), Basis.RUNTIME_DECLARED,
                     "런타임이 시간 초과를 선언한 도구 결과 수 / 판정 가능한 결과 수", m_tool_timeouts),
    MetricDefinition("tool_interruptions", A, ("tool.interrupted",), Basis.OBSERVED,
                     "중단 깃발이 선 도구 결과 수 / 깃발을 본 결과 수", m_tool_interruptions),
    MetricDefinition("tool_retries", A, ("tool.is_error", "tool.target", "tool.name"), Basis.OBSERVED,
                     "오류 뒤 같은 겨냥 재호출 수", m_tool_retries),
    MetricDefinition("turns", T, ("run.num_turns",), Basis.OBSERVED, "런타임이 보고한 회전 수", m_turns),
)
INTERRUPTION = Rule("execution-interruption-v2", 2, "execution_interruption", A, Basis.RUNTIME_DECLARED,
                    ("tool_timeouts", "tool_interruptions"), ("TIMEOUT_OBSERVED", "INTERRUPTED_OBSERVED", "NONE_OBSERVED"),
                    "런타임이 도구의 시간 초과(문구) · 중단(깃발)을 선언했나. 지연 문턱이 아니라 런타임의 선언이다",
                    "시간 제한을 늘릴까 · 배경으로 돌릴까", r_interruption)

PACK = SensingPack(
    "execution", "실행이 어떻게 끝났나 · 도구 결과에 풀리지 않은 실패 · 시간 초과 · 중단이 있었나",
    {**canon("tool.name", "tool.target", "tool.signature", "tool.is_error", "tool.output_chars", "call.stop_reason",
             "run.terminal_reason", "run.result_subtype", "run.is_error"), **NEW_CANON},
    tuple(M[n] for n in ("tool_results", "tool_outcome_unobservable", "tool_errors", "tool_failure_rate", "tool_targets",
                         "identical_call_max", "termination", "activity")) + NEW_METRICS,
    (R["execution_health"], R["tool_execution_health"], R["completion_state"], R["progress_state"], INTERRUPTION))
