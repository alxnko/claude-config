#!/usr/bin/env bash
# Prune Claude Code session scratchpads whose entire tree has been untouched
# for MAX_AGE_DAYS. Live sessions write constantly, so they are never stale.
# Runs at SessionStart. Safe to run by hand.
set -uo pipefail

MAX_AGE_DAYS="${CLAUDE_SCRATCH_MAX_AGE_DAYS:-2}"
UID_N="$(id -u)"

# The harness passes hook JSON on stdin; skip our own session defensively.
SELF=""
if [ ! -t 0 ]; then
  SELF="$(timeout 2 cat 2>/dev/null | jq -r '.session_id // empty' 2>/dev/null || true)"
fi

freed=0
for base in /tmp /var/tmp; do
  root="$base/claude-$UID_N"
  [ -d "$root" ] || continue
  [ -O "$root" ] || continue          # must be owned by us

  # Session dirs sit at <root>/<sanitized-project>/<session-uuid>
  while IFS= read -r -d '' d; do
    [ -n "$d" ] || continue
    case "$d" in */"$SELF") continue;; esac
    # If nothing anywhere in the tree is newer than the cutoff, it is dead.
    if [ -z "$(find "$d" -newermt "-${MAX_AGE_DAYS} days" -print -quit 2>/dev/null)" ]; then
      sz=$(du -sm "$d" 2>/dev/null | cut -f1)
      rm -rf -- "$d" && freed=$(( freed + ${sz:-0} ))
    fi
  done < <(find "$root" -mindepth 2 -maxdepth 2 -type d \
             -regextype posix-extended \
             -regex '.*/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' -print0 2>/dev/null)

  find "$root" -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null
done

if [ "$freed" -gt 0 ]; then
  printf '{"systemMessage":"Pruned %s MB of Claude scratchpads older than %s days."}\n' "$freed" "$MAX_AGE_DAYS"
fi
exit 0
