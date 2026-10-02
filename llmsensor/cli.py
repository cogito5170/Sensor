"""명령줄.

    python3 -m llmsensor read  <세션.jsonl> [--model m.json] [--json] [--sidechain]
    python3 -m llmsensor fit   <세션.jsonl>... -o m.json [--min-n 5]
    python3 -m llmsensor check -- <명령...>

`read` 는 **집계와 판독만** 낸다 -- 질문 · 답 · 명령의 글은 내보내지 않는다(이유 문자열에 겨냥 이름이 들어갈 수는 있다).
"""
from __future__ import annotations

import argparse
import json
import sys

from .model import PerformanceModel
from .pipeline import sense
from .sensors import ExternalOutcomeSensor
from .trace import from_claude_code

ABBR = {"OK": "ok", "SUSPECT": "?", "FAULT": "X", "UNKNOWN": "-"}
SHORT = {"execution": "exe", "constraint": "con", "consistency": "cst", "behavior": "beh", "outcome": "out"}


def _row(i, rep) -> str:
    t = rep["telemetry"]
    st = " ".join(f"{SHORT[r['sensor']]}:{ABBR[r['status']]}" for r in rep["readings"])
    v = rep["verdict"]
    return (f"#{i:<3d} T={t['T']:>10,} L={t['L']:>3d} E={t['E']:>2d} R={t['R']:>2d}  {st}  "
            f"Q={rep['fusion']['Q']:.2f}  {v['action']}(규칙 {v['rule']})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="llmsensor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("read", help="세션 JSONL 의 과업마다 센서 판독")
    a.add_argument("transcript")
    a.add_argument("--model")
    a.add_argument("--json", action="store_true")
    a.add_argument("--sidechain", action="store_true")
    f = sub.add_parser("fit", help="세션들에서 성능모형 M_P 를 짓는다")
    f.add_argument("transcripts", nargs="+")
    f.add_argument("-o", "--out", required=True)
    f.add_argument("--min-n", type=int, default=5)
    c = sub.add_parser("check", help="외부 결과 센서 하나를 돌린다")
    c.add_argument("command", nargs=argparse.REMAINDER)
    k = sub.add_parser("l0-check", help="L0 Telemetry 수집기와 이 저장소의 수집기가 같은 레코드를 내는지 맞댄다")
    k.add_argument("source", choices=("cc_jsonl", "cc_stream", "sweagent"))
    k.add_argument("path")
    ns = ap.parse_args(argv)

    if ns.cmd == "l0-check":
        from .telemetry.l0 import compare
        r = compare(ns.source, ns.path)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 2 if not r["available"] else 0 if r["same"] else 1

    if ns.cmd == "read":
        model = PerformanceModel.load(ns.model) if ns.model else None
        tasks = from_claude_code(ns.transcript, ns.sidechain)
        reps = [sense(t, model) for t in tasks]
        if ns.json:
            print(json.dumps(reps, ensure_ascii=False, indent=1))
        else:
            print(f"과업 {len(tasks)} · 성능모형 {'있음' if model else '없음(토큰 센서는 UNKNOWN)'} · "
                  f"Q 는 {'보정됨' if reps and reps[0]['fusion']['calibrated'] else '보정 전 -- 순서 점수'}")
            for i, r in enumerate(reps):
                print(_row(i, r))
                for rd in r["readings"]:
                    if rd["status"] in ("FAULT", "SUSPECT"):
                        print(f"       {rd['sensor']}: {rd['why']}")
        return 0
    if ns.cmd == "fit":
        tasks = [t for p in ns.transcripts for t in from_claude_code(p)]
        m = PerformanceModel(ns.min_n).fit_tasks(tasks)
        m.save(ns.out)
        print(f"과업 {len(tasks)} 으로 성능모형을 지었다 -> {ns.out}"
              + ("" if len(tasks) >= ns.min_n else f" (min_n={ns.min_n} 미만 -- 기대값을 못 낸다)"))
        return 0
    cmd = ns.command[1:] if ns.command[:1] == ["--"] else ns.command
    if not cmd:
        ap.error("check 뒤에 명령이 필요하다")
    r = ExternalOutcomeSensor(cmd).read()
    print(json.dumps(r.to_dict(), ensure_ascii=False, indent=1))
    return {"OK": 0, "FAULT": 1}.get(r.status, 2)


if __name__ == "__main__":
    sys.exit(main())
