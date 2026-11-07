#!/usr/bin/env bash
# Saves what the bot learned (memory/, downloaded library files) back into the repository.
# Safe to run when nothing changed. Used by the GitHub workflow after every run.
set -u
PATHS="memory assets/library custom outputs work"
if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ]; then
  # the checkout step does not keep credentials on disk (so AI-written code can never read them); authenticate only here
  HOST="${GITHUB_SERVER_URL:-https://github.com}"; HOST="${HOST#https://}"
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@${HOST}/${GITHUB_REPOSITORY}.git"
fi
git config user.name  "motion-graphic-bot"
git config user.email "motion-graphic-bot@users.noreply.github.com"
for p in $PATHS; do [ -e "$p" ] && git add -A "$p"; done
if git diff --cached --quiet; then
  echo "memory: nothing new to save"
  exit 0
fi
git commit -q -m "bot: update memory and library [skip ci]" || exit 0
BRANCH="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# Two runs can finish at the same moment (the page starts 2 videos at once). Rebase on what the other run saved; when both touched the
# same JSON file (outputs/index.json, memory/*.json) the two versions are MERGED, nothing is lost.
resolve_conflicts() {
  for n in $(seq 1 40); do
    files="$(git diff --name-only --diff-filter=U)"
    [ -z "$files" ] && { GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true; git status | grep -q "rebase in progress" || return 0; continue; }
    for f in $files; do
      case "$f" in
        *.json) python3 "$HERE/merge_json.py" "$f" || git checkout --theirs -- "$f" 2>/dev/null || git rm -q -f "$f" 2>/dev/null || true ;;
        *) git checkout --theirs -- "$f" 2>/dev/null || git rm -q -f "$f" 2>/dev/null || true ;;
      esac
      git add -A -- "$f" 2>/dev/null || true
    done
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true
    git status | grep -q "rebase in progress" || return 0
  done
  return 1
}
for i in 1 2 3 4 5; do
  git fetch -q origin "$BRANCH" 2>/dev/null
  if ! git rebase -q "origin/$BRANCH" >/dev/null 2>&1; then
    resolve_conflicts || { git rebase --abort >/dev/null 2>&1; echo "memory: could not merge with the other run, retrying..."; sleep $((i * 3)); continue; }
  fi
  if git push -q origin "HEAD:$BRANCH"; then
    echo "memory: saved to the repository"
    exit 0
  fi
  echo "memory: push attempt $i failed, retrying..."
  sleep $((i * 3))
done
echo "memory: could NOT push (check Settings -> Actions -> General -> Workflow permissions = Read and write)"
exit 0
