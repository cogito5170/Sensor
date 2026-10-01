"""시험용 과업 · 세션 JSONL 짓기."""
import json

from llmsensor import Task, ToolCall


def task(calls=(), answer="", prompt="일을 해라", tokens=(1000,), cls="default", t0=0.0, t1=10.0):
    return Task(prompt=prompt, cls=cls, turns=[{"input_tokens": t} for t in tokens],
                calls=[c if isinstance(c, ToolCall) else ToolCall(*c) for c in calls], answer=answer, t0=t0, t1=t1)


def bash(cmd, ok=True, out=""):
    return ToolCall("Bash", {"command": cmd}, ok, out)


def write_session(path, turns):
    """turns: [("user", text) | ("tool", name, input, ok, output) | ("text", s) | ("sys", text) | ("side", text)]"""
    lines, n, t = [], 0, 0

    def ts():
        nonlocal t
        t += 1
        return f"2026-10-01T00:00:{t:02d}Z"

    for x in turns:
        n += 1
        if x[0] in ("user", "sys"):
            lines.append({"type": "user", "timestamp": ts(), "message": {"role": "user", "content": x[1]}})
        elif x[0] == "side":
            lines.append({"type": "user", "isSidechain": True, "timestamp": ts(),
                          "message": {"role": "user", "content": x[1]}})
        elif x[0] == "text":
            mid = f"m{n}"
            # 한 모형 호출이 두 줄로 쪼개져 온다 -- usage 는 같은 id 에 두 번
            lines.append({"type": "assistant", "timestamp": ts(), "message": {
                "id": mid, "usage": {"input_tokens": 100, "output_tokens": 5}, "content": [{"type": "thinking"}]}})
            lines.append({"type": "assistant", "timestamp": ts(), "message": {
                "id": mid, "usage": {"input_tokens": 100, "output_tokens": 20},
                "content": [{"type": "text", "text": x[1]}]}})
        else:
            _, name, inp, ok, out = x
            tid = f"tu{n}"
            lines.append({"type": "assistant", "timestamp": ts(), "message": {
                "id": f"m{n}", "usage": {"input_tokens": 1000, "cache_read_input_tokens": 500, "output_tokens": 10},
                "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
            lines.append({"type": "user", "timestamp": ts(), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": out}],
                 "is_error": not ok}]}})
    with open(path, "w", encoding="utf-8") as f:
        for d in lines:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        f.write("not json\n")
