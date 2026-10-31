#!/usr/bin/env python3
"""Claude Code usage by role and by worktree/PR, from local transcripts (deduplicated).

Usage: subagent-usage.py [PROJECT_DIR | --all-projects] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                         [--prices prices.json] [--strict]

Scope: PROJECT_DIR if given; --all-projects scans EVERY dir under ~/.claude/projects (HOME-relative);
default = every ~/.claude/projects dir for the current repo (main checkout under any path spelling
+ its worktree sessions). The report starts with a coverage block.

Deduplication (why raw sums are ~2.4x too high): Claude Code writes one transcript record per content
block of an API response, each repeating the identical usage, and the same responses reappear in
duplicate project dirs (two path spellings of one repo) and in forked transcripts. So responses are
deduplicated GLOBALLY by message.id across all files (never per session). Subagent files are read
before main files so a response is attributed to its subagent; isSidechain records in main files are
skipped. Among copies of one id the FINAL one (non-null stop_reason) with max output_tokens wins;
if no copy is final the max-output copy is used and counted `partial` (its usage may be low, Claude
Code issue #100381). Two final copies with differing usage are a `conflict`. Records without a
message.id are counted individually and reported as `unidentified`.

Pricing: "--prices" takes JSON {"<model-id>": {"input","cache_read","cache_write"(5-minute rate),
"cache_write_1h","output"}} (optionally "long": {...} + "long_threshold" for tiered models). Cache
writes are split by usage.cache_creation.ephemeral_{5m,1h}_input_tokens; without that breakdown they
are priced as 5-minute writes and counted `assumed_ttl`. Unknown models are never priced at $0
silently: they are listed in an UNPRICED section. `--strict` exits 2 on any unpriced model or conflict.

These are ESTIMATES: processed tokens and API-equivalent dollars are NOT Max-plan quota, and Anthropic
publishes no API-dollar -> plan conversion. "Context" = input + cache read + cache write.
"""
import argparse, collections, datetime, glob, json, os, re, statistics, sys

ap = argparse.ArgumentParser()
ap.add_argument("project_dir", nargs="?")
ap.add_argument("--all-projects", action="store_true", help="scan every dir under ~/.claude/projects")
ap.add_argument("--since", default=(datetime.date.today() - datetime.timedelta(days=7)).isoformat())
ap.add_argument("--until", default="9999-12-31", help="exclusive end date YYYY-MM-DD")
ap.add_argument("--prices")
ap.add_argument("--strict", action="store_true", help="exit 2 if any unpriced model or conflict exists")
a = ap.parse_args()
ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def repo_dirs():
    """Every ~/.claude/projects dir for the current repo: the main checkout under any path spelling
    (e.g. a symlinked /home/x/home/x/...) AND its worktree sessions (<repo>--claude-worktrees-*).
    Missing one once hid ~3/4 of a window's spend (2026-10-12), so the default is ALL of them."""
    import subprocess
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        top = os.getcwd()
    tail = "-".join(os.path.realpath(top).strip("/").split("/")[-3:]).replace(".", "-")
    return sorted(x for x in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(x)
                  and (x.endswith("-" + tail) or ("-" + tail + "--claude-worktrees-") in x))


if a.project_dir:
    dirs = [a.project_dir]
elif a.all_projects:
    dirs = sorted(x for x in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(x))
else:
    dirs = repo_dirs()
since_ts = datetime.datetime.fromisoformat(a.since).timestamp()
prices = json.load(open(a.prices)) if a.prices else {}
prices = {k: v for k, v in prices.items() if isinstance(v, dict)}
WORKTREE = re.compile(r"\.claude/worktrees/([A-Za-z0-9._+-]+)")
KEYS = ("input", "cache_read", "cache_write", "output")


