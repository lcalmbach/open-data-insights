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

# ── 5. Push to GitHub ───────────────────────────────────────────────────────

echo "▶ Pushing to GitHub (origin/main) …"
git push origin main

# ── 6. Push to Heroku ───────────────────────────────────────────────────────

echo "▶ Pushing to Heroku …"
git push heroku main

# ── 7. Run migrations ───────────────────────────────────────────────────────

echo "▶ Running migrations on Heroku …"
heroku run python manage.py migrate --app "$HEROKU_APP"

echo ""
echo "✅  Deployed $new_version to https://ogd-data-insights-d6c65d72da95.herokuapp.com/"
