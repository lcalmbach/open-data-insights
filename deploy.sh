#!/usr/bin/env bash
# deploy.sh — bump version, push to GitHub and Heroku, run migrations
#
# Usage:
#   ./deploy.sh patch          # 1.3.1 → 1.3.2  (default)
#   ./deploy.sh minor          # 1.3.1 → 1.4.0
#   ./deploy.sh major          # 1.3.1 → 2.0.0
#   ./deploy.sh 1.5.0          # set exact version

set -euo pipefail

PYPROJECT="pyproject.toml"
HEROKU_APP="ogd-data-insights"

# ── 1. Determine new version ────────────────────────────────────────────────

current=$(grep '^version' "$PYPROJECT" | head -1 | sed 's/.*"\(.*\)".*/\1/')
bump="${1:-patch}"

IFS='.' read -r major minor patch <<< "$current"

case "$bump" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
  [0-9]*.*) major=""; minor=""; patch="" ;;   # exact version provided
esac

if [[ -n "$major" ]]; then
  new_version="${major}.${minor}.${patch}"
else
  new_version="$bump"
fi

echo "▶ Bumping version: $current → $new_version"

# ── 2. Update pyproject.toml ────────────────────────────────────────────────

sed -i "s/^version = \"$current\"/version = \"$new_version\"/" "$PYPROJECT"

# ── 3. Update uv.lock ───────────────────────────────────────────────────────

echo "▶ Updating uv.lock …"
uv lock

# ── 4. Commit ───────────────────────────────────────────────────────────────

git add "$PYPROJECT" uv.lock
git diff --cached --quiet && { echo "Nothing to commit."; exit 0; }
git commit -m "Bump version to $new_version"

# ── 5. Tag the release ──────────────────────────────────────────────────────
# Guarded: this script has aborted after the commit before (expired credentials),
# and re-running it would otherwise die here on an existing tag under `set -e`.

if git rev-parse -q --verify "refs/tags/$new_version" >/dev/null; then
  echo "▶ Tag $new_version already exists — leaving it as is."
else
  git tag -a "$new_version" -m "Release $new_version"
  echo "▶ Tagged $new_version"
fi

# ── 6. Push to GitHub ───────────────────────────────────────────────────────

echo "▶ Pushing to GitHub (origin/main) …"
# --follow-tags pushes the annotated tag above along with the commit, without
# dragging along unrelated local tags the way --tags would.
git push --follow-tags origin main

# ── 7. Push to Heroku ───────────────────────────────────────────────────────

echo "▶ Pushing to Heroku …"
# Migrations run in the Procfile `release` phase, which Heroku executes *before*
# routing traffic to the new release. Running them here instead left a window where
# new code served requests against the old schema.
git push heroku main

echo ""
echo "✅  Deployed $new_version to https://ogd-data-insights-d6c65d72da95.herokuapp.com/"
