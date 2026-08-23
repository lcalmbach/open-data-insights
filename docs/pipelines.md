# Pipelines

## Insights (daily)

    python manage.py run_etl_pipeline

Sync datasets -> generate stories -> auto-subscribe users to new templates ->
email published stories. Failures at any step email an admin alert and, by
default, the pipeline continues; `--stop-on-error` changes that.

Steps individually: `synch_data`, `generate_stories`, `send_stories`.
Useful flags: `--id`, `--story_focus_id`, `--date`, `--force`, `--lang`.

`synch_data --keep-csv` keeps a downloaded CSV *and reuses it* on the next run,
which matters when a source is multi-GB. It is a debugging tool: a cached CSV
means that dataset silently stops updating, so it logs at WARNING and must not be
left in a scheduled job.

## Press review (daily, plus weekly for that cohort)

    python manage.py run_press_review_pipeline

Harvest -> score -> send, in one command. Steps individually:
`harvest_press_review`, `rate_press_review_relevance`, `send_press_review_digests`,
`prune_press_review_articles`.

Weekly cohort, mail only:

    python manage.py run_press_review_pipeline --frequency weekly --skip-harvest --skip-rating

Harvest and scoring stay daily for everyone; weekly users simply accumulate
unsent scores until their run collects them.

**Harvest** applies the two-tier keyword filter:
`(required OR'd, skipped when source.local) AND (topic OR'd)`, where topics
include every active user's own keywords. Entries older than
`PRESSREVIEW_HARVEST_MAX_AGE_DAYS` are ignored, and articles past
`PRESSREVIEW_ARTICLE_RETENTION_DAYS` are pruned at the end.

**Scoring** judges each unscored article against each user's topics and stores a
1-10 score. It skips users whose frequency is `none`. It only looks at articles
with *no* score yet, so editing topics leaves old scores stale — which is why
saving preferences triggers `rescore_user`.

**Sending** filters by the user's own threshold and source selection, caps one
digest at `PRESSREVIEW_DIGEST_MAX_ITEMS` (the remainder stays queued rather than
being dropped), and marks `digest_sent`.

## Settings that shape behaviour

| Setting | Default | Effect |
|---|---|---|
| `PRESSREVIEW_RELEVANCE_THRESHOLD` | 7 | Seeds new users; each user overrides |
| `PRESSREVIEW_HARVEST_MAX_AGE_DAYS` | 2 | Ignore older feed entries |
| `PRESSREVIEW_ARTICLE_RETENTION_DAYS` | 90 | Prune older articles (0 disables) |
| `PRESSREVIEW_DIGEST_MAX_ITEMS` | 25 | Cap one digest |
| `PRESSREVIEW_AI_MODEL` | claude-haiku-4-5 | Relevance scoring |
| `PRESSREVIEW_PREVIEW_MAX_ARTICLES` | 20 | Ad-hoc preview cap |
| `DEFAULT_AI_MODEL` | deepseek-v4-pro | Story generation |

`PRESSREVIEW_AI_MODEL` is separate from `DEFAULT_AI_MODEL` on purpose: rating a
headline 1-10 is classification and gains nothing from reasoning tokens.
Measured per article: deepseek-v4-pro ~7.1s, deepseek-v4-flash ~3.0s (it still
reasons), claude-haiku-4-5 ~1.5s.

Scoring cost scales as **articles x users** — the term to watch as users grow.
