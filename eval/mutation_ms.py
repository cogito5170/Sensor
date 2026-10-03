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
     '    if now is None or o.time_base != "unix_ms":', '    if now is None:'),   # 창 길 · 창 없는 길이 같은 줄을 쓴다(CMD-S21)
    ('S5: 본 적 없는 행동을 0 회로 미리 채운다', 'llmsensor/sensing/l0.py',
     'st = self.state[run] = {"pending": 0, "acts": {}, "deps": {}', 'st = self.state[run] = {"pending": 0, "acts": {"compaction": 0}, "deps": {}'),
    ('S5: 행동 사건이 없으면 빈 값(0)으로', 'llmsensor/sensing/actions/__init__.py',
     'return _m(ctx, "runtime_actions", None, (), reason=', 'return _m(ctx, "runtime_actions", {}, (), reason='),
    ('S3: 선언되지 않은 상태 코드를 결함으로', 'llmsensor/sensing/l0.py',
     'if ec is not None or (sc is not None and sc >= 400) else None', 'if ec is not None or sc is not None else None'),
    ('S3: 의존 대상을 하나로 접는다(격리 없음)', 'llmsensor/sensing/l0.py',
     '        name = "probe." + str(d["target"]).lstrip("#")', '        name = "provider"'),
    # 실체 id 를 글자로 갈라 실행을 찾던 길(_run_of)은 걷었다 -- 엔진이 실체를 세울 때 실행을 기억한다(CMD-S24: 행동 id 에 ':')
    ('S3 · S24: 실체가 자기 실행을 기억하지 않는다(시계를 못 찾는다)', 'llmsensor/state/engine.py',
     '            self._ent_run[ent] = run_id', '            pass'),
    ('S21: 첫 창을 고른다', 'llmsensor/sensing/provider/__init__.py',
     '    lo = min(1 - x["utilization"] for x in ws.values())', '    lo = 1 - next(iter(ws.values()))["utilization"]'),
    ('S21: 마지막 창을 고른다', 'llmsensor/sensing/provider/__init__.py',
     '    lo = min(1 - x["utilization"] for x in ws.values())', '    lo = 1 - list(ws.values())[-1]["utilization"]'),
    ('S21: 사용률을 못 본 창을 빼고 최소', 'llmsensor/sensing/provider/__init__.py',
     '    if blind:\n        return None, blind\n', '    ws = {n: x for n, x in ws.items() if n not in blind}\n'),
    ('S21: 창 없는 보고 뒤에 낡은 창이 남는다', 'llmsensor/sensing/l0.py',
     '            if st["wins"]:', '            if False:'),
    ('S21: 같은 여유의 창들 가운데 가장 이른 재설정', 'llmsensor/sensing/provider/__init__.py',
     '        return max(rs), [w.id]', '        return min(rs), [w.id]'),
    ('S21: 창을 무시한다(v1 길만)', 'llmsensor/sensing/l0.py',
     '        if ev["type"] == "provider.rate_limit_window" and data.get("window_name") is not None:',
     '        if False:'),
    ('S21: 선언된 재설정 시각을 평가 시각이 있을 때만 낸다(BD-90 위반)', 'llmsensor/sensing/provider/__init__.py',
     '    t, refs, why, _ = _declared_reset(L)\n    if t is None:', '    t, refs, why, o = _declared_reset(L)\n    if t is None or o.time_base != "unix_ms":'),
    ('S23: tool.end 를 보지 않는다(모두 기다리는 중)', 'llmsensor/state/metrics.py',
     '        done = set(e.value["indices"]) if e is not None and e.value is not None else set()', '        done = set()'),
    ('S23: L0 없이도 기다리는 중으로 짐작', 'llmsensor/state/metrics.py',
     '        if L.run.get("l0.last_event") is None:', '        if False:'),
    ('S23: 결과를 본 호출도 기다리는 중으로 센다', 'llmsensor/state/metrics.py',
     '        wait = [t for t in blind if', '        wait = [t for t in _tool_rows(L, tool) if'),
    ('S23: 두 이유를 바꿔 단다', 'llmsensor/state/rules.py',
     '    if p == n:\n        return f"도구 호출 {n} 개가 결과를 기다리는', '    if p == 0:\n        return f"도구 호출 {n} 개가 결과를 기다리는'),
    ('S23: 근거를 가르지 않는다', 'llmsensor/state/rules.py',
     '기다리는 중이다(tool.end 가 아직 없다)", [P]', '기다리는 중이다(tool.end 가 아직 없다)", [U]'),
    ('S24: dispatch 만 있는데 COMPLETED', 'llmsensor/sensing/action_state/__init__.py',
     'return Result("STARTED", Status.INFERRED', 'return Result("COMPLETED", Status.INFERRED'),
    ('S24: is_error 를 못 봤는데 COMPLETED', 'llmsensor/sensing/action_state/__init__.py',
     '    if v["is_error"] is None:\n        return _unk(', '    if False:\n        return _unk('),
    ('S24: dispatch 없는 result 를 받아들인다', 'llmsensor/sensing/action_state/__init__.py',
     '    if not v["dispatched"]:', '    if False:'),
    ('S24: 되풀이의 result 를 첫 시도에 붙인다', 'llmsensor/sensing/l0.py',
     'a = next((x for x in reversed(attempts) if x["ref"] == ref and x["result"] is None), None)',
     'a = next((x for x in attempts if x["ref"] == ref), None)'),
    ('S24: 실행 지표가 행동을 세지 않는다', 'llmsensor/state/metrics.py',
     '    return list(L.tools) + _action_rows(L)', '    return list(L.tools)'),
    ('S24: identical_call_max 가 행동 서명을 세지 않는다', 'llmsensor/state/metrics.py',
     '    for t in _tool_rows(L, None):', '    for t in L.tools:'),
    ('S24: 행동의 실패 시각을 마지막 행동 시각으로', 'llmsensor/state/metrics.py',
     '            row["tool.is_error"] = _Ref(x["result"], x["is_error"])', '            row["tool.is_error"] = _Ref(a.id, x["is_error"])'),
    ('S25: 편의 함수가 L0 묶기를 빼먹는다', 'llmsensor/run_state.py',
     '        l0 = self._l0(None)\n', '        l0 = []\n'),
    ('S25: 편의 함수가 레코드(compat)를 빼먹는다', 'llmsensor/run_state.py',
     '        recs, _ = self._records(only_changed=False)\n', '        recs = []\n'),
    ('S25: 어댑터가 시계를 버린다(신선도를 마지막 관측에 맞춘다)', 'llmsensor/run_state.py',
     '        return now if now is not None else (self.clock() if self.clock is not None else None)', '        return now'),
    ('S25: 어댑터가 준 now 보다 시계를 앞세운다', 'llmsensor/run_state.py',
     '        return now if now is not None else (self.clock() if self.clock is not None else None)',
     '        return self.clock() if self.clock is not None else now'),
    ('SEN1: 자란 레코드를 버린다(받은 id 는 멱등으로 건너뜀)', 'llmsensor/run_state.py',
     '                    E.replace(b, evaluate=False)\n                    replaced += 1', '                    replaced += 1'),
    ('SEN1: 레코드 차례의 평가를 건너뛴다(잠금 근거 시각이 틀린다)', 'llmsensor/run_state.py',
     '            for run in sorted(touched if phase is l0 else hit):', '            for run in sorted(touched if phase is l0 else ()):'),
    ('SEN1: 바뀐 마지막 사건 앞으로 L0 묶기를 되감지 않는다', 'llmsensor/run_state.py',
     '                    self._binder.restore(run, self._snap[run][1])', '                    pass'),
    ('SEN1: 바뀐 레코드를 알아보지 못한다', 'llmsensor/run_state.py',
     '            return not only_changed or self._raw.get(rid) != (rec, at)', '            return not only_changed'),
    ('SEN1: 이력에 기대는 설정에서도 이어 받는다', 'llmsensor/run_state.py',
     '    return not cfg.min_consecutive and cfg.resource_bands is None and cfg.latency_slo is None', '    return True'),
    ('SEN1: replace 가 실행 요약 칸을 먼저 받은 레코드에 맞춘다', 'llmsensor/state/engine.py',
     'key=lambda rid: L.ordinal[rid], default=None)', 'key=lambda rid: -L.ordinal[rid], default=None)'),
    ('SEN2-D: 이어 받은 실행을 모두 그 차례의 마지막 시각에 평가한다', 'llmsensor/run_state.py',
     '                b = last.get(run) or _last_by_run(recs + l0)[run]',
     '                b = phase[-1] if phase else _last_by_run(recs + l0)[run]'),
    ('SEN2-E: 본 레코드가 사라져도 다시 짓지 않는다', 'llmsensor/run_state.py',
     '        if known - seen:', '        if False:'),
    ('S19: 결과를 못 본 도구가 있는데 NO_TOOL_RUN_YET', 'llmsensor/sensing/execution/__init__.py',
     '    if res.value == 0 and unobs.value == 0:', '    if res.value == 0:'),
    ('S19: 도구 결과가 있는데 NO_TOOL_RUN_YET', 'llmsensor/sensing/execution/__init__.py',
     '    if res.value == 0 and unobs.value == 0:', '    if unobs.value == 0:'),
    ('S22: 그 실행의 사건이 하나도 없는데 NO_TOOL_RUN_YET', 'llmsensor/sensing/execution/__init__.py',
     '        if not calls and last.value is None:', '        if False:'),
    ('S22: L0 사건만 있으면 UNKNOWN(BD-89 이전 조건 -- 모델 호출만 센다)', 'llmsensor/sensing/execution/__init__.py',
     '        if not calls and last.value is None:', '        if not calls:'),
    ('S22: 근거 시각에서 마지막 L0 사건을 뺀다', 'llmsensor/sensing/execution/__init__.py',
     '("tool_results", "tool_outcome_unobservable", "activity", "run_last_event"), basis=Basis.OBSERVED)',
     '("tool_results", "tool_outcome_unobservable", "activity"), basis=Basis.OBSERVED)'),
    ('S22: 근거 시각에서 모델 호출을 뺀다', 'llmsensor/sensing/execution/__init__.py',
     '("tool_results", "tool_outcome_unobservable", "activity", "run_last_event"), basis=Basis.OBSERVED)',
     '("tool_results", "tool_outcome_unobservable", "run_last_event"), basis=Basis.OBSERVED)'),
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
