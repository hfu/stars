#!/bin/bash
# Commit whatever changed in the gh-pages worktree and push it, retrying on
# transient failures. Run from inside the gh-pages worktree.
#
# Why retry: on 2026-09-13 a push was rejected with `remote: Internal Server
# Error` (GitHub-side HTTP 500) after collection and commit had both
# succeeded, losing that sample. A short wait and a second attempt absorbs
# that class of failure.
#
# What this does NOT fix: runs that never get a runner at all. The same day a
# job sat queued for ~3 hours and the concurrency group cancelled the pending
# runs behind it. No job-side retry can help there.
#
# Both gh-pages workflows share the `stars-monitoring` concurrency group, so the
# remote normally can't move under us; the rebase is there for the rare case it
# did, not as the expected path.
set -euo pipefail

MAX_ATTEMPTS="${PUSH_MAX_ATTEMPTS:-4}"
COMMIT_MESSAGE="${1:?usage: push-gh-pages.sh <commit message>}"

git config user.name "stars-monitoring-bot"
git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git commit -q -m "$COMMIT_MESSAGE"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if git push origin HEAD:gh-pages; then
    echo "pushed on attempt $attempt"
    exit 0
  fi
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    break
  fi
  wait_s=$((attempt * 10))
  echo "push attempt $attempt failed; retrying in ${wait_s}s"
  sleep "$wait_s"
  # A transient error can hit the fetch too; don't let that end the retries.
  if git fetch -q origin gh-pages; then
    if ! git rebase -q origin/gh-pages; then
      # Two writers diverging on the same file isn't something to resolve
      # automatically -- fail loudly rather than guess.
      git rebase --abort || true
      echo "rebase onto origin/gh-pages conflicted; giving up" >&2
      exit 1
    fi
  fi
done

echo "push failed after $MAX_ATTEMPTS attempts" >&2
exit 1
