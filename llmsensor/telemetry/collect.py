"""원천 -> 텔레메트리 레코드. **원천이 준 값만 옮긴다.** 추정 · 합산 · 해석은 derive.py 의 몫이다.

    from_cc_jsonl(path, run_id)      Claude Code 세션 JSONL (사람 말 하나 ~ 다음 말 = 실행 하나로 자르지 않는다 --
                                      파일 하나 = 실행 하나. 하위 에이전트 줄(isSidechain)은 뺀다)
    from_cc_stream(path, run_id)     run_claude.py 가 남긴 {"_t": 도착 ms, "line": {...}} 줄들
    from_sweagent(path, run_id)      SWE-agent .traj(.gz)

**겨냥 글은 남기지 않는다.** 도구 인자에서 꺼낸 겨냥(파일 경로 · URL · Grep 패턴 · 웹 검색어 · 실행 파일 경로)은
열쇠 해시(HMAC-SHA256, 12 hex)로만 남는다. 평문으로 남는 것은 `^[A-Za-z][A-Za-z0-9_.+-]*$` 꼴의 **맨 프로그램 이름**
(git · python3 · pytest ...)뿐이다 -- 걸음 종류를 가르는 데 필요하고, 경로가 아니다.

열쇠: 환경 변수 `LLMSENSOR_HASH_KEY` 가 있으면 그것, 없으면 **수집 프로세스마다 무작위로 만들고 저장하지 않는다.**
그래서 한 수집(한 데이터셋) 안에서는 같은 겨냥이 같은 해시를 받아 반복 · 재시도를 셀 수 있지만, 해시에서 글을 되찾거나
사전 대입으로 맞춰 볼 수 없다. 데이터셋 사이에서 해시를 맞대려면 같은 열쇠를 환경 변수로 줘야 한다.
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
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


class Hasher:
    """겨냥 · 인자를 열쇠 해시로. 열쇠를 안 주면 무작위(저장 안 함)."""

    def __init__(self, key: "bytes | str | None" = None):
        if key is None:
            key = os.environ.get("LLMSENSOR_HASH_KEY") or secrets.token_bytes(32)
        self.key = key.encode() if isinstance(key, str) else key

    def __call__(self, text: str) -> str:
        return hmac.new(self.key, text.encode(), hashlib.sha256).hexdigest()[:12]


_DEFAULT: "Hasher | None" = None
PROGRAM = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]*$")


def default_hasher() -> Hasher:
    """한 프로세스 안의 모든 수집이 같은 열쇠를 쓰게."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Hasher()
    return _DEFAULT


def _sig(name, inp, h: Hasher) -> str:
    return h(name + json.dumps(inp or {}, ensure_ascii=False, sort_keys=True))


def _head(name, inp, h: Hasher) -> str:
    """이름:겨냥. 겨냥이 맨 프로그램 이름(Bash 명령의 첫 낱말)이면 평문, 그 밖(경로 · 패턴 · 검색어 ...)은 #해시."""
    nm, _, target = call_head(ToolCall(name, inp or {})).partition(":")
    if not target:
        return nm
    if "command" in (inp or {}) and PROGRAM.match(target):
        return f"{nm}:{target}"
    return f"{nm}:#{h(target)}"


def _take(src: dict, mapping: dict) -> "tuple[dict, list]":
    """{칸: 원천 키} -> (값들, 원천이 null 로 준 칸들). 키가 없으면 값 없음 + 목록에도 없음(= unobserved)."""
    vals, nulls = {}, []
    for field, key in mapping.items():
        if key in src:
            if src[key] is None:
                nulls.append(field)
            else:
                vals[field] = src[key]
    return vals, nulls


def _text_len(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(x.get("text", "")) for x in content if isinstance(x, dict) and x.get("type") == "text")
    return 0


TIMEOUT_TEXT = re.compile(r"Command timed out after")    # Claude Code Bash 의 런타임 선언(앞 실험 t11 에서 봄)


def _timed_out(tool_name, block) -> "bool | None":
    """Bash 결과 글에 런타임의 시간 초과 문구가 있나. 다른 도구는 문구를 모르므로 None(못 봄)."""
    if tool_name != "Bash":
        return None
    c = block.get("content")
    txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict)) \
        if isinstance(c, list) else ""
    return bool(TIMEOUT_TEXT.search(txt))


def _usage_fields(u: dict) -> "tuple[dict, list]":
    vals, nulls = _take(u, {"input_tokens": "input_tokens", "cache_read_input_tokens": "cache_read_input_tokens",
                            "cache_creation_input_tokens": "cache_creation_input_tokens",
                            "output_tokens": "output_tokens"})
    od = u.get("output_tokens_details")
    if isinstance(od, dict):
        v, n = _take(od, {"thinking_tokens": "thinking_tokens"})
        vals.update(v)
        nulls += n
    st = u.get("server_tool_use")
    if isinstance(st, dict):
        vals["server_tool_requests"] = sum(v for v in st.values() if isinstance(v, int))
    if isinstance(u.get("iterations"), list):
        vals["iterations"] = len(u["iterations"])
    cc = u.get("cache_creation")
    if isinstance(cc, dict):
        v, n = _take(cc, {"cache_creation_5m_input_tokens": "ephemeral_5m_input_tokens",
                          "cache_creation_1h_input_tokens": "ephemeral_1h_input_tokens"})
        vals.update(v)
        nulls += n
    return vals, nulls


