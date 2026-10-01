"""SWE-agent `.traj` -> Task.

SWE-agent 추적에는 **종료 코드가 없다.** 그래서 호출의 성공 여부(ok)를 관측 글에서 추정한다 -- ERR 정규식.
이것은 어댑터의 추정이지 관측이 아니다. 재현 스크립트가 일부러 낸 오류(버그 재현)도 실패로 읽힌다.

    걸음 하나        -> ToolCall("Bash", {"command": action}, ok=ERR 없음, output=observation)
    마지막 걸음의 생각 -> answer (제출하며 남긴 말)
    첫 사람 말(이슈)  -> prompt
    model_stats      -> turns = [{input_tokens: tokens_sent, output_tokens: tokens_received}]
    인스턴스의 저장소 -> cls  (성능모형이 저장소마다 기대값을 둔다)
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

from ..trace import Task, ToolCall

ERR = re.compile(r"Traceback \(most recent call last\)|\b\w*Error:|command not found|No such file or directory|"
                 r"Your proposed edit has introduced new syntax error|^usage: ", re.M)


def _load(path):
    p = Path(path)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def _repo(instance_id: str) -> str:
    return instance_id.split("__")[0]


def from_sweagent(path, instance_id: "str | None" = None) -> Task:
    d = _load(path)
    iid = instance_id or Path(path).name.split(".")[0]
    steps = d.get("trajectory") or []
    calls = [ToolCall("Bash", {"command": s.get("action") or ""}, not ERR.search(s.get("observation") or ""),
                      s.get("observation") or "") for s in steps]
    hist = [h for h in d.get("history") or [] if not h.get("is_demo")]
    users = [h.get("content") for h in hist if h.get("role") == "user"]
    prompt = users[0] if users and isinstance(users[0], str) else ""
    ms = (d.get("info") or {}).get("model_stats") or {}
    turns = [{"input_tokens": ms.get("tokens_sent") or 0, "output_tokens": ms.get("tokens_received") or 0}]
    answer = (steps[-1].get("thought") or "") if steps else ""
    info = d.get("info") or {}
    return Task(prompt=prompt, cls=_repo(iid), turns=turns, calls=calls, answer=answer,
                meta={"instance_id": iid, "exit_status": info.get("exit_status"),
                      "api_calls": ms.get("api_calls"), "patch_chars": len(info.get("submission") or "")})
