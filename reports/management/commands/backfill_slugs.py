# reports/management/commands/backfill_slugs.py
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Iterable, Callable, Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Model, QuerySet

from reports.models.story_template import StoryTemplate
from reports.models.story_table_template import StoryTemplateTable
from reports.models.graphic_template import StoryTemplateGraphic
from reports.models.story_context import StoryTemplateContext


def gen_slug(n: int = 10) -> str:
    """Generate a short random slug (hex)."""
    return uuid.uuid4().hex[:n]

def backfill_global_unique_slugs(
    qs: QuerySet,
    slug_attr: str = "slug",
    dry_run: bool = False,
    chunk_size: int = 1000,
) -> int:
    """
    Backfill for models where slug is globally unique (e.g., StoryTemplate).
    """
    model = qs.model
    updated = 0

    # Track already used slugs to avoid collisions in-memory
    used = set(
        model.objects.exclude(**{f"{slug_attr}__isnull": True})
        .exclude(**{slug_attr: ""})
        .values_list(slug_attr, flat=True)
    )

    # iterate only items missing slug
    qs_missing = qs.filter(**{f"{slug_attr}__isnull": True}) | qs.filter(**{slug_attr: ""})
    qs_missing = qs_missing.order_by("pk")

    with transaction.atomic():
        for obj in qs_missing.iterator(chunk_size=chunk_size):
            # if model's save() sets slug itself, just call save()
            slug = getattr(obj, slug_attr, None)
            if not slug:
                # try model's save() logic first
                if not dry_run:
                    # call save() to trigger model's logic
                    obj.save()
                    # if still empty, set ourselves
                    if not getattr(obj, slug_attr, None):
                        s = gen_slug()
                        while s in used:
                            s = gen_slug()
                        setattr(obj, slug_attr, s)
                        obj.save(update_fields=[slug_attr])
                updated += 1

                # in both paths, ensure we track the used value
                if not dry_run:
                    used.add(getattr(obj, slug_attr))
    return updated

def backfill_per_parent_unique_slugs(
    qs: QuerySet,
    parent_field: str = "story_template",
    slug_attr: str = "slug",
    dry_run: bool = False,
    chunk_size: int = 1000,
) -> int:
    """
    Backfill for child models where slug must be unique per parent (e.g., StoryTemplateTable/Graphic/Context).
    """
    model = qs.model
    updated = 0

    # map parent_id -> set(slugs)
    used_per_parent = defaultdict(set)
    for row in model.objects.exclude(**{f"{slug_attr}__isnull": True}).exclude(**{slug_attr: ""}).values(parent_field, slug_attr):
        used_per_parent[row[parent_field]].add(row[slug_attr])

    qs_missing = qs.filter(**{f"{slug_attr}__isnull": True}) | qs.filter(**{slug_attr: ""})
    qs_missing = qs_missing.order_by("pk")

    with transaction.atomic():
        for obj in qs_missing.iterator(chunk_size=chunk_size):
            parent_id = getattr(obj, f"{parent_field}_id")
            current = getattr(obj, slug_attr, None)

            if not current:
                if not dry_run:
                    # try model's own save() first
                    obj.save()
                    current = getattr(obj, slug_attr, None)

                if not current:
                    # generate ourselves and ensure uniqueness per parent
                    s = gen_slug()
                    used = used_per_parent[parent_id]
                    while s in used:
                        s = gen_slug()
                    if not dry_run:
                        setattr(obj, slug_attr, s)
                        obj.save(update_fields=[slug_attr])
                        used.add(s)
                updated += 1

    return updated


class Command(BaseCommand):
    help = "Backfill missing slugs for StoryTemplate and related child models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Don't write changes, only report counts--dry-run.",
        )
        parser.add_argument(
            "--only",
            nargs="*",
            choices=[
                "StoryTemplate",
                "StoryTemplateTable",
                "StoryTemplateGraphic",
                "StoryTemplateContext",
            ],
            help="Limit to specific models.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        only = set(options["only"] or [])

        total_updated = 0

        # 1) Parent first (global unique)
        if not only or "StoryTemplate" in only:
            self.stdout.write(self.style.NOTICE("Backfilling StoryTemplate..."))
            cnt = backfill_global_unique_slugs(StoryTemplate.objects.all(), dry_run=dry_run)
            total_updated += cnt
            self.stdout.write(self.style.SUCCESS(f"StoryTemplate updated: {cnt}"))

        # 2) Children (per parent unique)
        children = [
            ("StoryTemplateTable", StoryTemplateTable),
            ("StoryTemplateGraphic", StoryTemplateGraphic),
            ("StoryTemplateContext", StoryTemplateContext),
        ]
        for name, model in children:
            if only and name not in only:
                continue
            self.stdout.write(self.style.NOTICE(f"Backfilling {name}..."))
            cnt = backfill_per_parent_unique_slugs(model.objects.all(), parent_field="story_template", dry_run=dry_run)
            total_updated += cnt
            self.stdout.write(self.style.SUCCESS(f"{name} updated: {cnt}"))

        self.stdout.write(self.style.MIGRATE_HEADING(f"Done. Total updated: {total_updated}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run mode: no changes were written."))
