"""execution_health 의 **첫 평가점** 값 분포 (baseline#3 CMD-S19 끝난 기준 3).

    PYTHONPATH=../Telemetry python3 eval/first_eval.py cc_jsonl <a.jsonl> ... -- cc_stream <b.stream.jsonl> ... -- sweagent <c.traj[.gz]> ...

원천 -> L0 사건 -> 꼴 v3 레코드(compat) + L0 묶기 -> 상태 (eval/l1_on_l0.py 와 같은 길). 두 순서로 넣는다:

    pipeline   eval/l1_on_l0.py 그대로 -- 레코드(인과 순서: 호출 i, 그 호출의 도구들, ...) 다음 L0 묶기
    time       묶음을 시각으로 합친 순서(같은 시각 · 시각 없음은 원래 순서 유지). SWE-agent 는 시각이 없어 pipeline 과 같다.
               인공물이 있다: tool_call 묶음 시각 = tool.start, model_call 묶음 시각 = 응답 끝 -> 도구가 부모 호출보다 앞에 설 수 있다
    seq        L0 를 **사건 순서(seq)로 흘려 넣는다**(CMD-S22) -- 실시간 흐름. 사건 n 개를 받은 뒤의 상태 = 앞 n 개 사건만으로
               지은 엔진의 상태(엔진은 레코드 id 로 멱등이라 자라는 레코드를 다시 받지 못한다 -- 그래서 접두마다 새로 짓는다).
               첫 tool.start 를 담은 접두까지만 잰다

실행마다 execution_health 의 첫 값(CREATE) · 그 평가를 일으킨 묶음의 종류 · 마지막 값, 그리고 첫 도구 레코드 전에
NO_TOOL_RUN_YET · UNKNOWN 이 몇 번 평가됐는지를 센다.
내용은 내지 않는다 -- 값 · 상태 · 수만.
"""
from __future__ import annotations

import collections
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.sensing.liveness import batches  # noqa: E402
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402

NAME = "execution_health"


def _events(source, path, run_id):
    from telemetry import collect
    fn = {"cc_jsonl": collect.from_cc_jsonl, "cc_stream": collect.from_cc_stream, "sweagent": collect.from_sweagent}[source]
    if str(path).endswith(".gz"):
        with tempfile.NamedTemporaryFile(suffix=Path(path).name[:-3], delete=False) as f, gzip.open(path, "rb") as g:
            shutil.copyfileobj(g, f)
        try:
            return fn(f.name, run_id)
        finally:
            Path(f.name).unlink()
    return fn(path, run_id)


def _key(b):
    return b.at if b.at is not None else float("inf")


def _health(evs):
    from telemetry.compat import to_sensor_records
    E = StateEngine()
    E.ingest_all(from_telemetry(to_sensor_records(evs)))
    E.ingest_all(batches(evs))
    st = next((s for (ent, n), s in E.current.items() if n == NAME and ent.startswith("agent:")), None)
    return (st.status.value, st.value) if st is not None else ("NONE", None)


def one_seq(evs, cap=400):
    evs = sorted(evs, key=lambda e: e["seq"])
    k = next((i for i, e in enumerate(evs) if e["type"] == "tool.start"), len(evs))
    seq = [_health(evs[:n]) for n in range(1, min(k + 1, len(evs), cap) + 1)]   # k+1 번째 접두가 첫 tool.start 를 담는다
    before = seq[:k]
    return {"first": seq[0], "first_kind": evs[0]["type"], "last": seq[-1], "evals": len(seq),
            "no_tool_before_first_tool": sum(v == "NO_TOOL_RUN_YET" for _, v in before),
            "unknown_before_first_tool": sum(s == "UNKNOWN" for s, _ in before)}


def one(source, path, order):
    from telemetry.compat import to_sensor_records
    run_id = f"{source}:{Path(path).name.split('.')[0]}"
    evs = _events(source, path, run_id)
    if order == "seq":
        return one_seq(evs)
    bs = from_telemetry(to_sensor_records(evs)) + list(batches(evs))
    if order == "time" and source != "sweagent":
        bs = sorted(bs, key=_key)                       # 안정 정렬 -- 같은 시각은 인과 순서 그대로
    E = StateEngine()
    seq, kinds = [], []                                 # 평가마다 execution_health 값(엔진 상태를 받은 뒤 읽는다) · 그 묶음의 종류
    for b in bs:
        E.ingest(b)
        for (ent, n), st in E.current.items():
            if n == NAME and ent.startswith("agent:"):
                seq.append((st.status.value, st.value))
                kinds.append(b.kind)
    if not seq:
        return None
    first_tool = next((i for i, k in enumerate(kinds) if k == "tool_call"), len(seq))
    before = seq[:first_tool]                           # 첫 도구 레코드 전의 평가들
    return {"first": seq[0], "first_kind": kinds[0], "last": seq[-1], "evals": len(seq),
            "no_tool_before_first_tool": sum(v == "NO_TOOL_RUN_YET" for _, v in before),
            "unknown_before_first_tool": sum(s == "UNKNOWN" for s, _ in before)}


def main(argv=None):
    a = list(argv if argv is not None else sys.argv[1:])
    groups, cur = [], None
    for x in a:
        if x == "--":
            cur = None
        elif cur is None:
            cur = (x, [])
            groups.append(cur)
        else:
            cur[1].append(x)
    out = {}
    for source, paths in groups:
        for order in ("pipeline", "time", "seq"):
            rows = [r for r in (one(source, p, order) for p in paths) if r is not None]
            fmt = lambda t: f"{t[0]} {t[1]}" if t[1] is not None else t[0]
            out[f"{source}/{order}"] = {
                "runs": len(paths), "evaluated": len(rows),
                "first": dict(collections.Counter(fmt(r["first"]) for r in rows).most_common()),
                "last": dict(collections.Counter(fmt(r["last"]) for r in rows).most_common()),
                "first_batch_kind": dict(collections.Counter(r["first_kind"] for r in rows).most_common()),
                # 첫 도구 레코드 전에 NO_TOOL_RUN_YET · UNKNOWN 이 몇 번 평가됐나 -> 실행 수
                "no_tool_evals_before_first_tool": dict(sorted(collections.Counter(
                    r["no_tool_before_first_tool"] for r in rows).items())),
                "unknown_evals_before_first_tool": dict(sorted(collections.Counter(
                    r["unknown_before_first_tool"] for r in rows).items())),
            }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
