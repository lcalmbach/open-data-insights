# Open Data Insights (ODI)

Django app that turns Swiss open data into published, multilingual data stories,
plus a personalised press review. Live at open-data-insights.org (Heroku).

## Four subsystems, one Django app

| Subsystem | Entry point | What it does |
|---|---|---|
| **ETL** | `synch_data`, `run_etl_pipeline` | Syncs 84 datasets into the `opendata` schema |
| **Insights** | `generate_stories`, `send_stories` | SQL context -> LLM story -> charts -> translation -> email |
| **Press review** | `run_press_review_pipeline` | RSS/sitemap harvest -> per-user LLM scoring -> digest |
| **Web** | `reports/views.py` | Public site, story pages, admin tooling |

They share a database and models on purpose. See `docs/architecture.md` before
proposing to split them.

## Rules that are easy to break

1. **Never import ETL/LLM code at module level in `views.py` or `urls.py`.**
   `reports/services/__init__.py` is lazy (PEP 562) for this reason. Importing
   eagerly pulls pandas/pyarrow/anthropic (~160 MB) into every web worker and
   pushes the dynos past their 512 MB quota. `WebImportBoundaryTests` guards it.
2. **Story pages render stored `Graphic.content_html`, not live code.** Changing a
   chart in code changes nothing on an existing story until that graphic is
   regenerated. See `docs/charts.md`.
3. **Placeholders are substituted in both SQL and settings.** A settings value
   naming something the SQL also produces must use the same placeholder.
4. **Migrations run in the Heroku `release` phase**, not after the push. A failed
   migration aborts the deploy by design.

## Working agreements

- Verify against real data before claiming a fix; this repo has repeatedly proved
  intuitions wrong. Charts can be checked in a real browser — see
  `.claude/commands/verify-chart.md`.
- Run `uv run pytest` before committing. The suite is green; keep it that way.
- Don't add a dependency to serve a page. Prefer a local import in the one
  function that needs it.

## Where to look

- `docs/domain-model.md` — Story, StoryTemplate, Focus, Graphic, press review models
- `docs/pipelines.md` — what each command does and when it runs
- `docs/charts.md` — graphic types, settings, placeholders
- `docs/deployment.md` — deploy, scheduler, environment
- `docs/testing.md` — how the suite is wired
- `docs/gotchas.md` — landmines that have already cost time
