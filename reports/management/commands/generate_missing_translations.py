from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from openai import OpenAI

from reports.models.graphic import Graphic
from reports.models.lookups import Language, LanguageEnum
from reports.models.story import Story
from reports.models.story_table import StoryTable


class Command(BaseCommand):
    help = (
        "Generate missing translated Story records for stories that currently only "
        "exist in English. Also creates missing StoryTable/Graphic variants."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to the database.",
        )
        parser.add_argument(
            "--story-id",
            type=int,
            help="Only process one English story id.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit number of English stories to process.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        story_id = options.get("story_id")
        limit = options.get("limit")

        english_id = LanguageEnum.ENGLISH.value
        languages = list(
            Language.objects.exclude(id=english_id).order_by("sort_order", "value")
        )
        if not languages:
            self.stdout.write(self.style.WARNING("No target languages found."))
            return

        english_stories = (
            Story.objects.select_related("templatefocus__story_template")
            .filter(language_id=english_id)
            .order_by("id")
        )
        if story_id:
            english_stories = english_stories.filter(id=story_id)
        if limit:
            english_stories = english_stories[:limit]

        total_missing = 0
        created_stories = 0
        created_tables = 0
        created_graphics = 0

        for story in english_stories:
            for language in languages:
                if self._story_variant_exists(story, language.id):
                    continue
                total_missing += 1
                self.stdout.write(
                    f"Missing translation: story={story.id} lang={language.value} ({language.id})"
                )
                if dry_run:
                    continue

                with transaction.atomic():
                    translated_story = self._create_story_translation(story, language)
                    created_stories += 1
                    created_tables += self._copy_tables(story, translated_story, language.id)
                    created_graphics += self._copy_graphics(
                        story, translated_story, language.id
                    )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run complete. Missing translations found: {total_missing}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"Created stories: {created_stories}, "
                f"tables: {created_tables}, "
                f"graphics: {created_graphics}, "
                f"missing pairs processed: {total_missing}"
            )
        )

    def _story_variant_exists(self, story: Story, language_id: int) -> bool:
        return Story.objects.filter(
            templatefocus_id=story.templatefocus_id,
            reference_period_start=story.reference_period_start,
            reference_period_end=story.reference_period_end,
            published_date=story.published_date,
            language_id=language_id,
        ).exists()

    def _get_client(self, model_name: str) -> OpenAI:
        if model_name == "deepseek-chat":
            return OpenAI(
                api_key=getattr(settings, "DEEPSEEK_API_KEY", None),
                base_url="https://api.deepseek.com",
            )
        return OpenAI(api_key=getattr(settings, "OPENAI_API_KEY", None))

    def _translate_text(
        self, client: OpenAI, model_name: str, text: str, target_language_name: str, max_tokens: int
    ) -> str:
        if not text:
            return text
        messages = [
            {
                "role": "system",
                "content": (
                    f"Translate the input text to {target_language_name}. "
                    "Preserve meaning, links, markdown structure, and numeric values. "
                    "Return only the translated text."
                ),
            },
            {"role": "user", "content": text},
        ]
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.0,
            max_tokens=max_tokens,
        )
        translated = (response.choices[0].message.content or "").strip()
        return translated or text

    def _create_story_translation(self, source_story: Story, language: Language) -> Story:
        model_name = source_story.ai_model or getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o")
        client = self._get_client(model_name)

        translated_story = Story(
            templatefocus=source_story.templatefocus,
            title=self._translate_text(
                client, model_name, source_story.title or "", language.value, 120
            ),
            summary=self._translate_text(
                client, model_name, source_story.summary or "", language.value, 500
            ),
            published_date=source_story.published_date,
            prompt_text=f"Backfilled translation from story {source_story.id} ({LanguageEnum.ENGLISH.name})",
            context_values=source_story.context_values,
            ai_model=model_name,
            reference_period_start=source_story.reference_period_start,
            reference_period_end=source_story.reference_period_end,
            content=self._translate_text(
                client, model_name, source_story.content or "", language.value, 3000
            ),
            language_id=language.id,
        )
        translated_story.full_clean()
        translated_story.save()
        return translated_story

    def _copy_tables(self, source_story: Story, target_story: Story, language_id: int) -> int:
        count = 0
        for source_table in StoryTable.objects.filter(story=source_story):
            StoryTable.objects.create(
                story=target_story,
                table_template=source_table.table_template,
                title=source_table.title,
                data=source_table.data,
                language_id=language_id,
                sort_order=source_table.sort_order,
            )
            count += 1
        return count

    def _copy_graphics(self, source_story: Story, target_story: Story, language_id: int) -> int:
        count = 0
        for source_graphic in Graphic.objects.filter(story=source_story):
            Graphic.objects.create(
                story=target_story,
                graphic_template=source_graphic.graphic_template,
                title=source_graphic.title,
                content_html=source_graphic.content_html,
                data=source_graphic.data,
                language_id=language_id,
                sort_order=source_graphic.sort_order,
            )
            count += 1
        return count
