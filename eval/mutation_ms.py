"""MS 센싱의 원칙을 하나씩 깨뜨려 시험이 빨개지는지 본다(과제 §18 Mutation coverage).

결정 문맥 · 참조 정책의 변이는 그 코드와 함께 cogito5170/DC 로 옮겼다(baseline PC-08) -- DC 는 자기 변이를 따로 돌린다.

    python3 eval/mutation_ms.py [--out eval/results/mutation_ms.json]
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = [
    ("latency: 표본이 모자라도 백분위를 낸다", "llmsensor/sensing/_base.py",
     "    if len(xs) < min_samples(p):\n        return None", "    if not xs:\n        return None"),
    ("latency: SLO 없이 NORMAL 을 지어낸다", "llmsensor/sensing/latency/__init__.py",
     'return Result(None, Status.NOT_APPLICABLE, "지연 SLO 가 설정되지 않았다', 'return Result("NORMAL", Status.INFERRED, "지연 SLO 가 설정되지 않았다'),
    ("provider: 모르는 런타임 상태를 WARNING 으로 짐작", "llmsensor/sensing/provider/__init__.py",
     "        hit = table.get(dec.value[\"status\"])", "        hit = table.get(dec.value[\"status\"], \"WARNING\")"),
    ("provider: 429 를 무시", "llmsensor/sensing/provider/__init__.py",
     'LIMIT_ERRORS = {"429", "RATE_LIMITED"}', 'LIMIT_ERRORS = set()'),
    ("provider 어댑터: 출처 없는 OpenAI 503 대응", "llmsensor/providers/openai.py",
     "K.RATE_LIMITED if status == 429 else K.UNKNOWN", "K.RATE_LIMITED if status == 429 else K.UNAVAILABLE"),
    ("cost: 표에 없는 모형을 haiku 값으로 짐작", "llmsensor/sensing/cost/pricing.py",
     "    return (m, PRICES[m]) if m in PRICES else None", "    return (m, PRICES.get(m, PRICES[\"claude-haiku-4-5\"]))"),
    ("cost: 계산 못 하는 호출을 건너뛰고 부분 합", "llmsensor/sensing/cost/__init__.py",
     "        if v is None:\n            return _m(ctx, \"cost_estimate\", None, i, Basis.PROVIDER_DECLARED,",
     "        if v is None:\n            continue\n            return _m(ctx, \"cost_estimate\", None, i, Basis.PROVIDER_DECLARED,"),
    ("quality: 라벨 없음을 FAILED 로", "llmsensor/sensing/quality/__init__.py",
     '        return _unk("외부 평가가 없다 -- 품질 점수를 만들지 않는다", ["external_outcome"])',
     '        return _inf("FAILED", "x", ["external_outcome"])'),
    ("execution: 판정 근거 없이 NONE_OBSERVED", "llmsensor/sensing/execution/__init__.py",
     '    return _unk("시간 초과 · 중단을 판정할 수 있는 도구 결과가 없다", ["tool_timeouts", "tool_interruptions"])',
     '    return _inf("NONE_OBSERVED", "x", ["tool_timeouts"])'),
    # (옮김) '수집기: 스트림의 캐시 쓰기 나눔을 버린다' -- 수집기가 Telemetry 로 옮겨 가(CMD-T9) 같은 변이도 그쪽 하니스에 있다.
    # Sensor 에는 그 코드가 없어 NOT_APPLIED 였다(baseline#3 CMD-S13)
    ('liveness: 운영자 timeout 없이 문턱을 지어낸다', 'llmsensor/sensing/liveness/__init__.py',
     '    timeout = cfg.liveness_timeout_ms\n', '    timeout = cfg.liveness_timeout_ms or 30_000\n'),
    ('liveness: 차례를 모르면 입력 대기로 짐작', 'llmsensor/sensing/liveness/__init__.py',
     '    if turn.value is None:\n        return _unk(', '    if turn.value is None:\n        return _res("AWAITING_INPUT", "x", ["turn_open"])\n        return _unk('),
    ('liveness: 런타임 heartbeat 를 무음으로 센다', 'llmsensor/sensing/liveness/__init__.py',
     '(_ev(L, "l0.last_event"), _ev(L, "l0.heartbeat"))', '(_ev(L, "l0.last_event"),)'),
    ('liveness: 차례 밖 공백(사람 대기)을 멈춤으로', 'llmsensor/sensing/liveness/__init__.py',
     '    if turn.value is False:\n', '    if False:\n'),
    ('liveness: 종료 사건 없이 닫힌 흐름을 ENDED 로', 'llmsensor/sensing/liveness/__init__.py',
     '        return _res("ENDED_WITHOUT_TERMINAL",', '        return _res("ENDED",'),
    ('liveness: 전부 null 인 종료 요약을 끝으로', 'llmsensor/sensing/liveness/__init__.py',
     '    declared = {k: v for k, v in (term.value or {}).items() if v is not None}', '    declared = term.value'),
    ('liveness: 시간 기준이 섞인 시각을 뺀다', 'llmsensor/sensing/liveness/__init__.py',
     '    if len(bases) > 1:', '    if False:'),
    ('liveness: 센서가 시계를 읽는다', 'llmsensor/sensing/liveness/__init__.py',
     '    now = ctx.get("now")\n', '    now = __import__("time").time() * 1000\n'),
    ('liveness: 평가 순간의 값(ACTIVE)을 뒤 시각에 지금 값으로', 'llmsensor/state/engine.py',
     '            fr = Freshness.STALE              # 그 값은', '            pass  # fr = Freshness.STALE              # 그 값은'),
    ('liveness: 차례 끝을 안 내는 원천(cc_jsonl 훅 없음)에서 열림으로 짐작', 'llmsensor/sensing/liveness/__init__.py',
     '    if end is None and src not in ENDS_ALWAYS:', '    if False:'),
    ('liveness: turn.continued 를 차례 끝으로', 'llmsensor/sensing/l0.py',
     '    "turn.continued": ("l0.turn_continued", Basis.OBSERVED),', '    "turn.continued": ("l0.turn_end", Basis.OBSERVED),'),
    ('liveness: turn.end 를 보지 않고 차례가 돈다고', 'llmsensor/sensing/liveness/__init__.py',
     '    running = start is not None and (end is None or start.value["seq"] > end.value["seq"])', '    running = start is not None'),
    ('liveness: input.removed(흡수 · 취소)를 무시한다', 'llmsensor/sensing/l0.py',
     'max(0, n - 1) if ev["type"] == "input.removed"', 'n if ev["type"] == "input.removed"'),
    ('cost v2: 예산 없음을 UNKNOWN 으로(BD-39 위반)', 'llmsensor/sensing/cost/__init__.py',
     'return Result(None, Status.NOT_APPLICABLE, "예산이 설정되지 않았다", ("cost_bounds",))', 'return _unk("예산이 설정되지 않았다", ["cost_bounds"])'),
    ('cost v2: 단가 없는 호출을 빼고 부분 합으로 WITHIN', 'llmsensor/sensing/cost/__init__.py',
     '    elif L.calls and unpriced == 0:\n', '    elif L.calls:\n'),
    ('cost v2: 단가 없는 호출이 있으면 소진도 증명하지 않는다', 'llmsensor/sensing/cost/__init__.py',
     '        lower = max(x for x in (rv, est if priced else None, 0.0) if x is not None)', '        lower = rv if rv is not None else (est if unpriced == 0 else 0.0)'),
    ('cost v2: 중간 스냅숏 보고가 모든 호출을 덮는다고 짐작', 'llmsensor/sensing/cost/__init__.py',
     '            covers = all(t is not None and t <= snap.value for t in ts)', '            covers = True'),
    ('cost v2: 덮는 보고를 두고 추정이 이긴다', 'llmsensor/sensing/cost/__init__.py',
     '        total, source = rv, "reported"', '        total, source = (est, "estimate") if (L.calls and unpriced == 0) else (rv, "reported")'),
    ('cost v3: 보고된 소진을 영구로 두지 않는다', 'llmsensor/sensing/cost/__init__.py',
     '["cost_bounds"],\n                    final=True)', '["cost_bounds"])'),
    ('cost v3: 추정 소진을 영구로(BD-64 위반)', 'llmsensor/sensing/cost/__init__.py',
     '["cost_bounds"])\n    if v["total"] is not None:', '["cost_bounds"], final=True)\n    if v["total"] is not None:'),
    ('cost v2: 단가표 판본을 근거에서 뺀다', 'llmsensor/sensing/cost/__init__.py',
     '"pricing": pricing.VERSION}', '"pricing": None}'),
    ('BD-57: 값을 정한 근거 중 가장 늦은 시각을 쓴다', 'llmsensor/state/engine.py',
     '        return min(ts) if ts else None', '        return max(ts) if ts else None'),
    ('BD-57: 미해결 실패의 시각 대신 모든 근거의 가장 늦은 시각', 'llmsensor/state/rules.py',
     '[prefix + "tool_targets", prefix + "tool_failure_rate"], decided_by=tg.inputs[:nu])', '[prefix + "tool_targets", prefix + "tool_failure_rate"])'),
    ('S2: 처분을 모르면 백그라운드로 짐작', 'llmsensor/sensing/l0.py',
     '            c["unknown" if m is None else "backgrounded" if m else "killed"] += 1', '            c["backgrounded" if m is None or m else "killed"] += 1'),
    ('S2: 두 길의 시간 초과 수가 어긋나도 L0 처분을 쓴다', 'llmsensor/sensing/execution/__init__.py',
     '        if l0.value["timeouts"] == len(hit):', '        if True:'),
    ('S2: 섞인 처분을 하나로 접는다', 'llmsensor/sensing/execution/__init__.py',
     'val = ("TIMEOUT_BACKGROUNDED" if v.get("backgrounded") == n', 'val = ("TIMEOUT_BACKGROUNDED" if v.get("backgrounded")'),
    ('S4: 런타임이 선언한 거절을 무시', 'llmsensor/sensing/provider/__init__.py',
     'DECLARED_STATUS_V3 = {**DECLARED_STATUS, "rejected": "LIMITED"}', 'DECLARED_STATUS_V3 = dict(DECLARED_STATUS)'),
    ('S4: 사용률을 모르면 여유를 1.0 으로', 'llmsensor/sensing/provider/__init__.py',
     'return _m(ctx, "quota_headroom", None, (), reason=', 'return _m(ctx, "quota_headroom", 1.0, (), reason='),
    ('S4: 시간 기준이 다른 시각에서 뺀다', 'llmsensor/sensing/provider/__init__.py',
     '    if now is None or r.time_base != "unix_ms":', '    if now is None:'),
    ('S5: 본 적 없는 행동을 0 회로 미리 채운다', 'llmsensor/sensing/l0.py',
     '        a = _action(acts.setdefault(run, {}), ev)', '        a = _action(acts.setdefault(run, {"compaction": 0}), ev)'),
    ('S5: 행동 사건이 없으면 빈 값(0)으로', 'llmsensor/sensing/actions/__init__.py',
     'return _m(ctx, "runtime_actions", None, (), reason=', 'return _m(ctx, "runtime_actions", {}, (), reason='),
    ('S3: 선언되지 않은 상태 코드를 결함으로', 'llmsensor/sensing/l0.py',
     'if ec is not None or (sc is not None and sc >= 400) else None', 'if ec is not None or sc is not None else None'),
    ('S3: 의존 대상을 하나로 접는다(격리 없음)', 'llmsensor/sensing/l0.py',
     '        name = "probe." + str(d["target"]).lstrip("#")', '        name = "provider"'),
    ('S3: 의존 실체가 자기 실행의 시계를 못 찾는다', 'llmsensor/state/engine.py',
     'ent.startswith(("tool:", "dependency:"))', 'ent.startswith("tool:")'),
    ('S19: 결과를 못 본 도구가 있는데 NO_TOOL_RUN_YET', 'llmsensor/sensing/execution/__init__.py',
     '    if res.value == 0 and unobs.value == 0:', '    if res.value == 0:'),
    ('S19: 도구 결과가 있는데 NO_TOOL_RUN_YET', 'llmsensor/sensing/execution/__init__.py',
     '    if res.value == 0 and unobs.value == 0:', '    if unobs.value == 0:'),
    ('S19: 모델 호출도 못 봤는데 NO_TOOL_RUN_YET', 'llmsensor/sensing/execution/__init__.py',
     '        if not calls:\n', '        if False:\n'),
    ('S19: 없음의 주장에서 마지막 관측을 뺀다(시각 없음)', 'llmsensor/sensing/execution/__init__.py',
     '("tool_results", "tool_outcome_unobservable", "activity"), basis=Basis.OBSERVED,\n                      decided_by=tuple(act.inputs))',
     '("tool_results", "tool_outcome_unobservable"), basis=Basis.OBSERVED)'),
]


def run_tests():
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=ROOT,
                          capture_output=True, text=True).returncode


def main():
    out = []
    assert run_tests() == 0, "고치기 전에 시험이 초록이어야 한다"
    for name, f, a, b in M:
        p = ROOT / f
        src = p.read_text(encoding="utf-8")
        if a not in src:
            out.append({"mutation": name, "result": "NOT_APPLIED"})
            continue
        p.write_text(src.replace(a, b, 1), encoding="utf-8")
        try:
            rc = run_tests()
        finally:
            p.write_text(src, encoding="utf-8")
        out.append({"mutation": name, "file": f, "result": "RED" if rc else "GREEN"})
    out_path = ROOT / (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "eval/results/mutation_ms.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in out:
        print(f"{r['result']:12s} {r['mutation']}")
    bad = [r for r in out if r["result"] != "RED"]
    if bad:     # NOT_APPLIED 도 실패다 -- 변이가 겨눈 코드가 사라졌다는 뜻이고, 그 원칙은 이제 아무도 붙들지 않는다
        print(f"실패: RED 가 아닌 변이 {len(bad)} 개 -- " + ", ".join(f"{r['mutation']}({r['result']})" for r in bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
