import logging
from typing import Optional, Iterable, Dict, Any
from django.contrib.auth import get_user_model
from django.db import transaction
from reports.models.story_template import StoryTemplate

logger = logging.getLogger(__name__)


class StorySubscriptionService:
    """Service that subscribes users with auto_subscribe=True to story templates.

    The service is idempotent: it only creates missing subscriptions and skips
    ones that already exist. It relies on the StoryTemplateSubscription related
    manager available as `template.subscriptions` (see models.StoryTemplateSubscription.related_name).
    """

    def subscribe_users_to_new_stories(self, templates: Optional[Iterable[StoryTemplate]] = None) -> Dict[str, Any]:
        User = get_user_model()
        users = User.objects.filter(auto_subscribe=True, is_active=True)
        if not users.exists():
            logger.info("No active users with auto_subscribe=True found")
            return {"success": True, "successful": 0, "failed": 0, "details": []}

        # default to published templates
        if templates is None:
            templates_qs = StoryTemplate.objects.filter(is_published=True, active=True)
        else:
            templates_qs = templates

        total_ok = 0
        total_failed = 0
        details = []

        for template in templates_qs:
            # subscribe all users to this template
            with transaction.atomic():
                for user in users:
                    try:
                        created = False
                        # Use the StoryTemplateSubscription related manager on the template
                        # related_name is 'subscriptions', so template.subscriptions exists
                        rel = getattr(template, "subscriptions")

                        # check active subscription (not cancelled)
                        exists = rel.filter(user=user, cancellation_date__isnull=True).exists()
                        if not exists:
                            rel.create(user=user)
                            created = True

                        if created:
                            total_ok += 1

                        details.append({"user": str(user), "template_id": template.id, "created": bool(created)})
                    except Exception as e:
                        logger.exception("Error subscribing user %s to template %s: %s", user, getattr(template, 'id', None), e)
                        total_failed += 1
                        details.append({"user": str(user), "template_id": getattr(template, 'id', None), "error": str(e)})
                        # continue with other users/templates
        success = total_failed == 0
        return {"success": success, "successful": total_ok, "failed": total_failed, "details": details}
