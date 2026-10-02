"""층 3 -- 의미 상태를 만드는 규칙. 규칙은 상태 저장과 떨어져 있고, 순수 함수다(같은 입력 -> 같은 출력).

규칙마다: id · 버전 · 상태 이름 · 실체 · 근거(Basis) · 입력 지표 · 값 집합 · 뜻 · 지원하는 결정.

**경험적 문턱이 있는 규칙은 하나도 없다** -- 지금 저장소의 데이터로 정당화되는 문턱이 없기 때문이다(앞 SWE-bench 실험:
센서 점수가 토큰 수 하나를 못 이겼다). 그래서 규칙은 셋 중 하나다:
    DEFINITIONAL      정의에서 따라 나온다(마지막 결과가 실패 = 미해결, 비용 ≥ 예산 = 소진)
    RUNTIME_DECLARED  경계를 런타임이 선언했다(자동 압축 문턱, 종료 사유)
    OPERATOR_ASSUMED  운영자가 설정에 문턱을 줬을 때만 동작한다. 안 줬으면 NOT_APPLICABLE 또는 UNKNOWN
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .model import Basis, EntityType, Status

U, NA = Status.UNKNOWN, Status.NOT_APPLICABLE


@dataclass(frozen=True)
class Result:
    value: object
    status: Status
    reason: str
    evidence: tuple            # 근거로 삼은 지표 이름들
    final: bool = False
    basis: "Basis | None" = None   # 이 값의 근거가 규칙 근거와 다를 때(예: 값 하나만 운영자 문턱에 기댄다). None = 규칙 근거
    # 이 값을 **정한** 관측 id 들(BD-57 · BD-63). 주면 상태의 근거 시각 = 그 가운데 **가장 이른** 시각 -- 값을 정하지 않은
    # 새 근거가 낡은 결론을 신선하게 보이게 하지 않는다. 비우면 예전대로(근거 지표의 관측 중 가장 늦은 시각)
    decided_by: tuple = ()


@dataclass(frozen=True)
class Rule:
    id: str
    version: int
    state: str
    entity: EntityType
    basis: Basis
    inputs: tuple
    values: tuple              # UNKNOWN · NOT_APPLICABLE 은 모든 상태에 공통이라 뺀다
    meaning: str
    decision: str              # 이 상태가 돕는 결정(§32 질문 1)
    fn: Callable = field(compare=False, repr=False)
    # 평가 시각(now)에 기대는 값 -- 그 순간에만 참이다. 평가 뒤 시각으로 질의하면 STALE(엔진 view), 다시 재려면 advance()
    clock_values: tuple = ()
    # 소유 층 표시(BD-35 · BD-52). 건강 성격 상태는 "ASSESS" -- 이름 · 값은 그대로, Health 저장소가 서면 옮긴다. None = 상태 층(L2)
    owner_layer: "str | None" = None
    # 실체마다 따로 서는 규칙(도구처럼). subjects(Ledger) -> 이름들, subject_metrics(이름) -> 그 실체의 지표 정의들
    subjects: "Callable | None" = field(default=None, compare=False, repr=False)
    subject_metrics: "Callable | None" = field(default=None, compare=False, repr=False)


def _inf(v, reason, ev, final=False, decided_by=()):
    return Result(v, Status.INFERRED, reason, tuple(ev), final, None, tuple(decided_by))


def _unk(reason, ev=()):
    return Result(None, U, reason, tuple(ev))


# ---- 맥락 ----
def r_context_pressure(M, prev, cfg):
    ctx, win, thr = M["context_tokens"], M["context_window"], M["compaction_threshold"]
    if ctx.value is None:
        return _unk("맥락 크기를 모른다: " + ctx.reason, ["context_tokens"])
    if win.value is not None and ctx.value >= win.value:
        return _inf("AT_CONTEXT_LIMIT", f"맥락 {ctx.value:,} ≥ 창 {win.value:,}", ["context_tokens", "context_window"])
    if thr.value is not None:
        if ctx.value >= thr.value:
            return _inf("ABOVE_COMPACTION_THRESHOLD", f"맥락 {ctx.value:,} ≥ 런타임 압축 문턱 {thr.value:,}",
                        ["context_tokens", "compaction_threshold"])
        return _inf("BELOW_COMPACTION_THRESHOLD", f"맥락 {ctx.value:,} < 런타임 압축 문턱 {thr.value:,}",
                    ["context_tokens", "compaction_threshold"])
    if win.value is not None:
        return _inf("BELOW_CONTEXT_LIMIT", f"맥락 {ctx.value:,} < 창 {win.value:,} (압축 문턱은 선언되지 않았다)",
                    ["context_tokens", "context_window"])
    return _unk("창도 압축 문턱도 모른다 -- 이용률의 경계가 없다", ["context_tokens"])


# ---- 실행 ----
def _blind(prefix, n, pend):
    """결과를 못 본 호출 n 개의 까닭(S23) -- 기다리는 중(tool.end 아직 없음)과 원천이 주지 않음(tool.end 는 왔다)을 가른다.
    값은 둘 다 UNKNOWN 이고 이유 · 근거만 다르다. 가를 근거(L0 tool.end)가 없으면 그렇다고 말한다."""
    p = pend.value if pend is not None else None
    U, P = prefix + "tool_outcome_unobservable", prefix + "tool_outcome_pending"
    if p is None:
        return (f"도구 호출 {n} 개의 결과(is_error)를 못 봤다 -- 아직 안 왔는지 원천이 주지 않는지 모른다"
                f"({pend.reason if pend is not None and pend.reason else 'L0 tool.end 를 받지 않았다'})", [U])
    if p == n:
        return f"도구 호출 {n} 개가 결과를 기다리는 중이다(tool.end 가 아직 없다)", [P]
    if p == 0:
        return f"도구 호출 {n} 개의 결과(is_error)를 원천이 주지 않는다(tool.end 는 왔다) -- 이 런타임 추적의 한계", [U]
    return f"결과를 기다리는 호출 {p} 개 · 원천이 결과(is_error)를 주지 않은 호출 {n - p} 개", [P, U]


def _health(prefix):
    def fn(M, prev, cfg):
        res, unobs, tg = M[prefix + "tool_results"], M[prefix + "tool_outcome_unobservable"], M[prefix + "tool_targets"]
        if res.value == 0:
            if unobs.value:
                return _unk(*_blind(prefix, unobs.value, M.get(prefix + "tool_outcome_pending")))
            return _unk("본 도구 실행이 없다 -- 실패가 없었다는 증거도 없다", [prefix + "tool_results"])
        t = tg.value
        nu = len(t["unresolved"])     # tool_targets 의 입력 순서: 미해결 겨냥의 마지막 결과들, 그다음 회복된 겨냥의 마지막 결과들
        if t["unresolved"]:
            return _inf("UNRESOLVED_FAILURES", f"겨냥 {nu}/{t['targets']} 의 마지막 결과가 실패",
                        [prefix + "tool_targets", prefix + "tool_failure_rate"], decided_by=tg.inputs[:nu])
        if t["recovered"]:
            return _inf("RECOVERED_FAILURES", f"실패했던 겨냥 {len(t['recovered'])} 개가 뒤에 성공",
                        [prefix + "tool_targets", prefix + "tool_failure_rate"], decided_by=tg.inputs[nu:])
        extra = f" (결과를 못 본 호출 {unobs.value} 개 제외)" if unobs.value else ""
        return _inf("NO_FAILURE_OBSERVED", f"결과 {res.value} 개 중 실패 없음{extra} -- 건강이 증명된 것은 아니다",
                    [prefix + "tool_results", prefix + "tool_failure_rate"])
    return fn


# ---- 과업 ----
TERMINATION_MAP = {   # 런타임이 선언한 문자열 -> 값. 표에 없는 문자열은 추측하지 않고 UNKNOWN
    ("result_subtype", "success"): "ENDED_NORMALLY",
    ("result_subtype", "error_max_turns"): "ENDED_BY_LIMIT",
    ("result_subtype", "error_during_execution"): "ENDED_WITH_ERROR",
    ("terminal_reason", "completed"): "ENDED_NORMALLY",
    ("terminal_reason", "max_turns"): "ENDED_BY_LIMIT",
    ("terminal_reason", "submitted"): "ENDED_NORMALLY",                 # SWE-agent
    ("terminal_reason", "submitted (exit_cost)"): "ENDED_BY_LIMIT",     # SWE-agent: 비용 한도로 강제 제출
}


def r_completion(M, prev, cfg):
    t = M["termination"]
    if t.value is None:
        if M["activity"].value["model_calls"] or M["activity"].value["tool_results"]:
            return _inf("RUNNING", "관측이 들어오고 있고 끝 요약이 아직 없다", ["activity"])
        return _unk("관측이 없다", ["activity"])
    v = t.value
    for k in ("result_subtype", "terminal_reason"):
        hit = TERMINATION_MAP.get((k, v.get(k)))
        if hit:
            if v.get("is_error") and hit == "ENDED_NORMALLY":
                hit = "ENDED_WITH_ERROR"
            return _inf(hit, f"런타임 종료 선언 {k}={v.get(k)!r} -- 과업이 **성공**했다는 뜻이 아니다",
                        ["termination"], final=True)
    if v.get("is_error"):
        return _inf("ENDED_WITH_ERROR", "런타임이 is_error=true 로 끝났다", ["termination"], final=True)
    return Result(None, U, f"표에 없는 종료 선언 {v} -- 추측하지 않는다", ("termination",), True)


def r_progress(M, prev, cfg):
    if M["termination"].value is not None:
        return Result(None, NA, "끝난 과업 -- 진행 상태가 정의되지 않는다", ("termination",), True)
    k = cfg.stall_repeat_threshold
    if k is None:
        return _unk("진행을 판정할 검증된 근거가 없다(토큰은 진행이 아니다). 정체 문턱도 설정되지 않았다",
                    ["activity"])
    rep = M["identical_call_max"]
    if rep.value is None:
        return _unk("도구 서명이 없다", ["identical_call_max"])
    if rep.value >= k:
        return _inf("STALLED", f"같은 (도구, 인자) {rep.value} 번 ≥ 설정 문턱 {k}", ["identical_call_max"])
    return _inf("NO_STALL_DETECTED", f"같은 (도구, 인자) 최대 {rep.value} 번 < {k} -- 진행 중이라는 뜻은 아니다",
                ["identical_call_max"])


# ---- 자원 ----
def r_resource_state(M, prev, cfg):
    if cfg.cost_budget_usd is None:
        return Result(None, NA, "예산이 설정되지 않았다", ("cost_fraction",))
    f = M["cost_fraction"]
    if f.value is None:
        return _unk("비용을 아직 못 봤다: " + M["cost_usd"].reason, ["cost_usd"])
    if f.value >= 1:
        return _inf("BUDGET_EXHAUSTED", f"비용/예산 = {f.value:.3f} ≥ 1", ["cost_fraction", "cost_margin"])
    return _inf("WITHIN_BUDGET", f"비용/예산 = {f.value:.3f} < 1", ["cost_fraction", "cost_margin"])


def r_resource_pressure(M, prev, cfg):
    bands = cfg.resource_bands
    if cfg.cost_budget_usd is None or not bands:
        return Result(None, NA, "예산 또는 압력 띠가 설정되지 않았다", ("cost_fraction",))
    f = M["cost_fraction"]
    if f.value is None:
        return _unk("비용을 아직 못 봤다", ["cost_usd"])
    return _inf(band(f.value, bands, prev), f"비용/예산 = {f.value:.3f}, 설정 띠 {[b.label for b in bands]}",
                ["cost_fraction"])


def band(x, bands, prev, base="LOW"):
    """흔들림 억제가 있는 띠 판정. 들어가려면 enter 이상, 이미 그 띠(또는 위)면 exit 밑으로 내려가야 나간다."""
    order = [base] + [b.label for b in bands]
    cur = 0
    for i, b in enumerate(bands, 1):
        if x >= b.enter:
            cur = i
    if prev in order:
        p = order.index(prev)
        while p > cur and x < bands[p - 1].exit:       # exit 밑으로 내려간 띠만 하나씩 내려온다
            p -= 1
        cur = max(cur, p)
    return order[cur]


# ---- 런타임 ----
def r_rate_limit(M, prev, cfg):
    u = M["rate_limit_utilization"]
    if u.value is None:
        return _unk(u.reason, ["rate_limit_utilization"])
    if u.value >= 1:
        return _inf("EXHAUSTED", f"사용률 {u.value} ≥ 1", ["rate_limit_utilization"])
    return _inf("AVAILABLE", f"사용률 {u.value} < 1 (경고 문턱은 런타임 사건에 있으나 꼴 v2 에 안 담았다)",
                ["rate_limit_utilization"])


def r_reliability(M, prev, cfg):
    api, st = M["api_error"], M["stop_reasons"]
    if api.value is not None and api.value["reported"]:
        return _inf("FAILURE_OBSERVED", f"API 오류 보고 {api.value['value']!r}", ["api_error"], decided_by=api.inputs)
    if st.value is not None and st.value["abnormal"]:
        return _inf("FAILURE_OBSERVED", f"한도에 잘린 생성 {st.value['abnormal']}", ["stop_reasons"],
                    decided_by=st.inputs)
    covered = []
    if api.value is not None:
        covered.append("API 오류 보고 없음(보고된 null)")
    if st.value is not None and st.value["observed"]:
        covered.append(f"멈춤 사유 {st.value['observed']} 개 정상")
    if covered:
        return _inf("NO_FAILURE_OBSERVED", " · ".join(covered) + " -- 신뢰가 증명된 것은 아니다",
                    [n for n, ok in (("api_error", api.value is not None), ("stop_reasons", bool(covered))) if ok])
    return _unk("API 오류 상태도 멈춤 사유도 못 봤다", ["api_error", "stop_reasons"])


A, T, R, TL = EntityType.AGENT, EntityType.TASK, EntityType.RUNTIME, EntityType.TOOL
HEALTH = ("NO_FAILURE_OBSERVED", "RECOVERED_FAILURES", "UNRESOLVED_FAILURES")

RULES = [
    Rule("context-pressure-v1", 1, "context_pressure", A, Basis.RUNTIME_DECLARED,
         ("context_tokens", "context_window", "compaction_threshold"),
         ("BELOW_CONTEXT_LIMIT", "BELOW_COMPACTION_THRESHOLD", "ABOVE_COMPACTION_THRESHOLD", "AT_CONTEXT_LIMIT"),
         "맥락이 런타임이 선언한 경계(자동 압축 문턱 · 창)의 어느 쪽에 있나. 경계는 런타임 것이지 우리 것이 아니다",
         "다음 호출 전에 맥락을 줄일까", r_context_pressure),
    Rule("execution-health-v2", 2, "execution_health", A, Basis.DEFINITIONAL,
         ("tool_results", "tool_outcome_unobservable", "tool_outcome_pending", "tool_targets", "tool_failure_rate"), HEALTH,
         "도구 실행 결과에 풀리지 않은 실패가 있나. 겨냥마다 마지막 결과로 본다(실패율 문턱이 아니다)",
         "다시 시도할까 · 사람에게 올릴까", _health(""), owner_layer="ASSESS"),
    Rule("tool-execution-health-v2", 2, "tool_execution_health", TL, Basis.DEFINITIONAL,
         ("tool_results", "tool_outcome_unobservable", "tool_outcome_pending", "tool_targets", "tool_failure_rate"), HEALTH,
         "도구 하나에 대한 execution_health -- 도구마다 따로", "이 도구를 계속 쓸까", _health(""), owner_layer="ASSESS"),
    Rule("completion-state-v1", 1, "completion_state", T, Basis.RUNTIME_DECLARED, ("termination", "activity"),
         ("RUNNING", "ENDED_NORMALLY", "ENDED_BY_LIMIT", "ENDED_WITH_ERROR"),
         "런타임이 실행을 어떻게 끝냈다고 선언했나. **과업 성공이 아니다**(SWE-bench: 정상 제출 243 중 해결 69 이하)",
         "결과를 검증으로 넘길까 · 한도를 올릴까", r_completion),
    Rule("progress-state-v1", 1, "progress_state", T, Basis.OPERATOR_ASSUMED, ("identical_call_max", "termination"),
         ("STALLED", "NO_STALL_DETECTED"),
         "같은 호출 반복으로 본 정체. 문턱은 운영자 가정 -- 기본 설정에서는 UNKNOWN",
         "끊을까", r_progress),
    Rule("resource-state-v1", 1, "resource_state", A, Basis.DEFINITIONAL, ("cost_fraction", "cost_margin"),
         ("WITHIN_BUDGET", "BUDGET_EXHAUSTED"), "보고된 비용이 설정 예산 안인가", "멈출까", r_resource_state),
    Rule("resource-pressure-v1", 1, "resource_pressure", A, Basis.OPERATOR_ASSUMED, ("cost_fraction",),
         ("LOW",), "설정 띠로 본 비용 압력(띠 이름은 설정이 정한다). 띠가 없으면 NOT_APPLICABLE",
         "싼 경로로 바꿀까", r_resource_pressure),
    Rule("rate-limit-state-v1", 1, "rate_limit_state", R, Basis.DEFINITIONAL, ("rate_limit_utilization",),
         ("AVAILABLE", "EXHAUSTED"), "요금 한도 사용률이 1 에 닿았나", "늦출까", r_rate_limit),
    Rule("runtime-reliability-v2", 2, "runtime_reliability", R, Basis.DEFINITIONAL, ("api_error", "stop_reasons"),
         ("NO_FAILURE_OBSERVED", "FAILURE_OBSERVED"),
         "API 오류 보고 · 한도에 잘린 생성이 있었나. '실패를 못 봤다' 와 '건강하다' 를 가른다",
         "다른 공급자로 돌릴까", r_reliability, owner_layer="ASSESS"),
]
