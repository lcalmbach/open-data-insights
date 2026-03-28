from types import SimpleNamespace

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from reports.management.commands.publish_story_images import (
    _build_s3_key,
    _story_image_lookup_kwargs,
)


class PublishStoryImagesHelperTests(SimpleTestCase):
    def test_build_s3_key_prefixes_media_location(self):
        self.assertEqual(
            _build_s3_key("story_template_focus/example.jpg", "media"),
            "media/story_template_focus/example.jpg",
        )

    def test_build_s3_key_keeps_existing_media_prefix(self):
        self.assertEqual(
            _build_s3_key("media/story_template_focus/example.jpg", "media"),
            "media/story_template_focus/example.jpg",
        )

    def test_story_image_lookup_prefers_identifier_key(self):
        image = SimpleNamespace(
            image_identifier_key="img-123",
            image_source_url="https://example.com/source",
            remote_url="https://example.com/remote",
            image=SimpleNamespace(name="story_template_focus/example.jpg"),
            title="Example",
            author="Author",
            image_source="Source",
        )

        self.assertEqual(
            _story_image_lookup_kwargs(image),
            {"image_identifier_key": "img-123"},
        )

    def test_story_image_lookup_falls_back_to_uploaded_image_name(self):
        image = SimpleNamespace(
            image_identifier_key="",
            image_source_url="",
            remote_url="",
            image=SimpleNamespace(name="story_template_focus/example.jpg"),
            title="",
            author="",
            image_source="",
        )

        self.assertEqual(
            _story_image_lookup_kwargs(image),
            {"image": "story_template_focus/example.jpg"},
        )

    def test_story_image_lookup_requires_stable_identifier(self):
        image = SimpleNamespace(
            image_identifier_key="",
            image_source_url="",
            remote_url="",
            image=SimpleNamespace(name=""),
            title="Example",
            author="",
            image_source="",
        )

        with self.assertRaises(CommandError):
            _story_image_lookup_kwargs(image)
