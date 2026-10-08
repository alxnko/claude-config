# claude-config

My portable Claude Code setup: global instructions, agents, my own skills, and
a secrets-free settings template. The repo **is** `~/.claude`, with an
allowlist `.gitignore`: everything is ignored except the files named in it. So
transcripts, memory, history, caches, plugin downloads and credentials can
never be committed.

## What's in it

| Path | What |
|---|---|
| `CLAUDE.md`, `RTK.md` | Global instructions loaded in every project |
| `agents/` | `sonnet-worker`, `opus-worker`, `sonnet-reviewer`, `opus-reviewer` (medium effort; model routing policy) |
| `skills/shipping-to-merge/`, `skills/graphify/` | My own skills |
| `settings.portable.json` | `settings.json` with secrets and machine-local values removed (`$HOME` for paths) |
| `skills-manifest.txt` | Third-party skills that were symlinks, so not committed; reinstall from their sources |
| `hooks/prune-scratchpads.sh` | SessionStart hook |
| `scripts/subagent-usage.py` | Subagent dispatches by type and token/context usage by model, from transcripts — measures the routing policy |
| `apply-model-ceiling.py` | Enforces the model policy (no Fable; Opus orchestrator, Sonnet default worker, medium effort) |
| `scripts/` | `export-settings.py`, `install-settings.py`, `pre-commit` |

**Never committed, by design:** `settings.json` (it holds tokens), `.credentials.json`,
`.claude.json`, `projects/` (transcripts and per-project memory), `history.jsonl`,
`plugins/` (downloaded), and every cache or backup.

## New device

**Order: install Claude Code first, then pull this repo into `~/.claude`.**
Logging in creates `~/.claude` and your credentials, which stay local. The
repo then only adds its tracked files on top.

```bash
# 1. Install Claude Code (https://docs.claude.com/en/docs/claude-code), run it once and log in
claude            # then /exit

# 2. Pull this repo into the existing ~/.claude (the folder is not empty, so no plain `git clone`)
cd ~/.claude
git init -b main
git remote add origin git@github.com:alxnko/claude-config.git   # or https://github.com/alxnko/claude-config.git
git fetch origin
git checkout -f -B main --track origin/main   # overwrites only the tracked files listed above

# 3. Build this machine's settings.json from the template.
#    It keeps local tokens and endpoints, backs the old file up, and skips hooks whose program is missing.
python3 scripts/install-settings.py
python3 apply-model-ceiling.py        # optional: re-asserts the model policy

# 4. Protect future commits
ln -sf ../../scripts/pre-commit .git/hooks/pre-commit

# 5. Restart Claude Code. Plugins listed in settings (superpowers, claude-mem) install from
#    their marketplaces; check with /plugin. Reinstall the skills in skills-manifest.txt
#    if you want them.
```

**Cloning first also works.** `git clone git@github.com:alxnko/claude-config.git ~/.claude`
into a folder that doesn't exist yet, then install Claude Code, run
`python3 ~/.claude/scripts/install-settings.py`, and log in. Claude Code adds its
own files next to the repo's, and the allowlist keeps them untracked.

**Optional tools the hooks call:** `rtk`, `caveman`. Without them,
`install-settings.py` leaves those hooks out and lists them. Install the tools
and re-run it to enable them.

**Machine-local settings** (telemetry endpoints and tokens, a local API proxy) are
never exported. Add them to `~/.claude/settings.json` by hand on each device; the
installer preserves them on every later run.

## Keeping devices in sync

```bash
# after changing instructions, agents, skills or settings on any device
cd ~/.claude
git add -A && git commit -m "…" && git push     # the pre-commit hook re-exports settings and scans for secrets

# on the other devices
cd ~/.claude && git pull && python3 scripts/install-settings.py
```

`git add -A` is safe here: the allowlist means only the files above can ever be
staged.
