"""CMD-SEN1 (BD-257): 이어 받기 == 전체를 다시 짓기 -- 값 · 유효성 · 근거 시각(observed_at).

무작위 사건 흐름(Telemetry Recorder 로 짓는다 -- 모형 호출 · 도구(성공 · 실패 · 결과 못 봄 · 예외) · 실행기 행동(되풀이 ref) ·
heartbeat · 차례 사건 · 요금 한도와 창 · 스냅숏 · run.end, 실행 하나나 둘)을 무작위 자리에서 자른다. 자른 앞부분마다
rlo 훅처럼 **그때까지의 전체 사건**을 extend 에 넘긴다. 마지막 사건이 llm.response 면 그 판은 '끝나지 않은' 판(같은 id,
다른 내용)이다 -- Telemetry 의 말대로 transcript 가 자라면 끝나지 않은 마지막 응답만 바뀐다. 자란 레코드(도구 결과가 다음
조각에 옴)는 자르는 자리에서 저절로 생긴다.
"""
import copy
import itertools
import random
import unittest

from llmsensor.run_state import from_l0
from llmsensor.state import DEFAULT_CONFIG
from llmsensor.telemetry.l0 import require

require()
from telemetry.hashing import Hasher  # noqa: E402
from telemetry.ledger import MemorySink  # noqa: E402
from telemetry.recorder import Recorder  # noqa: E402

T0 = 1_790_000_000_000


def stream(seed: int, n: int = 60, runs: int = 1) -> list:
    rnd = random.Random(seed)
    sink = MemorySink()
    now = [T0]

    def wall():
        now[0] += rnd.choice((500, 2_000, 30_000))
        return now[0]
    mono = itertools.count(0, 7)
    recs = [Recorder(f"r{seed}-{k}", sink, source="inproc:ms", wall=wall, mono=lambda: next(mono),
                     hasher=Hasher(b"k" * 32)) for k in range(runs)]
    calls = [0] * runs
    for _ in range(n):
        k = rnd.randrange(runs)
        rec = recs[k]
        r = rnd.random()
        if r < 0.22:
            rec.llm_response(calls[k], "anthropic", stop_reason=rnd.choice(("tool_use", "end_turn", "max_tokens")),
                             usage={"input_tokens": rnd.randint(1, 50), "output_tokens": rnd.randint(1, 900),
                                    "cache_read_input_tokens": rnd.randint(0, 90_000),
                                    "cache_creation_input_tokens": rnd.randint(0, 900)})
            calls[k] += 1
        elif r < 0.50:
            name = rnd.choice(("Bash", "Read", "Edit"))
            inp = {"command": rnd.choice(("pytest -x", "ls", "make"))} if name == "Bash" else {"file_path": rnd.choice("ab")}
            outcome = rnd.choice((True, False, False, None, "exc"))
            try:
                with rec.tool(name, inp, call_index=max(calls[k] - 1, 0)) as t:
                    if outcome == "exc":
                        raise RuntimeError("x")
                    if outcome is not None:
                        t.result(is_error=outcome, output="o" * rnd.randint(0, 40))
            except RuntimeError:
                pass
        elif r < 0.62:
            outcome = rnd.choice((True, False, None))
            with rec.action(rnd.choice(("RETURN", "RETRY")), action_ref=f"cmd-{rnd.randint(0, 3)}",
                            target=rnd.choice((None, "t1")), args=rnd.choice((None, {}, {"x": 1}))) as a:
                if outcome is not None:
                    a.result(is_error=outcome)
        elif r < 0.70:
            rec.heartbeat(rnd.choice(("w1", "w2")))
        elif r < 0.80:
            rec.emit(rnd.choice(("input.received", "turn.start", "turn.end")))
        elif r < 0.86:
            u = round(rnd.random(), 2)
            rec.emit("provider.rate_limit", utilization=u, declared_status=rnd.choice(("allowed", "allowed_warning")),
                     resets_at_ms=T0 + 3_600_000, limit_type="seven_day")
            for w in rnd.sample(("five_hour", "seven_day"), rnd.randint(0, 2)):
                rec.emit("provider.rate_limit_window", window_name=w, utilization=round(rnd.random(), 2),
                         resets_at_ms=T0 + rnd.randint(1, 9) * 3_600_000)
        elif r < 0.90:
            rec.emit("run.snapshot", cost_usd=round(rnd.random(), 4))
        elif r < 0.93:
            rec.llm_error(calls[k], "anthropic", http_status=rnd.choice((429, 500, 529)))
        else:
            rec.emit("runtime.limits", context_window=200_000, autocompact_threshold=160_000)
    if rnd.random() < 0.5:
        for rec in recs:
            rec.run_end(result_subtype="success", terminal_reason="completed", is_error=False,
                        cost_usd=round(rnd.random(), 3))
    return sink.events


