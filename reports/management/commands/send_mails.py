from django.core.management.base import BaseCommand
from daily_tasks import synch_datasets, make_data_insights, send_data_insights

class Command(BaseCommand):
    help = 'Runs the daily data job: sync, generate, send'

    def handle(self, *args, **options):
        # Step 3: send emails
        self.stdout.write("📬 Sending insights...")
        send_data_insights.run()