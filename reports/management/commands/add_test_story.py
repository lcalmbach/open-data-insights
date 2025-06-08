from django.core.management.base import BaseCommand
from reports.models import Story
from datetime import datetime

class Command(BaseCommand):
    help = "Adds a test story about a record heat event on May 22, 2025"

    def handle(self, *args, **kwargs):
        story = Story.objects.create(
            title="Record Cold day in May",
            prompt_text=(
                "Write a story about an exceptional cold record: "
                "on May 22, 2025, the highest temperature ever recorded in May was measured."
            ),
            ai_model="gpt-4-turbo",
            reference_period="May 22, 2025",
            content=(
                "On May 2, 2025, Switzerland experienced its coldest May day on record. "
                "Temperatures soared above previous highs, with multiple stations reporting values "
                "well above 35°C. This exceptional Cold wave highlights ongoing climate variability "
                "and may signal an early start to the summer season."
            ),
            published_date=datetime(2025, 5, 23, 9, 0),
        )
        self.stdout.write(self.style.SUCCESS(f"Story '{story.title}' successfully created with ID {story.id}"))

        story2 = Story.objects.create(
            title="Health Limit for Fine Particles Exceeded",
            prompt_text=(
                "Generate a story about an air quality event: "
                "on May 21, 2025, fine particle concentrations exceeded the WHO health guideline of 200 µg/m³."
            ),
            ai_model="gpt-4-turbo",
            reference_period="May 21, 2025",
            content=(
                "On May 21, 2025, air quality measurements in several urban areas showed exceptionally "
                "high levels of fine particulate matter (PM10), exceeding 200 µg/m³. "
                "This value is well above the WHO daily health guideline and may pose significant risks, "
                "especially to children, the elderly, and those with respiratory conditions. "
                "Local health authorities have advised residents to stay indoors and avoid heavy physical exertion. "
                "Such pollution episodes are often linked to traffic, industrial emissions, and weather inversions."
            ),
            published_date=datetime(2025, 5, 22, 9, 0),
        )

        self.stdout.write(self.style.SUCCESS(f"Story '{story2.title}' successfully created with ID {story2.id}"))
