"""실행 센서 -- 명령이 돌았나 · API 가 성공했나 · 쓴다던 파일이 있나.

겨냥(call_head)마다 **마지막** 호출의 결과를 본다. 중간에 실패했다가 같은 겨냥이 나중에 성공했으면 풀린 것이다.
마지막이 실패로 남은 겨냥이 있으면 FAULT.

**한계:** 탐색용 명령(grep 이 못 찾음 · ls 가 없는 파일)의 실패는 과업 실패가 아니다. 그래서 `ignore` 의 겨냥은
세지 않는다. 그 밖의 '실패해도 되는' 호출은 이 센서가 구분 못 한다 -- 거짓 FAULT 의 주된 길이다.
도구가 실패를 성공으로 보고하는 것(exit 0 인데 아무것도 안 함)은 못 잡는다. 그것은 외부 결과 센서의 몫이다.
"""
from __future__ import annotations

import os

from ..reading import Reading, OK, SUSPECT, FAULT, UNKNOWN
from ..trace import Task, call_head

EXPLORE = ("Bash:grep", "Bash:rg", "Bash:ls", "Bash:cat", "Bash:find", "Bash:head", "Bash:tail", "Bash:test",
           "Bash:which", "Bash:[", "Bash:diff", "Bash:pgrep", "Bash:stat", "Bash:wc")
EXPLORE_TOOLS = ("Read", "Glob", "Grep", "WebFetch", "WebSearch", "ToolSearch")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


class ExecutionSensor:
    name = "execution"

    def __init__(self, ignore=EXPLORE, ignore_tools=EXPLORE_TOOLS, check_files: bool = False):
        self.ignore = set(ignore)
        self.ignore_tools = set(ignore_tools)
        self.check_files = check_files

    def _counted(self, c) -> bool:
        return c.name not in self.ignore_tools and call_head(c) not in self.ignore

    def read(self, task: Task) -> Reading:
        calls = [c for c in task.calls if self._counted(c)]
        if not calls:
            return Reading(self.name, UNKNOWN, "실행할 도구 호출이 없다 -- 실행 증거 없음",
                           detail={"calls": len(task.calls), "counted": 0})
        last: dict = {}
        for c in calls:
            last[call_head(c)] = c
        unresolved = sorted(h for h, c in last.items() if c.ok is False)
        missing = sorted(h for h, c in last.items() if c.ok is None)
        gone = []
        if self.check_files:
            for c in calls:
                p = (c.input or {}).get("file_path")
                if c.name in WRITE_TOOLS and c.ok and p and not os.path.exists(p):
                    gone.append(p)
        det = {"calls": len(task.calls), "counted": len(calls), "targets": len(last),
               "errors": sum(c.ok is False for c in calls), "unresolved": unresolved, "no_result": missing,
               "written_but_missing": sorted(set(gone))}
        frac = len(unresolved) / len(last)
        if unresolved or gone:
            why = []
            if unresolved:
                why.append(f"마지막 호출이 실패로 남은 겨냥 {len(unresolved)}/{len(last)}")
            if gone:
                why.append(f"썼다는데 없는 파일 {len(set(gone))}")
            return Reading(self.name, FAULT, " · ".join(why), frac, det)
        if missing:
            return Reading(self.name, SUSPECT, f"결과가 안 온 호출 {len(missing)} -- 끊겼거나 기록 누락", frac, det)
        return Reading(self.name, OK, f"겨냥 {len(last)} 개의 마지막 호출이 전부 성공", 0.0, det)
