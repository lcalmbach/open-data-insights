import logging
from typing import Optional, Iterable, Dict, Any
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from reports.models.story_template import StoryTemplate

logger = logging.getLogger(__name__)


class StorySubscriptionService:
    """Service that subscribes users with auto_subscribe=True to story templates.

    The service is idempotent: it only creates missing subscriptions and skips
    ones that already exist.
    """

    def subscribe_users_to_new_stories(
        self, templates: Optional[Iterable[StoryTemplate]] = None
    ) -> Dict[str, Any]:
        """Subscribe all auto-subscribe users to the given templates.

        Returns:
            {
                "success": bool,           # True if no errors occurred
                "successful": int,         # Alias for 'created' to match pipeline expectations
                "created": int,            # Number of new subscriptions created
                "skipped": int,            # Number of existing subscriptions skipped
                "failed": int,             # Number of failures
                "details": [...]           # Per-user/template results
            }
        """
        User = get_user_model()
        users = User.objects.filter(auto_subscribe=True, is_active=True)
        if not users.exists():
            logger.info("No active users with auto_subscribe=True found")
            return {
                "success": True,
                "successful": 0,
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "details": [],
            }

        # Default to not yet published, these are the new ones that no user has had to opportunity to
        # subscribe to, active templates
        if templates is None:
            templates_qs = StoryTemplate.objects.filter(is_published=False, active=True)
        else:
            templates_qs = templates

        return self.subscribe_users_to_templates(users=users, templates=templates_qs)

    def subscribe_users_to_templates(
        self,
        users: Optional[Iterable[Any]] = None,
        templates: Optional[Iterable[StoryTemplate]] = None,
    ) -> Dict[str, Any]:
        """Subscribe (optionally filtered) users to the provided templates."""
        User = get_user_model()
        if users is None:
            users_iterable = User.objects.filter(is_active=True)
        else:
            users_iterable = users

        users_list = list(users_iterable)
        if not users_list:
            logger.info("No users provided for subscription request.")
            return {
                "success": True,
                "successful": 0,
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "details": [],
            }

        if templates is None:
            templates_iterable = StoryTemplate.objects.filter(active=True)
        else:
            templates_iterable = templates

        if hasattr(templates_iterable, "prefetch_related"):
            templates_iterable = templates_iterable.prefetch_related("subscriptions")

        templates_list = list(templates_iterable)
        if not templates_list:
            logger.info("No story templates provided for subscription request.")
            return {
                "success": True,
                "successful": 0,
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "details": [],
            }

        total_created = 0
        total_skipped = 0
        total_failed = 0
        details = []

        for template in templates_list:
            existing_user_ids = set(
                template.subscriptions.filter(cancellation_date__isnull=True).values_list(
                    "user_id", flat=True
                )
            )

            for user in users_list:
                try:
                    if user.id in existing_user_ids:
                        total_skipped += 1
                        details.append(
                            {
                                "user": str(user),
                                "template_id": template.id,
                                "status": "skipped",
                                "success": True,
                            }
                        )
                    else:
                        with transaction.atomic():
                            template.subscriptions.create(user=user)
                        total_created += 1
                        details.append(
                            {
                                "user": str(user),
                                "template_id": template.id,
                                "status": "created",
                                "success": True,
                            }
                        )
                except IntegrityError as e:
                    logger.warning(
                        "Subscription already exists for user %s, template %s: %s",
                        user,
                        template.id,
                        e,
                    )
                    total_skipped += 1
                    details.append(
                        {
                            "user": str(user),
                            "template_id": template.id,
                            "status": "skipped",
                            "success": True,
                        }
                    )
                except Exception as e:
                    logger.exception(
                        "Error subscribing user %s to template %s: %s",
                        user,
                        template.id,
                        e,
                    )
                    total_failed += 1
                    details.append(
                        {
                            "user": str(user),
                            "template_id": template.id,
                            "status": "failed",
                            "success": False,
                            "error": str(e),
                        }
                    )

        success = total_failed == 0
        return {
            "success": success,
            "successful": total_created,
            "created": total_created,
            "skipped": total_skipped,
            "failed": total_failed,
            "details": details,
        }
