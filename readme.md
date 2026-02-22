# Open Data Insights (ODI)

## Introduction

Open data portals host thousands of datasets on weather, mobility, environment, economics, and more. The problem is not a lack of data — it’s that users are **drowning in it**. Most open data is raw, low-level, and requires filtering, querying, and analysis before it becomes meaningful. Keeping track of what actually matters over time is hard, even for experts.

**Open Data Insights** is a thin, opinionated layer on top of open data portals that turns selected datasets into **actionable stories** instead of raw tables.

Rather than asking every user to write their own queries, the platform:

* **Synchronizes selected datasets** from open data portals onto the ODI platform.
* Uses **insight templates** that describe *what story should be told* (via a prompt) and *which numbers matter* (via a set of predefined queries).
* Optionally attaches **tables and charts** to each story to support the narrative.
* Uses **time frames and triggers** so that stories are generated only when they are relevant:

  * Monthly stories are created as soon as a full month of data is available.
  * Daily or event-based stories are generated only when certain conditions are met (e.g. extreme weather, bad air quality, dry spells).
* Lets users **subscribe** to specific story types and receive **email notifications** when new stories are published.

For example, for a weather dataset you might define several insight templates:

* **Very hot weather** – generated when the daily maximum temperature exceeds the 95th percentile for that month.
* **Bad air quality** – triggered when the air quality index rises above a configured threshold.
* **Heat or drought spells** – published when there are a given number of consecutive days with high temperatures, no precipitation, or both.

In other words, instead of forcing users to monitor dashboards or query raw data, Open Data Insights sends them **curated, narrative summaries** only when something noteworthy happens — helping them **avoid drowning in data** by focusing on the stories that matter. 

While insight templates provide strong contextual grounding — forcing the language model to use the actual reported numbers — the quality of the generated narratives naturally varies. Hallucinations are rare, but the stories are not intended to be polished news articles. Instead, they serve as lightweight, automatically produced summaries that can inspire further reporting or support deeper personal analysis. Every story includes a prominent link back to the underlying dataset, encouraging users to explore the raw data themselves and dig deeper into the trends behind the narrative.


## 🌐 Live Demo

