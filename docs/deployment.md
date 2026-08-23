# Deployment

Heroku app `ogd-data-insights`, served at open-data-insights.org.
Two Standard-1X web dynos (512 MB each) plus scheduler one-off dynos.

## Deploying

    ./deploy.sh            # patch bump, or: ./deploy.sh minor | major | 1.2.3

Bumps the version, regenerates `uv.lock`, commits, pushes to GitHub and Heroku.
Migrations are **not** run by the script — they run in the Procfile `release`
phase, which Heroku executes before routing traffic to the new release.

> If `deploy.sh` fails partway (a common cause: expired credentials), it has
> already bumped and committed. Do not run it again — `git push heroku main`
> deploys what is committed.

Credentials expire. `heroku login` then `git push heroku main`.

## Procfile

    release: python manage.py migrate --noinput
    web: gunicorn report_generator.wsgi --workers 1 --threads 4 --worker-class gthread \
         --max-requests 200 --max-requests-jitter 50 --timeout 60

**One worker, four threads** is deliberate. Two workers each load the full
scientific stack and exceeded the 512 MB quota before serving a request. One
worker with threads gives *more* concurrency (4 vs 2) at a fifth of the memory,
because serving pre-rendered pages is I/O bound.

A second worker is affordable again (~93 MB each) but only helps if requests
queue, which is a CPU signal, not a memory one.

## Scheduler

Heroku Scheduler runs in **UTC**. Current jobs:

    python manage.py run_etl_pipeline
    python manage.py run_press_review_pipeline

Offset them so they do not contend for dynos.

## Environment

Required: `SECRET_KEY`, `DATABASE_URL`, one of
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY`, `DEFAULT_AI_MODEL`,
SMTP credentials. `ANTHROPIC_API_KEY` is required in practice because press
review scoring defaults to `claude-haiku-4-5`.

Optional: `USE_S3_MEDIA` + AWS keys, `SYNC_DATABASE_URL` for `synch_prod`,
and the `PRESSREVIEW_*` settings in `docs/pipelines.md`.

## Local vs production data

Template, graphic and press review configuration lives **in the database**, so
local and production diverge. A code deploy does not carry a chart's settings.
`synch_prod` syncs template objects; graphics then need regenerating on the
target, because pages render stored HTML.

Postgres schemas: `report_generator` (Django) and `opendata` (synced data).
Anything hitting `opendata` via raw SQL needs the schema qualified when run
through `heroku pg:psql`, whose `search_path` is not the app's.
