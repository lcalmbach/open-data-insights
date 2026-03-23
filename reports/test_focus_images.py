from datetime import date
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from reports.models.lookups import (
    LookupCategory,
    Period,
    PeriodDirection,
    PERIOD_CATEGORY_ID,
    PERIOD_DIRECTION_CATEGORY_ID,
)
from reports.models.story import Story
from reports.models.story_template import (
    StoryImage,
    StoryTemplate,
    StoryTemplateFocus,
    StoryTemplateFocusImage,
)
from reports.services.focus_images import resolve_story_images


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="odi-test-media-"))
class FocusImageResolverTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        period_category = LookupCategory.objects.create(
            id=PERIOD_CATEGORY_ID,
            name="Period",
            description="",
        )
        direction_category = LookupCategory.objects.create(
            id=PERIOD_DIRECTION_CATEGORY_ID,
            name="Direction",
            description="",
        )
        cls.period = Period.objects.create(
            category=period_category,
            value="Daily",
            description="",
            sort_order=0,
        )
        cls.direction = PeriodDirection.objects.create(
            category=direction_category,
            value="Backward",
            description="",
            sort_order=0,
        )

    def _build_story(self) -> Story:
        template = StoryTemplate.objects.create(
            title="Image test story",
            description="",
            reference_period=self.period,
            period_direction=self.direction,
            prompt_text="prompt",
            active=True,
        )
        focus = StoryTemplateFocus.objects.create(
            story_template=template,
            filter_value="focus-1",
        )
        return Story.objects.create(
            templatefocus=focus,
            title="Story",
            summary="Summary",
            content="Content",
            published_date=date(2026, 3, 23),
            reference_period_start=date(2026, 3, 22),
            reference_period_end=date(2026, 3, 22),
        )

    def test_resolves_remote_url_image(self):
        story = self._build_story()
        image = StoryImage.objects.create(
            remote_url="https://example.com/image.jpg",
            title="Remote image",
        )
        StoryTemplateFocusImage.objects.create(
            focus=story.templatefocus,
            image=image,
            sort_order=0,
        )

        images = resolve_story_images(story)

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].display_url, "https://example.com/image.jpg")

    def test_display_url_prefers_uploaded_file_over_remote_url(self):
        story = self._build_story()
        image = StoryImage.objects.create(
            remote_url="https://example.com/fallback.jpg",
            title="Uploaded image",
        )
        image.image.save(
            "example.jpg",
            SimpleUploadedFile("example.jpg", b"fake-image-bytes", content_type="image/jpeg"),
            save=True,
        )
        StoryTemplateFocusImage.objects.create(
            focus=story.templatefocus,
            image=image,
            sort_order=0,
        )

        images = resolve_story_images(story)

        self.assertEqual(len(images), 1)
        self.assertIn("example.jpg", images[0].display_url)
        self.assertNotEqual(images[0].display_url, "https://example.com/fallback.jpg")
