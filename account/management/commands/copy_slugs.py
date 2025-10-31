from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Any, List

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.apps import apps


# Models
CustomUser = apps.get_model("account", "CustomUser")
Dataset = apps.get_model("reports", "Dataset")
StoryTemplate = apps.get_model("reports", "StoryTemplate")
StoryTemplateTable = apps.get_model("reports", "StoryTemplateTable")
StoryTemplateGraphic = apps.get_model("reports", "StoryTemplateGraphic")
StoryTemplateContext = apps.get_model("reports", "StoryTemplateContext")

# Which fields identify the SAME row across environments (adjust to your schema if needed)
MATCH_FIELDS: Dict[Any, Tuple[str, ...]] = {
    CustomUser: ("email",),
    Dataset: ("name",),
    StoryTemplate: ("name",),
    StoryTemplateTable: ("story_template__name", "name"),
    StoryTemplateGraphic: ("story_template__name", "name"),
    StoryTemplateContext: ("story_template__name", "key"),
}

MODEL_LIST = [
    CustomUser,
    Dataset,
    StoryTemplate,
    StoryTemplateTable,
    StoryTemplateGraphic,
    StoryTemplateContext,
]

MODEL_NAME = {m: f"{m._meta.app_label}.{m.__name__}" for m in MODEL_LIST}


@dataclass
class Stats:
    matched: int = 0
    updated: int = 0
    skipped_same: int = 0
    skipped_missing_dst: int = 0
    skipped_no_src_slug: int = 0
    skipped_has_other_slug: int = 0


class Command(BaseCommand):
    help = "Copy ONLY slug values from source DB (default) to destination DB (alias) by matching on stable fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="prod",
            help="Destination DB alias (default: 'prod').",
        )
        parser.add_argument(
            "--only",
            nargs="*",
            choices=[MODEL_NAME[m] for m in MODEL_LIST],
            help="Limit to specific models (e.g. 'reports.StoryTemplate account.CustomUser').",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite destination slug if it already exists and is different.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not write changes; only report.",
        )

    def handle(self, *args, **opts):
        dst_alias = opts["database"]
        dry = opts["dry_run"]
        force = opts["force"]
        only = set(opts.get("only") or [])

        # verify dest alias exists
        from django.conf import settings
        if dst_alias not in settings.DATABASES:
            raise CommandError(f"Database alias '{dst_alias}' not found in settings.DATABASES.")

        selected = [m for m in MODEL_LIST if not only or MODEL_NAME[m] in only]

        self.stdout.write(self.style.NOTICE(f"Destination alias: {dst_alias}"))
        if dry:
            self.stdout.write(self.style.WARNING("Dry-run mode: no changes will be written."))

        total = Stats()
        for model in selected:
            st = self._copy_model_slugs(model, dst_alias, dry=dry, force=force)
            total.matched += st.matched
            total.updated += st.updated
            total.skipped_same += st.skipped_same
            total.skipped_missing_dst += st.skipped_missing_dst
            total.skipped_no_src_slug += st.skipped_no_src_slug
            total.skipped_has_other_slug += st.skipped_has_other_slug

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"matched={total.matched}, updated={total.updated}, "
                f"same={total.skipped_same}, missing_dst={total.skipped_missing_dst}, "
                f"no_src_slug={total.skipped_no_src_slug}, has_other_slug={total.skipped_has_other_slug}"
            )
        )

    def _copy_model_slugs(self, model, dst_alias: str, *, dry: bool, force: bool) -> Stats:
        name = MODEL_NAME[model]
        match_fields = MATCH_FIELDS.get(model)
        if not match_fields:
            raise CommandError(f"No MATCH_FIELDS defined for {name}")

        self.stdout.write(self.style.MIGRATE_HEADING(f"[{name}] copying slugs…"))

        stats = Stats()

        # Iterate all source rows (local/default)
        src_qs = model.objects.using("default").all().select_related(
            *(f.split("__")[0] for f in match_fields if "__" in f)
        )

        for src in src_qs.iterator(chunk_size=1000):
            src_slug = getattr(src, "slug", None)
            if not src_slug:
                stats.skipped_no_src_slug += 1
                continue

            # Build lookup for destination using match_fields
            lookup = {}
            for f in match_fields:
                if "__" in f:
                    # follow relation, e.g. story_template__name
                    parts = f.split("__")
                    val = src
                    for p in parts:
                        val = getattr(val, p)
                        if val is None:
                            break
                    if val is None:
                        lookup = None
                        break
                    lookup[f] = val
                else:
                    lookup[f] = getattr(src, f)

            if not lookup:
                stats.skipped_missing_dst += 1
                continue

            # Resolve destination object by the same lookup (translated to FK where necessary)
            try:
                dst_obj = model.objects.using(dst_alias).get(**lookup)
            except model.DoesNotExist:
                stats.skipped_missing_dst += 1
                continue

            stats.matched += 1

            dst_slug = getattr(dst_obj, "slug", None)
            if dst_slug == src_slug:
                stats.skipped_same += 1
                continue

            if dst_slug and dst_slug != src_slug and not force:
                # already has a different slug; keep unless --force
                stats.skipped_has_other_slug += 1
                continue

            if dry:
                self.stdout.write(self.style.SUCCESS(f"  -> would set slug: {lookup}  {dst_slug!r} -> {src_slug!r}"))
                stats.updated += 1
                continue

            # Write slug only
            with transaction.atomic(using=dst_alias, savepoint=True):
                setattr(dst_obj, "slug", src_slug)
                dst_obj.save(using=dst_alias, update_fields=["slug"])
                self.stdout.write(self.style.SUCCESS(f"  -> set slug: {lookup}  {dst_slug!r} -> {src_slug!r}"))
                stats.updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  ↳ matched={stats.matched}, updated={stats.updated}, same={stats.skipped_same}, "
                f"missing_dst={stats.skipped_missing_dst}, no_src_slug={stats.skipped_no_src_slug}, "
                f"has_other_slug={stats.skipped_has_other_slug}"
            )
        )
        return stats
