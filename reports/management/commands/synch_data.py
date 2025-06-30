from django.core.management.base import BaseCommand
from daily_tasks import synch_datasets

class Command(BaseCommand):
    help = 'Runs the daily data job: sync, generate, send'

    def handle(self, *args, **options):
        synch_datasets.run()
