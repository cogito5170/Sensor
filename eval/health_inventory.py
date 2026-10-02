"""건강 차원(liveness · retry · recovery · dependency · action outcome)이 **원천에 이미 있나** -- 짓기 전 재고 조사.

    python3 eval/health_inventory.py <runs 디렉터리> <self.jsonl> <sweagent trajs 디렉터리> [--out eval/results/health_inventory.json]

원천 원문은 싣지 않는다(이 세션의 대화가 들어 있다). 개수 · 키 · 값 집합만 낸다.
같은 원천에 지금 수집기 · 상태 층을 돌려, 원천에 있는 사건이 상태에 닿는지도 함께 본다.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llmsensor.state import StateEngine, from_telemetry  # noqa: E402
from llmsensor.telemetry.collect import TIMEOUT_TEXT, from_cc_jsonl  # noqa: E402

C = collections.Counter


def stream(runs):
    ev, prog, gaps, ends, rl, ptc, perm, sub, mcp = C(), [], {}, C(), [], C(), 0, C(), C()
    status, starts = C(), 0
    for f in sorted(glob.glob(str(Path(runs) / "*.stream.jsonl"))):
        L = [json.loads(x) for x in open(f, encoding="utf-8")]
        name = Path(f).name.split(".")[0]
        ts = [w["_t"] for w in L]
        gaps[name] = round(max(b - a for a, b in zip(ts, ts[1:])))
        ends["result" if any(w["line"].get("type") == "result" for w in L) else "no_result"] += 1
        for w in L:
            d = w["line"]
            sub_t = d.get("subtype") or (d.get("event") or {}).get("type")
            ev[f"{d.get('type')}/{sub_t}"] += 1
            if d.get("type") == "tool_progress":
                prog.append({"run": name, "elapsed_s": d.get("elapsed_time_seconds"), "heartbeat": d.get("heartbeat")})
            if d.get("subtype") == "status":
                status[d.get("status")] += 1
            if sub_t == "message_start":
                starts += 1
            if d.get("subtype") == "init":
                mcp[len(d.get("mcp_servers") or [])] += 1
            if d.get("subtype") == "post_turn_summary":
                ptc[f"{d.get('status_category')}|needs_action={bool(d.get('needs_action'))}"] += 1
            if d.get("type") == "rate_limit_event":
                i = d["rate_limit_info"]
                rl.append({"status": i.get("status"), **{k: v.get("utilization") for k, v in (i.get("unifiedWindows") or {}).items()}})
            if d.get("type") == "result":
                perm += len(d.get("permission_denials") or [])
                s = d.get("subagent_stats") or {}
                for k in ("spawned", "failed", "completed"):
                    sub[k] += s.get(k, 0)
    fh = [r["five_hour"] for r in rl if r.get("five_hour") is not None]
    return {"event_types": dict(ev.most_common()), "status_events": dict(status), "message_starts": starts,
            "tool_progress": prog, "max_silent_gap_ms": gaps, "stream_end": dict(ends),
            "init_mcp_server_count": {str(k): v for k, v in mcp.items()}, "post_turn_summary": dict(ptc),
            "permission_denials": perm, "subagent_stats_sum": dict(sub),
            "rate_limit_events": len(rl), "rate_limit_status": dict(C(r["status"] for r in rl)),
            "five_hour_utilization": {"min": min(fh), "max": max(fh), "distinct": sorted(set(fh))} if fh else None}


def _text(c):
    if isinstance(c, str):
        return c
    return " ".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""


def cc_jsonl(path):
    names, api_err, compact, bg_timeouts, webfetch_err, hooks, queue = {}, [], [], 0, C(), C(), C()
    regex = C()
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        ty = d.get("type")
        if ty == "assistant":
            for c in d["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    names[c["id"]] = c["name"]
            if d.get("isApiErrorMessage") or d.get("apiErrorStatus"):
                q = d.get("quotaLimits") or {}
                api_err.append({"error": d.get("error"), "status": d.get("apiErrorStatus"), "model": d["message"].get("model"),
                                "quota_status": q.get("status"), "quota_type": q.get("rateLimitType"),
                                "overage": q.get("overageStatus"), "fallback_available": q.get("unifiedRateLimitFallbackAvailable")})
        elif d.get("subtype") == "compact_boundary":
            m = d.get("compactMetadata") or {}
            compact.append({k: m.get(k) for k in ("trigger", "preTokens", "postTokens", "durationMs")})
        elif d.get("subtype") == "stop_hook_summary":
            hooks["runs"] += 1
            hooks["errors"] += len(d.get("hookErrors") or [])
            hooks["prevented"] += bool(d.get("preventedContinuation"))
        elif ty == "queue-operation":
            queue[f"{d.get('operation')}|{d.get('reason')}"] += 1
        elif ty == "user":
            tur = d.get("toolUseResult") if isinstance(d.get("toolUseResult"), dict) else {}
            if "timedOutAfterMs" in tur:
                bg_timeouts += 1
            for c in d["message"].get("content", []) if isinstance(d["message"].get("content"), list) else []:
                if not (isinstance(c, dict) and c.get("type") == "tool_result"):
                    continue
                nm, txt = names.get(c.get("tool_use_id")), _text(c.get("content"))
                if nm == "Bash":
                    hit, real = bool(TIMEOUT_TEXT.search(txt)), "timedOutAfterMs" in tur or (
                        c.get("is_error") is True and txt.lstrip().startswith("Exit code") and bool(TIMEOUT_TEXT.search(txt)))
                    regex[("TP" if real else "FP") if hit else ("FN" if real else "TN")] += 1
                if nm == "WebFetch" and c.get("is_error"):
                    m = re.search(r'"error_type"\s*:\s*"([A-Z_]+)"', txt)
                    webfetch_err[m.group(1) if m else "unstructured"] += 1
    recs = from_cc_jsonl(path, "cc_jsonl_self:inv")
    E = StateEngine().ingest_all(from_telemetry(recs))
    states = {n: (st.status.name, st.value) for (ent, n), st in E.current.items()
              if n in ("rate_limit_state", "runtime_reliability", "execution_interruption", "context_pressure")}

    def last(key):
        ms = [(int(i.rsplit("@", 1)[1]), m) for i, m in E.metrics.items() if i.startswith(key + "@")]
        m = max(ms, key=lambda x: x[0])[1]
        return {"value": m.value, "reason": m.reason}
    return {"api_error_messages": api_err, "compaction": compact, "bash_timeout_moved_to_background": bg_timeouts,
            "timeout_regex_vs_runtime": dict(regex), "webfetch_errors": dict(webfetch_err), "stop_hooks": dict(hooks),
            "queue_operations": dict(queue),
            "collector": {"synthetic_model_calls": sum(r["kind"] == "model_call" and r.get("model") == "<synthetic>"
                                                       for r in recs),
                          "tool_calls_timed_out": sum(r["kind"] == "tool_call" and r.get("timed_out") is True for r in recs)},
            "states_now": states, "cost_estimate": last("agent:cc_jsonl_self:inv/cost_estimate")}


def sweagent(trajs):
    keys, step, n = C(), C(), 0
    for f in sorted(glob.glob(str(Path(trajs) / "*.traj.gz"))):
        d = json.load(gzip.open(f))
        n += 1
        keys.update((d.get("info") or {}).get("model_stats", {}).keys())
        for s in d.get("trajectory") or []:
            step.update(s.keys())
    return {"trajs": n, "model_stats_keys": sorted(keys), "trajectory_step_keys": sorted(step)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("self_jsonl")
    ap.add_argument("trajs")
    ap.add_argument("--out", default="eval/results/health_inventory.json")
    a = ap.parse_args(argv)
    out = {"cc_stream": stream(a.runs), "cc_jsonl_self": cc_jsonl(a.self_jsonl), "sweagent": sweagent(a.trajs)}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, default=str)[:4000])


if __name__ == "__main__":
    main()
