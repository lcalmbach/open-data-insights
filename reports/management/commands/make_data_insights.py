from datetime import date
from django.core.management.base import BaseCommand
from daily_tasks import make_data_insights

class Command(BaseCommand):
    help = 'Runs the data insights generation process'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, help='ID of the record to process')
        parser.add_argument('--date', type=lambda d: date.fromisoformat(d), help='Run date (YYYY-MM-DD)')
        parser.add_argument('--force', action='store_true', help='Force creation even if date does not match')

    def handle(self, *args, **options):
        self.stdout.write("🔹 Generating insights...")

        story_id = options.get('id')
        run_date = options.get('date')
        force = options.get('force', False)

        make_data_insights.run(story_id=story_id, run_date=run_date, force=force)

        self.stdout.write("✅ Daily job completed.")
