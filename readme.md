# Open Data Insights

**Open Data Insights** is a Django-based platform that transforms open datasets into automated, human-readable reports and insights. It is designed for statistical offices, journalists, and civic tech enthusiasts who want to turn raw public data into stories — automatically, every day.

## 🌐 Live Demo

Hosted on Heroku:  
👉 [https://ogd-data-insights-d6c65d72da95.herokuapp.com/](https://ogd-data-insights-d6c65d72da95.herokuapp.com/)

## 📦 Features

- ✅ **Automated Data Pipeline**: Daily data synchronization from public APIs (e.g., OpenDataSoft)
- ✅ **AI-Powered Insights**: Automatic generation of natural-language reports using OpenAI GPT
- ✅ **Email Notifications**: Automated email delivery to subscribed users
- ✅ **Modular Architecture**: Clean separation of concerns: sync → analyze → publish
- ✅ **Template-Based Stories**: Configurable story templates for different data types
- ✅ **Multi-Dataset Support**: Handles various data sources (weather, tourism, economics, etc.)
- ✅ **Extensible Design**: New datasets and story types can be added easily
- ✅ **Django Admin Interface**: Easy management of datasets, templates, and subscriptions

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