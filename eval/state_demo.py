"""§40 시연 -- 원 관측 -> 파생 지표 -> 의미 상태 -> 상태 그래프 -> 질의 -> 최소 결정 문맥.

    python3 eval/state_demo.py            (결과: eval/results/state_demo.txt)

입력은 과제 문서의 예시 수를 텔레메트리 레코드(꼴 v2)로 만든 것이다 -- 실제 실행이 아니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.state import REGISTRY, StateEngine, from_telemetry  # noqa: E402
from llmsensor.state.config import Band, DEFAULT_CONFIG  # noqa: E402
from llmsensor.telemetry.schema import record  # noqa: E402

RUN = "demo:example"
CFG = DEFAULT_CONFIG.with_(version="demo-v1", cost_budget_usd=0.10,
                           resource_bands=(Band("MEDIUM", 0.5, 0.45), Band("HIGH", 0.75, 0.7)))


def build():
    recs, t = [], 0.0
    plan = ["Bash:pytest", "Read:#a1", "Bash:pytest", "Edit:#a1", "Bash:pytest", "Grep:#p",
            "Read:#b2", "Edit:#b2", "WebFetch:#doc", "WebFetch:#doc", "Bash:git"]
    errors = {2: True, 9: True}   # 11 회 중 2 회 실패(과제 예시): pytest 는 실패 뒤 성공(회복), WebFetch 는 미해결
    for i, head in enumerate(plan):
        t += 1650.0
        last = i == len(plan) - 1
        recs.append(record("model_call", RUN, "cc_stream", call_index=i, model="claude-opus-5-5", t_start_ms=t - 900,
                           t_end_ms=t, time_base="monotonic_ms", input_tokens=10,
                           cache_read_input_tokens=(130000 if last else 20000 + 10000 * i),
                           cache_creation_input_tokens=(6990 if last else 900), output_tokens=842,
                           thinking_tokens=300, stop_reason="tool_use", tool_calls_per_message=1,
                           output_text_chars=120, context_window=180000))
        name = head.split(":")[0]
        recs.append(record("tool_call", RUN, "cc_stream", call_index=i, tool_index=i, tool_name=name, tool_head=head,
                           tool_sig=f"sig{i}", tool_input_chars=40, t_issued_ms=t + 10, t_result_ms=t + 400,
                           time_base="monotonic_ms", is_error=errors.get(i, False), tool_output_chars=500))
    return recs


def end_record(t):
    return record("run", RUN, "cc_stream", reported_null=["api_error_status"], cost_usd=0.07,
                  autocompact_threshold=144000, context_window=180000, rate_limit_utilization=0.62,
                  result_subtype="success", terminal_reason="completed", is_error=False, run_duration_ms=18200)


def main():
    L = []
    p = L.append
    recs = build()
    E = StateEngine(CFG).ingest_all(from_telemetry(recs))
    A = f"agent:{RUN}"

    p("=" * 70 + "\n1. RAW OBSERVATIONS (마지막 모형 호출과 도구 결과 합계)\n" + "=" * 70)
    last = [r for r in recs if r["kind"] == "model_call"][-1]
    for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens",
              "thinking_tokens", "stop_reason", "context_window"):
        p(f"  {k:30s} = {last[k]}")
    tools = [r for r in recs if r["kind"] == "tool_call"]
    p(f"  {'tool_calls':30s} = {len(tools)}\n  {'tool_errors':30s} = {sum(r['is_error'] for r in tools)}")
    p(f"  {'cost_usd':30s} = (아직 없음 -- 이 런타임은 실행 끝에만 보고)\n  {'budget (설정)':30s} = {CFG.cost_budget_usd}")

    p("\n" + "=" * 70 + "\n2. DERIVED METRICS (층 2)\n" + "=" * 70)
    latest = {}
    for m in E.metrics.values():
        if m.entity_id == A:
            latest[m.name] = m
    for n in ("context_tokens", "context_window", "context_utilization", "context_margin", "tool_results",
              "tool_errors", "tool_failure_rate", "tool_targets", "cost_usd", "cost_margin"):
        m = latest[n]
        v = f"{m.value:.4f}" if isinstance(m.value, float) else m.value
        p(f"  {n:22s} = {v}   [{m.status.value}, {m.basis.value}]" + (f"  -- {m.reason}" if m.reason else ""))

    def states(E, title):
        p("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)
        for ent in (A, f"task:{RUN}", f"runtime:{RUN}"):
            for v in E.query(ent):
                p(f"  {v.entity_id.split(':')[0]}.{v.name:22s} = {str(v.value):28s} {v.status.value:14s} "
                  f"{v.freshness.value:9s} [{v.rule}]")
                p(f"      why: {v.reason}")

    states(E, "3a. SEMANTIC STATE (층 3) -- 실행 중")
    # 실행 끝 요약이 오면: 같은 관측 + 요약을 새 엔진에 넣는다(요약의 시각 = 그 실행에서 본 가장 늦은 시각 -- 하한)
    E = StateEngine(CFG).ingest_all(from_telemetry(recs + [end_record(None)]))
    states(E, "3b. SEMANTIC STATE -- 실행 끝 요약이 온 뒤(비용 · 압축 문턱 · 종료가 관측됨)")

    p("\n" + "=" * 70 + "\n4. STATE GRAPH (registry 에서)\n" + "=" * 70)
    p(REGISTRY.render_graph())

    p("\n" + "=" * 70 + "\n5. QUERY (실행 끝 요약 뒤): '지금 실행 상태는?' -> execution_health · context_pressure · resource_pressure\n"
      + "=" * 70)
    for v in E.query(A, ["execution_health", "context_pressure", "resource_pressure"]):
        p(f"  {v.name} = {v.value}  (status={v.status.value}, freshness={v.freshness.value}, age_ms={v.age_ms}, "
          f"rule={v.rule}, evidence={len(v.evidence_refs)})")

    p("\n  explain(execution_health) -- 상태 -> 규칙 -> 지표 -> 관측:")
    ex = E.explain(A, "execution_health")
    p(f"    rule: {ex['rule']['id']} v{ex['rule']['version']} [{ex['rule']['basis']}]")
    for n in ex["evidence"]:
        p(f"    metric {n['name']} = {n['value']}")
        for o in n["inputs"][:4]:
            if "observation" in o:
                p(f"      <- {o['observation']} = {o['value']} (t={o['observed_at']}, {o['source']})")
    p("    transitions: " + "; ".join(f"{t.previous} -> {t.new} @ {t.at} ({t.trigger})" for t in ex["transitions"]))

    p("\n" + "=" * 70 + "\n6. MINIMAL DECISION CONTEXT\n" + "=" * 70)
    p(json.dumps(E.decision_context(RUN), ensure_ascii=False, indent=1))

    p("\n" + "=" * 70 + "\n7. LLM 제안은 상태가 되지 않는다\n" + "=" * 70)
    E.propose(A, "execution_health", "FAILING", "llm", "I think the runtime is failing")
    p(f"  proposal 보관: {len(E.proposals)} 개 · execution_health 는 그대로 "
      f"{E.query(A, ['execution_health'])[0].value}")

    p("\n" + "=" * 70 + "\n8. 45 분 뒤 같은 질의(새 관측 없음)\n" + "=" * 70)
    now = E.ledgers[RUN].last_at + 45 * 60_000
    for v in E.query(A, ["execution_health", "context_pressure"], now=now):
        p(f"  {v.name} = {v.value}  status={v.status.value}  freshness={v.freshness.value}  age_ms={v.age_ms:.0f}")
    p("  " + "; ".join(f"{e.name}: {e.event.value}" for e in E.tick({RUN: now})))

    out = "\n".join(L) + "\n"
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    Path("eval/results/state_demo.txt").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
