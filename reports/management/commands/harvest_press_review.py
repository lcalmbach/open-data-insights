from django.core.management.base import BaseCommand
from reports.services import PressReviewHarvestService


class Command(BaseCommand):
    help = "Harvest active Press Review RSS sources and store matching articles"

    def handle(self, *args, **options):
        service = PressReviewHarvestService()
        result = service.harvest()

        self.stdout.write(self.style.SUCCESS("Press review harvest complete"))
        self.stdout.write(f"Sources checked: {result['sources_checked']}")
        self.stdout.write(f"New articles: {result['articles_new']}")
        self.stdout.write(f"Skipped: {result['articles_skipped']}")
        if result.get("articles_pruned"):
            self.stdout.write(f"Pruned (past retention): {result['articles_pruned']}")
        if result["errors"]:
            self.stdout.write(self.style.WARNING(f"Errors: {len(result['errors'])}"))
            for err in result["errors"]:
                self.stdout.write(f"  - {err}")
