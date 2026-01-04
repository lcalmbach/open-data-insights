from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StoryTemplateSubscription


@receiver(post_save, sender=get_user_model())
def subscribe_new_user_to_templates(sender, instance, created, **kwargs):
    """Subscribe every newly created user to all story templates."""
    if not created:
        return
    StoryTemplateSubscription.subscribe_user_to_all_templates(instance)
