# Roadmap

Where this is going, and what has already been decided. Reference documentation
lives in `docs/`; this file is intent, not state.

Last reviewed: 2026-08-15

## Next

- **CI.** No automated test run exists; the suite runs only when invoked by hand.
  A GitHub Actions workflow running the non-DB tests on push would have caught
  most of what broke recently. Highest value per effort of anything here.
- **Groundwater insight.** `ds_100164` (954k rows) and `ds_100164_stations` are
  migrated to production and the map colour-binning and legend work is done, but
  no StoryTemplate exists yet. Add an index on `(stationnr, date)` when the
  template starts querying it — not before.
- **Publish the heat-days chart.** Graphic 146 and its settings exist only in the
  local database; production's Hot Day template still carries the old graphic.
  Needs `synch_prod` plus regeneration on the target.

## Considering

- **Story page weight.** Pages inline their chart HTML; "Neighbourhood Profiles"
  averages 168 KB per graphic across 236 graphics, and one page reached 1.3 MB of
  which 98% was inline chart payload. Serving chart data from an endpoint and
  lazy-loading would cut it sharply. The memory work made this survivable, not
  fixed.
- **Task queue.** Press review "Apply" does LLM work inside a web request (~30 s,
  near Heroku's router timeout), and long dataset syncs die when a deploy
  restarts the dyno. Both point at a queue rather than an architecture change.
- **Split `reports` into apps** — `web`, `etl`, `insights`, `pressreview` — same
  project and database. Move code, not models: 213 migrations make relocating
  models expensive. Purely about making boundaries visible.
- **News ↔ data cross-linking.** ODI now holds both a news pipeline and 84
  datasets, which almost nobody does. Starting from a fired trigger and looking
  for press coverage avoids the coverage problem entirely, and "the data says
  something notable and nobody wrote about it" is the genuinely valuable output.
  Join axis is template topics (77 of 78 tagged); datasets themselves are not.
- **Anomaly detection as story leads.** Statistical change detection across the
  daily-synced datasets, surfacing leads for an editor. Fits the existing
  cadence; the hard part is tuning so it stops crying wolf.
- **Data release calendar.** Newsrooms plan around publication dates, and the ODS
  catalogue already gives the update rhythm. Cheap, and the kind of utility that
  keeps a tab open.

## Blocked

- **mybasel.ch events.** Scraping is technically straightforward and permitted by
  robots.txt, but the listings belong to PROZ (proz.online), not mybasel. Waiting
  on permission. Worth asking whether they have a feed or API — more stable than
  scraping CSS classes. If it goes ahead: watch for multi-week exhibitions
  repeating daily, and treat "parsed 0 events" as a failure, because scrapers
  break silently.

## Known issues, not yet scheduled

- Duplicate subscriptions are possible: `reports/signals.py` subscribes every new
  user to all templates, ignoring `auto_subscribe`, and there is no uniqueness
  constraint on (user, template). Duplicates are counted twice.
- Five templates have no default focus. The app works, so the old "exactly one
  default focus" invariant looks obsolete — worth confirming rather than assuming.
- CNN yields little: the source is live via its news sitemap, but the topic
  keywords are German and CNN is English.
- `CHANGELOG.md` stopped at 1.2.1 while the app is on 1.10.x. Either revive it or
  drop it in favour of `git log`.

## Decided against

- **Splitting into separate services.** One maintainer, and the shared ORM is an
  asset. The isolation that matters — ETL not running in the web process —
  already exists. See `docs/architecture.md`.
- **Reviving `:focus_filter`.** Removed with its backing field; focus conditions
  use `:filter_value`.
- **Reasoning about chart behaviour from documentation.** Verify in a browser;
  it has been wrong more than once.
