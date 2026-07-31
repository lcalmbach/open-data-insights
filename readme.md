# Open Data Insights (ODI)

## Introduction

Open data portals host thousands of datasets on weather, mobility, environment, economics, and more. The problem is not a lack of data — it is that most of it is raw, low-level, and requires filtering, querying, and analysis before it becomes meaningful.

**Open Data Insights** is a thin, opinionated layer on top of open data portals that turns selected datasets into **actionable stories** instead of raw tables.

The platform:

- **Synchronizes selected datasets** from open data portals on a configurable schedule.
- Uses **story templates** that describe *what story should be told* (via an LLM prompt) and *which numbers matter* (via a set of predefined SQL queries).
- Optionally attaches **charts and tables** to each story to support the narrative.
- Applies **time frames and publish conditions** so stories are created only when relevant — monthly stories appear as soon as a full month of data is available; event-based stories fire only when conditions are met (extreme weather, bad air quality, etc.).
- Lets users **subscribe** to story types and receive **email notifications** when new stories are published.

Stories are lightweight, automatically produced summaries — not polished journalism. Every story links back to the underlying dataset so readers can explore the raw data themselves.

## 🌐 Live Demo

👉 [https://www.open-data-insights.org](https://www.open-data-insights.org/)

## 📦 Features

| Feature | Notes |
|---|---|
| **Multi-LLM story generation** | OpenAI GPT-4o, Anthropic Claude (Opus / Sonnet / Haiku), DeepSeek Chat — switchable per template via a lookup table |
| **Story templates** | Prompt, system prompt, context queries, publish conditions, focus areas (multi-neighbourhood / multi-topic), reference period |
| **Charts** | Line, bar, stacked bar, area, scatter, pie, heatmap, histogram, radar/spider, horizontal ranking bar, choropleth, map markers, word cloud |
| **Tables** | SQL-driven data tables attached to stories |
| **Email subscriptions** | Users subscribe to templates; stories are emailed on publish |
| **RSS feeds** | Per-language RSS 2.0 feeds at `/feed/rss/en/`, `/feed/rss/de/`, `/feed/rss/fr/` — up to 20 stories, max 90 days old; auto-discovery links in every page |
| **Story access logging** | Every page view logged with user, IP, timestamp; bots detected from User-Agent; 5-minute deduplication for human visitors |
| **Multi-language** | Stories generated natively in each language or translated from English |
| **DB sync** | `synch_prod` command syncs templates and child objects between environments |
| **Template cloning** | `clone_story_template` duplicates a template with all focus areas, graphics, contexts, and tables |
| **SEO** | `/robots.txt` and `/sitemap.xml` included |
| **Django Admin** | Full admin interface for all models |

## 🔧 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Django 4.2 |
| Database | PostgreSQL |
| Data processing | Pandas, NumPy |
| Charting | Altair / Vega-Lite, Leaflet |
| AI | OpenAI, Anthropic Claude, DeepSeek |
| Email | Django email + SMTP / AWS SES |
| Media storage | AWS S3 (via django-storages) |
| Static files | WhiteNoise |
| Deployment | Heroku (gunicorn) |
| Dependency management | uv + uv.lock |

## 📂 Project Structure

```
open-data-insights/
├── account/                        # User authentication and profiles
├── report_generator/               # Django project settings and root URLs
├── reports/                        # Main application
│   ├── management/commands/        # Management commands
│   │   ├── generate_stories.py     # Run story generation pipeline
│   │   ├── run_etl_pipeline.py     # Sync datasets + generate stories
│   │   ├── send_stories.py         # Email published stories
│   │   ├── run_press_review_pipeline.py   # Harvest + score + send press review
│   │   ├── harvest_press_review.py # Harvest RSS sources into PressReviewArticle
│   │   ├── rate_press_review_relevance.py # LLM-score articles per user keywords
│   │   ├── send_press_review_digests.py   # Email the press review digest
│   │   ├── prune_press_review_articles.py # Delete articles past retention
│   │   ├── synch_data.py           # Sync data tables between DBs
│   │   ├── synch_prod.py           # Sync template objects between environments
│   │   └── clone_story_template.py # Clone a template with all children
│   ├── migrations/                 # Django migrations
│   ├── models/                     # One file per model
│   │   ├── story_template.py       # StoryTemplate, StoryTemplateFocus
│   │   ├── story.py                # Story
│   │   ├── graphic_template.py     # StoryTemplateGraphic
│   │   ├── story_context.py        # StoryTemplateContext
│   │   ├── story_table_template.py # StoryTemplateTable
│   │   ├── story_access.py         # StoryAccess (access log)
│   │   ├── lookups.py              # LookupCategory, LookupValue + proxies
│   │   └── ...
│   ├── services/                   # Business logic
│   │   ├── story_processor.py      # LLM story generation
│   │   ├── dataset_sync.py         # Dataset synchronisation
│   │   ├── email_service.py        # Email delivery
│   │   ├── press_review_service.py # RSS harvesting, relevance scoring, digest mailer
│   │   └── database_client.py      # Query runner
│   ├── sitemaps.py                 # Sitemap classes
│   ├── feeds.py                    # RSS feed classes (per language)
│   └── visualizations/
│       └── plotting.py             # All chart types (Altair + Leaflet)
├── templates/                      # Django HTML templates + robots.txt
├── static/                         # CSS / JS / images
├── deploy.sh                       # One-command deploy script
├── pyproject.toml                  # Project metadata + dependencies
├── uv.lock                         # Locked dependency versions
└── Procfile                        # Heroku: gunicorn
```

## 🚀 Local Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL
- API key for at least one LLM (OpenAI, Anthropic, or DeepSeek)

### Setup

```bash
# 1. Clone
git clone https://github.com/lcalmbach/open-data-insights.git
cd open-data-insights

# 2. Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Create virtualenv and install dependencies
uv venv --python 3.12
uv sync

# 4. Configure environment — create a .env file (see Environment Variables below)

# 5. Migrate and create superuser
python manage.py migrate
python manage.py createsuperuser

# 6. Run
python manage.py runserver
```

### Environment Variables

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | ✅ | Django secret key |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | ✅ | PostgreSQL connection |
| `OPENAI_API_KEY` | one of three | For GPT-4o |
| `ANTHROPIC_API_KEY` | one of three | For Claude models |
| `DEEPSEEK_API_KEY` | one of three | For DeepSeek Chat |
| `DEFAULT_AI_MODEL` | ✅ | e.g. `gpt-4o`, `claude-sonnet-4-6`, `deepseek-chat` |
| `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | ✅ | SMTP credentials |
| `USE_S3_MEDIA` | optional | `True` to store media on S3 |
| `AWS_STORAGE_BUCKET_NAME` | if S3 | |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_S3_REGION_NAME` | if S3 | |
| `SYNC_DATABASE_URL` | optional | Second DB for `synch_prod` |

## 🛠 Deployment

### First-time Heroku setup

```bash
heroku create your-app-name
heroku addons:create heroku-postgresql:essential-0
heroku config:set SECRET_KEY=... OPENAI_API_KEY=...   # etc.
git push heroku main
heroku run python manage.py migrate
heroku run python manage.py createsuperuser
```

### Ongoing deploys — `deploy.sh`

Commit your feature work first, then run the deploy script:

```bash
./deploy.sh          # patch bump  1.3.1 → 1.3.2  (default)
./deploy.sh minor    # minor bump  1.3.1 → 1.4.0
./deploy.sh major    # major bump  1.3.1 → 2.0.0
./deploy.sh 2.0.0    # set exact version
```

The script automatically:
1. Bumps the version in `pyproject.toml`
2. Regenerates `uv.lock`
3. Commits the version files
4. Pushes to **GitHub** (`origin/main`)
5. Pushes to **Heroku** and runs `python manage.py migrate`

## 📊 Running the Pipeline

```bash
# Sync all datasets and generate stories
python manage.py run_etl_pipeline

# Generate stories only (data already synced)
python manage.py generate_stories

# Send published stories by email
python manage.py send_stories

# Clone a story template (by ID or slug)
python manage.py clone_story_template 42
python manage.py clone_story_template my-slug --title "Copy of My Template"
python manage.py clone_story_template 42 --dry-run
```

### Press Review

A second, independent insight channel, parallel to story generation: news sources and
keywords are curated by staff (Django admin), users pick their own topics *and which
sources to include* on their profile page, and a daily pipeline harvests articles,
scores them per user with an LLM, and emails a digest. Harvesting is global (every
active source, once); each user's source selection filters what gets scored and sent
to them, and an empty selection means "all active sources". Users can also browse
their matched articles in the app under **Tools → Press Review**.

Run the whole pipeline with one command — the press review equivalent of
`run_etl_pipeline`, with the same skip flags and admin-alert-on-failure behaviour:

```bash
python manage.py run_press_review_pipeline
```

```
--frequency daily|weekly   Which cadence to mail (default: daily)
--model MODEL              Override the scoring model
--skip-harvest             Skip RSS harvesting
--skip-rating              Skip relevance scoring
--skip-email               Skip digest sending
--stop-on-error            Abort on failure (default: continue)
```

The individual steps can also be run on their own:

```bash
# 1. Harvest active RSS sources into PressReviewArticle (two-tier keyword filter)
python manage.py harvest_press_review

# 2. Score new articles for relevance against each user's press review keywords
python manage.py rate_press_review_relevance

# 3. Email the digest to users with unsent, above-threshold scores
python manage.py send_press_review_digests
```

Each user picks a digest frequency on their profile — **None**, **Daily**, or **Weekly**
(mutually exclusive, so an article is never delivered twice). Add a second, weekly
scheduler entry for the weekly cohort:

```bash
# Weekly schedule (only mails users who chose "Weekly digest")
python manage.py run_press_review_pipeline --frequency weekly --skip-harvest --skip-rating
```

Harvesting and scoring stay on the daily schedule regardless — they run for everyone,
and weekly users simply accumulate unsent scores until their weekly run picks them up.
Hence `--skip-harvest --skip-rating` on the weekly entry: it only needs to mail.

Each user also sets their own **relevance threshold** (1–10) on their profile — only
articles the AI scores at or above it reach them. Since a score is stored for *every*
article, lowering the threshold retroactively surfaces already-scored articles at no
extra LLM cost.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PRESSREVIEW_RELEVANCE_THRESHOLD` | `7` | Threshold seeded for *new* users; each user can override it |
| `PRESSREVIEW_HARVEST_MAX_AGE_DAYS` | `2` | Ignore feed entries older than this |
| `PRESSREVIEW_DIGEST_MAX_ITEMS` | `25` | Max articles in one digest |
| `PRESSREVIEW_ARTICLE_RETENTION_DAYS` | `90` | Delete articles older than this (`0` disables) |
| `PRESSREVIEW_RESCORE_MAX_ARTICLES` | `50` | Max articles re-scored in one user-triggered rescore |
| `PRESSREVIEW_PREVIEW_MAX_ARTICLES` | `20` | Max articles scored for an ad-hoc topic preview |
| `PRESSREVIEW_AI_MODEL` | `claude-haiku-4-5` | Model used for relevance scoring |
| `PRESSREVIEW_PREVIEW_AI_MODEL` | (same as above) | Override just the in-request preview |
| `PRESSREVIEW_PREVIEW_WINDOW_DAYS` | `7` | How far back the tool looks when previewing |
| `PRESSREVIEW_HARVEST_MIN_INTERVAL_MINUTES` | `2` | Skip refetching a source fetched this recently |

**Keywords are two-tiered, and the distinction matters.** Global keywords (admin) decide
what gets *collected*; a user's topics decide how collected articles are *ranked*. So the
harvest filter is the union of the global topic keywords and every active user's topics —
without that union, adding a personal topic nobody curated globally would silently return
nothing, because the articles were never stored in the first place.

The tool's **Apply** button harvests before previewing, passing the (possibly unsaved)
topics into that filter, so a brand-new topic finds articles immediately instead of
waiting for the next scheduled run. Fetching is cheap (HTTP only); the LLM scoring is the
cost, which is why scoring uses a fast model and previews are capped. Measured per
article: `deepseek-v4-pro` ~7.1s, `deepseek-v4-flash` ~3.0s (it still spends reasoning
tokens), `claude-haiku-4-5` ~1.5s. A typical Apply runs ~30s (harvest plus 20 scored
articles); a single scoring call is ~221 input / ~50 output tokens.

`PRESSREVIEW_AI_MODEL` is deliberately separate from `DEFAULT_AI_MODEL`, which drives
story generation — rating a headline 1–10 is short-text classification and gains nothing
from reasoning tokens, whereas story writing does. Scoring cost scales as
**articles × users**, so it is the term to watch as the user base grows.

On a 12-article comparison, Haiku and Pro agreed on the send/skip decision for 11 of 12
(mean score difference 1.3). The one disagreement was an on-topic war headline Pro rated
9 and Haiku 3 — worth knowing that with sitemap sources there is no article summary, so
the model judges the headline alone. If misses like that matter more than cost, set
`PRESSREVIEW_AI_MODEL=deepseek-v4-flash` (or `-pro`) to trade latency back for accuracy.

Over the digest cap, the highest-scoring articles are sent and the remainder stays
queued for the next run — nothing is dropped, and the held-back count is reported in the
command output.

### Source formats: RSS and news sitemaps

Each `PressReviewSource` has a **feed type**:

| Feed type | When to use |
|---|---|
| `rss` (default) | Normal RSS/Atom feeds — parsed with `feedparser` |
| `news_sitemap` | Publishers that no longer maintain RSS |

Many large publishers quietly stopped updating their RSS feeds (CNN's return HTTP 200
but are years stale), while keeping a **Google News sitemap** fresh — because Google News
depends on it. Those provide direct article URLs, headlines and precise publication
timestamps, usually at `/sitemap/news.xml` and declared in the site's `robots.txt`.

Both formats normalise to the same internal entry shape, so the keyword filter, scoring
and digest are identical either way. The one difference: **sitemaps carry no article
summary**, so keyword matching and LLM scoring work from the headline alone.

Two things to watch when adding a foreign-language source:

- Mandatory keywords (`Basel`, `Basler`, …) reject anything that doesn't mention them.
  Set **local = true** on the source to bypass that check.
- Topic keywords must match the source's language. German keywords never match English
  headlines, so an English source needs English topic keywords or it yields nothing.

Articles older than the retention window are deleted automatically at the end of each
harvest, which bounds table growth and keeps stale news out of digests. Per-user scores
cascade with their article — they are derived data. To run it manually or preview it:

```bash
python manage.py prune_press_review_articles --dry-run   # report only, delete nothing
python manage.py prune_press_review_articles --days 30    # override the window
python manage.py prune_press_review_articles --days 0     # disable
```

On the **Tools → Press Review** page the relevance threshold is also adjustable per view
(starting from the user's saved default), so they can explore a wider or narrower net
without changing the threshold their email digest uses. This is instant and free: a
score is stored for *every* article regardless of any threshold, so filtering never
needs new LLM calls.

Changing **topics** is the case that does need work. Scoring only looks at articles with
no score yet, so existing articles keep scores computed against the previous topics.
The **Re-score against my topics** button on that page clears the user's scores and
re-judges their articles against the current topic list. It costs one LLM call per
article, so it is explicit rather than automatic, and bounded by
`PRESSREVIEW_RESCORE_MAX_ARTICLES` (default `50`) to keep the request responsive —
anything past the bound is left unscored and picked up by the next scheduled rating run.

To bootstrap sources/keywords/subscribers from the legacy `work/pressreview`
proof-of-concept's Postgres schema (one-off, historical articles are not migrated):

```bash
python manage.py import_pressreview_data
```

## 📈 Chart Types

Chart settings are stored as JSON on each `StoryTemplateGraphic`. The `type` field selects the renderer:

| type | Description |
|---|---|
| `line` | Line chart |
| `bar` | Vertical bar (add `"horizontal": true` for horizontal) |
| `bar_stacked` | Stacked bar |
| `area` | Area chart |
| `point` / `scatter` | Scatter / point chart |
| `pie` | Pie chart |
| `heatmap` | Heatmap |
| `histogram` | Histogram with auto-binning |
| `radar` | Radar / spider chart |
| `ranking_bar` | Horizontal ranking bars — all grey, one highlighted |
| `choropleth` | Leaflet choropleth from GeoJSON |
| `map-markers` | Leaflet marker map |
| `wordcloud` | Word cloud |

### Ranking Bar example

```json
{
  "type": "ranking_bar",
  "category": "Neighborhood",
  "value": "Value",
  "highlight": ":filter_expression",
  "highlight_color": "#e45756",
  "bar_color": "#bbbbbb",
  "sort": "descending",
  "tooltips": ["Neighborhood", "Value", "Rank"]
}
```

## 📬 Story Access Log

Every story page view is recorded in `reports_storyaccess`:

- **Authenticated users**: deduplicated per user + story within 5 minutes
- **Anonymous visitors**: deduplicated per IP + story within 5 minutes
- **Bots** (detected via User-Agent regex): always logged, never deduplicated

Visible in Django Admin under **Reports → Story Accesses**.

## 🗺️ SEO

- `GET /robots.txt` — disallows admin and staff-only routes
- `GET /sitemap.xml` — lists all published story URLs and static pages

## 📡 RSS Feeds

Per-language RSS 2.0 feeds are available for use with any feed reader (Feedly, Inoreader, etc.):

| Language | URL |
|---|---|
| English | `GET /feed/rss/en/` |
| German | `GET /feed/rss/de/` |
| French | `GET /feed/rss/fr/` |

Each feed returns up to 20 stories published within the last 90 days. Auto-discovery `<link>` tags are included in every page so browsers and feed readers detect the feeds automatically.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

## 📄 License

MIT License — see [LICENSE](LICENSE).

## 🙋‍♂️ About

Created by **Lukas Calmbach** to make public data more transparent and actionable.

**Links**: [Live Demo](https://www.open-data-insights.org) · [GitHub](https://github.com/lcalmbach/open-data-insights) · [Contact](mailto:lcalmbach@gmail.com)
