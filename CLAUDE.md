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

Three models, all at medium effort: **Opus 5.5** is the orchestrator and handles escalations, high-risk work and high-risk/unclear review; **Sonnet 5.5** is the default worker and routine reviewer; **Haiku 5.5** does read-only lookups (`haiku-scout`) and, EXPERIMENTALLY since 2026-10-09, small isolated low-risk builds (`haiku-worker`), never judgment, review or high-risk code. Never use Fable. Claude Code never uses the Max plan's monthly API credit (reserved for other work, 2026-10-08).
- Dispatch subagents by `subagent_type` from `~/.claude/agents/`: `sonnet-worker` (default), `opus-worker`, `sonnet-reviewer`, `opus-reviewer`, `haiku-scout`, `haiku-worker`. Each carries its model, `effort: medium` and a `maxTurns` backstop. A repo's tracked `.claude/agents/` copy overrides the personal one; keep them in sync.
- **Cost = calls × context, ranked by PRICE, not token share** (2026-10-09→12, API-equivalent via `--prices`: Opus subagents 37% of cost on 21% of tokens, Sonnet 35% on 52%, Opus orchestrator 28%, Haiku ~0%). Output and cache writes cost far more per token than cache reads. Keep tasks small (one concern per PR, split by platform); workers soft-hand-off at ~75 tool calls / ~120–150k context (`maxTurns` is only a brake: sonnet-worker 110 trial, haiku-worker 30); review-fix rounds go to a FRESH agent with a precise handoff unless the old one is still small; never idle-poll; never let a worker spawn build sub-agents; re-review only the delta. Orchestrator: checkpoint to `work_state`, then a fresh session / `/clear` at each wave boundary (soft target ~200k; keep context mid-investigation). Primary metric: priced cost per accepted, verified PR including rework; the operator cross-checks plan quota with `/usage` (API-equivalent is not Max quota). Every model stays at medium; change one routing rule per wave of data. Details: `~/.claude/skills/shipping-to-merge/delegating-to-subagents.md` § Cost discipline.
- Route by the **judgment a task needs, not its size**; optimise cost per *completed* task. **Opus decides, Sonnet builds** (operator, 2026-10-01): for high-risk work (security/privacy, data lifecycle, risky migrations, the project's declared high-risk domains) the Opus orchestrator settles the design in the brief, `sonnet-worker` implements it, and `opus-reviewer` reviews behavior changes there. Touching a high-risk subsystem is not by itself a reason for Opus; unresolved judgment is. `opus-worker` is for judgment that cannot be settled up front: architecture, ambiguous or conflicting requirements, hard multi-system debugging, and anything a Sonnet worker failed. When Sonnet struggles, escalate to Opus rather than raising its effort.
- Keep contexts small: one focused task per agent, a fresh agent (with a short handoff) for a new task, concise reports. Measure with `~/.claude/scripts/subagent-usage.py --prices ~/.claude/scripts/prices.json`.
- Pick the reviewer by the consequence of the change (not its path): clearly routine → sonnet-reviewer; high-risk **or unclear** → opus-reviewer, including any later delta that changes behaviour or a test's assertion strength (only a purely mechanical delta on a high-risk PR, after Opus verified the invariant, may go to sonnet-reviewer). The orchestrator independently re-verifies every worker's claims before merging.
- Don't trust the agent label: when testing or doubting routing, verify the model that actually ran (`/tasks`, the transcript, `effective_model` in the tool result where exposed).
- Full rules: `~/.claude/skills/shipping-to-merge/delegating-to-subagents.md` § Model routing.
