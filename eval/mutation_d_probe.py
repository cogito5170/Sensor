"""CMD-SEN2 탐침: 변이 D(extend 가 이어 받은 실행을 모두 그 차례의 마지막 시각에 평가)가 값을 바꿀 수 있는가.

두 실행이 섞인 무작위 흐름(tests/test_run_state_extend.stream, runs=2)을 끊어 넣으며 extend 하고, 끝에서 전체를 다시 지은 것과
견준다 -- 바른 코드와 변이 D 를 심은 코드 각각, 기본 설정과 평가 시각을 읽는 설정(liveness_timeout_ms) 각각.

    PYTHONPATH=../Telemetry python3 eval/mutation_d_probe.py [--out eval/results/mutation_d_probe.json]

내용은 내지 않는다 -- 흐름 수와 다른 흐름 수만.
"""
import json
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llmsensor import run_state  # noqa: E402
from llmsensor.state import DEFAULT_CONFIG  # noqa: E402
from tests.test_run_state_extend import deep, provisional, stream  # noqa: E402

ORIG = '                b = last.get(run) or _last_by_run(recs + l0)[run]'
MUT = '                b = phase[-1] if phase else _last_by_run(recs + l0)[run]'
SEEDS = range(300, 500)


def mutated():
    src = Path(run_state.__file__).read_text(encoding="utf-8")
    assert src.count(ORIG) == 1, "변이 D 가 겨눈 줄이 없다"
    m = types.ModuleType("run_state_mut_d")
    m.__file__, m.__package__ = run_state.__file__, "llmsensor"
    exec(compile(src.replace(ORIG, MUT), run_state.__file__, "exec"), m.__dict__)
    return m


def differs(mod, cfg, seed):
    evs = stream(seed, n=random.Random(seed).randint(20, 90), runs=2)
    rnd = random.Random(seed * 7 + 1)
    cuts = sorted(rnd.sample(range(1, len(evs)), min(rnd.randint(1, 5), len(evs) - 1)))
    rs = mod.from_l0(provisional(evs[:cuts[0]]), cfg)
    for c in cuts[1:] + [len(evs)]:
        rs.extend(provisional(evs[:c]) if c < len(evs) else evs)
    a, b = deep(rs)["states"], deep(run_state.from_l0(evs, cfg))["states"]
    keys = a.keys() | b.keys()
    any_diff = any(a.get(k) != b.get(k) for k in keys)
    value_diff = any((a.get(k) or (None,) * 4)[:3] != (b.get(k) or (None,) * 4)[:3] for k in keys)
    return any_diff, value_diff


def main():
    out = ROOT / (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "eval/results/mutation_d_probe.json")
    mods = {"correct": run_state, "mutation_d": mutated()}
    cfgs = {"default": DEFAULT_CONFIG, "liveness_timeout_ms=60000": DEFAULT_CONFIG.with_(liveness_timeout_ms=60_000)}
    res = {"streams": len(SEEDS), "seeds": [SEEDS.start, SEEDS.stop - 1], "runs_per_stream": 2, "cells": []}
    for cn, cfg in cfgs.items():
        for mn, mod in mods.items():
            d = [differs(mod, cfg, s) for s in SEEDS]
            cell = {"config": cn, "code": mn, "streams_differing_any": sum(x for x, _ in d),
                    "streams_differing_value_status_time": sum(y for _, y in d)}
            res["cells"].append(cell)
            print(cell)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("->", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
