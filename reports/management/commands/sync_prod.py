from __future__ import annotations

from typing import Iterable, Dict, Any, Optional
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction, models
from django.apps import apps


# ---- Modelle dynamisch auflösen (vermeidet Import-Loops) ----
Dataset = apps.get_model("reports", "Dataset")
StoryTemplate = apps.get_model("reports", "StoryTemplate")
StoryTemplateGraphic = apps.get_model("reports", "StoryTemplateGraphic")
StoryTemplateTable = apps.get_model("reports", "StoryTemplateTable")
StoryTemplateContext = apps.get_model("reports", "StoryTemplateContext")


PARENT_MODELS = [Dataset, StoryTemplate]
CHILD_SPECS = [
    (StoryTemplateGraphic, "story_template", StoryTemplate),
    (StoryTemplateTable, "story_template", StoryTemplate),
    (StoryTemplateContext, "story_template", StoryTemplate),
]

MODEL_NAME = {
    Dataset: "Dataset",
    StoryTemplate: "StoryTemplate",
    StoryTemplateGraphic: "StoryTemplateGraphic",
    StoryTemplateTable: "StoryTemplateTable",
    StoryTemplateContext: "StoryTemplateContext",
}

EXCLUDE_FIELDS_BY_MODEL = {
    Dataset: {"id", "slug"},
    StoryTemplate: {"id", "slug"},
    StoryTemplateGraphic: {"id", "slug"},
    StoryTemplateTable: {"id", "slug"},
    StoryTemplateContext: {"id", "slug"},
}


def _is_concrete_field(f: models.Field) -> bool:
    return isinstance(f, models.Field) and not f.auto_created


def _iter_model_fields(model: models.Model) -> Iterable[models.Field]:
    for f in model._meta.get_fields():
        if _is_concrete_field(f):
            yield f


def _values_dict_from_instance(
    obj: models.Model,
    *,
    exclude: Iterable[str] = (),
) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for f in _iter_model_fields(obj.__class__):
        if f.name in exclude:
            continue
        if isinstance(f, models.ManyToManyField):
            continue
        # For ForeignKey fields, use the underlying "<field>_id" value (integer)
        # so we don't pass source-DB model instances into destination DB operations.
        if isinstance(f, models.ForeignKey):
            data[f.attname] = getattr(obj, f.attname)
            continue
        data[f.name] = getattr(obj, f.name)
    return data


