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
        parser.add_argument(
            "--story_template_id",
            type=int,
            help="If set, subscribe users only to this story template.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        story_template_id = options.get("story_template_id")

        templates_qs = StoryTemplate.objects.all()
        if story_template_id:
            templates_qs = templates_qs.filter(id=story_template_id)
        templates = list(templates_qs)
        if not templates:
            if story_template_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"No StoryTemplate found with id={story_template_id}."
                    )
                )
            else:
                self.stdout.write(self.style.WARNING("No StoryTemplate objects found."))
            return

        users = CustomUser.objects.filter(auto_subscribe=True, is_active=True)
        if not users.exists():
            self.stdout.write(self.style.WARNING("No users found with auto_subscribe=True."))
            return

        total_added_count = 0
        for user in users:
            user_added_count = 0
            # use a transaction per user to avoid partial state if not dry-run
            with transaction.atomic():
                for template in templates:
                    subscriptions = template.subscriptions
                    if subscriptions.filter(user=user).exists():
                        continue  # already subscribed
                    else:
                        Subscription.objects.create(user=user, story_template=template)
                        user_added_count += 1
                        total_added_count += 1

                # if dry_run we rollback explicitly
                if dry_run:
                    transaction.set_rollback(True)

            self.stdout.write(
                f"User {getattr(user, 'email', str(user))}: "
                f"added {user_added_count} subscriptions"
                f"{' (dry-run)' if dry_run else ''}"
            )

        scope = (
            f"story_template_id={story_template_id}"
            if story_template_id
            else "all story templates"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Autosubscribe pass completed for {scope}. "
                f"Added {total_added_count} subscriptions"
                f"{' (dry-run)' if dry_run else ''}."
            )
        )