def records(path):
    if os.path.getmtime(path) < since_ts:
        return
    with open(path, errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and a.since <= r.get("timestamp", "") < a.until:
                yield r


def cost(model, c):
    """API-equivalent $ of one response, or None if the model has no price entry.
    c: input, cache_read, cw5, cw1 (cache writes by TTL), output."""
    p = prices.get(model)
    if not p:
        return None
    if "long" in p and c["input"] + c["cache_read"] + c["cw5"] + c["cw1"] > p.get("long_threshold", 10**12):
        p = p["long"]
    return (c["input"] * p.get("input", 0) + c["cache_read"] * p.get("cache_read", 0)
            + c["cw5"] * p.get("cache_write", 0) + c["cw1"] * p.get("cache_write_1h", 2 * p.get("input", 0))
            + c["output"] * p.get("output", 0)) / 1e6


def parse_usage(u):
    """Normalise a usage dict -> (call, assumed_ttl). Writes are split into 5m / 1h when reported."""
    total = u.get("cache_creation_input_tokens", 0) or 0
    cc = u.get("cache_creation")
    assumed = False
    if isinstance(cc, dict) and ("ephemeral_1h_input_tokens" in cc or "ephemeral_5m_input_tokens" in cc):
        cw1 = min(cc.get("ephemeral_1h_input_tokens", 0) or 0, total)
    else:
        cw1, assumed = 0, total > 0
    return {"input": u.get("input_tokens", 0) or 0, "cache_read": u.get("cache_read_input_tokens", 0) or 0,
            "cw5": total - cw1, "cw1": cw1, "output": u.get("output_tokens", 0) or 0}, assumed


class Agent:
    def __init__(self):
        self.calls = 0
        self.u = collections.Counter()
        self.peak = 0
        self.model = None
        self.role = None
        self.worktree = None
        self.usd = 0.0

    def note(self, r):
        """Per-record metadata (role, worktree named by the first user prompt)."""
        self.role = self.role or r.get("attributionAgent")
        if self.worktree is None and r.get("type") == "user":
            text = json.dumps((r.get("message") or {}).get("content", ""))
            hit = WORKTREE.search(text)
            self.worktree = hit.group(1).rstrip(".") if hit else "-"

    def add(self, model, c, usd):
        self.calls += 1
        self.u.update({"input": c["input"], "cache_read": c["cache_read"],
                       "cache_write": c["cw5"] + c["cw1"], "output": c["output"]})
        self.peak = max(self.peak, c["input"] + c["cache_read"] + c["cw5"] + c["cw1"])
        self.model = model
        self.usd += usd or 0.0

    @property
    def ctx(self):
        return self.u["input"] + self.u["cache_read"] + self.u["cache_write"]


class Resp:
    """All copies of one message.id (or one unidentified record)."""
    __slots__ = ("agent", "fkey", "is_sub", "min_ts", "best", "best_final", "final_tuples", "assumed", "model")

    def __init__(self, agent, fkey, is_sub, ts):
        self.agent, self.fkey, self.is_sub, self.min_ts = agent, fkey, is_sub, ts
        self.best = self.best_final = None
        self.final_tuples = set()
        self.assumed = False
        self.model = None


dispatch = collections.Counter()
seen_dispatch = set()
main = collections.defaultdict(Agent)  # model -> Agent (main sessions, all files)
sub_agents = []
inventory = []
resps = {}            # message.id -> Resp
unident = []          # Resp per record without message.id
raw = 0
sidechain_skipped = 0
subs, mains = [], []
for dd in dirs:
    s = sorted(glob.glob(os.path.join(dd, "*", "subagents", "*.jsonl")))
    m = sorted(glob.glob(os.path.join(dd, "*.jsonl")))
    inventory.append((dd, len(m), len(s)))
    subs += s
    mains += m

for f, is_sub in [(f, True) for f in subs] + [(f, False) for f in mains]:
    fag = Agent() if is_sub else None
    if is_sub:
        sub_agents.append(fag)
    for r in records(f):
        if fag:
            fag.note(r)
        m = r.get("message") or {}
        content = m.get("content")
        if not is_sub and r.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                    if b.get("id") in seen_dispatch:
                        continue
                    seen_dispatch.add(b.get("id"))
                    i = b.get("input") or {}
                    dispatch[(i.get("subagent_type") or "(untyped)") + (f" model={i['model']}" if i.get("model") else "")] += 1
        u = m.get("usage")
        if not (u and m.get("model")) or m["model"] == "<synthetic>":
            continue
        if not is_sub and r.get("isSidechain"):
            sidechain_skipped += 1
            continue
        raw += 1
        call, assumed = parse_usage(u)
        mid = m.get("id")
        ts = r.get("timestamp", "")
        if mid:
            rs = resps.get(mid)
            if rs is None:
                rs = resps[mid] = Resp(fag, f, is_sub, ts)
        else:
            rs = Resp(fag, f, is_sub, ts)
            unident.append(rs)
        rs.min_ts = min(rs.min_ts, ts)
        cand = (call["output"], call, m["model"], assumed)
        if rs.best is None or cand[0] > rs.best[0]:
            rs.best = cand
        if m.get("stop_reason"):
            rs.final_tuples.add((call["input"], call["cache_read"], call["cw5"] + call["cw1"], call["output"]))
            if rs.best_final is None or cand[0] > rs.best_final[0]:
                rs.best_final = cand

# resolve each response
partial = conflicts = assumed_ttl = 0
unpriced = collections.defaultdict(collections.Counter)  # model -> token totals
by_file = collections.defaultdict(list)
total_usd = 0.0
for rs in list(resps.values()) + unident:
    pick = rs.best_final or rs.best
    if rs.best_final is None:
        partial += 1
    if len(rs.final_tuples) >= 2:
        conflicts += 1
    _, c, model, assumed = pick
    if assumed:
        assumed_ttl += 1
    usd = cost(model, c) if prices else 0.0
    if usd is None:
        t = unpriced[model]
        t["responses"] += 1
        t.update({"input": c["input"], "cache_read": c["cache_read"], "cache_write": c["cw5"] + c["cw1"], "output": c["output"]})
        usd = 0.0
    total_usd += usd
    ag = rs.agent if rs.is_sub else main[model]
    ag.add(model, c, usd)
    by_file[rs.fkey].append((rs.min_ts, c, model, usd))

# cache rewrites after a >5 min gap (responses idx>0 in a file)
def _t(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None

rw_n, rw_usd, rw_write_usd = 0, 0.0, 0.0
for items in by_file.values():
    items.sort(key=lambda x: x[0])
    for i in range(1, len(items)):
        ts, c, model, usd = items[i]
        t0, t1 = _t(items[i - 1][0]), _t(ts)
        w = c["cw5"] + c["cw1"]
        if t0 is None or t1 is None or w <= 30_000 or c["cache_read"] >= w or t1 - t0 <= 300:
            continue
        rw_n += 1
        rw_usd += usd
        p = prices.get(model)
        if p:
            rw_write_usd += (c["cw5"] * p.get("cache_write", 0) + c["cw1"] * p.get("cache_write_1h", 2 * p.get("input", 0))) / 1e6

agents = [x for x in sub_agents if x.calls]
for x in agents:
    x.role = x.role or "(unknown)"
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


print("transcript dirs (main sessions / subagent files):")
for dd, nm, ns in inventory[:25]:
    print(f"  {nm:4} / {ns:5}  {dd}")
if len(inventory) > 25:
    print(f"  ... {len(inventory) - 25} more dirs ({sum(x[1] for x in inventory)} main / {sum(x[2] for x in inventory)} subagent files in total)")
n_unique = len(resps)
print("\ncoverage:")
print(f"  dirs scanned:            {len(dirs)}")
print(f"  raw usage records:       {raw}  (+{sidechain_skipped} isSidechain records in main files skipped)")
print(f"  unique responses:        {n_unique}  (by message.id)")
print(f"  duplicates collapsed:    {raw - n_unique - len(unident)}")
print(f"  partial:                 {partial}  (no final copy; usage may be low)")
print(f"  conflicts:               {conflicts}  (>=2 final copies with different usage)")
print(f"  unidentified:            {len(unident)}  (no message.id; each counted)")
print(f"  assumed_ttl:             {assumed_ttl}  (no 5m/1h breakdown; priced as 5-minute writes)")
print(f"  unpriced models:         {', '.join(sorted(unpriced)) or 'none'}")
print(f"\nsince:   {a.since}  until: {a.until}\nNOTE: estimates; processed tokens != cost != Max quota (see --prices)")
if prices:
    print(f"TOTAL API-equivalent (priced models only): ${total_usd:,.4f}")
print(f"\nlarge cache rewrites after a >5 min gap (consistent with TTL expiry; cause not proven): "
      f"{rw_n} responses, ${rw_usd:,.2f} total response cost, ${rw_write_usd:,.2f} of it cache writes")
if unpriced:
    print("\nUNPRICED (no entry in --prices; NOT included in any $ figure):")
    for model, t in sorted(unpriced.items()):
        print(f"  {model:44} responses={t['responses']} in={t['input']} cache_r={t['cache_read']} "
              f"cache_w={t['cache_write']} out={t['output']}")
print("\ndispatches by subagent_type (main transcripts):")
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
if a.strict and (unpriced or conflicts):
    print(f"--strict: {len(unpriced)} unpriced model(s), {conflicts} conflict(s)", file=sys.stderr)
    sys.exit(2)
