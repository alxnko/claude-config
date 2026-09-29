---
name: shipping-to-merge
description: Use when taking a finished repo change all the way to merged — isolating work in a worktree+branch, verifying with the full local gate, opening one PR per repo, babysitting reviews and CI, and auto-merging to the repo's default branch once fully green. Triggers include "ship this", "open a PR and merge when it's green", "take this to master", per-repo delivery, or driving an existing PR to merge.
---

# Shipping to Merge

## Overview

Drive one repo's change from working tree to merged on the default branch, with no skipped gate. The whole value is the gates: this skill exists because agents repeatedly merge too early, push nothing while claiming "fixed", open PRs off a stale base, or squash-merge. Every step below is a real, observed failure turned into a checkpoint.

**Core principle:** Never advance a stage until the prior stage's gate is *verified with command output*, not assumed. Evidence before assertions. (REQUIRED BACKGROUND: `superpowers:verification-before-completion`.)

**Scope per invocation:** ONE repo, ONE branch, ONE PR. Multiple repos → run this whole cycle serially, repo A fully merged before starting B. This matches "one PR per repo, when fully ready."

## When to Use

- A repo's change is built (or nearly) and you want it isolated, verified, PR'd, and merged.
- You have an open PR and want it babysat to a clean merge.
- NOT for: exploratory work, work the user hasn't asked to ship, or anything spanning repos in one branch.

## The Pipeline (each arrow is a gate — do not cross it unverified)

```
worktree+branch → build → FULL verify → CODE REVIEW → push → PR → babysit (reviews+CI) → final re-verify → merge → clean up worktree
```

### 1. Isolate — worktree + fresh branch
- **Worktree location is fixed: `<repo>/.claude/worktrees/<branch>` — never the repo root, never a sibling `../wt-*` dir.** Create it explicitly so the worktree skill's default placement can't dump `wt-*` into the project root or a sibling folder:
  ```bash
  root=$(git rev-parse --show-toplevel)
  git -C "$root" worktree add "$root/.claude/worktrees/<branch>" -b <branch> origin/<default-branch>
  ```
  `.claude/worktrees/` is gitignored in these repos; if it isn't, add it. Pass this exact path when delegating to `superpowers:using-git-worktrees`.
- Branch off the repo's **current default-branch tip**, not whatever is checked out.
- Detect the default branch — it is NOT always `master`:
  ```bash
  gh repo view --json defaultBranchRef -q .defaultBranchRef.name   # e.g. master | test | mobile_app_dev
  ```
- Confirm you are on the worktree's branch and path before editing: `git rev-parse --show-toplevel` and `git branch --show-current`. (Absolute worktree paths have silently hit the main checkout before; parallel agents have hijacked the branch.)

### 2. Build
- Implement on the branch. Per-phase, run only the **scoped fast lane** (`scripts/test-fast.sh tests/<domain>` or the repo's equivalent). Commit a phase only when its fast lane is green.
- Commit messages: Conventional Commits. **Never** `--no-verify`.

### 3. FULL verify — the pre-PR gate (MANDATORY, no exceptions)
- Run the repo's complete gate (`scripts/verify.sh`, or the project's documented full lint+types+tests command). Fix **everything**. Open the PR only when it is fully green.
- Confirm base is not stale before PR:
  ```bash
  rtk proxy git fetch origin
  rtk proxy git diff --shortstat origin/<default-branch>..HEAD   # raw range; plain `rtk git diff` lies (summary, not patch)
  ```
  If default-branch moved under you, rebase/merge it in and re-run the full gate.

### 3.5. CODE REVIEW — mandatory, BEFORE you push/open the PR (REQUIRED SUB-SKILL: `superpowers:requesting-code-review`)

Green CI + passing tests is **not** review — every bug this gate has caught shipped with both green. Review the committed work on the branch *before* it becomes a PR, so findings are fixed in the branch instead of argued in PR comments. Every change touching product code gets a reviewer subagent. Config-only changes (CI yaml, editorconfig, lockfiles) may skip — state that explicitly.

