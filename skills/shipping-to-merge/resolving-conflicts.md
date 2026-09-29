# Resolving Conflicts Safely (nothing broken, nothing lost)

Read this the moment any git command prints `CONFLICT`, before you touch a single file.

The failure mode is **silent loss**: blindly taking one side, or a rebase dropping commits, so the
merge looks clean and the tests pass while real changes have vanished. Nothing downstream catches it —
the gate can only verify the code that survived.

## 1. Snapshot first — make it unrecoverable-proof

```bash
rtk proxy git rev-parse HEAD          # record your tip; written down = recoverable via reflog
rtk proxy git branch backup/<branch>  # cheap safety branch pointing at current work
```

Do this BEFORE resolving. It is the difference between "undo" and "reconstruct from memory".

## 2. Prefer merge-in over rebase

```bash
rtk proxy git fetch origin
rtk proxy git merge origin/<default-branch>   # NOT rebase, unless the repo demands linear history
```

Merge preserves your commits as-is and gives one clear resolution point. Rebase rewrites your commits
and is where they get dropped under conflict. If the repo demands linear history, rebase — then verify
the commit count before/after.

## 3. Resolve by understanding BOTH sides — never blanket-accept

- NEVER `git checkout --ours/--theirs`, never `git merge -X ours/theirs` across the board. That
  discards one side wholesale — that IS the loss, and it looks like a clean resolution.
- Open each conflicted file. Read both sides. Produce a resolution that keeps the **intent of both**.
- If you cannot tell what a side meant: **STOP and ask.** Do not guess. A wrong guess here is
  indistinguishable from success until someone notices their feature is gone.
- Delete-vs-edit and rename conflicts drop content most often — decide those explicitly, out loud.

## 4. Verify nothing was lost — with output, before committing the merge

```bash
rtk proxy git diff --stat HEAD                      # files touched by the resolution — sanity-check the set
rtk proxy git log --oneline backup/<branch>..HEAD   # confirm none of your commits disappeared
rtk proxy git diff backup/<branch>                  # what actually changed vs your pre-merge work
rtk proxy git grep -nE '^(<<<<<<<|=======|>>>>>>>)' || echo clean   # no leftover markers
```

Then re-run the **full gate** (SKILL.md step 3). A merge resolution is new code — it must pass the gate
before push, no exceptions.

## 5. If it goes wrong

- Mid-merge: `git merge --abort`
- After: `git reset --hard <recorded-tip>` or `git reset --hard backup/<branch>`

Nothing is lost while the backup branch and the reflog exist. Delete `backup/<branch>` only after the
PR is merged and verified.

## Report

State explicitly what conflicted, how you resolved each one, and paste the section-4 output proving no
commits vanished. "Resolved conflicts" with no evidence = treat as unverified.
