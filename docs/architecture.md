# Architecture

## Shape

One Django project, two apps (`account`, `reports`), one database, one Heroku app.
`reports` carries four concerns: ETL, insight generation, press review, and the
public website.

    reports/
      models/          20 files
      services/        ETL, story generation, email, press review  (~6k lines)
      visualizations/  ECharts + Leaflet chart builders
      management/commands/   27 commands
      views.py         the website
      migrations/      213 files

## Why it stays one app

This is a deliberate choice, not drift.

- **One maintainer.** Splitting into services means two deploy pipelines, two
  sets of config, and coordinating schema changes across them.
- **The shared ORM is the asset.** Split, and you either share a database —
  coupled at the schema, decoupled in deployment, the worst of both — or build
  and version APIs between your own components.
- **The split that matters already exists.** ETL does not run in the web
  process; it runs as scheduler one-off dynos. That is the isolation that counts.

The pattern has a name: a modular monolith. The failure mode is not size, it is
entanglement.

## What entanglement already cost

Web workers were loading pandas, pyarrow, wordcloud, matplotlib, anthropic and
openai — about 160 MB — because `views.py` imported one name from
`reports.services`, whose `__init__.py` eagerly imported every service. Two
workers at 224 MB exceeded the 512 MB dyno quota and produced hundreds of R14
errors.

The fix was not a split. It was making the package lazy and moving imports to
their call sites: importing `reports.views` went from +119.8 MB to +1.4 MB, and a
worker serving story pages from 224 MB to 93 MB.

`WebImportBoundaryTests` now fails if that boundary is crossed again. It imports
in a subprocess, because by the time the suite runs another test may already have
imported pandas and would mask the regression.

## If you do want to split it

Split by concern into Django apps — `web`, `etl`, `insights`, `pressreview` —
inside the same project and database. **Move code, not models:** relocating
services and views is trivial, relocating models across apps means migration
surgery against 213 existing migrations.

Separate deployment is only worth it when another person joins, or when ETL needs
genuinely different hardware.

## Known rough edges

- A long dataset sync and the web app share a slug, so deploying during a
  57-minute sync kills the job.
- Press review "Apply" does LLM work inside a web request (~30 s, near Heroku's
  router timeout). The honest fix is a task queue, not a service split.
