from __future__ import annotations

from typing import Iterable, Dict, Any, Optional
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction, models
from django.apps import apps
from django.conf import settings


# ---- Modelle dynamisch auflösen (vermeidet Import-Loops) ----
Dataset = apps.get_model("reports", "Dataset")
StoryTemplate = apps.get_model("reports", "StoryTemplate")
StoryTemplateGraphic = apps.get_model("reports", "StoryTemplateGraphic")
StoryTemplateTable = apps.get_model("reports", "StoryTemplateTable")
StoryTemplateContext = apps.get_model("reports", "StoryTemplateContext")

# Resolve the project's custom user model from settings.AUTH_USER_MODEL
user_app_label, user_model_name = settings.AUTH_USER_MODEL.rsplit(".", 1)
CustomUser = apps.get_model(user_app_label, user_model_name)

PARENT_MODELS = [Dataset, StoryTemplate, CustomUser]
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
    CustomUser: "CustomUser",
}

EXCLUDE_FIELDS_BY_MODEL = {
    Dataset: {"id", "slug"},
    StoryTemplate: {"id", "slug"},
    StoryTemplateGraphic: {"id", "slug"},
    StoryTemplateTable: {"id", "slug"},
    StoryTemplateContext: {"id", "slug"},
    CustomUser: {"id"},  # adjust if you want to exclude more user fields (e.g. password)
}