def provisional(prefix: list) -> list:
    """끝나지 않은 마지막 응답: 같은 id, 다른 내용(출력 토큰 · 멈춤 사유가 아직 없다)."""
    if not prefix or prefix[-1]["type"] != "llm.response":
        return prefix
    last = copy.deepcopy(prefix[-1])
    last["data"]["output_tokens"] = 1
    last["data"]["stop_reason"] = None
    return prefix[:-1] + [last]


def snapshot(rs) -> dict:
    return {k: (st.value, st.status.value, st.observed_at) for k, st in rs.engine.current.items()}


def deep(rs) -> dict:
    """값 · 유효성 · 근거 시각에 더해 이유 글과 장부의 실행 요약 칸(L0 묶기가 쌓은 수 포함)까지 -- 겉값이 같아도 속이 틀린 것을 잡는다."""
    st = {k: (s.value, s.status.value, s.observed_at, s.reason) for k, s in rs.engine.current.items()}
    led = {run: sorted((f, repr(o.value), o.observed_at) for f, o in L.run.items()) for run, L in rs.engine.ledgers.items()}
    return {"states": st, "ledger_run": led}


class SameAsFullRebuild(unittest.TestCase):
    def _check(self, seed, runs, cfg=DEFAULT_CONFIG):
        evs = stream(seed, n=random.Random(seed).randint(20, 90), runs=runs)
        rnd = random.Random(seed * 7 + 1)
        cuts = sorted(rnd.sample(range(1, len(evs)), min(rnd.randint(1, 5), len(evs) - 1)))
        rs = from_l0(provisional(evs[:cuts[0]]), cfg)
        for c in cuts[1:] + [len(evs)]:
            rs.extend(provisional(evs[:c]) if c < len(evs) else evs)
        full = from_l0(evs, cfg)
        once = from_l0(evs, cfg, evaluate="once")
        a, b, c = snapshot(rs), snapshot(full), snapshot(once)
        self.assertEqual(a, b, f"seed {seed} cuts {cuts}")
        self.assertEqual(c, b, f"seed {seed} (once)")
        self.assertEqual(deep(rs), deep(full), f"seed {seed} cuts {cuts} (reason · ledger)")
        return rs

    def test_random_streams_one_run(self):
        for seed in range(60):
            self._check(seed, 1)

    def test_random_streams_two_runs(self):
        for seed in range(100, 130):
            self._check(seed, 2)

    def test_new_events_only_also_works(self):
        for seed in range(200, 215):
            evs = stream(seed, 70)
            cut = len(evs) // 2
            rs = from_l0(evs[:cut])
            rs.extend(evs[cut:])                                  # 본 사건 없이 새 것만
            self.assertEqual(snapshot(rs), snapshot(from_l0(evs)), seed)

    def test_reports_what_it_did(self):
        evs = stream(3, 60)
        rs = from_l0(evs[:30])
        rs.extend(evs)
        self.assertEqual(rs.last_extend["mode"], "incremental")
        self.assertGreater(rs.last_extend["new"], 0)
        rs.extend(evs)
        self.assertEqual(rs.last_extend["mode"], "unchanged")

    def test_grown_tool_record_is_replaced_not_dropped(self):
        rec_evs = stream(5, 80)
        i = next(i for i, e in enumerate(rec_evs) if e["type"] == "tool.end"
                 and e["data"].get("is_error") is not None)
        rs = from_l0(rec_evs[:i])                                 # tool.start 는 있고 tool.end 는 아직
        rs.extend(rec_evs[:i + 1])
        self.assertGreater(rs.last_extend["replaced"], 0)
        self.assertEqual(snapshot(rs), snapshot(from_l0(rec_evs[:i + 1])))

    def test_history_config_falls_back_to_rebuild(self):
        cfg = DEFAULT_CONFIG.with_(min_consecutive={"execution_health": 2})
        evs = stream(9, 60)
        rs = from_l0(evs[:30], cfg)
        rs.extend(evs)
        self.assertEqual(rs.last_extend["mode"], "rebuild:history_config")
        self.assertEqual(snapshot(rs), snapshot(from_l0(evs, cfg)))


if __name__ == "__main__":
    unittest.main()
