#!/usr/bin/env python3
"""Subagent routing and token usage from Claude Code transcripts.

Usage: subagent-usage.py [PROJECT_DIR] [--since YYYY-MM-DD]
PROJECT_DIR defaults to the ~/.claude/projects entry for the current directory.
Prints dispatches by subagent_type (from main-session transcripts) and, per model,
subagent token volume plus per-agent context (median / p95 / max) and call counts.
Tokens = input + cache read + cache creation (what fills the context) and output.
"""
import argparse, collections, datetime, glob, json, os, statistics

ap = argparse.ArgumentParser()
ap.add_argument("project_dir", nargs="?")
ap.add_argument("--since", default=(datetime.date.today() - datetime.timedelta(days=7)).isoformat())
a = ap.parse_args()
d = a.project_dir or os.path.expanduser("~/.claude/projects/" + os.getcwd().replace("/", "-").replace(".", "-"))
since_ts = datetime.datetime.fromisoformat(a.since).timestamp()

def records(path):
    if os.path.getmtime(path) < since_ts:
        return
    with open(path, errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("timestamp", "") >= a.since:
                yield r

dispatch = collections.Counter()
for f in glob.glob(os.path.join(d, "*.jsonl")):
    for r in records(f):
        content = (r.get("message") or {}).get("content")
        if r.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                    i = b["input"]
                    key = i.get("subagent_type") or "(untyped)"
                    if i.get("model"):
                        key += f" model={i['model']}"
                    dispatch[key] += 1

agents = collections.defaultdict(list)  # model -> [(calls, ctx_tokens, out_tokens, max_ctx)]
for f in glob.glob(os.path.join(d, "*", "subagents", "*.jsonl")):
    calls = ctx = out = mx = 0
    model = None
    for r in records(f):
        m = r.get("message") or {}
        u = m.get("usage")
        if not (u and m.get("model")):
            continue
        c = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        calls, ctx, out, mx, model = calls + 1, ctx + c, out + u.get("output_tokens", 0), max(mx, c), m["model"]
    if calls:
        agents[model].append((calls, ctx, out, mx))

print(f"project: {d}\nsince:   {a.since}\n\ndispatches by subagent_type:")
for k, v in dispatch.most_common():
    print(f"  {k:28} {v}")
total = sum(x[1] for v in agents.values() for x in v) or 1
if any(" model=" in k for k in dispatch):
    print("  ^ a bare model= override bypasses the agent types' routing and effort")
print("\nsubagent usage by model:")
for model, v in sorted(agents.items(), key=lambda kv: -sum(x[1] for x in kv[1])):
    ctxs = sorted(x[3] for x in v)
    p95 = ctxs[min(len(ctxs) - 1, int(0.95 * len(ctxs)))]
    vol = sum(x[1] for x in v)
    print(f"  {model}: agents={len(v)} calls={sum(x[0] for x in v)} context-tokens={vol/1e6:.1f}M ({100*vol/total:.0f}%) "
          f"output={sum(x[2] for x in v)/1e6:.2f}M")
    print(f"    per-agent max context: median={statistics.median(ctxs)/1e3:.0f}k p95={p95/1e3:.0f}k max={ctxs[-1]/1e3:.0f}k; "
          f"agents over 200k: {sum(c > 200_000 for c in ctxs)}")