# Auto-register any model that has a ForeignKey to the CustomUser model.
# This will pick up Subscription (or any other user-owned model) regardless of its name.
for m in apps.get_models():
    # skip parent models already known
    if m in (Dataset, StoryTemplate, StoryTemplateGraphic, StoryTemplateTable, StoryTemplateContext, CustomUser):
        continue
    for f in m._meta.get_fields():
        if isinstance(f, models.ForeignKey) and getattr(f.remote_field, "model", None) == CustomUser:
            # avoid duplicates if already present
            if not any(spec[0] is m for spec in CHILD_SPECS):
                CHILD_SPECS.append((m, f.name, CustomUser))
                MODEL_NAME[m] = m.__name__
                EXCLUDE_FIELDS_BY_MODEL.setdefault(m, {"id"})
            break

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
        mt.add_argument("--user", action="store_true", help=f"Interpret --id as {user_model_name}.id")

        # Backwards compatibility: Full-batch run (ohne --id)
        parser.add_argument(
            "--only",
            nargs="*",
            choices=[MODEL_NAME[m] for m in [Dataset, StoryTemplate, StoryTemplateGraphic, StoryTemplateTable, StoryTemplateContext, CustomUser]],
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

        flags = [k for k in ("dataset", "story_template", "table_template", "graphic_template", "context", "user") if opts.get(k)]
        if len(flags) != 1:
            raise CommandError("Provide exactly one of --dataset / --story_template / --table_template / --graphic_template / --context / --user together with --id.")

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
        elif flag == "user":
            # Sync the CustomUser as a parent-like model
            parent = self._sync_one_parent_by_id(CustomUser, entity_id, src_alias, dst_alias, dry)
            if parent is None:
                return
            # If we detected a Subscription model, sync that user's subscriptions
            if Subscription:
                # use parent.pk to sync only that user's child rows
                self._sync_children_of_parent_pk(Subscription, Subscription_parent_field or "user", parent.pk, src_alias, dst_alias, dry)

    def _sync_one_parent_by_id(self, model, pk: int, src_alias: str, dst_alias: str, dry: bool):
        name = MODEL_NAME[model]
        self.stdout.write(self.style.MIGRATE_HEADING(f"[{name}] sync single parent id={pk} …"))

        try:
            obj = model.objects.using(src_alias).get(pk=pk)
        except model.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"  - Source {name} id={pk} not found."))
            return None

        # use an appropriate lookup (slug / username / email / pk)
        lookup_field, lookup_value = _parent_lookup_field_and_value(obj)
        if lookup_field == "pk":
            # pk is not stable across DBs — warn and skip
            self.stdout.write(self.style.WARNING(f"  - Skipped {name} id={pk} (no stable lookup field like slug/username/email)."))
            return None

        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(model, set())) | {"id"}
        data = _values_dict_from_instance(obj, exclude=exclude)
        dst_mgr = model.objects.using(dst_alias)

        if dry:
            exists = dst_mgr.filter(**{lookup_field: lookup_value}).exists()
            if exists:
                self.stdout.write(self.style.SUCCESS(f"  -> would UPDATE {name} {lookup_field}={lookup_value}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"  -> would CREATE {name} {lookup_field}={lookup_value}"))
            return obj  # für story_template-children / user-children

        with transaction.atomic(using=dst_alias):
            dst_obj, created = dst_mgr.update_or_create(**{lookup_field: lookup_value}, defaults=data)
            self.stdout.write(self.style.SUCCESS(
                f"  -> {'CREATED' if created else 'UPDATED'} {name} {lookup_field}={lookup_value}"
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
            lookup_field, lookup_value = _parent_lookup_field_and_value(obj)
            if lookup_field == "pk":
                stats.skipped += 1
                continue

            data = _values_dict_from_instance(obj, exclude=exclude)

            if dry:
                if dst_mgr.filter(**{lookup_field: lookup_value}).exists():
                    stats.updated += 1
                else:
                    stats.created += 1
                continue

            with transaction.atomic(using=dst_alias):
                dst_obj, created = dst_mgr.update_or_create(**{lookup_field: lookup_value}, defaults=data)
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
            if not parent_obj:
                stats.skipped += 1
                continue

            lookup_field, lookup_value = _parent_lookup_field_and_value(parent_obj)
            if lookup_field == "pk":
                stats.skipped += 1
                continue

            if dry:
                if not dst_parent.filter(**{lookup_field: lookup_value}).exists():
                    stats.skipped += 1
                    continue
                if slug:
                    exists = dst_child.filter(**{f"{parent_field}__{lookup_field}": lookup_value, "slug": slug}).exists()
                else:
                    exists = dst_child.filter(**{f"{parent_field}__{lookup_field}": lookup_value}).exists()
                if exists: stats.updated += 1
                else: stats.created += 1
                continue

            with transaction.atomic(using=dst_alias):
                try:
                    dst_parent_obj = dst_parent.get(**{lookup_field: lookup_value})
                except parent_model.DoesNotExist:
                    # Parent missing → try to upsert parent from source
                    self._sync_one_parent_by_id(parent_obj.__class__, parent_obj.pk, src_alias, dst_alias, dry=False)
                    dst_parent_obj = dst_parent.get(**{lookup_field: lookup_value})

                defaults = _values_dict_from_instance(obj, exclude=exclude)

                try:
                    if slug:
                        dst_obj = dst_child.get(**{parent_field: dst_parent_obj, "slug": slug})
                    else:
                        # try a UNIQUE_FIELDS lookup if available, else create new
                        if hasattr(child_model, "UNIQUE_FIELDS"):
                            lookup = {k: getattr(obj, k) for k in child_model.UNIQUE_FIELDS}
                            dst_obj = dst_child.get(**{parent_field: dst_parent_obj}, **lookup)
                        else:
                            raise child_model.DoesNotExist
                    for k, v in defaults.items():
                        setattr(dst_obj, k, v)
                    dst_obj.save(update_fields=list(defaults.keys()))
                    stats.updated += 1
                except child_model.DoesNotExist:
                    # create
                    kwargs = {parent_field: dst_parent_obj}
                    if slug:
                        kwargs["slug"] = slug
                    dst_obj = child_model(**defaults, **kwargs)
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
                    f"      -> {'UPDATE' if exists else 'CREATE'} {name} slug={slug}"
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

    def _sync_children_of_parent_pk(self, child_model, parent_field: str, parent_pk: int, src_alias: str, dst_alias: str, dry: bool):
        """
        Synchronize only the children of a specific parent identified by parent PK.
        Used when syncing a single parent (e.g. CustomUser -> Subscription).
        """
        name = MODEL_NAME.get(child_model, child_model.__name__)
        self.stdout.write(self.style.NOTICE(f"    syncing {name} for parent pk={parent_pk} …"))

        src_qs = child_model.objects.using(src_alias).select_related(parent_field).filter(**{parent_field + "__pk": parent_pk})
        dst_child = child_model.objects.using(dst_alias)
        dst_parent_mgr = child_model._meta.get_field(parent_field).remote_field.model.objects.using(dst_alias)

        exclude = set(EXCLUDE_FIELDS_BY_MODEL.get(child_model, set())) | {"id", parent_field + "_id"}

        for obj in src_qs.iterator(chunk_size=1000):
            slug = getattr(obj, "slug", None)
            parent_obj = getattr(obj, parent_field, None)
            defaults = _values_dict_from_instance(obj, exclude=exclude)

            # determine a stable lookup for the parent (slug/username/email)
            if not parent_obj:
                self.stdout.write(self.style.WARNING(f"      · Source child without parent, skipping"))
                continue
            lookup_field, lookup_value = _parent_lookup_field_and_value(parent_obj)
            if lookup_field == "pk":
                # cannot reliably map parent across DBs
                self.stdout.write(self.style.WARNING(f"      · Skipping children for parent pk={parent_pk}: no stable lookup on parent"))
                continue

            if dry:
                # If parent doesn't exist in dst, report warning
                if not dst_parent_mgr.filter(**{lookup_field: lookup_value}).exists():
                    self.stdout.write(self.style.WARNING(f"      · Parent missing in dst: {lookup_field}={lookup_value}"))
                    continue
                # determine existence by parent lookup + slug if slug exists, else by UNIQUE_FIELDS fallback or presence
                if slug:
                    exists = dst_child.filter(**{f"{parent_field}__{lookup_field}": lookup_value, "slug": slug}).exists()
                else:
                    if hasattr(child_model, "UNIQUE_FIELDS"):
                        uniq_lookup = {k: getattr(obj, k) for k in child_model.UNIQUE_FIELDS}
                        exists = dst_child.filter(**{f"{parent_field}__{lookup_field}": lookup_value}, **uniq_lookup).exists()
                    else:
                        exists = dst_child.filter(**{f"{parent_field}__{lookup_field}": lookup_value}).exists()
                self.stdout.write(self.style.SUCCESS(
                    f"      -> would {'UPDATE' if exists else 'CREATE'} {name} (parent {lookup_field}={lookup_value})"
                ))
                continue

            with transaction.atomic(using=dst_alias):
                # Ensure parent exists in dst (by stable lookup)
                try:
                    dst_parent_obj = dst_parent_mgr.get(**{lookup_field: lookup_value})
                except dst_parent_mgr.model.DoesNotExist:
                    # Parent missing → try upserting parent from source (using source parent PK)
                    self._sync_one_parent_by_id(parent_obj.__class__, parent_obj.pk, src_alias, dst_alias, dry=False)
                    dst_parent_obj = dst_parent_mgr.get(**{lookup_field: lookup_value})

                # try to find dst child by parent relation and slug if available, else by other unique fields if defined
                try:
                    if slug:
                        dst_obj = dst_child.get(**{parent_field: dst_parent_obj, "slug": slug})
                    else:
                        # attempt a best-effort lookup: if child model defines UNIQUE_FIELDS tuple, use it
                        if hasattr(child_model, "UNIQUE_FIELDS"):
                            lookup = {k: getattr(obj, k) for k in child_model.UNIQUE_FIELDS}
                            dst_obj = dst_child.get(**{parent_field: dst_parent_obj}, **lookup)
                        else:
                            # fallback: create new if we cannot uniquely identify
                            raise child_model.DoesNotExist
                    for k, v in defaults.items():
                        setattr(dst_obj, k, v)
                    dst_obj.save(update_fields=list(defaults.keys()))
                    self.stdout.write(self.style.SUCCESS(f"      -> UPDATED {name} parent {lookup_field}={lookup_value}"))
                except child_model.DoesNotExist:
                    dst_obj = child_model(**defaults, **{parent_field: dst_parent_obj})
                    dst_obj.save(using=dst_alias)
                    self.stdout.write(self.style.SUCCESS(f"      -> CREATED {name} parent {lookup_field}={lookup_value}"))

def _parent_lookup_field_and_value(obj: models.Model):
    """
    Return a stable lookup (field_name, value) for parent objects.

    Preference order:
      - slug
      - username
      - email
      - fallback to pk (caller may treat pk as unstable)
    """
    if getattr(obj, "slug", None):
        return "slug", getattr(obj, "slug")
    if getattr(obj, "username", None):
        return "username", getattr(obj, "username")
    if getattr(obj, "email", None):
        return "email", getattr(obj, "email")
    return "pk", getattr(obj, "pk")
