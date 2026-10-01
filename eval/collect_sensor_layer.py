"""수집한 원천들을 한 records.jsonl 로. run_id 앞머리가 원천 · 역할을 말한다.

    cc_jsonl_self:<세션>       이 에이전트 세션 자신(스냅숏)
    cc_stream:<과업>           claude -p 실행(도착 시각 찍은 stream-json)
    cc_jsonl_child:<과업>      같은 실행의 JSONL 기록 -- 대조에만
    sweagent:<인스턴스>        SWE-agent 추적

    python3 eval/collect_sensor_layer.py <runs 디렉터리> <self.jsonl> <sweagent trajs 디렉터리> -o records.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.telemetry.collect import from_cc_jsonl, from_cc_stream, from_sweagent  # noqa: E402
from llmsensor.telemetry.schema import check  # noqa: E402


def child_jsonl(cwd: str) -> "str | None":
    """claude 는 작업 디렉터리 경로의 영숫자 아닌 글자를 - 로 바꾼 이름 아래에 기록을 쓴다(probe0 로 확인한 꼴)."""
    import re
    key = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    hits = glob.glob(str(Path.home() / ".claude/projects" / key / "*.jsonl"))
    return hits[0] if len(hits) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("self_jsonl")
    ap.add_argument("trajs")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    recs, missing = [], []
    recs += from_cc_jsonl(a.self_jsonl, "cc_jsonl_self:" + Path(a.self_jsonl).stem[:8])
    for s in sorted(Path(a.runs).glob("*.stream.jsonl")):
        name = s.name.split(".")[0]
        recs += from_cc_stream(s, "cc_stream:" + name)
        cj = child_jsonl(str((Path(a.runs) / "work" / name).resolve()))
        if cj:
            recs += from_cc_jsonl(cj, "cc_jsonl_child:" + name)
        else:
            missing.append(name)
    for t in sorted(Path(a.trajs).glob("*.traj.gz")):
        recs += from_sweagent(t, "sweagent:" + t.name.split(".")[0])
    bad = [(r["run_id"], e) for r in recs for e in check(r)]
    with open(a.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"records": len(recs), "schema_errors": len(bad), "first_errors": bad[:5],
                      "child_jsonl_missing": missing}, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
