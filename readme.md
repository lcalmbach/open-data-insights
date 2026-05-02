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
