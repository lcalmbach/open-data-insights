from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from reports.models import StoryTemplate
from account.models import CustomUser
from reports.models import StoryTemplateSubscription as Subscription

class Command(BaseCommand):
    help = "Ensure users with auto_subscribe=True are subscribed to all story templates"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Show what would change without persisting",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        templates = list(StoryTemplate.objects.all())
        if not templates:
            self.stdout.write(self.style.WARNING("No StoryTemplate objects found."))
            return

        users = CustomUser.objects.filter(auto_subscribe=True, is_active=True)
        if not users.exists():
            self.stdout.write(self.style.WARNING("No users found with auto_subscribe=True."))
            return

        added_count = 0
        for user in users:
            # use a transaction per user to avoid partial state if not dry-run
            with transaction.atomic():
                for template in templates:
                    subscriptions = template.subscriptions
                    if subscriptions.filter(user=user).exists():
                        continue  # already subscribed
                    else:
                        Subscription.objects.create(user=user, story_template=template)
                        added_count += 1

                # if dry_run we rollback explicitly
                if dry_run:
                    transaction.set_rollback(True)

            self.stdout.write(f"User {getattr(user, 'email', str(user))}: added {added_count} subscriptions{' (dry-run)' if dry_run else ''}")

        self.stdout.write(self.style.SUCCESS("Autosubscribe pass completed."))
