from datetime import date

from django.test import TestCase
from django.urls import reverse

from account.models import CustomUser
from reports.models.lookups import (
    PERIOD_CATEGORY_ID,
    PERIOD_DIRECTION_CATEGORY_ID,
    LookupCategory,
    Period,
    PeriodDirection,
)
from reports.models.story import Story
from reports.models.story_rating import StoryRating
from reports.models.story_template import StoryTemplate


class StoryRatingsContextTests(TestCase):
    def setUp(self):
        period_category = LookupCategory.objects.create(
            id=PERIOD_CATEGORY_ID, name="Period", description=""
        )
        direction_category = LookupCategory.objects.create(
            id=PERIOD_DIRECTION_CATEGORY_ID, name="PeriodDirection", description=""
        )
        period = Period.objects.create(
            category=period_category, value="Daily", description="", sort_order=0
        )
        direction = PeriodDirection.objects.create(
            category=direction_category, value="Backward", description="", sort_order=0
        )
        self.template = StoryTemplate.objects.create(
            title="Template",
            description="",
            reference_period=period,
            period_direction=direction,
            prompt_text="prompt",
            active=True,
        )
        self.story = Story.objects.create(
            template=self.template,
            title="Story",
            summary="Summary",
            content="Content",
            published_date=date(2026, 2, 8),
            reference_period_start=date(2026, 2, 7),
            reference_period_end=date(2026, 2, 7),
        )
        self.user = CustomUser.objects.create_user(
            email="user@example.com",
            password="password",
            first_name="Test",
            last_name="User",
            country="US",
        )

    def test_stories_view_includes_rating_context(self):
        self.client.force_login(self.user)
        StoryRating.objects.create(story=self.story, user=self.user, rating=4)

        response = self.client.get(reverse("stories"), {"story": self.story.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rating_count"], 1)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.0)
        self.assertEqual(response.context["rating_stars_full"], 4)
        self.assertEqual(response.context["rating_stars_half"], 0)

    def test_half_star_rounding_in_context(self):
        self.client.force_login(self.user)
        StoryRating.objects.create(story=self.story, user=self.user, rating=4)
        other_user = CustomUser.objects.create_user(
            email="user2@example.com",
            password="password",
            first_name="Other",
            last_name="User",
            country="US",
        )
        StoryRating.objects.create(story=self.story, user=other_user, rating=5)

        response = self.client.get(reverse("stories"), {"story": self.story.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rating_count"], 2)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.5)
        self.assertEqual(response.context["rating_stars_full"], 4)
        self.assertEqual(response.context["rating_stars_half"], 1)

    def test_rate_story_creates_new_record_each_time(self):
        self.client.force_login(self.user)

        url = reverse("rate_story", args=(self.story.id,))
        self.client.post(url, {"rating": 3, "rating_text": "ok"}, follow=True)
        self.assertEqual(
            StoryRating.objects.filter(story=self.story, user=self.user).count(), 1
        )

        response = self.client.post(
            url, {"rating": 5, "rating_text": "great"}, follow=True
        )
        self.assertEqual(
            StoryRating.objects.filter(story=self.story, user=self.user).count(), 2
        )
        self.assertEqual(response.context["user_rating"], 5)

    def test_home_view_includes_rating_context(self):
        self.client.force_login(self.user)
        StoryRating.objects.create(story=self.story, user=self.user, rating=4)

        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_story"].id, self.story.id)
        self.assertEqual(response.context["rating_count"], 1)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.0)