def _get_connection(alias: str):
    if alias not in connections.databases:
        raise CommandError(f"Database alias '{alias}' not found in settings.DATABASES.")
    return connections[alias]


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class Command(BaseCommand):
    help = "Sync reports models between databases using slugs. Upsert only, no deletions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--direction",
            choices=["push", "pull"],
            required=True,
            help="push = from default to TARGET, pull = from TARGET to default",
        )
        parser.add_argument(
            "--database",
            default="prod",
            help="Target database alias for push/pull (default: 'prod').",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Don't write changes, just report what would be done.",
        )

        # Einzel-Entität Sync: --id + genau eine Zielart
        parser.add_argument("--id", type=int, help="Local PK of the entity to sync (source DB side).")

        mt = parser.add_mutually_exclusive_group()
        mt.add_argument("--dataset", action="store_true", help="Interpret --id as Dataset.id")
        mt.add_argument("--story_template", action="store_true", help="Interpret --id as StoryTemplate.id (sync incl. children)")
        mt.add_argument("--table_template", action="store_true", help="Interpret --id as StoryTemplateTable.id")
        mt.add_argument("--graphic_template", action="store_true", help="Interpret --id as StoryTemplateGraphic.id")
        mt.add_argument("--context", action="store_true", help="Interpret --id as StoryTemplateContext.id")

        # Backwards compatibility: Full-batch run (ohne --id)
        parser.add_argument(
            "--only",
            nargs="*",
            choices=[MODEL_NAME[m] for m in [Dataset, StoryTemplate, StoryTemplateGraphic, StoryTemplateTable, StoryTemplateContext]],
            help="(Batch mode) Limit to specific models.",
        )

    def handle(self, *args, **opts):
        direction: str = opts["direction"]
        target_alias: str = opts["database"]
        dry: bool = opts["dry_run"]

        _get_connection("default")
        _get_connection(target_alias)

        if direction == "push":
            src_alias, dst_alias = "default", target_alias
        else:
            src_alias, dst_alias = target_alias, "default"

        self.stdout.write(self.style.NOTICE(f"Sync direction: {direction} ({src_alias} → {dst_alias})"))
        if dry:
            self.stdout.write(self.style.WARNING("Dry-run mode: no data will be written."))

        # Einzel-Entität?
        if opts.get("id") is not None:
            self._sync_single(opts, src_alias, dst_alias, dry)
            return

        # Batch-Modus (wie zuvor)
        only = opts.get("only")
        total = SyncStats()

        selected_parents = [m for m in PARENT_MODELS if (not only or MODEL_NAME[m] in only)]
        selected_children = [spec for spec in CHILD_SPECS if (not only or MODEL_NAME[spec[0]] in only)]

        for model in selected_parents:
            stats = self._sync_parent_model(model, src_alias, dst_alias, dry)
            total.created += stats.created; total.updated += stats.updated; total.skipped += stats.skipped

        for (child_model, parent_field, parent_model) in selected_children:
            stats = self._sync_child_model(child_model, parent_field, parent_model, src_alias, dst_alias, dry)
            total.created += stats.created; total.updated += stats.updated; total.skipped += stats.skipped

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created: {total.created}, Updated: {total.updated}, Skipped: {total.skipped}"
        ))

    # ----------------- Einzel-Entität -----------------

    def _sync_single(self, opts, src_alias: str, dst_alias: str, dry: bool):
        entity_id: int = opts["id"]

        flags = [k for k in ("dataset", "story_template", "table_template", "graphic_template", "context") if opts.get(k)]
        if len(flags) != 1:
            raise CommandError("Provide exactly one of --dataset / --story_template / --table_template / --graphic_template / --context together with --id.")

        flag = flags[0]

        if flag == "dataset":
            self._sync_one_parent_by_id(Dataset, entity_id, src_alias, dst_alias, dry)
        elif flag == "story_template":
            # Parent + alle Kinder dieses Templates
            parent = self._sync_one_parent_by_id(StoryTemplate, entity_id, src_alias, dst_alias, dry)
            if parent is None:
                return
            # Kinder per Parent-Slug syncen (nur die zugehörigen)
            for (child_model, parent_field, parent_model) in CHILD_SPECS:
                if parent_model is StoryTemplate:
                    self._sync_children_of_parent_slug(child_model, parent_field, parent.slug, src_alias, dst_alias, dry)
        elif flag == "table_template":
            self._sync_one_child_by_id(StoryTemplateTable, "story_template", entity_id, src_alias, dst_alias, dry)
        elif flag == "graphic_template":
            self._sync_one_child_by_id(StoryTemplateGraphic, "story_template", entity_id, src_alias, dst_alias, dry)
        elif flag == "context":
            self._sync_one_child_by_id(StoryTemplateContext, "story_template", entity_id, src_alias, dst_alias, dry)

    def _sync_one_parent_by_id(self, model, pk: int, src_alias: str, dst_alias: str, dry: bool):
        name = MODEL_NAME[model]
        self.stdout.write(self.style.MIGRATE_HEADING(f"[{name}] sync single parent id={pk} …"))

        try:
            obj = model.objects.using(src_alias).get(pk=pk)
        except model.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"  - Source {name} id={pk} not found."))
            return None

        slug = getattr(obj, "slug", None)
        if not slug:
            self.stdout.write(self.style.WARNING(f"  - Skipped {name} id={pk} (no slug)."))
            return None

        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(model, set())) | {"id"}
        data = _values_dict_from_instance(obj, exclude=exclude)
        dst_mgr = model.objects.using(dst_alias)

        if dry:
            exists = dst_mgr.filter(slug=slug).exists()
            if exists:
                self.stdout.write(self.style.SUCCESS(f"  -> would UPDATE {name} slug={slug}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"  -> would CREATE {name} slug={slug}"))
            return obj  # für story_template-children

        with transaction.atomic(using=dst_alias):
            dst_obj, created = dst_mgr.update_or_create(slug=slug, defaults=data)
            self.stdout.write(self.style.SUCCESS(
                f"  -> {'CREATED' if created else 'UPDATED'} {name} slug={slug}"
            ))
            return obj

    def _sync_one_child_by_id(self, child_model, parent_field: str, pk: int, src_alias: str, dst_alias: str, dry: bool):
        name = MODEL_NAME[child_model]
        self.stdout.write(self.style.MIGRATE_HEADING(f"[{name}] sync single child id={pk} …"))

        try:
            child = child_model.objects.using(src_alias).select_related(parent_field).get(pk=pk)
        except child_model.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"  - Source {name} id={pk} not found."))
            return

        slug = getattr(child, "slug", None)
        parent = getattr(child, parent_field, None)
        parent_slug = getattr(parent, "slug", None) if parent else None

        if not slug or not parent or not parent_slug:
            self.stdout.write(self.style.WARNING(f"  - Skipped {name} id={pk} (missing slug/parent)."))
            return

        # Stelle sicher, dass Parent in Ziel existiert (Upsert Parent)
        self._sync_one_parent_by_id(parent.__class__, parent.pk, src_alias, dst_alias, dry)

        # Upsert Child (Lookup: (parent, slug))
        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(child_model, set())) | {"id", parent_field + "_id"}
        data = _values_dict_from_instance(child, exclude=exclude)

        dst_child_mgr = child_model.objects.using(dst_alias)
        dst_parent_mgr = parent.__class__.objects.using(dst_alias)

        if dry:
            parent_exists = dst_parent_mgr.filter(slug=parent_slug).exists()
            if not parent_exists:
                self.stdout.write(self.style.WARNING(f"    · Parent missing in dst: {parent.__class__.__name__} slug={parent_slug}"))
                return
            exists = dst_child_mgr.filter(**{parent_field + "__slug": parent_slug, "slug": slug}).exists()
            self.stdout.write(self.style.SUCCESS(
                f"  -> would {'UPDATE' if exists else 'CREATE'} {name} parent={parent_slug} slug={slug}"
            ))
            return

        with transaction.atomic(using=dst_alias):
            dst_parent_obj = dst_parent_mgr.get(slug=parent_slug)
            try:
                dst_obj = dst_child_mgr.get(**{parent_field: dst_parent_obj, "slug": slug})
                # update
                for k, v in data.items():
                    setattr(dst_obj, k, v)
                dst_obj.save(update_fields=list(data.keys()))
                self.stdout.write(self.style.SUCCESS(
                    f"  -> UPDATED {name} parent={parent_slug} slug={slug}"
                ))
            except child_model.DoesNotExist:
                # create
                dst_obj = child_model(**data, **{parent_field: dst_parent_obj}, slug=slug)
                dst_obj.save(using=dst_alias)
                self.stdout.write(self.style.SUCCESS(
                    f"  -> CREATED {name} parent={parent_slug} slug={slug}"
                ))

    # ----------------- Batch-Helfer (wie zuvor) -----------------

    def _src_qs(self, model, using_alias: str):
        return model.objects.using(using_alias).all()

    def _dst_manager(self, model, using_alias: str):
        return model.objects.using(using_alias)

    def _sync_parent_model(self, model, src_alias: str, dst_alias: str, dry: bool) -> SyncStats:
        stats = SyncStats()
        name = MODEL_NAME[model]
        self.stdout.write(self.style.MIGRATE_HEADING(f"[{name}] syncing parents…"))

        src_qs = self._src_qs(model, src_alias).order_by("pk")
        dst_mgr = self._dst_manager(model, dst_alias)

        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(model, set())) | {"id"}

        for obj in src_qs.iterator(chunk_size=1000):
            slug = getattr(obj, "slug", None)
            if not slug:
                stats.skipped += 1
                continue

            data = _values_dict_from_instance(obj, exclude=exclude)

            if dry:
                if dst_mgr.filter(slug=slug).exists():
                    stats.updated += 1
                else:
                    stats.created += 1
                continue

            with transaction.atomic(using=dst_alias):
                dst_obj, created = dst_mgr.update_or_create(slug=slug, defaults=data)
                if created: stats.created += 1
                else: stats.updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"  -> {name}: created {stats.created}, updated {stats.updated}, skipped {stats.skipped}"
        ))
        return stats

    def _sync_child_model(self, child_model, parent_field: str, parent_model, src_alias: str, dst_alias: str, dry: bool) -> SyncStats:
        stats = SyncStats()
        name = MODEL_NAME[child_model]
        self.stdout.write(self.style.MIGRATE_HEADING(f"[{name}] syncing children…"))

        src_qs = self._src_qs(child_model, src_alias).select_related(parent_field).order_by("pk")
        dst_child = self._dst_manager(child_model, dst_alias)
        dst_parent = self._dst_manager(parent_model, dst_alias)

        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(child_model, set())) | {"id", parent_field + "_id"}

        for obj in src_qs.iterator(chunk_size=1000):
            slug = getattr(obj, "slug", None)
            parent_obj = getattr(obj, parent_field, None)
            parent_slug = getattr(parent_obj, "slug", None) if parent_obj else None

            if not slug or not parent_obj or not parent_slug:
                stats.skipped += 1
                continue

            if dry:
                if not dst_parent.filter(slug=parent_slug).exists():
                    stats.skipped += 1
                    continue
                exists = dst_child.filter(**{parent_field + "__slug": parent_slug, "slug": slug}).exists()
                if exists: stats.updated += 1
                else: stats.created += 1
                continue

            with transaction.atomic(using=dst_alias):
                try:
                    dst_parent_obj = dst_parent.get(slug=parent_slug)
                except parent_model.DoesNotExist:
                    # Parent fehlt → erst Parent upserten
                    self._sync_one_parent_by_id(parent_model, parent_obj.pk, src_alias, dst_alias, dry=False)
                    dst_parent_obj = dst_parent.get(slug=parent_slug)

                defaults = _values_dict_from_instance(obj, exclude=exclude)

                try:
                    dst_obj = dst_child.get(**{parent_field: dst_parent_obj, "slug": slug})
                    for k, v in defaults.items():
                        setattr(dst_obj, k, v)
                    dst_obj.save(update_fields=list(defaults.keys()))
                    stats.updated += 1
                except child_model.DoesNotExist:
                    dst_obj = child_model(**defaults, **{parent_field: dst_parent_obj}, slug=slug)
                    dst_obj.save(using=dst_alias)
                    stats.created += 1

        self.stdout.write(self.style.SUCCESS(
            f"  -> {name}: created {stats.created}, updated {stats.updated}, skipped {stats.skipped}"
        ))
        return stats

    def _sync_children_of_parent_slug(self, child_model, parent_field: str, parent_slug: str, src_alias: str, dst_alias: str, dry: bool):
        """
        Synchronisiert nur die Kinder eines bestimmten Parents (identifiziert über parent_slug).
        Wird im Single-Modus bei --story_template verwendet.
        """
        name = MODEL_NAME[child_model]
        self.stdout.write(self.style.NOTICE(f"    syncing {name} for parent slug={parent_slug} …"))

        src_qs = child_model.objects.using(src_alias).select_related(parent_field).filter(**{parent_field + "__slug": parent_slug})
        dst_child = child_model.objects.using(dst_alias)
        dst_parent = StoryTemplate.objects.using(dst_alias)

        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(child_model, set())) | {"id", parent_field + "_id"}

        for obj in src_qs.iterator(chunk_size=1000):
            slug = getattr(obj, "slug")
            defaults = _values_dict_from_instance(obj, exclude=exclude)

            if dry:
                exists_parent = dst_parent.filter(slug=parent_slug).exists()
                if not exists_parent:
                    self.stdout.write(self.style.WARNING(f"      · Parent missing in dst: StoryTemplate slug={parent_slug}"))
                    continue
                exists = dst_child.filter(**{parent_field + "__slug": parent_slug, "slug": slug}).exists()
                self.stdout.write(self.style.SUCCESS(
                    f"      -> would {'UPDATE' if exists else 'CREATE'} {name} slug={slug}"
                ))
                continue

            with transaction.atomic(using=dst_alias):
                dst_parent_obj = dst_parent.get(slug=parent_slug)
                try:
                    dst_obj = dst_child.get(**{parent_field: dst_parent_obj, "slug": slug})
                    for k, v in defaults.items():
                        setattr(dst_obj, k, v)
                    dst_obj.save(update_fields=list(defaults.keys()))
                    self.stdout.write(self.style.SUCCESS(f"      -> UPDATED {name} slug={slug}"))
                except child_model.DoesNotExist:
                    dst_obj = child_model(**defaults, **{parent_field: dst_parent_obj}, slug=slug)
                    dst_obj.save(using=dst_alias)
                    self.stdout.write(self.style.SUCCESS(f"      -> CREATED {name} slug={slug}"))
