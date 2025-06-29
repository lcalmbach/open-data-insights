### Open-Data-Insights

* A Django web application hosted on Heroku
* Generates **data stories** from structured open data (e.g., tourism, rent prices, electricity, etc.)
* Daily task pipeline that:

  * Syncs datasets from APIs (e.g. OpenDataSoft)
  * Generates insights and reports
  * Sends emails to subscribed users
* Backend logic lives in a folder like `daily_tasks/`
* Heroku used for deployment
* GitHub used for source control
* App name: `open-data-insights`
* Purpose: turning open datasets into interpretable, automated summaries (data journalism meets automation)

---

### 📝 Suggested `README.md`

```markdown
# Open Data Insights

**Open Data Insights** is a Django-based platform that transforms open datasets into automated, human-readable reports and insights. It is designed for statistical offices, journalists, and civic tech enthusiasts who want to turn raw public data into stories — automatically, every day.

## 🌐 Live Demo

Hosted on Heroku:  
👉 [https://ogd-data-insights.herokuapp.com](https://ogd-data-insights.herokuapp.com)

## 📦 Features

- ✅ Daily data synchronization from public APIs (e.g., OpenDataSoft)
- ✅ Automatic generation of natural-language reports from time series
- ✅ Email notifications to subscribed users
- ✅ Modular data pipeline: sync → analyze → publish
- ✅ Designed for extensibility (new datasets can be added easily)

## 🔧 Tech Stack

- **Python 3.12**
- **Django 4.x**
- **Pandas**, **Requests**, **Celery-ready** (but Heroku Scheduler used for now)
- Hosted on **Heroku**, using **PostgreSQL**

## 📂 Project Structure

```

open-data-insights/
├── daily\_tasks/              # Modular scripts for data sync + insight generation
│   ├── data\_news.py
│   ├── make\_data\_insights.py
│   ├── send\_data\_insights.py
│   └── synch\_dataset.py
├── reports/                  # Django app (includes management commands)
│   └── management/commands/
│       └── daily\_job.py      # Runs the full daily pipeline
├── templates/                # Django templates for story display
├── static/                   # CSS/JS assets
├── requirements.txt
└── Procfile                  # Heroku dyno configuration

````

## 🚀 Running the Daily Job

```bash
python manage.py daily_job
````

This will:

1. Synchronize selected open datasets
2. Generate insights and story content
3. Email subscribers

You can also run the individual components directly using:

```bash
python daily_tasks/make_data_insights.py --id 42 --date 2025-06-28 --force
```

## 📬 Email Subscriptions

Users can subscribe to selected datasets and receive data stories by email (daily or weekly). Email delivery is handled via Django’s built-in system (SMTP or SES).

## 🛠 Deployment

### Heroku

To deploy:

```bash
git push heroku main
```

Use Heroku Scheduler to run the daily job:

```bash
python manage.py daily_job
```

### GitHub

Main source code is hosted on GitHub:
[https://github.com/lcalmbach/open-data-insights](https://github.com/lcalmbach/open-data-insights)

## 📄 License

MIT License (or update if different)

---

## 🙋‍♂️ About

Created by Lukas Calmbach.
Built to make public data more transparent and actionable.

```

---

Would you like me to:
- Localize this into German as well?
- Add instructions for local dev setup (virtualenv, `.env`, etc.)?
- Add badges (e.g. Heroku deployment, license, Python version)?

Let me know, and I’ll tailor it further.
```
