#!/usr/bin/env bash
# Run India-track paper-trading cycles headlessly.
# Usage: ./loop_in.sh [cycles] [sleep_minutes]
set -euo pipefail
cd "$(dirname "$0")"

LOCK=".loop_in.pid"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "ERROR: loop_in.sh is already running in this checkout (pid $(cat "$LOCK"))" >&2
  exit 1
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

CYCLES="${1:-1}"
SLEEP_MIN="${2:-30}"

for i in $(seq 1 "$CYCLES"); do
  echo "=== cycle $i/$CYCLES $(date -u +%FT%TZ) ==="

  if git remote get-url origin >/dev/null 2>&1; then
    git fetch origin main 2>/dev/null || echo "WARNING: could not fetch origin/main" >&2
    if git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
      git checkout -B main origin/main
    fi
  fi

  PROMPT="$(cat CYCLE_IN.md)"
  claude -p "$PROMPT" \
    --allowedTools "Read" "Glob" "Grep" "WebSearch" "WebFetch" \
      "Edit" "Write" \
      "Bash(python3 core_in/*)" "Bash(git add:*)" "Bash(git commit:*)" \
      "Bash(git rev-parse:*)" "Bash(git log:*)" "Bash(git diff:*)" \
      "Bash(git status:*)" "Bash(git fetch:*)" "Bash(git checkout -B main origin/main)" \
      "Bash(git pull:*)" \
    --permission-mode acceptEdits \
    || echo "cycle $i failed; continuing"

  if git remote get-url origin >/dev/null 2>&1; then
    if ! git push origin main; then
      echo "push rejected — rebasing onto origin/main and retrying" >&2
      if git pull --rebase origin main; then
        git push origin main || echo "WARNING: push still failing — resolve manually" >&2
      else
        git rebase --abort 2>/dev/null || true
        echo "WARNING: rebase failed — commits are local only" >&2
      fi
    fi
  fi

  [ "$i" -lt "$CYCLES" ] && sleep $((SLEEP_MIN * 60))
done
