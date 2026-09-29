#!/usr/bin/env python3
"""Merge settings.portable.json into this machine's ~/.claude/settings.json.
Keeps local-only env keys (tokens, local endpoints) and backs the file up first.
Hooks whose program does not exist on this machine are skipped (listed)."""
import json, os, shlex, shutil, time
from pathlib import Path

C = Path.home() / ".claude"
HOME = str(Path.home())
portable = json.loads((C / "settings.portable.json").read_text().replace("$HOME", HOME))
target = C / "settings.json"
local = json.loads(target.read_text()) if target.exists() else {}
if target.exists():
    shutil.copy2(target, target.with_name(f"settings.json.bak-{int(time.time())}"))

def program_exists(cmd: str) -> bool:
    try:
        prog = shlex.split(cmd)[0]
    except ValueError:
        return False
    return os.path.exists(prog) if "/" in prog else shutil.which(prog) is not None

skipped = []
hooks = {}
for event, matchers in portable.get("hooks", {}).items():
    kept_m = []
    for m in matchers:
        hs = [h for h in m.get("hooks", []) if h.get("type") != "command" or program_exists(h["command"])]
        skipped += [f"{event}: {h['command'][:80]}" for h in m.get("hooks", []) if h not in hs]
        if hs:
            kept_m.append({**m, "hooks": hs})
    if kept_m:
        hooks[event] = kept_m
portable["hooks"] = hooks

merged = {**local, **portable}
merged["env"] = {**local.get("env", {}), **portable.get("env", {})}
target.write_text(json.dumps(merged, indent=2) + "\n")
print("merged settings.portable.json into settings.json")
for s in skipped:
    print("  skipped hook (program not installed here):", s)