class _Calls:
    """모형 호출 · 도구 호출을 모으는 공용 장부."""

    def __init__(self, run_id, source, time_base, hasher=None):
        self.run_id, self.source, self.tb = run_id, source, time_base
        self.h = hasher or default_hasher()
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
                           "tool_head": _head(block.get("name", ""), inp, self.h),
                           "tool_sig": _sig(block.get("name", ""), inp, self.h),
                           "tool_input_chars": len(json.dumps(inp, ensure_ascii=False)), "t_issued_ms": t}
        self.tool_order.append(tid)

    def tool_result(self, block, t, extra=None, extra_nulls=()):
        d = self.tools.get(block.get("tool_use_id"))
        if d is None:
            return
        d["is_error"] = bool(block.get("is_error"))
        d["timed_out"] = _timed_out(d["tool_name"], block)
        d["tool_output_chars"] = _text_len(block.get("content"))
        d["t_result_ms"] = t
        if extra:
            d.update(extra)
        d["nulls"] = list(extra_nulls)

    def records(self, model_extra=None):
        out = []
        for i, mid in enumerate(self.order):
            c = self.calls[mid]
            vals = {k: c.get(k) for k in ("model", "t_start_ms", "t_end_ms", "stop_reason", "thinking_duration_ms",
                                          "first_chunk_ms", "stream_chunks", "stream_thinking_estimate")}
            vals.update(c.get("usage") or {})
            nl = set(c.get("unulls") or ())
            if c.get("sr_null"):
                nl.add("stop_reason")
            if c.get("tdm_null"):
                nl.add("thinking_duration_ms")
            nulls = [k for k in nl if vals.get(k) is None]
            vals.update(call_index=i, time_base=self.tb, tool_calls_per_message=c["tools"],
                        output_text_chars=c["text"])
            vals.update(model_extra or {})
            out.append(record("model_call", self.run_id, self.source, reported_null=nulls, **vals))
        for j, tid in enumerate(self.tool_order):
            d = dict(self.tools[tid], tool_index=j, time_base=self.tb)
            nulls = [k for k in d.pop("nulls", []) if d.get(k) is None]
            out.append(record("tool_call", self.run_id, self.source, reported_null=nulls, **d))
        return out


