"""CMD-SEN1 실기록 대조: Claude Code JSONL 을 앞에서부터 잘라 **그때까지의 transcript 에서 L0 를 다시 모아** extend 에 넘긴다 --
rlo 훅이 도구 호출마다 하는 그대로다(끝나지 않은 마지막 응답의 판은 Telemetry 가 낸다). 끝에서 전체를 다시 지은 것과 견준다.

    TELEMETRY_HASH_KEY=<고정> PYTHONPATH=../Telemetry python3 eval/extend_real.py <세션.jsonl> [자를 곳 수=5] [씨앗=7]

해시 열쇠를 고정해야 모을 때마다 도구 이름 해시가 같다(기본 열쇠는 프로세스마다 무작위 -- 보고 13).
내용은 내지 않는다 -- 줄 · 사건 · 상태 수와 시간만.
"""
import json
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.run_state import from_l0  # noqa: E402
from tests.test_run_state_extend import snapshot  # noqa: E402


def main(src, n_cuts=5, seed=7):
    from telemetry import collect
    lines = Path(src).read_text(encoding="utf-8").splitlines(keepends=True)
    tmp = Path(tempfile.mkdtemp()) / "prefix.jsonl"

    def upto(n):
        tmp.write_text("".join(lines[:n]), encoding="utf-8")
        return collect.from_cc_jsonl(str(tmp), "cc_jsonl:self")

    N = len(lines)
    rnd = random.Random(seed)
    cuts = sorted(rnd.sample(range(N // 4, N - 50), n_cuts)) + [N - 3, N]
    evs_all = upto(N)
    rs = from_l0(upto(cuts[0]))
    steps = []
    for c in cuts[1:]:
        evs = upto(c)
        t = time.perf_counter()
        rs.extend(evs)
        steps.append({"lines": c, "events": len(evs), "extend_s": round(time.perf_counter() - t, 4),
                      **{k: v for k, v in rs.last_extend.items() if k != "runs"}})
    t = time.perf_counter()
    full = from_l0(evs_all)
    t_each = time.perf_counter() - t
    t = time.perf_counter()
    once = from_l0(evs_all, evaluate="once")
    t_once = time.perf_counter() - t
    a, b, c = snapshot(rs), snapshot(full), snapshot(once)
    print(json.dumps({"lines": N, "events": len(evs_all), "states": len(b), "incremental_equals_full_each": a == b,
                      "once_equals_full_each": c == b, "full_each_s": round(t_each, 2), "full_once_s": round(t_once, 3),
                      "steps": steps}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], *[int(x) for x in sys.argv[2:]])
