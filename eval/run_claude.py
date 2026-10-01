"""claude -p 를 돌리며 stdout 의 줄마다 **도착 시각**(단조 ms)을 찍어 남긴다.

    python3 eval/run_claude.py <작업이름> <출력 디렉터리>

stream-json 의 stream_event 에는 런타임 시각이 없다. 수집기가 받은 시각이 그 사건의 유일한 시간 관측이다
(파이프 지연이 섞인다 -- 서버 시각이 아니다).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.sensor_tasks import TASKS  # noqa: E402

MODEL = "claude-haiku-4-5"
TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]


def run(name: str, out: Path) -> dict:
    task = TASKS[name]
    work = out / "work" / name
    work.mkdir(parents=True, exist_ok=True)
    task["seed"](work)
    cmd = ["claude", "-p", task["prompt"], "--model", MODEL, "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--max-turns", str(task.get("max_turns", 20)), "--allowedTools", *TOOLS]
    path = out / f"{name}.stream.jsonl"
    t0 = time.monotonic()
    with open(path, "w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             text=True, bufsize=1)
        try:
            for line in p.stdout:
                t = (time.monotonic() - t0) * 1000
                try:
                    f.write(json.dumps({"_t": round(t, 3), "line": json.loads(line)}, ensure_ascii=False) + "\n")
                except json.JSONDecodeError:
                    f.write(json.dumps({"_t": round(t, 3), "raw": line.rstrip()}, ensure_ascii=False) + "\n")
            p.wait(timeout=task.get("timeout", 400))
        except subprocess.TimeoutExpired:
            p.kill()
    return {"task": name, "returncode": p.returncode, "seconds": round(time.monotonic() - t0, 1), "cwd": str(work)}


if __name__ == "__main__":
    names = sys.argv[2:] or list(TASKS)
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for n in names:
        r = run(n, out)
        print(json.dumps(r, ensure_ascii=False), flush=True)
