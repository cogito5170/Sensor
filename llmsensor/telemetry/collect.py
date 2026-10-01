"""원천 -> 텔레메트리 레코드. **원천이 준 값만 옮긴다.** 추정 · 합산 · 해석은 derive.py 의 몫이다.

    from_cc_jsonl(path, run_id)      Claude Code 세션 JSONL (사람 말 하나 ~ 다음 말 = 실행 하나로 자르지 않는다 --
                                      파일 하나 = 실행 하나. 하위 에이전트 줄(isSidechain)은 뺀다)
    from_cc_stream(path, run_id)     run_claude.py 가 남긴 {"_t": 도착 ms, "line": {...}} 줄들
    from_sweagent(path, run_id)      SWE-agent .traj(.gz)
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..trace import ToolCall, call_head
from .schema import record


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _sig(name, inp) -> str:
    return hashlib.sha256((name + json.dumps(inp or {}, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:12]


def _head(name, inp) -> str:
    return call_head(ToolCall(name, inp or {}))


def _text_len(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(x.get("text", "")) for x in content if isinstance(x, dict) and x.get("type") == "text")
    return 0


def _usage_fields(u: dict) -> dict:
    od = u.get("output_tokens_details") or {}
    st = u.get("server_tool_use") or {}
    return {"input_tokens": u.get("input_tokens"), "cache_read_input_tokens": u.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
            "output_tokens": u.get("output_tokens"), "thinking_tokens": od.get("thinking_tokens"),
            "server_tool_requests": (sum(v for v in st.values() if isinstance(v, int)) if st else None),
            "iterations": len(u["iterations"]) if isinstance(u.get("iterations"), list) else None}


class _Calls:
    """모형 호출 · 도구 호출을 모으는 공용 장부."""

    def __init__(self, run_id, source, time_base):
        self.run_id, self.source, self.tb = run_id, source, time_base
        self.calls: dict = {}          # message id -> dict
        self.order: list = []
        self.tools: dict = {}          # tool_use id -> dict
        self.tool_order: list = []

    def call(self, mid):
        if mid not in self.calls:
            self.calls[mid] = {"t_start_ms": None, "t_end_ms": None, "tools": 0, "text": 0}
            self.order.append(mid)
        return self.calls[mid]

    def seen(self, c, t):
        if t is None:
            return
        c["t_start_ms"] = t if c["t_start_ms"] is None else min(c["t_start_ms"], t)
        c["t_end_ms"] = t if c["t_end_ms"] is None else max(c["t_end_ms"], t)

    def tool_use(self, mid, block, t):
        c = self.call(mid)
        c["tools"] += 1
        tid = block.get("id") or f"anon{len(self.tool_order)}"
        inp = block.get("input") or {}
        self.tools[tid] = {"call_index": self.order.index(mid), "tool_name": block.get("name", ""),
                           "tool_head": _head(block.get("name", ""), inp), "tool_sig": _sig(block.get("name", ""), inp),
                           "tool_input_chars": len(json.dumps(inp, ensure_ascii=False)), "t_issued_ms": t}
        self.tool_order.append(tid)

    def tool_result(self, block, t, extra=None):
        d = self.tools.get(block.get("tool_use_id"))
        if d is None:
            return
        d["is_error"] = bool(block.get("is_error"))
        d["tool_output_chars"] = _text_len(block.get("content"))
        d["t_result_ms"] = t
        if extra:
            d.update(extra)

    def records(self, model_extra=None):
        out = []
        for i, mid in enumerate(self.order):
            c = self.calls[mid]
            vals = {k: c.get(k) for k in ("model", "t_start_ms", "t_end_ms", "stop_reason", "thinking_duration_ms",
                                          "first_chunk_ms", "stream_chunks", "stream_thinking_estimate")}
            vals.update(c.get("usage") or {})
            vals.update(call_index=i, time_base=self.tb, tool_calls_per_message=c["tools"],
                        output_text_chars=c["text"])
            vals.update(model_extra or {})
            out.append(record("model_call", self.run_id, self.source, **vals))
        for j, tid in enumerate(self.tool_order):
            d = dict(self.tools[tid], tool_index=j, time_base=self.tb)
            out.append(record("tool_call", self.run_id, self.source, **d))
        return out


def from_cc_jsonl(path, run_id: str) -> "list[dict]":
    L = _Calls(run_id, "cc_jsonl", "unix_ms")
    cost = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "cost-state":
                cost = d
            if d.get("isSidechain"):
                continue
            m = d.get("message")
            if not isinstance(m, dict):
                continue
            t = _ts(d.get("timestamp"))
            if d.get("type") == "assistant" and m.get("id"):
                c = L.call(m["id"])
                L.seen(c, t)
                c["model"] = m.get("model")
                if m.get("usage"):
                    c["usage"] = _usage_fields(m["usage"])
                if m.get("stop_reason"):
                    c["stop_reason"] = m["stop_reason"]
                if d.get("thinkingDurationMs") is not None:
                    c["thinking_duration_ms"] = d["thinkingDurationMs"]
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        L.tool_use(m["id"], b, t)
                    elif isinstance(b, dict) and b.get("type") == "text":
                        c["text"] += len(b.get("text", ""))
            elif d.get("type") == "user" and isinstance(m.get("content"), list):
                tur = d.get("toolUseResult") if isinstance(d.get("toolUseResult"), dict) else {}
                extra = {"interrupted": tur.get("interrupted"),
                         "reported_duration_ms": (tur["durationSeconds"] * 1000 if isinstance(
                             tur.get("durationSeconds"), (int, float)) else None)}
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        L.tool_result(b, t, extra)
    recs = L.records()
    if cost:
        mu = cost.get("modelUsage") or {}
        recs.append(record(
            "run", run_id, "cc_jsonl", run_duration_ms=cost.get("totalDuration"),
            api_duration_ms=cost.get("totalAPIDuration"),
            api_duration_without_retries_ms=cost.get("totalAPIDurationWithoutRetries"),
            cost_usd=cost.get("totalCostUSD"),
            reported_input_tokens=sum(v.get("inputTokens") or 0 for v in mu.values()) if mu else None,
            reported_output_tokens=sum(v.get("outputTokens") or 0 for v in mu.values()) if mu else None,
            reported_cache_read_input_tokens=sum(v.get("cacheReadInputTokens") or 0 for v in mu.values()) if mu else None,
            reported_cache_creation_input_tokens=sum(v.get("cacheCreationInputTokens") or 0 for v in mu.values())
            if mu else None))
    return recs


def from_cc_stream(path, run_id: str) -> "list[dict]":
    """줄마다 {"_t": 수집기 단조 ms, "line": 원래 줄}. stream_event 에는 런타임 시각이 없어 _t 를 쓴다."""
    L = _Calls(run_id, "cc_stream", "monotonic_ms")
    cur = None
    run = {}
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    for row in rows:
        t, d = row.get("_t"), row.get("line") or {}
        ty = d.get("type")
        if d.get("parent_tool_use_id"):           # 하위 에이전트 사건은 뺀다
            continue
        if ty == "stream_event":
            ev = d.get("event") or {}
            et = ev.get("type")
            if et == "message_start":
                msg = ev.get("message") or {}
                cur = msg.get("id")
                c = L.call(cur)
                L.seen(c, t)
                c["model"] = msg.get("model")
                c["stream_chunks"] = 0
                c["_start"] = t
            elif cur is not None:
                c = L.call(cur)
                L.seen(c, t)
                if et == "content_block_delta":
                    c["stream_chunks"] += 1
                    if c.get("first_chunk_ms") is None and t is not None:
                        c["first_chunk_ms"] = t - c["_start"]
                elif et == "message_delta":
                    if ev.get("usage"):
                        c["usage"] = _usage_fields(ev["usage"])
                    c["stop_reason"] = (ev.get("delta") or {}).get("stop_reason")
        elif ty == "system" and d.get("subtype") == "thinking_tokens" and cur is not None:
            L.call(cur)["stream_thinking_estimate"] = d.get("estimated_tokens")
        elif ty == "assistant":
            m = d.get("message") or {}
            mid = m.get("id")
            if mid:
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        L.tool_use(mid, b, t)
                    elif isinstance(b, dict) and b.get("type") == "text":
                        L.call(mid)["text"] += len(b.get("text", ""))
        elif ty == "user":
            m = d.get("message") or {}
            tur = d.get("tool_use_result") if isinstance(d.get("tool_use_result"), dict) else {}
            for b in m.get("content") or [] if isinstance(m.get("content"), list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    L.tool_result(b, t, {"interrupted": tur.get("interrupted")})
        elif ty == "rate_limit_event":
            run["rate_limit_utilization"] = (d.get("rate_limit_info") or {}).get("utilization")
        elif ty == "autocompact_state":
            run["autocompact_threshold"] = (d.get("value") or {}).get("threshold")
        elif ty == "result":
            mu = d.get("modelUsage") or {}
            m0 = next(iter(mu.values()), {}) if len(mu) == 1 else {}
            u = d.get("usage") or {}
            run.update(model=next(iter(mu), None) if len(mu) == 1 else None,
                       run_duration_ms=d.get("duration_ms"), api_duration_ms=d.get("duration_api_ms"),
                       ttft_ms=d.get("ttft_ms"), num_turns=d.get("num_turns"), cost_usd=d.get("total_cost_usd"),
                       terminal_reason=d.get("terminal_reason"), result_subtype=d.get("subtype"),
                       is_error=d.get("is_error"), api_error_status=(None if d.get("api_error_status") is None
                                                                      else str(d.get("api_error_status"))),
                       permission_denials=len(d.get("permission_denials") or []),
                       context_window=m0.get("contextWindow"), max_output_tokens=m0.get("maxOutputTokens"),
                       reported_input_tokens=u.get("input_tokens"), reported_output_tokens=u.get("output_tokens"),
                       reported_cache_read_input_tokens=u.get("cache_read_input_tokens"),
                       reported_cache_creation_input_tokens=u.get("cache_creation_input_tokens"))
    recs = L.records({"context_window": run.get("context_window")})
    recs.append(record("run", run_id, "cc_stream", **run))
    return recs


def from_sweagent(path, run_id: str) -> "list[dict]":
    p = Path(path)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        d = json.load(f)
    L = _Calls(run_id, "sweagent", None)
    for i, s in enumerate(d.get("trajectory") or []):
        c = L.call(i)
        c["text"] = len(s.get("response") or "")
        act = s.get("action") or ""
        name = act.split()[0] if act.split() else ""
        L.tool_use(i, {"id": f"s{i}", "name": name, "input": {"command": act}}, None)
        tid = f"s{i}"
        L.tools[tid]["tool_output_chars"] = len(s.get("observation") or "")
        L.tools[tid]["t_result_ms"] = None
    recs = L.records()
    info = d.get("info") or {}
    ms = info.get("model_stats") or {}
    recs.append(record("run", run_id, "sweagent", cost_usd=ms.get("instance_cost"),
                       terminal_reason=info.get("exit_status"), tokens_sent=ms.get("tokens_sent"),
                       tokens_received=ms.get("tokens_received"), api_calls=ms.get("api_calls")))
    return recs
