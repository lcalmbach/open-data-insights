from django.core.management.base import BaseCommand
from daily_tasks import synch_datasets, make_data_insights, send_data_insights

class Command(BaseCommand):
    help = 'Runs the daily data job: sync, generate, send'

    def handle(self, *args, **options):
        self.stdout.write("🔄 Starting daily job...")

        # Step 1: sync dataset
        self.stdout.write("🔹 Syncing dataset...")
        synch_datasets.run()  # or whatever function you defined

        # Step 2: generate data insights
        self.stdout.write("🔹 Generating insights...")
        make_data_insights.run()

        # Step 3: send emails
        self.stdout.write("📬 Sending insights...")
        send_data_insights.run()

        self.stdout.write("✅ Daily job completed.")
