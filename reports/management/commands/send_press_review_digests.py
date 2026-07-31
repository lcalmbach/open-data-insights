from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from reports.services import PressReviewMailer


class Command(BaseCommand):
    help = "Send the Press Review digest to users with unsent, above-threshold article scores"

    def add_arguments(self, parser):
        User = get_user_model()
        parser.add_argument(
            "--date",
            type=str,
            help="Date label to use in the email subject (YYYY-MM-DD format). Defaults to today.",
        )
        parser.add_argument(
            "--frequency",
            choices=[
                User.PRESS_REVIEW_FREQUENCY_DAILY,
                User.PRESS_REVIEW_FREQUENCY_WEEKLY,
            ],
            default=User.PRESS_REVIEW_FREQUENCY_DAILY,
            help=(
                "Which cadence to send. Run with 'daily' on a daily schedule and "
                "'weekly' on a weekly schedule; each only mails users who chose it."
            ),
        )

    def handle(self, *args, **options):
        send_date = None
        if options.get("date"):
            try:
                send_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stdout.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD format."))
                return

        service = PressReviewMailer()
        result = service.send_digests_for_date(
            send_date=send_date, frequency=options["frequency"]
        )

        self.stdout.write(self.style.SUCCESS("Press review digest send complete"))
        self.stdout.write(f"Frequency: {result['frequency']}")
        self.stdout.write(f"Sent: {result['total_sent']}")
        self.stdout.write(f"Articles: {result['total_articles']}")
        if result.get("total_held_back"):
            self.stdout.write(
                self.style.WARNING(
                    f"Held back: {result['total_held_back']} (digest cap reached; "
                    f"they go out on the next run)"
                )
            )
        if result["errors"]:
            self.stdout.write(self.style.WARNING(f"Errors: {len(result['errors'])}"))
            for err in result["errors"]:
                self.stdout.write(f"  - {err}")
