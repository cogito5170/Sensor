"""MS 센싱 · 결정 문맥의 원칙을 하나씩 깨뜨려 시험이 빨개지는지 본다(과제 §18 Mutation coverage).

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
     "        hit = DECLARED_STATUS.get(dec.value[\"status\"])", "        hit = DECLARED_STATUS.get(dec.value[\"status\"], \"WARNING\")"),
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
    ("DC: N/A 선택 상태를 거르지 않는다", "llmsensor/decision/context/__init__.py",
     "            if sv.status is Status.NOT_APPLICABLE and not need.required:  # Filter",
     "            if False:  # Filter"),
    ("DC: STALE 을 쓸 수 있다고 한다", "llmsensor/decision/context/__init__.py",
     "            usable = sv.status.usable and sv.freshness is not Freshness.STALE    # Validate",
     "            usable = sv.status.usable or sv.freshness is Freshness.STALE    # Validate"),
    ("DC: 전제 조건 없이 모든 행동을 가능하다고", "llmsensor/decision/context/__init__.py",
     "        if a == \"COMPACT_CONTEXT\" and not capabilities.get(\"compaction\", False):",
     "        if False:"),
    ("DC: 목표를 제약으로 받는다", "llmsensor/decision/context/__init__.py",
     "            if k not in CONSTRAINT_KEYS:\n                raise ValueError", "            if False:\n                raise ValueError"),
    ("DC: 이유 문자열(원 수치)을 넣는다", "llmsensor/decision/context/__init__.py",
     "                ent, need.state, sv.value, sv.status.value,", "                ent, need.state, sv.reason, sv.status.value,"),
    ("DC: 얼린 뒤 저장소를 따라 바뀐다(상태를 살아 있는 참조로)", "llmsensor/decision/context/__init__.py",
     "    def explain(self) -> dict:\n        return json.loads(self._provenance)",
     "    def explain(self) -> dict:\n        import random\n        return {'x': random.random()}"),
    ("정책: 모르는 맥락 압력으로 맥락을 줄인다", "llmsensor/policy/context.py",
     '        return Decision(NAME, ctx.context_id, _pick(ctx, "KEEP_CONTEXT"),\n                        "맥락 압력을 모른다',
     '        return Decision(NAME, ctx.context_id, _pick(ctx, "REDUCE_CONTEXT"),\n                        "맥락 압력을 모른다'),
    ("정책: 가능하지 않은 행동을 고른다", "llmsensor/policy/__init__.py",
     "    return next((a for a in prefs if a in ctx.available_actions), None)", "    return prefs[0]"),
    ("수집기: 스트림의 캐시 쓰기 나눔을 버린다", "llmsensor/telemetry/collect.py",
     "                        merged = dict(c.get(\"_start_usage\") or {})", "                        merged = {}"),
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
    return 0 if all(r["result"] == "RED" for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
