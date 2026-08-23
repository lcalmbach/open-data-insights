---
description: Pre-deploy checks, then deploy on my go-ahead
---

Run pre-deploy verification, then wait for my go-ahead before pushing.

1. `uv run python manage.py check` and `uv run pytest`.
2. Report commits ahead of `origin` and `heroku`, and any uncommitted changes.
3. List new migrations and what they do; flag anything not purely additive.
4. If the change relies on database-resident config (templates, graphics, press
   review settings), verify those objects exist on production.
5. Note any new dependency or environment variable.

Then stop and summarise: what will change in production, and what will not.

On my go-ahead: `./deploy.sh`. If it fails after the version bump, do **not**
rerun it — `git push heroku main` deploys what is already committed. Afterwards,
confirm the release, the dynos, a couple of live URLs, and check the logs for
R14 or tracebacks.