👉 [https://ogd-data-insights.org](https://ogd-data-insights.org/)

## 📦 Features

- ✅ **Automated Data Pipeline**: Daily data synchronization from public APIs (e.g., OpenDataSoft)
- ✅ **AI-Powered Insights**: Automatic generation of natural-language reports using OpenAI GPT
- ✅ **Email Notifications**: Automated email delivery to subscribed users
- ✅ **Template-Based Stories**: Configurable story templates for different data types
- ✅ **Multi-Dataset Support**: Handles various data sources (weather, tourism, economics, etc.)
- ✅ **Extensible Design**: New datasets and story types can be added easily
- ✅ **Django Admin Interface**: Easy management of datasets, templates, and subscriptions

## 🗺️ Leaflet Map Markers

The `map-markers` chart type now renders Leaflet fragments (no full HTML page). Each map returns a `<div>` plus an inline `<script>` that initializes the Leaflet map. Assets are injected once in the main template when at least one map is present.

Key settings (same as before unless noted):

- `latitude` / `longitude` (or `lat`/`lon`): required coordinate fields.
- `center_lat` / `center_lon`: optional map center (defaults to mean of points).
- `zoom_start`: initial zoom (default `11`).
- `tiles`: `"OpenStreetMap"` or a URL template like `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`.
- `tile_attribution`: override attribution text for tiles.
- `width` / `height`: numbers are treated as pixels; `"container"`/`"100%"` uses `width:100%` and a 400px height fallback.
- `marker_style`: `"circle"` or `"marker"`.
- `cluster`: `true` enables marker clustering for regular markers.

Notes:

- Circle markers are **not clustered** (they render directly on the map even if `cluster` is enabled).
- Each map container gets a unique ID, so multiple maps per page are safe.

Demo script:

- `reports/visualizations/map_demo.py` prints a minimal HTML page containing two maps. It also shows how assets are included only when maps are present.

## 🗺️ Leaflet Choropleth

The `choropleth` (alias: `chloropleth`) chart type renders a Leaflet choropleth from GeoJSON + a joined value column. It returns the same kind of Leaflet fragment (a `<div>` + inline `<script>`), so assets are injected the same way as for `map-markers`.

Demo script:

- `reports/visualizations/choropleth_demo.py` prints a minimal HTML page containing a small, inline GeoJSON choropleth.

## 🔧 Tech Stack

- **Backend**: Python 3.12, Django 4.x
- **Database**: PostgreSQL (production), SQLite (development)
- **Data Processing**: Pandas, NumPy, SQLAlchemy
- **AI Integration**: OpenAI GPT-4 for story generation
- **Email**: Django's built-in email system with SMTP/SES support
- **Task Scheduling**: Heroku Scheduler (production), Django management commands
- **Deployment**: Heroku with PostgreSQL addon
- **Version Control**: GitHub

## 📂 Project Structure

```
open-data-insights/
├── account/                   # User authentication and management
├── daily_tasks_obsolete/      # Legacy scripts (being migrated)
├── reports/                   # Main Django app
│   ├── management/commands/   # Django management commands
│   │   ├── daily_job.py      # Main daily pipeline
│   │   ├── sync_datasets.py  # Data synchronization
│   │   └── generate_stories.py # Story generation
│   ├── models.py             # Database models
│   ├── services/             # Business logic services
│   │   ├── dataset_sync.py   # Dataset synchronization service
│   │   ├── story_generation.py # Story generation service
│   │   ├── email_service.py  # Email delivery service
│   │   └── database_client.py # Database abstraction
│   └── views.py              # Web views
├── templates/                # Django templates
├── static/                   # CSS/JS/Images
├── requirements.txt          # Python dependencies
├── Procfile                  # Heroku configuration
└── manage.py                 # Django management script
```

## 🚀 Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL (for production) or SQLite (for development)
- OpenAI API key (for story generation)
- Email service configuration (SMTP/SES)

### Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/lcalmbach/open-data-insights.git
   cd open-data-insights
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   ```bash
   # Create .env file with:
   SECRET_KEY=your-secret-key
   OPENAI_API_KEY=your-openai-api-key
   EMAIL_HOST=your-smtp-host
   EMAIL_HOST_USER=your-email
   EMAIL_HOST_PASSWORD=your-password
   ```

5. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create superuser**:
   ```bash
   python manage.py createsuperuser
   ```

7. **Run development server**:
   ```bash
   python manage.py runserver
   ```

## 📊 Running the Daily Pipeline

### Full Daily Job
```bash
python manage.py daily_job
```

This executes the complete pipeline:
1. **Sync datasets** from configured APIs
2. **Generate insights** using AI-powered analysis
3. **Send email notifications** to subscribers

### Individual Commands

**Sync specific dataset**:
```bash
python manage.py sync_datasets --dataset-id 42
```

**Generate stories for specific date**:
```bash
python manage.py generate_stories --date 2025-06-28 --force
```

**Send email notifications**:
```bash
python manage.py send_emails --template-id 1
```

## 📬 Email Subscriptions

Users can subscribe to receive automated data stories via email:
- **Daily summaries**: Weather, traffic, economic indicators
- **Weekly reports**: Tourism trends, housing market analysis
- **Monthly insights**: Long-term trend analysis

Email delivery supports both HTML and plain text formats with embedded charts and visualizations.

## 🤖 AI-Powered Story Generation

The platform uses OpenAI's GPT models to transform raw data into human-readable narratives:

- **Template-based prompts**: Each story type has customizable prompts
- **Context-aware generation**: Incorporates historical data and trends
- **Multi-language support**: Stories can be generated in multiple languages
- **Configurable tone**: Formal reports vs. casual summaries

## 🛠 Deployment

### Heroku Deployment

1. **Create Heroku app**:
   ```bash
   heroku create your-app-name
   ```

2. **Set environment variables**:
   ```bash
   heroku config:set SECRET_KEY=your-secret-key
   heroku config:set OPENAI_API_KEY=your-openai-api-key
   ```

3. **Deploy**:
   ```bash
   git push heroku main
   ```

4. **Run migrations**:
   ```bash
   heroku run python manage.py migrate
   ```

5. **Set up scheduler**:
   ```bash
   heroku addons:create scheduler:standard
   heroku addons:open scheduler
   ```
   Add daily job: `python manage.py daily_job`

### Environment Variables

Required environment variables:
- `SECRET_KEY`: Django secret key
- `OPENAI_API_KEY`: OpenAI API key for story generation
- `EMAIL_HOST`: SMTP server host
- `EMAIL_HOST_USER`: Email username
- `EMAIL_HOST_PASSWORD`: Email password
- `DATABASE_URL`: PostgreSQL connection string (auto-set by Heroku)

Media storage on S3 (recommended on Heroku):
- `USE_S3_MEDIA=True`
- `AWS_STORAGE_BUCKET_NAME=<your-bucket>`
- `AWS_ACCESS_KEY_ID=<aws-access-key>`
- `AWS_SECRET_ACCESS_KEY=<aws-secret-key>`
- `AWS_S3_REGION_NAME=<region>` (for example `eu-central-1`)
- Optional: `AWS_MEDIA_LOCATION=media`
- Optional: `AWS_S3_CUSTOM_DOMAIN=<cdn-or-custom-domain>`

## 🔧 Configuration

### Adding New Datasets

1. **Define dataset in Django Admin**:
   - Source URL and API configuration
   - Field mappings and transformations
   - Sync schedule and filters

2. **Create story templates**:
   - Define prompts for AI generation
   - Set up data queries and context
   - Configure email templates

3. **Test and deploy**:
   ```bash
   python manage.py sync_datasets --dataset-id NEW_ID --test
   ```

## 📈 Monitoring and Logging

- **Application logs**: Available via `heroku logs --tail`
- **Email delivery tracking**: Built-in Django logging
- **Data sync monitoring**: Automated error notifications
- **Performance metrics**: Database query optimization

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙋‍♂️ About

Created by **Lukas Calmbach** to make public data more transparent and actionable.

**Mission**: Democratize data insights by automatically transforming complex datasets into accessible, human-readable stories that inform and engage the public.

---

**Links**:
- 🌐 [Live Demo](https://ogd-data-insights.herokuapp.com)
- 📧 [Contact](mailto:lcalmbach@gmail.com)
- 🐙 [GitHub](https://github.com/lcalmbach/open-data-insights)
