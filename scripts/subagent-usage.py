#!/usr/bin/env python3
"""Claude Code usage by role and by worktree/PR, from local transcripts.

Usage: subagent-usage.py [PROJECT_DIR] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--prices prices.json]

PROJECT_DIR defaults to the ~/.claude/projects entry for the current directory.
Reports the MAIN session (orchestrator) and every subagent, grouped by model, by
role (agent type) and by worktree (the `.claude/worktrees/<name>` its prompt names,
i.e. its branch/PR). Token categories are kept apart because they are priced
differently: uncached input, cache read, cache write, output. "Context" =
input + cache read + cache write (what fills the window on each call).

Processed tokens are NOT cost and NOT Max-plan quota. `--prices` takes a JSON file
{"<model-id>": {"input": $/M, "cache_read": $/M, "cache_write": $/M, "output": $/M}}
(optionally "long": {...same keys...} and "long_threshold": tokens for tiered models)
and adds an API-equivalent estimate; Anthropic publishes no API-dollar -> Max conversion.
"""
import argparse, collections, datetime, glob, json, os, re, statistics

ap = argparse.ArgumentParser()
ap.add_argument("project_dir", nargs="?")
ap.add_argument("--since", default=(datetime.date.today() - datetime.timedelta(days=7)).isoformat())
ap.add_argument("--until", default="9999-12-31", help="exclusive end date YYYY-MM-DD")
ap.add_argument("--prices")
a = ap.parse_args()
d = a.project_dir or os.path.expanduser("~/.claude/projects/" + os.getcwd().replace("/", "-").replace(".", "-"))
since_ts = datetime.datetime.fromisoformat(a.since).timestamp()
prices = json.load(open(a.prices)) if a.prices else {}
WORKTREE = re.compile(r"\.claude/worktrees/([A-Za-z0-9._+-]+)")


def records(path):
    if os.path.getmtime(path) < since_ts:
        return
    with open(path, errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if a.since <= r.get("timestamp", "") < a.until:
                yield r


def cost(model, u):
    p = prices.get(model)
    if not p:
        return 0.0
    ctx = u["input"] + u["cache_read"] + u["cache_write"]
    if "long" in p and ctx > p.get("long_threshold", 10**12):
        p = p["long"]
    return sum(u[k] * p.get(k, 0) for k in ("input", "cache_read", "cache_write", "output")) / 1e6


class Agent:
    def __init__(self):
        self.calls = 0
        self.u = collections.Counter()
        self.peak = 0
        self.model = None
        self.role = None
        self.worktree = None
        self.usd = 0.0

    def add(self, r):
        m = r.get("message") or {}
        if self.worktree is None and r.get("type") == "user":
            text = json.dumps(m.get("content", ""))
            hit = WORKTREE.search(text)
            self.worktree = hit.group(1).rstrip(".") if hit else "-"
        self.role = self.role or r.get("attributionAgent")
        u = m.get("usage")
        if not (u and m.get("model")) or m["model"] == "<synthetic>":
            return
        call = {
            "input": u.get("input_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0),
            "cache_write": u.get("cache_creation_input_tokens", 0),
            "output": u.get("output_tokens", 0),
        }
        self.calls += 1
        self.u.update(call)
        self.peak = max(self.peak, call["input"] + call["cache_read"] + call["cache_write"])
        self.model = m["model"]
        self.usd += cost(m["model"], call)

    @property
    def ctx(self):
        return self.u["input"] + self.u["cache_read"] + self.u["cache_write"]


dispatch = collections.Counter()
main = collections.defaultdict(Agent)  # model -> Agent (main sessions, all files)
for f in glob.glob(os.path.join(d, "*.jsonl")):
    for r in records(f):
        m = r.get("message") or {}
        content = m.get("content")
        if r.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                    i = b["input"]
                    dispatch[(i.get("subagent_type") or "(untyped)") + (f" model={i['model']}" if i.get("model") else "")] += 1
        if m.get("model") and not r.get("isSidechain"):
            main[m["model"]].add(r)

agents = []
for f in glob.glob(os.path.join(d, "*", "subagents", "*.jsonl")):
    ag = Agent()
    for r in records(f):
        ag.add(r)
    if ag.calls:
        ag.role = ag.role or "(unknown)"
        agents.append(ag)

total = sum(x.ctx for x in main.values()) + sum(x.ctx for x in agents) or 1


def line(label, group):
    ctx = sum(x.ctx for x in group)
    u = collections.Counter()
    for x in group:
        u.update(x.u)
    peaks = [x.peak for x in group]
    usd = sum(x.usd for x in group)
    s = (f"  {label:44} agents={len(group):3} calls={sum(x.calls for x in group):6} "
         f"ctx={ctx/1e6:8.1f}M ({100*ctx/total:4.1f}%) in={u['input']/1e6:.1f}M "
         f"cache_r={u['cache_read']/1e6:.1f}M cache_w={u['cache_write']/1e6:.1f}M out={u['output']/1e6:.2f}M")
    if peaks:
        s += f" peak med={statistics.median(peaks)/1e3:.0f}k max={max(peaks)/1e3:.0f}k >200k={sum(p > 200_000 for p in peaks)}"
    if prices:
        s += f" ~${usd:,.2f}"
    print(s)


print(f"project: {d}\nsince:   {a.since}  until: {a.until}\nNOTE: processed tokens != cost != Max quota (see --prices)\n")
print("dispatches by subagent_type (main transcripts):")
for k, v in dispatch.most_common():
    print(f"  {k:28} {v}")
print("\nmain session (orchestrator) by model:")
for model, ag in sorted(main.items()):
    line(model, [ag])
print("\nsubagents by model:")
for model in sorted({x.model for x in agents}):
    line(model, [x for x in agents if x.model == model])
print("\nsubagents by role:")
for role in sorted({x.role for x in agents}):
    line(role, [x for x in agents if x.role == role])
print("\nsubagents by worktree (branch/PR; '-' = none named):")
by_wt = collections.defaultdict(list)
for x in agents:
    by_wt[x.worktree or "-"].append(x)
for wt, group in sorted(by_wt.items(), key=lambda kv: -sum(x.ctx for x in kv[1])):
    roles = collections.Counter(x.role for x in group)
    line(wt[:44], group)
    print(f"  {'':44} roles: {', '.join(f'{k}×{v}' for k, v in roles.most_common())}")
