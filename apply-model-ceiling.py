#!/usr/bin/env python3
"""Cap Claude Code at Opus on this machine.

Sets, idempotently, in ~/.claude/settings.json:
  availableModels          allowlist; fable is absent, so nothing can resolve to it.
                           Entries are FAMILY aliases ("opus" = any opus version).
                           Order matters: if the tier default is not allowed, Default
                           resolves to the FIRST entry, so opus leads.
  enforceAvailableModels   the allowlist is inert without this flag.
  env.CLAUDE_CODE_SUBAGENT_MODEL
                           default model for subagents when the Agent call omits one.
                           Precedence: explicit model > agent frontmatter > this >
                           INHERIT PARENT. That last fallback is why subagents were
                           silently running on the parent's model.

Deliberately NOT set: CLAUDE_CODE_SUBAGENT_MODEL_FORCE. It discards every explicit
model override, so intentional sonnet/haiku subagents would be upgraded to opus —
that raises cost. This is a ceiling, not a pin.

Safe to re-run. Writes a timestamped backup before changing anything.
"""
import json, pathlib, shutil, sys, datetime

ALLOWLIST = ["opus", "sonnet", "haiku"]
SUBAGENT_MODEL = "sonnet"  # default worker since 2026-09-29; escalations pass model "opus" or use the opus-worker agent

p = pathlib.Path.home() / ".claude" / "settings.json"
p.parent.mkdir(parents=True, exist_ok=True)

if p.exists():
    try:
        settings = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"refusing to touch {p}: it is not valid JSON ({e}). Fix it first.")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = p.with_name(f"settings.json.bak-{stamp}")
    shutil.copy2(p, backup)
    print(f"backup: {backup}")
else:
    settings = {}

before = json.dumps(settings, sort_keys=True)
settings["availableModels"] = ALLOWLIST
settings["enforceAvailableModels"] = True
settings.setdefault("env", {})["CLAUDE_CODE_SUBAGENT_MODEL"] = SUBAGENT_MODEL
settings["model"] = "opus"          # orchestrator
settings["effortLevel"] = "medium"  # operator 2026-09-29: opus medium + sonnet medium

if json.dumps(settings, sort_keys=True) == before:
    print("already applied; nothing changed")
else:
    p.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"applied to {p}")

print(f"  availableModels        = {settings['availableModels']}")
print(f"  enforceAvailableModels = {settings['enforceAvailableModels']}")
print(f"  CLAUDE_CODE_SUBAGENT_MODEL = {settings['env']['CLAUDE_CODE_SUBAGENT_MODEL']}")
print("\nVerify (should print claude-opus-5, not a fable model):")
print("  cd /tmp && claude -p 'Reply with exactly: ok' --model fable >/dev/null")
print("  python3 - <<'EOF'\n"
      "import json,glob,os\n"
      "f=max(glob.glob(os.path.expanduser('~/.claude/projects/-tmp/*.jsonl')),key=os.path.getmtime)\n"
      "print(sorted({json.loads(l).get('message',{}).get('model') for l in open(f)\n"
      "              if json.loads(l).get('type')=='assistant'} - {None}))\n"
      "EOF")