**Fill the skill's actual template — don't improvise one.** It lives at `superpowers/skills/requesting-code-review/code-reviewer.md`; read it and fill it. Hand-rolled prompts silently drop its checklist (testing-verifies-real-behavior-not-mocks, migration strategy, backward compatibility, plan-alignment, the explicit Ready-to-merge verdict, and "if the PLAN itself is wrong, say so").

**The reviewer MUST be given the requirements, not just the diff.** Fill all four placeholders: `{DESCRIPTION}`, `{PLAN_OR_REQUIREMENTS}` (the actual plan/task text the change must satisfy — a file path is not enough if the reviewer won't open it), `{BASE_SHA}`, `{HEAD_SHA}`. A reviewer without requirements can only check the code against itself.

**When a spec or plan governs the change, review the code AGAINST it — not just for local correctness.** If the repo has a spec, design doc, or an implementation plan with acceptance criteria that this change implements (e.g. `docs/specs/*`, `docs/plans/*`, an ADR, a ticket), the reviewer MUST be handed that source text (paste it or the exact excerpt — a bare path the reviewer won't open is a skipped requirement) and MUST answer, per governing requirement: *is this requirement actually met by the code, is any invariant/acceptance-criterion violated, and does the change silently deviate from what the spec/plan mandates?* A change whose diff is internally clean but that fails a spec requirement, weakens a documented invariant, or drifts from the plan is a FAIL — "the code is self-consistent" is not the bar. Include the standing instruction *"if the PLAN or SPEC itself is wrong, say so"* so a reviewer who spots a bad requirement flags it rather than faithfully implementing a mistake. Where no spec/plan governs the change, review against the stated `{DESCRIPTION}`/requirements as before.

**Add one instruction beyond the template:** *"Trace what this change breaks elsewhere — list every existing read/write path that depends on what it altered."* Cross-cutting integration gaps are the highest-value class of finding and never show up in a diff-local read.

**Do NOT hand the reviewer a threat-list.** Enumerating the risks you already thought of ("check for TOCTOU, IDOR, timing") *narrows the reviewer's aperture to your list* and it will miss what you didn't name — this is an observed failure, not a theory. Anchor in the requirements, let the reviewer reason outward. Targeted probes are a supplement AFTER an open-ended pass, never the frame.

**A finding is a claim, not proof.** Verify each one yourself against the committed file before acting — reviewers cite stale mid-edit state, misread harness limitations as code bugs, and flag pre-existing/out-of-scope issues. Equally: do not dismiss a finding because tests pass. Sequential tests pass while a race ships.

Triage: fix **Critical + Important** before you open the PR. Record **Minor** (fix or explicitly defer with a reason). If the reviewer is wrong, push back with evidence — and say so in the report. Re-run the step-3 full gate after fixes, then proceed to push.

### 4. Push & open the PR
- Push the branch. **Verify the pushed tip equals your local HEAD** (`git rev-parse HEAD` == `git rev-parse @{u}`). "Fixed/pushed" claims have been false before — confirm.
- One PR, full metadata in the body. Target the default branch.

### 5. Babysit — reviews + CI
- Watch CI to completion. If it fails: read the actual failing job log, fix the **root cause**, push, re-confirm tip, watch again. Loop until green. Do not declare green from a stale view — confirm the run is for the current tip.
- Triage every review comment with `review-resolve` (pass the PR number). Fix real findings; reply with rationale on false ones. Resolve Gemini/Copilot threads.
- `claude-mem:babysit` can drive this watch loop.

### 6. Final re-verify (the merge gate)
All must be true, each checked with output — not memory:
- [ ] CI fully green **for the current pushed tip** (not an earlier run).
- [ ] **Step 3.5 code review ran** (or was explicitly declared config-only), and every Critical/Important is fixed or has a recorded rationale. Never merge product code that no reviewer saw. **If a spec/plan governed the change, the review verified the code AGAINST it (requirements met, no invariant/acceptance-criterion violated), not just for local correctness.**
- [ ] All review threads resolved.
- [ ] Base still current (`git diff --shortstat origin/<default>..HEAD` shows only your work).
- [ ] **Conflicts: either state "no conflicts occurred", OR confirm `resolving-conflicts.md` was read and followed, pasting its loss-check output** (`git log --oneline backup/<branch>..HEAD`). This box cannot be ticked silently — an unanswered conflict question is an unverified merge.
- [ ] Repo-specific invariants hold — e.g. for Alembic repos, `alembic heads` shows exactly **1** (back-to-back PRs cause dual heads).

### 7. Merge
- **Merge commit only. Never squash, never rebase-merge.**
  ```bash
  gh pr merge <n> --merge
  ```
- Merge to the repo's **default branch** (detected in step 1 — master/test/mobile_app_dev as applicable).
- After merge: `rtk proxy git diff <default>..HEAD` raw to confirm the merged content is what you intended (back-to-back merges have clobbered symbols before).

### 8. Clean up the worktree — remove the folder, don't just unregister
Once the PR is merged and verified, tear down the worktree so no stale copy is left on disk. `git worktree remove` deletes the folder **and** the registry entry; `git worktree prune` alone only unregisters and leaves the directory behind — never stop at prune.
```bash
root=$(git -C <main-repo> rev-parse --show-toplevel)   # run from the MAIN checkout, not the worktree
git -C "$root" worktree remove "$root/.claude/worktrees/<branch>" --force
rm -rf "$root/.claude/worktrees/<branch>"              # belt-and-suspenders: if the dir survived (locked/partial), delete it
git -C "$root" worktree prune                          # drop any now-dangling registry entry
git -C "$root" branch -d <branch>                      # delete the merged local branch
```
- Confirm the folder is gone: `test -d "$root/.claude/worktrees/<branch>" && echo STILL-THERE || echo removed`.
- Delete `backup/<branch>` too if you made one during conflict resolution.

## DELEGATING the build — load the requirements first

**Trigger (not a judgement call): you are about to dispatch a subagent to build any part of this change.**

Before you write that prompt: **Read `delegating-to-subagents.md` in this skill's directory and copy its requirement list into the prompt verbatim.**

Why this is not optional: **a subagent only does what its prompt says, so an omitted requirement is a skipped gate** — silently, and you won't see it until the defect ships. Every gap observed in practice traces to a requirement left out of the dispatch. The file also carries the non-negotiable division: you MAY delegate the build (steps 1–3.5); you MUST NOT delegate the merge gate (steps 5–7) — a subagent's "done, green, pushed" is a *claim*, and it has been false.

If you do the build yourself, skip the file and say so.

## CONFLICT — stop and load the procedure

**Trigger (not a judgement call): any git command prints `CONFLICT`, or a merge/rebase/cherry-pick exits non-zero.**

When that happens: **STOP.** Do not open a conflicted file, do not resolve anything, do not reach for `--ours`/`--theirs`. **Read `resolving-conflicts.md` in this skill's directory first, then follow it.**

Why this is not optional: the failure mode is **silent loss**. Blanket-accepting one side, or rebasing through a conflict, deletes real work while the merge looks clean, the markers are gone, and the gate passes — because the gate can only check the code that survived. Nothing downstream catches it. And the file's first step (`git branch backup/<branch>`, *before* resolving) is what makes the mistake undoable — it is worthless if you read it afterwards.

Conflicts surface at step 3 (default branch moved under you) and step 6 (merge). If none occur, **say so explicitly in your report** — silence is not evidence of a clean merge.

## Merge Autonomy

This skill is **granted explicit standing authority to merge** once step 6 is fully green — it overrides the default "no merge without explicit ask" rule *for this skill only*. The grant is conditional: every box in step 6 verified with command output. Any unchecked box → STOP, do not merge, report what's blocking.

Deploy/promote to dev/prod is still NOT covered — merging to the default branch is the end of this skill.

## Red Flags — STOP

| Thought | Reality |
|---|---|
| "Tests passed earlier, skip the full gate" | Full gate is mandatory pre-PR. Run it. |
| "CI was green last I looked" | Confirm green for the *current* tip. Pushes invalidate prior runs. |
| "I pushed the fix" | Verify `HEAD == @{u}`. Claims of pushing have been false. |
| "Base is probably fine" | `git diff origin/<default>..HEAD` or it's stale. |
| "Squash is cleaner" | Merge commit only. Always. |
| "Default branch is master" | Detect it. FE=test, mobile=mobile_app_dev. |
| "Worktree dir is fine in the repo root" | NO. `<repo>/.claude/worktrees/<branch>` only. `wt-*` in root or `../` is wrong. |
| "`rtk git diff` shows the change" | That's a summary. Use `rtk proxy git diff` for the real patch/range. |
| "`git log`/`--graph` shows the merge landed" | rtk's filtered `log`/`graph` **lies**: observed showing no merge commit and wrong parents on a correct merge. Anything load-bearing (did the merge commit land? what are its parents?) needs `rtk proxy git log` or `git rev-parse`. |
| "I'll merge then check heads" | Check `alembic heads == 1` BEFORE merge. |
| "Just accept theirs/ours to clear the conflict" | That discards a whole side = silent loss. Read both, keep both intents. |
| "Rebase to tidy up before merge" | Rebase drops commits under conflict. Prefer `git merge`; verify commit count if you must rebase. |
| "Conflict resolved, push it" | Snapshot a backup branch first, re-run the full gate after, grep for leftover `<<<<<<<` markers. |
| "The subagent said it's green and pushed" | A claim, not evidence. Read the diff, confirm `HEAD==@{u}`, confirm CI green for that tip yourself. |
| "CI is green and tests pass, skip the review" | Every bug this gate caught shipped green. Sequential tests pass while a race ships. Review anyway. |
| "I'll list the risks so the reviewer focuses" | A threat-list *narrows* the reviewer to your list and blinds it to what you didn't name. Anchor in requirements; probe after. |
| "The reviewer found it, so it's real" | A finding is a claim. Verify against the committed file — stale mid-edit reads and harness quirks masquerade as bugs. |
| "That linter/IDE diagnostic is just stale mid-edit noise" | Verify before dismissing — the rule cuts BOTH ways. An undefined-name diagnostic was waved off as stale and shipped a `NameError` 500 to a live endpoint. Cheap to check: does the symbol exist in the committed file? |
| "Review after the PR is open" | Fix in the branch, not in PR comments. Review at step 3.5, before push. |
| "I'll just give the subagent a short brief" | An omitted requirement is a skipped gate. Paste the full build-subagent requirement list. |
| "Unit tests pass, no need to run the app" | Runtime changes (UI/endpoint/CLI) need behavioral verification. Run it, or say it wasn't run. |
| "More parallel agents = faster" | Past ~3 build agents per machine, load manufactures false reds and re-runs; everything gets slower. Cap at 3, full gate once per PR (see `delegating-to-subagents.md` resource rules). |
| "Subagent opened the PR, I can merge" | Orchestrator owns steps 5–7. Independently re-verify before merge — never hand off the merge gate. |

## Quick Reference

| Step | Gate to verify before advancing |
|---|---|
| Worktree | on correct branch+path, branched off live default tip |
| Build | scoped fast lane green per phase |
| Verify | full gate green + base not stale |
| Review | reviewer got the REQUIREMENTS + "what does this break elsewhere"; Critical/Important fixed; gate re-run |
| Push | pushed tip == local HEAD |
| PR | metadata complete, targets default branch |
| Babysit | CI green for current tip + all reviews resolved |
| Merge | step-6 checklist all output-verified → `gh pr merge --merge` |
| Clean up | `git worktree remove --force` (deletes folder), then `rm -rf` + `prune` — never just unregister |
