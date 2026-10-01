"""레코드 -> 파생 텔레메트리. 레코드만 본다(원천을 다시 열지 않는다) -- 층을 지킨다.

못 본 값에서 나온 파생은 None 이다. 0 으로 메우지 않는다.
"""
from __future__ import annotations

import collections
import math


def _sub(a, b):
    return None if a is None or b is None else a - b


def _sum(xs):
    xs = list(xs)
    return None if not xs or any(x is None for x in xs) else sum(xs)


def by_run(records):
    runs = collections.defaultdict(lambda: {"model_call": [], "tool_call": [], "run": []})
    for r in records:
        runs[r["run_id"]][r["kind"]].append(r)
    for v in runs.values():
        v["model_call"].sort(key=lambda r: r["call_index"])
        v["tool_call"].sort(key=lambda r: r["tool_index"])
    return runs


def calls(run) -> "list[dict]":
    """호출 단위 파생. catalog.CALL_VARS 의 이름을 쓴다."""
    tools = collections.defaultdict(list)
    for t in run["tool_call"]:
        tools[t["call_index"]].append(t)
    out, prev, cum, ctx_prev = [], None, 0, None
    med_hist = []
    for m in run["model_call"]:
        ts = tools.get(m["call_index"], [])
        errs = [t["is_error"] for t in ts]
        lat = [_sub(t["t_result_ms"], t["t_issued_ms"]) for t in ts]
        ctx = _sum([m["input_tokens"], m["cache_read_input_tokens"], m["cache_creation_input_tokens"]])
        out_tok = m["output_tokens"]
        cum = None if cum is None or out_tok is None else cum + out_tok
        span = _sub(m["t_end_ms"], m["t_start_ms"])
        d = {
            "run_id": m["run_id"], "source": m["source"], "step_index": m["call_index"],
            "input_tokens": m["input_tokens"], "cache_read_input_tokens": m["cache_read_input_tokens"],
            "cache_creation_input_tokens": m["cache_creation_input_tokens"], "output_tokens": out_tok,
            "thinking_tokens": m["thinking_tokens"], "tool_calls_per_message": m["tool_calls_per_message"],
            "tool_errors": (sum(bool(e) for e in errs) if errs and None not in errs else (0 if not ts else None)),
            "tool_output_chars": _sum([t["tool_output_chars"] for t in ts]) if ts else 0,
            "tool_latency_ms": _sum(lat) if ts else None,
            "call_span_ms": span,
            "inter_call_gap_ms": _sub(m["t_start_ms"], prev["t_end_ms"]) if prev else None,
            "output_text_chars": m["output_text_chars"], "context_tokens": ctx,
            "context_growth": _sub(ctx, ctx_prev) if out else None,
            "cumulative_output_tokens": cum,
            "cache_hit_ratio": (m["cache_read_input_tokens"] / ctx if ctx else None),
            "thinking_ratio": (m["thinking_tokens"] / out_tok if out_tok and m["thinking_tokens"] is not None else None),
            "output_tokens_per_sec": (out_tok / (span / 1000) if out_tok is not None and span and span > 0 else None),
        }
        # 사건형 파생(분석의 상관에는 안 넣는다)
        if out_tok is not None:
            med = sorted(med_hist)[len(med_hist) // 2] if med_hist else None
            d["token_burst"] = (out_tok > 4 * med) if med and len(med_hist) >= 3 else None
            med_hist.append(out_tok)
        out.append(d)
        prev, ctx_prev = m, ctx
    for i, d in enumerate(out):
        g = [out[j]["context_growth"] for j in range(max(1, i - 2), i + 1)]
        c = out[i]["context_tokens"]
        d["token_stagnation"] = (all(x is not None and abs(x) < .01 * c for x in g) if i >= 3 and c else None)
        w = [out[j]["output_tokens"] for j in range(max(0, i - 5), i + 1)]
        dif = [b - a for a, b in zip(w, w[1:]) if a is not None and b is not None]
        d["token_oscillation"] = sum(1 for a, b in zip(dif, dif[1:]) if a * b < 0) if len(dif) >= 2 else None
    return out


def run_summary(run) -> dict:
    """실행 단위 파생. catalog.RUN_VARS."""
    from ..trace import ToolCall, retries
    cs = calls(run)
    tl = run["tool_call"]
    rr = run["run"][0] if run["run"] else {}
    errs = [t["is_error"] for t in tl]
    err_known = bool(tl) and None not in errs
    names = collections.Counter(t["tool_name"] for t in tl)
    n = len(tl)
    sigs = collections.Counter(t["tool_sig"] for t in tl)
    if err_known:
        tcs = [ToolCall(t["tool_name"], {"command": t["tool_head"]}, t["is_error"] is False) for t in tl]
        rc = retries(tcs)
    else:
        rc = None
    sent = rr.get("tokens_sent") if rr.get("tokens_sent") is not None else _sum(c["context_tokens"] for c in cs)
    recv = rr.get("tokens_received") if rr.get("tokens_received") is not None else _sum(c["output_tokens"] for c in cs)
    return {
        "run_id": (run["model_call"] or run["run"] or [{"run_id": "?"}])[0]["run_id"],
        "source": (run["model_call"] or run["run"] or [{"source": "?"}])[0]["source"],
        "tokens_sent": sent, "tokens_received": recv, "model_calls": len(run["model_call"]),
        "tool_call_count": n, "tool_error_rate": (sum(bool(e) for e in errs) / n if err_known else None),
        "identical_call_repeats": max(sigs.values()) if sigs else 0, "retry_count": rc,
        "action_diversity": len(sigs) / n if n else None,
        "tool_type_entropy": -sum(v / n * math.log2(v / n) for v in names.values()) if n else None,
        "cost_usd": rr.get("cost_usd"),
        "mean_tool_output_chars": (sum(t["tool_output_chars"] or 0 for t in tl) / n if n else None),
    }