def from_cc_jsonl(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    L = _Calls(run_id, "cc_jsonl", "unix_ms", hasher)
    cost, cost_at, last_ts = None, None, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _ts(d.get("timestamp")) is not None:
                last_ts = _ts(d.get("timestamp"))
            if d.get("type") == "cost-state":
                # **세션 끝 합계가 아니다** -- 그 줄까지의 누적 스냅숏이다(2026-10-02 실측: 577 줄 중 212 번째, 앞 27 호출의
                # 합과 토큰 · 비용이 정확히 같다). 자기 시각이 없어 바로 앞 줄의 시각을 스냅숏 시각으로 남긴다
                cost, cost_at = d, last_ts
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
                    c["usage"], c["unulls"] = _usage_fields(m["usage"])
                if m.get("stop_reason"):
                    c["stop_reason"] = m["stop_reason"]
                elif "stop_reason" in m:
                    c["sr_null"] = True             # 조각 줄은 null 을 준다 -- 끝까지 값이 안 오면 '보고된 null'
                if d.get("thinkingDurationMs") is not None:
                    c["thinking_duration_ms"] = d["thinkingDurationMs"]
                elif "thinkingDurationMs" in d:
                    c["tdm_null"] = True
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        L.tool_use(m["id"], b, t)
                    elif isinstance(b, dict) and b.get("type") == "text":
                        c["text"] += len(b.get("text", ""))
            elif d.get("type") == "user" and isinstance(m.get("content"), list):
                tur = d.get("toolUseResult") if isinstance(d.get("toolUseResult"), dict) else {}
                extra, tnull = _take(tur, {"interrupted": "interrupted"})
                if isinstance(tur.get("durationSeconds"), (int, float)):
                    extra["reported_duration_ms"] = tur["durationSeconds"] * 1000
                elif "durationSeconds" in tur:
                    tnull.append("reported_duration_ms")
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        L.tool_result(b, t, extra, tnull)
    recs = L.records()
    if cost:
        mu = cost.get("modelUsage") or {}
        recs.append(record(
            "run", run_id, "cc_jsonl", snapshot_at_ms=cost_at, run_duration_ms=cost.get("totalDuration"),
            api_duration_ms=cost.get("totalAPIDuration"),
            api_duration_without_retries_ms=cost.get("totalAPIDurationWithoutRetries"),
            cost_usd=cost.get("totalCostUSD"),
            reported_input_tokens=sum(v.get("inputTokens") or 0 for v in mu.values()) if mu else None,
            reported_output_tokens=sum(v.get("outputTokens") or 0 for v in mu.values()) if mu else None,
            reported_cache_read_input_tokens=sum(v.get("cacheReadInputTokens") or 0 for v in mu.values()) if mu else None,
            reported_cache_creation_input_tokens=sum(v.get("cacheCreationInputTokens") or 0 for v in mu.values())
            if mu else None))
    return recs


def from_cc_stream(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    """줄마다 {"_t": 수집기 단조 ms, "line": 원래 줄}. stream_event 에는 런타임 시각이 없어 _t 를 쓴다."""
    L = _Calls(run_id, "cc_stream", "monotonic_ms", hasher)
    cur = None
    run, run_nulls = {}, []
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
                c["_start_usage"] = dict(msg.get("usage") or {})   # 캐시 쓰기 5m/1h · server_tool_use 는 여기에만 온다
            elif cur is not None:
                c = L.call(cur)
                L.seen(c, t)
                if et == "content_block_delta":
                    c["stream_chunks"] += 1
                    if c.get("first_chunk_ms") is None and t is not None:
                        c["first_chunk_ms"] = t - c["_start"]
                elif et == "message_delta":
                    if ev.get("usage"):
                        # delta 가 최종값이다. delta 에 없는 칸만 message_start 의 usage 로 채운다
                        merged = dict(c.get("_start_usage") or {})
                        merged.update(ev["usage"])
                        c["usage"], c["unulls"] = _usage_fields(merged)
                    delta = ev.get("delta") or {}
                    c["stop_reason"] = delta.get("stop_reason")
                    if "stop_reason" in delta and delta["stop_reason"] is None:
                        c["sr_null"] = True
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
                    ex, tn = _take(tur, {"interrupted": "interrupted"})
                    L.tool_result(b, t, ex, tn)
        elif ty == "rate_limit_event":
            info = d.get("rate_limit_info") or {}
            run["rate_limit_utilization"] = info.get("utilization")
            run["rate_limit_status"] = info.get("status")
            run["rate_limit_threshold"] = info.get("surpassedThreshold")
        elif ty == "autocompact_state":
            run["autocompact_threshold"] = (d.get("value") or {}).get("threshold")
        elif ty == "result":
            mu = d.get("modelUsage") or {}
            m0 = next(iter(mu.values()), {}) if len(mu) == 1 else {}
            v, n = _take(d, {"run_duration_ms": "duration_ms", "api_duration_ms": "duration_api_ms",
                             "ttft_ms": "ttft_ms", "num_turns": "num_turns", "cost_usd": "total_cost_usd",
                             "terminal_reason": "terminal_reason", "result_subtype": "subtype",
                             "is_error": "is_error", "api_error_status": "api_error_status"})
            if "api_error_status" in v:
                v["api_error_status"] = str(v["api_error_status"])
            if isinstance(d.get("permission_denials"), list):
                v["permission_denials"] = len(d["permission_denials"])
            v2, n2 = _take(m0, {"context_window": "contextWindow", "max_output_tokens": "maxOutputTokens"})
            v3, n3 = _take(d.get("usage") or {}, {
                "reported_input_tokens": "input_tokens", "reported_output_tokens": "output_tokens",
                "reported_cache_read_input_tokens": "cache_read_input_tokens",
                "reported_cache_creation_input_tokens": "cache_creation_input_tokens"})
            run.update(v, **v2, **v3)
            if len(mu) == 1:
                run["model"] = next(iter(mu))
            run_nulls += n + n2 + n3
    recs = L.records({"context_window": run.get("context_window")})
    recs.append(record("run", run_id, "cc_stream", reported_null=[k for k in run_nulls if run.get(k) is None], **run))
    return recs


def from_sweagent(path, run_id: str, hasher: "Hasher | None" = None) -> "list[dict]":
    p = Path(path)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        d = json.load(f)
    L = _Calls(run_id, "sweagent", None, hasher)
    for i, s in enumerate(d.get("trajectory") or []):
        c = L.call(i)
        c["text"] = len(s.get("response") or "")
        act = s.get("action") or ""
        first = act.split()[0] if act.split() else ""
        # 첫 낱말이 경로(./run.sh · /tmp/x)일 수 있다 -- 맨 프로그램 이름만 평문
        name = first if not first or PROGRAM.match(first) else "#" + L.h(first)
        L.tool_use(i, {"id": f"s{i}", "name": name, "input": {"command": act}}, None)
        tid = f"s{i}"
        L.tools[tid]["tool_output_chars"] = len(s.get("observation") or "")
        L.tools[tid]["t_result_ms"] = None
    recs = L.records()
    info = d.get("info") or {}
    v, n = _take(info.get("model_stats") or {}, {"cost_usd": "instance_cost", "tokens_sent": "tokens_sent",
                                                  "tokens_received": "tokens_received", "api_calls": "api_calls"})
    v2, n2 = _take(info, {"terminal_reason": "exit_status"})
    recs.append(record("run", run_id, "sweagent", reported_null=n + n2, **v, **v2))
    return recs
