# Domain model

## Insights

**Dataset** — a source table synced into the `opendata` schema (84 of them).
Connectors: ODS (data.bs.ch and friends), plain URL/CSV, EIA. `import_type`
decides the sync strategy.

**StoryTemplate** — the blueprint for a recurring insight. Holds the prompt, the
reference period and direction, topics/regions, and whether title and lead are
generated. `story_source` picks between `llm` (generate the article) and
`context_json` (read it from the context payload).

**StoryTemplateFocus** — a template can publish several variants, one per focus.
A focus carries `filter_value` / `filter_expression`, which templates use in
their SQL. 175 of 248 focuses have a `filter_value`.

> `focus_filter` and `StoryTemplate.focus_filter_fields` were removed (migrations
> 0162 / 0164). The `:focus_filter` token is gone; use `:filter_value`.

**StoryTemplateContext** — the SQL that produces the JSON context handed to the
LLM. Its presence is what makes a template "data based".

**Story** — one published article, per language. English is generated first and
translated to German and French, so a single publication is three Story rows.

**StoryTemplateGraphic / Graphic** — the chart definition and its rendered
instance. See `docs/charts.md`; the important part is that `Graphic.content_html`
is *stored*, not rendered per request.

**StoryTemplateTable / StoryTable** — same split for tables. `StoryTable.data`
holds a JSON *string*, and `download_story_table_csv` parses it back.

**StoryTemplateSubscription** — who receives which insight by email.

> `reports/signals.py` subscribes every newly created user to all existing
> templates, ignoring `auto_subscribe`. There is no uniqueness constraint on
> (user, template), so duplicate rows are possible and are counted twice.

## Press review

Deliberately parallel to the insight pipeline, not part of it.

**PressReviewSource** — a curated feed. `feed_type` is `rss` or `news_sitemap`.
`local=true` exempts a source from the mandatory-keyword check.

**PressReviewKeyword** — the global harvest filter, two tiers: `required=True`
keywords (Basel, Basler, Basel-Stadt) that an article must contain, plus topic
keywords. A user's own topics are unioned into this filter, otherwise a personal
topic could only re-rank articles that were never collected.

**PressReviewArticle** — a harvested article. Deduped on `link`.

**UserPressReviewKeyword** — one user's topics.

**UserPressReviewArticleScore** — an LLM relevance score (1-10) per user and
article, plus `digest_sent`. Scores are stored for *every* article regardless of
threshold, which is why lowering a threshold surfaces older articles instantly
and for free.

**CustomUser** press review fields — `press_review_frequency`
(`none` | `daily` | `weekly`, default `none`, opt-in), `press_review_threshold`
(1-10), and `press_review_sources` (empty means *all active sources*).

> An empty source selection means "all", so ticking every box gives you *fewer*
> sources than ticking none — anything added later is excluded.
