from django.conf import settings
from django.core.management.base import BaseCommand

from reports.services import PressReviewHarvestService


class Command(BaseCommand):
    help = (
        "Delete harvested press review articles (and their derived per-user scores) "
        "older than the retention window. Also runs automatically after each harvest."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            help=(
                "Retention window in days. Defaults to "
                "settings.PRESSREVIEW_ARTICLE_RETENTION_DAYS. Use 0 to disable."
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be deleted without deleting anything.'
        )

    def handle(self, *args, **options):
        retention_days = options.get('days')
        if retention_days is None:
            retention_days = settings.PRESSREVIEW_ARTICLE_RETENTION_DAYS

        result = PressReviewHarvestService().prune_stale_articles(
            retention_days=retention_days, dry_run=options['dry_run']
        )

        if not result["enabled"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Pruning disabled (retention_days={result['retention_days']}); nothing removed."
                )
            )
            return

        articles = result["would_delete_articles"]
        scores = result["would_delete_scores"]

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: would delete {articles} article(s) and {scores} score(s) "
                    f"older than {result['retention_days']} day(s) (before {result['cutoff']})."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {articles} article(s) and {scores} score(s) older than "
                f"{result['retention_days']} day(s)."
            )
        )
