from django.core.management.base import BaseCommand
from reports.services import PressReviewRelevanceService


class Command(BaseCommand):
    help = "Score harvested Press Review articles for relevance against each user's keywords"

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            type=str,
            help="AI model id to use for scoring (defaults to settings.DEFAULT_AI_MODEL)",
        )

    def handle(self, *args, **options):
        service = PressReviewRelevanceService(model=options.get("model"))
        result = service.rate_all_users()

        self.stdout.write(self.style.SUCCESS("Press review relevance rating complete"))
        self.stdout.write(f"Model: {result['model']}")
        self.stdout.write(f"Rated: {result['rated']}")
        self.stdout.write(f"Skipped: {result['skipped']}")
        if result["errors"]:
            self.stdout.write(self.style.WARNING(f"Errors: {len(result['errors'])}"))
            for err in result["errors"]:
                self.stdout.write(f"  - {err}")
