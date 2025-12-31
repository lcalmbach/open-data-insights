from typing import Iterable

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from reports.models import StoryTemplate
from reports.services import StorySubscriptionService


class Command(BaseCommand):
    help = (
        "Subscribe a specific user/template pair or the entire user/template set. "
        "Defaults to subscribing every active user to every active template."
    )

    def add_arguments(self, parser):
        user_group = parser.add_mutually_exclusive_group()
        user_group.add_argument(
            "--user",
            type=str,
            help="Identifier for a single user (ID, slug, or email).",
        )
        user_group.add_argument(
            "--user_all",
            action="store_true",
            help="Subscribe every active user (default behaviour when --user is omitted).",
        )

        template_group = parser.add_mutually_exclusive_group()
        template_group.add_argument(
            "--template",
            type=str,
            help="Identifier for a single template (ID, slug, or title).",
        )
        template_group.add_argument(
            "--template_all",
            action="store_true",
            help="Subscribe to every active template (default when --template is omitted).",
        )

    def handle(self, *args, **options):
        user_identifier = options.get("user")
        template_identifier = options.get("template")

        target_all_users = options.get("user_all") or user_identifier is None
        target_all_templates = options.get("template_all") or template_identifier is None

        if target_all_users:
            users_to_subscribe: Iterable = None
            self.stdout.write("Targeting every active user for subscription.")
        else:
            user = self._resolve_user(user_identifier)
            users_to_subscribe = [user]
            self.stdout.write(f"Targeting user: {user}")

        if target_all_templates:
            templates_to_subscribe: Iterable[StoryTemplate] = None
            self.stdout.write("Targeting every active story template for subscription.")
        else:
            template = self._resolve_template(template_identifier)
            templates_to_subscribe = [template]
            self.stdout.write(f"Targeting template: {template}")

        service = StorySubscriptionService()
        result = service.subscribe_users_to_templates(
            users=users_to_subscribe, templates=templates_to_subscribe
        )

        summary = (
            f"Created {result['created']} subscriptions, skipped {result['skipped']}, "
            f"failed {result['failed']}."
        )

        if result["success"]:
            self.stdout.write(self.style.SUCCESS(summary))
        else:
            raise CommandError(
                f"{summary} Some subscriptions failed; check the logs for details."
            )

    def _resolve_user(self, identifier: str):
        user_model = get_user_model()
        lookups = []
        try:
            lookups.append(("id", int(identifier)))
        except (TypeError, ValueError):
            pass
        lookups.append(("slug", identifier))
        lookups.append(("email", identifier))

        for field, value in lookups:
            try:
                return user_model.objects.get(**{field: value})
            except user_model.DoesNotExist:
                continue
            except user_model.MultipleObjectsReturned:
                raise CommandError(
                    f"Multiple users matched '{identifier}' via {field}. "
                    "Provide a unique slug, email, or numeric ID."
                )

        raise CommandError(f"No user found matching '{identifier}'.")

    def _resolve_template(self, identifier: str):
        lookups = []
        try:
            lookups.append(("id", int(identifier)))
        except (TypeError, ValueError):
            pass
        lookups.append(("slug", identifier))
        lookups.append(("title", identifier))

        for field, value in lookups:
            try:
                return StoryTemplate.objects.get(**{field: value})
            except StoryTemplate.DoesNotExist:
                continue
            except StoryTemplate.MultipleObjectsReturned:
                raise CommandError(
                    f"Multiple templates matched '{identifier}' via {field}. "
                    "Provide a unique slug, title, or numeric ID."
                )

        raise CommandError(f"No story template found matching '{identifier}'.")
