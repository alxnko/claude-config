@RTK.md
# graphify
- **graphify** (`~/.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.

# Scratch space discipline

`/tmp` is a RAM-backed tmpfs (~16G, 50% of RAM) and is swap-compressed into zram.
Anything written there consumes physical memory, not disk.

- The session scratchpad is for **small** working files: diffs, logs, notes, short scripts.
- **Never** run builds, installs, or artifact-producing jobs inside the scratchpad.
  Build output goes in the project's own build dir, or under `/var/tmp` (real disk).
- Never point `GRADLE_USER_HOME`, `npm_config_cache`, `CARGO_TARGET_DIR`, or any
  build/cache root at `/tmp`.
- Delete large intermediates as soon as you're done with them; don't leave
  multi-hundred-MB trees behind for the next session to inherit.
- If a Bash call fails with ENOSPC, check `df -h /tmp` before anything else.

# Model routing (default since 2026-09-29)

Two tiers only, both at medium effort: **Opus 5.5** is the orchestrator and handles escalations; **Sonnet 5.5** is the default worker. Never use Fable.
- Dispatch subagents by `subagent_type` from `~/.claude/agents/`: `sonnet-worker` (default), `opus-worker`, `sonnet-reviewer`, `opus-reviewer`. Each carries its model and `effort: medium`.
- Route by the **judgment a task needs, not its size**; optimise cost per *completed* task. Opus handles architecture, ambiguity, cross-cutting, security/privacy, data lifecycle, risky migrations, hard debugging, the project's own declared high-risk domains (defined per project in its CLAUDE.md or memory, never here), and anything a Sonnet worker failed. When Sonnet struggles, escalate to Opus rather than raising its effort.
- Pick the reviewer by the risk of the change: clearly routine → sonnet-reviewer; high-risk **or unclear** → opus-reviewer. The orchestrator independently re-verifies every worker's claims before merging.
- Don't trust the agent label: when testing or doubting routing, verify the model that actually ran (`/tasks`, the transcript, `effective_model` in the tool result where exposed).
- Full rules: `~/.claude/skills/shipping-to-merge/delegating-to-subagents.md` § Model routing.
