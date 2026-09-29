#!/usr/bin/env python3
"""Write settings.portable.json (secrets and machine-local values removed) and
skills-manifest.txt from the live ~/.claude. Run before committing."""
import json, os, re
from pathlib import Path

C = Path.home() / ".claude"
HOME = str(Path.home())
# env keys that are secrets or point at services on THIS machine only
DROP_ENV = re.compile(r"^(OTEL_|ANTHROPIC_BASE_URL$|ANTHROPIC_API_KEY$|ANTHROPIC_AUTH_TOKEN$|_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL$|CLAUDE_CODE_ENABLE_TELEMETRY$|CLAUDE_CODE_ENHANCED_TELEMETRY_BETA$)")
SECRETISH = re.compile(r"(?i)(bearer\s+[a-z0-9._-]{12,}|token|secret|password|api[_-]?key)")

s = json.loads((C / "settings.json").read_text())
env = {k: v for k, v in s.get("env", {}).items() if not DROP_ENV.match(k)}
for k, v in env.items():
    if SECRETISH.search(k) or SECRETISH.search(v):
        raise SystemExit(f"refusing: env {k} looks secret; add it to DROP_ENV or remove it")
s["env"] = env
text = json.dumps(s, indent=2).replace(HOME, "$HOME")
(C / "settings.portable.json").write_text(text + "\n")

lines = []
for p in sorted((C / "skills").iterdir()):
    if p.is_symlink():
        lines.append(f"{p.name} -> {os.readlink(p).replace(HOME, '$HOME')}")
(C / "skills-manifest.txt").write_text(
    "# Third-party skills installed as symlinks on the source machine (not committed).\n"
    "# Reinstall them from their own sources on a new device.\n" + "\n".join(lines) + "\n")
print(f"wrote settings.portable.json ({len(env)} env keys kept) and skills-manifest.txt ({len(lines)} skills)")
