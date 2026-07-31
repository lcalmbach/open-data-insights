from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from reports.services import (
    EmailService,
    PressReviewHarvestService,
    PressReviewMailer,
    PressReviewRelevanceService,
)


class Command(BaseCommand):
    help = (
        "Run the complete Press Review pipeline: harvest RSS sources, score articles "
        "per user, and send digests. Parallel to run_etl_pipeline, which drives stories."
    )

    def add_arguments(self, parser):
        User = get_user_model()
        parser.add_argument(
            '--date',
            type=str,
            help='Date label for the digest email subject (YYYY-MM-DD). Defaults to today.'
        )
        parser.add_argument(
            '--frequency',
            choices=[
                User.PRESS_REVIEW_FREQUENCY_DAILY,
                User.PRESS_REVIEW_FREQUENCY_WEEKLY,
            ],
            default=User.PRESS_REVIEW_FREQUENCY_DAILY,
            help=(
                "Which cadence to mail in the send step. Harvesting and scoring always "
                "run for everyone; only the send step is split by cadence."
            ),
        )
        parser.add_argument(
            '--model',
            type=str,
            help='AI model id for relevance scoring (defaults to settings.DEFAULT_AI_MODEL)'
        )
        parser.add_argument(
            '--skip-harvest',
            action='store_true',
            help='Skip the RSS harvesting step'
        )
        parser.add_argument(
            '--skip-rating',
            action='store_true',
            help='Skip the relevance scoring step'
        )
        parser.add_argument(
            '--skip-email',
            action='store_true',
            help='Skip the digest sending step'
        )
        parser.add_argument(
            '--stop-on-error',
            action='store_true',
            help='Stop pipeline execution if a step fails (default continues automatically)'
        )

    def handle(self, *args, **options):
        send_date = None
        if options.get('date'):
            try:
                send_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR("Invalid date format. Use YYYY-MM-DD format.")
                )
                return

        frequency = options['frequency']
        continue_on_error = not options.get('stop_on_error', False)
        email_service = EmailService()
        date_label = send_date.strftime("%Y-%m-%d") if send_date else "today"

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Press Review pipeline (frequency: {frequency}, date: {date_label})"
            )
        )

        def _fail(step: str, message: str) -> bool:
            """Report a failed step; return True if the pipeline should stop."""
            self.stdout.write(self.style.ERROR(message))
            email_service.send_admin_alert(
                subject=f"Press Review pipeline failure: {step} ({date_label})",
                body=message,
            )
            if not continue_on_error:
                self.stdout.write(
                    "Stopping pipeline because --stop-on-error was set. "
                    "Remove that flag to continue past failures."
                )
                return True
            return False

        # Step 1: Harvest RSS sources
        if not options.get('skip_harvest'):
            self.stdout.write("Step 1: Harvesting RSS sources...")
            harvest_result = PressReviewHarvestService().harvest()
            summary = (
                f"Sources: {harvest_result['sources_checked']}, "
                f"New: {harvest_result['articles_new']}, "
                f"Skipped: {harvest_result['articles_skipped']}, "
                f"Pruned: {harvest_result['articles_pruned']}"
            )
            if harvest_result['errors']:
                failure_message = (
                    f"✗ Harvesting encountered {len(harvest_result['errors'])} source error(s). "
                    f"{summary}. Errors: " + "; ".join(harvest_result['errors'])
                )
                if _fail("Harvest", failure_message):
                    return
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Harvesting completed. {summary}")
                )
        else:
            self.stdout.write("Skipping RSS harvesting...")

        # Step 2: Score articles per user
        if not options.get('skip_rating'):
            self.stdout.write("Step 2: Scoring article relevance...")
            rating_result = PressReviewRelevanceService(model=options.get('model')).rate_all_users()
            summary = (
                f"Model: {rating_result['model']}, "
                f"Rated: {rating_result['rated']}, Skipped: {rating_result['skipped']}"
            )
            if rating_result['errors']:
                failure_message = (
                    f"✗ Relevance scoring encountered {len(rating_result['errors'])} error(s). "
                    f"{summary}. Errors: " + "; ".join(rating_result['errors'])
                )
                if _fail("Relevance scoring", failure_message):
                    return
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Relevance scoring completed. {summary}")
                )
        else:
            self.stdout.write("Skipping relevance scoring...")

        # Step 3: Send digests
        if not options.get('skip_email'):
            self.stdout.write(f"Step 3: Sending {frequency} digests...")
            send_result = PressReviewMailer().send_digests_for_date(
                send_date=send_date, frequency=frequency
            )
            summary = (
                f"Sent: {send_result['total_sent']}, "
                f"Articles: {send_result['total_articles']}"
            )
            if send_result.get('total_held_back'):
                summary += (
                    f", Held back: {send_result['total_held_back']} "
                    f"(digest cap; sent on the next run)"
                )
            if send_result['errors']:
                failure_message = (
                    f"✗ Digest sending encountered {len(send_result['errors'])} error(s). "
                    f"{summary}. Errors: " + "; ".join(send_result['errors'])
                )
                if _fail("Digest sending", failure_message):
                    return
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Digest sending completed. {summary}")
                )
        else:
            self.stdout.write("Skipping digest sending...")

        self.stdout.write(self.style.SUCCESS("Press Review pipeline completed!"))
