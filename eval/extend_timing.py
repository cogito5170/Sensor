"""CMD-SEN1 끝난 기준(시간): 합성 사건 흐름에서 마지막 10 사건을 이어 받는 값 대 전체를 다시 짓는 값.

    PYTHONPATH=../Telemetry python3 eval/extend_timing.py [사건 수=2000] [이어 받을 수=10]

사건은 tests/test_run_state_extend.py 의 생성기로 짓는다(Telemetry Recorder). 잰다:
    full_each   from_l0(전체)                        -- 지금까지의 길(묶음마다 평가)
    full_once   from_l0(전체, evaluate="once")       -- 실행마다 한 번 평가
    extend      from_l0(앞 n-k) 뒤 extend(전체)       -- rlo 훅처럼 전체 사건 목록을 넘긴다. 이 호출만 잰다
    extend_new  같은 것을 새 k 사건만 넘겨서
세 가지가 같은 상태(값 · 유효성 · 근거 시각)를 내는지도 본다.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.run_state import from_l0  # noqa: E402
from tests.test_run_state_extend import snapshot, stream  # noqa: E402


def timed(fn):
    t = time.perf_counter()
    r = fn()
    return r, time.perf_counter() - t


def main(n=2000, k=10, seed=11):
    evs = stream(seed, n)[:n]                    # 생성기는 사건을 넉넉히 낸다 -- 정확히 n 개로 자른다
    full, t_each = timed(lambda: from_l0(evs))
    once, t_once = timed(lambda: from_l0(evs, evaluate="once"))
    rs = from_l0(evs[:-k])
    _, t_ext = timed(lambda: rs.extend(evs))
    rs2 = from_l0(evs[:-k])
    _, t_new = timed(lambda: rs2.extend(evs[-k:]))
    same = snapshot(rs) == snapshot(full) == snapshot(once) == snapshot(rs2)
    out = {"events": len(evs), "extended": k, "same_states": same, "states": len(full.engine.current),
           "seconds": {"full_each": round(t_each, 3), "full_once": round(t_once, 3), "extend": round(t_ext, 4),
                       "extend_new_only": round(t_new, 4)},
           "extend_over_full_each": round(t_ext / t_each, 5), "extend_over_full_once": round(t_ext / t_once, 4),
           "last_extend": rs.last_extend}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]]
    main(*a)
