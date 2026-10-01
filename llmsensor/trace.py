"""관측: 한 과업(task)의 실행 흔적.

원천 둘:
  * `from_claude_code(path)` -- Claude Code 세션 JSONL. 사람이 친 말 하나에서 다음 말까지가 과업 하나다.
  * `Recorder` -- 직접 만든 에이전트 루프에서 손으로 남긴다.

`telemetry(task)` 가 텔레메트리 벡터 x = [T, R, E, L, latency, turns] 를 낸다. 이것은 **관측량**이지 성공의
센서가 아니다 -- 1,000 토큰에 틀릴 수도, 10,000 토큰에 완벽할 수도 있다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


@dataclass
class ToolCall:
    name: str
    input: dict = field(default_factory=dict)
    ok: "bool | None" = None        # None: 결과가 안 왔다(끊김 · 기록 누락)
    output: str = ""
    id: str = ""
    t: "float | None" = None


@dataclass
class Task:
    prompt: str = ""
    cls: str = "default"            # 과업 부류. 성능모형은 부류마다 따로 기대값을 둔다
    turns: list = field(default_factory=list)    # 모형 호출마다 usage dict
    calls: list = field(default_factory=list)    # ToolCall
    answer: str = ""                # 마지막 도구 호출 뒤의 모형 글(최종 답)
    t0: "float | None" = None
    t1: "float | None" = None
    meta: dict = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return sum(sum((u.get(k) or 0) for k in USAGE_KEYS) for u in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum((u.get("output_tokens") or 0) for u in self.turns)

    @property
    def latency(self) -> "float | None":
        return None if self.t0 is None or self.t1 is None else max(0.0, self.t1 - self.t0)


def call_head(c: ToolCall) -> str:
    """재시도 판정용 거친 지문: 도구 이름 + 무엇을 겨눴나(명령의 첫 낱말 · 파일 경로)."""
    inp = c.input or {}
    if "command" in inp:
        words = str(inp["command"]).split()
        # 'cd x &&' · 'python3 -m' 같은 앞머리를 건너뛰고 실제 실행 대상을 잡는다
        skip = {"cd": 2, "timeout": 2, "&&": 1, "env": 1, "sudo": 1, "time": 1, "nohup": 1, "setsid": 1}
        while words and (words[0] in skip or "=" in words[0]):
            words = words[skip.get(words[0], 1):]
        if words[:2] in (["python3", "-m"], ["python", "-m"]):
            words = words[2:]
        return f"{c.name}:{words[0] if words else ''}"
    for k in ("file_path", "path", "url", "pattern", "query"):
        if k in inp:
            return f"{c.name}:{inp[k]}"
    return c.name


def call_sig(c: ToolCall) -> str:
    """같은 호출인가 -- 이름 + 인자 정규형."""
    return c.name + json.dumps(c.input or {}, ensure_ascii=False, sort_keys=True)


def retries(calls: "list[ToolCall]") -> int:
    """오류 뒤에, 같은 겨냥(call_head)으로 다시 부른 수. 그 사이 같은 겨냥이 성공했으면 재시도가 아니다."""
    failing, n = set(), 0
    for c in calls:
        h = call_head(c)
        if h in failing:
            n += 1
        if c.ok is False:
            failing.add(h)
        elif c.ok is True:
            failing.discard(h)
    return n


def telemetry(task: Task) -> dict:
    calls = task.calls
    return {"T": task.tokens, "T_out": task.output_tokens, "turns": len(task.turns), "L": len(calls),
            "E": sum(c.ok is False for c in calls), "R": retries(calls), "latency": task.latency,
            "missing_results": sum(c.ok is None for c in calls)}


class Recorder:
    """직접 짠 루프에서 쓴다.

        rec = Recorder("파일을 고쳐라", cls="edit")
        rec.turn(input_tokens=900, output_tokens=120)
        rec.call("Bash", {"command": "pytest -q"}, ok=False, output="1 failed")
        rec.answer("고쳤습니다")
        task = rec.done()
    """

    def __init__(self, prompt: str = "", cls: str = "default", clock=None):
        import time
        self._clock = clock or time.time
        self.task = Task(prompt=prompt, cls=cls, t0=self._clock())

    def turn(self, **usage) -> "Recorder":
        self.task.turns.append(dict(usage))
        return self

    def call(self, name: str, input: "dict | None" = None, ok: "bool | None" = None, output: str = "") -> "Recorder":
        self.task.calls.append(ToolCall(name=name, input=dict(input or {}), ok=ok, output=output, t=self._clock()))
        self.task.answer = ""
        return self

    def answer(self, text: str) -> "Recorder":
        self.task.answer = (self.task.answer + "\n" + text).strip()
        return self

    def done(self) -> Task:
        self.task.t1 = self._clock()
        return self.task


# ---- Claude Code 세션 JSONL ----

def _ts(s) -> "float | None":
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _is_human(d: dict, content) -> bool:
    """사람이 친 말인가 -- 도구 결과 · 훅 · 시스템 주입(`<...>` 로 시작)이 아니어야 한다."""
    if d.get("isMeta"):
        return False
    if isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
        return False
    txt = _text_of(content).strip()
    return bool(txt) and not txt.startswith("<") and "Stop hook feedback" not in txt


def from_claude_code(path: "str | Path", sidechain: bool = False, cls_of=None) -> "list[Task]":
    """세션 JSONL -> 과업 목록. 같은 message.id 의 줄은 한 모형 호출의 조각이다(usage 는 마지막 것).
    cls_of(prompt) -> str 를 주면 과업 부류를 붙인다."""
    tasks: "list[Task]" = []
    cur: "Task | None" = None
    usage_by_id: dict = {}
    by_tool_id: dict = {}
    tail: list = []                 # 마지막 도구 호출 뒤의 글 조각

    def close():
        if cur is not None:
            cur.turns = list(usage_by_id.values())
            cur.answer = "\n".join(tail).strip()

    with Path(path).open(encoding="utf-8") as fh:
        lines = list(fh)
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = d.get("message")
        if not isinstance(m, dict) or (d.get("isSidechain") and not sidechain):
            continue
        t = _ts(d.get("timestamp"))
        content = m.get("content")
        if d.get("type") == "user":
            if _is_human(d, content):
                close()
                prompt = _text_of(content).strip()
                cur = Task(prompt=prompt, cls=cls_of(prompt) if cls_of else "default", t0=t, t1=t)
                tasks.append(cur)
                usage_by_id, by_tool_id, tail = {}, {}, []
                continue
            if cur is None or not isinstance(content, list):
                continue
            for x in content:
                if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("tool_use_id") in by_tool_id:
                    c = by_tool_id[x["tool_use_id"]]
                    c.ok = not bool(x.get("is_error"))
                    out = x.get("content")
                    c.output = out if isinstance(out, str) else _text_of(out)
            if t:
                cur.t1 = t
        elif d.get("type") == "assistant" and cur is not None:
            if m.get("usage"):
                usage_by_id[m.get("id") or len(usage_by_id)] = dict(m["usage"])
            for x in content if isinstance(content, list) else []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "tool_use":
                    c = ToolCall(name=x.get("name", ""), input=x.get("input") or {}, id=x.get("id", ""), t=t)
                    cur.calls.append(c)
                    by_tool_id[c.id] = c
                    tail = []
                elif x.get("type") == "text" and x.get("text", "").strip():
                    tail.append(x["text"])
            if t:
                cur.t1 = t
    close()
    return tasks

