#!/usr/bin/env bash
# MUSHY-35 — remove the two leaked credentials from all git history.
#
#   bash scripts/security/mushy35-scrub-history.sh
#
# Rewrites LOCAL history only. It does NOT push — verify the output, then run
# the push command it prints. Exists as a script because the equivalent
# one-liner breaks when a terminal wraps a newline into the --index-filter
# string (git then evals it as two commands and aborts).
set -euo pipefail

REPO=/mnt/slime-kingdom/opt/mushy
P1=client.ovpn
P2=scripts/pi-deploy/etc/netplan/60-wifi.yaml

cd "$REPO"

if [ -n "$(git status --porcelain)" ]; then
  echo "ABORT: working tree is dirty. Commit or stash first." >&2
  exit 1
fi

# filter-branch refuses to start if a previous run left this behind.
rm -rf .git/refs/original

echo ">>> rewriting $(git rev-list --all --count) commits across \
$(git for-each-ref --format='%(refname)' refs/heads | wc -l) branches \
and $(git tag | wc -l) tags — this takes a few minutes"

FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force \
  --index-filter "git rm --cached --ignore-unmatch -q -- '$P1' '$P2'" \
  --tag-name-filter cat -- --branches --tags

echo
echo ">>> VERIFY — the next line must be empty:"
LEFT=$(git log --all --oneline -- "$P1" "$P2")
if [ -n "$LEFT" ]; then
  echo "$LEFT"
  echo "FAIL: secrets still referenced. Do NOT push. Restore from the backup mirror." >&2
  exit 1
fi
echo "    (empty) — no commit on any branch or tag references either path"

echo
echo ">>> blob check: are the objects still reachable from any ref?"
if git rev-list --objects --all | grep -qE " ($P1|$P2)$"; then
  echo "FAIL: blob still reachable. Do NOT push." >&2
  exit 1
fi
echo "    clean"

echo
echo ">>> LOCAL REWRITE COMPLETE. Nothing pushed yet."
echo
echo "Next, to publish it:"
echo "  cd $REPO && rm -rf .git/refs/original && git reflog expire --expire=now --all && git gc --prune=now && git push --force origin --all && git push --force origin --tags"
echo
echo "Then re-sync fc1 (its fc1/prod SHA just changed):"
echo "  ssh ubuntu@172.16.10.5 'cd ~/mushroom_farm_ws/mushy-repo && git fetch origin && git reset --hard origin/fc1/prod'"
