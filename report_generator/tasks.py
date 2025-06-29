from celery import shared_task
from .models import Subscription  # your app logic

@shared_task
def run_daily_data_update():
    # call your logic to fill DB, generate stories, send emails
    print("Running daily job...")
