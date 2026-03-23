from __future__ import annotations

from reports.models.story import Story
from reports.models.story_template import StoryImage


def resolve_story_images(story: Story) -> list[StoryImage]:
    focus = getattr(story, "templatefocus", None)
    if focus is None:
        return []

    links = (
        focus.focus_image_links.select_related("image")
        .order_by("sort_order", "id")
    )
    images: list[StoryImage] = []
    for link in links:
        image = getattr(link, "image", None)
        if image and image.display_url:
            images.append(image)
    return images
