from __future__ import annotations

import mimetypes
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.models import Q

from reports.models.story_template import (
    StoryImage,
    StoryTemplate,
    StoryTemplateFocus,
    StoryTemplateFocusImage,
)


def _trimmed_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_s3_key(image_name: str, media_location: str) -> str:
    image_name = image_name.lstrip("/")
    media_location = (media_location or "").strip().strip("/")
    if not media_location:
        return image_name
    if image_name.startswith(f"{media_location}/"):
        return image_name
    return f"{media_location}/{image_name}"


def _story_image_lookup_kwargs(image: StoryImage | object) -> dict[str, str]:
    identifier_key = _trimmed_or_none(getattr(image, "image_identifier_key", None))
    if identifier_key:
        return {"image_identifier_key": identifier_key}

    image_source_url = _trimmed_or_none(getattr(image, "image_source_url", None))
    if image_source_url:
        return {"image_source_url": image_source_url}

    remote_url = _trimmed_or_none(getattr(image, "remote_url", None))
    if remote_url:
        return {"remote_url": remote_url}

    image_field = getattr(image, "image", None)
    image_name = _trimmed_or_none(getattr(image_field, "name", None))
    if image_name:
        return {"image": image_name}

    title = _trimmed_or_none(getattr(image, "title", None))
    author = _trimmed_or_none(getattr(image, "author", None))
    image_source = _trimmed_or_none(getattr(image, "image_source", None))
    if title and (author or image_source):
        lookup = {"title": title}
        if author:
            lookup["author"] = author
        if image_source:
            lookup["image_source"] = image_source
        return lookup

    raise CommandError(
        f"StoryImage has no stable lookup key. Set image_identifier_key, image_source_url, "
        f"remote_url, or ensure the uploaded file has a name."
    )


class Command(BaseCommand):
    help = (
        "Upload local StoryImage files to S3 and sync the corresponding StoryImage "
        "records plus focus-image links to a remote database."
    )

    def add_arguments(self, parser):
        selectors = parser.add_mutually_exclusive_group(required=True)
        selectors.add_argument(
            "--id",
            dest="ids",
            type=int,
            action="append",
            help="StoryImage.id to publish. Repeatable.",
        )
        selectors.add_argument(
            "--focus-id",
            dest="focus_ids",
            type=int,
            action="append",
            help="Publish all images linked to the given StoryTemplateFocus.id. Repeatable.",
        )
        selectors.add_argument(
            "--story-template-id",
            dest="story_template_ids",
            type=int,
            action="append",
            help="Publish all images linked to the given StoryTemplate.id. Repeatable.",
        )
        selectors.add_argument(
            "--all",
            action="store_true",
            help="Publish all StoryImage records.",
        )
        parser.add_argument(
            "--database",
            default="prod",
            help="Remote database alias defined in settings.DATABASES (default: prod).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be uploaded/synced without writing anything.",
        )
        parser.add_argument(
            "--upload-only",
            action="store_true",
            help="Only upload files to S3, skip remote database writes.",
        )
        parser.add_argument(
            "--db-only",
            action="store_true",
            help="Only sync remote database records, skip S3 uploads.",
        )
        parser.add_argument(
            "--skip-links",
            action="store_true",
            help="Sync StoryImage rows only, without StoryTemplateFocusImage links.",
        )

    def handle(self, *args, **options):
        if options["upload_only"] and options["db_only"]:
            raise CommandError("--upload-only and --db-only cannot be used together.")

        remote_alias = options["database"]
        if not options["upload_only"] and remote_alias not in connections.databases:
            raise CommandError(
                f"Database alias '{remote_alias}' not found. Set SYNC_DATABASE_URL or choose another alias."
            )

        images = list(self._select_images(options))
        if not images:
            self.stdout.write(self.style.WARNING("No StoryImage records matched the selection."))
            return

        s3_client = None
        bucket_name = None
        media_location = None
        if not options["db_only"]:
            bucket_name, media_location = self._load_s3_config()
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                region_name=os.environ.get("AWS_S3_REGION_NAME"),
                aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            )

        remote_focus_cache: dict[int, StoryTemplateFocus] = {}
        stats = {"uploaded": 0, "images_created": 0, "images_updated": 0, "links_created": 0, "links_updated": 0}

        for local_image in images:
            if not options["db_only"]:
                uploaded = self._upload_image_file(
                    local_image=local_image,
                    s3_client=s3_client,
                    bucket_name=bucket_name,
                    media_location=media_location,
                    dry_run=options["dry_run"],
                )
                if uploaded:
                    stats["uploaded"] += 1

            if options["upload_only"]:
                continue

            remote_image, image_created = self._upsert_remote_story_image(
                local_image=local_image,
                remote_alias=remote_alias,
                dry_run=options["dry_run"],
            )
            stats["images_created" if image_created else "images_updated"] += 1

            if options["skip_links"]:
                continue

            for link in local_image.focus_links.select_related("focus__story_template").all():
                remote_focus = self._ensure_remote_focus(
                    local_focus=link.focus,
                    remote_alias=remote_alias,
                    dry_run=options["dry_run"],
                    cache=remote_focus_cache,
                )
                link_created = self._upsert_remote_focus_link(
                    local_link=link,
                    remote_focus=remote_focus,
                    remote_image=remote_image,
                    remote_alias=remote_alias,
                    dry_run=options["dry_run"],
                )
                stats["links_created" if link_created else "links_updated"] += 1

        summary = (
            f"Processed {len(images)} image(s). "
            f"Uploads: {stats['uploaded']}. "
            f"StoryImage created/updated: {stats['images_created']}/{stats['images_updated']}. "
            f"Focus links created/updated: {stats['links_created']}/{stats['links_updated']}."
        )
        self.stdout.write(self.style.SUCCESS(summary))

    def _select_images(self, options):
        qs = StoryImage.objects.order_by("id").prefetch_related("focus_links__focus__story_template")
        if options.get("ids"):
            return qs.filter(id__in=options["ids"]).distinct()
        if options.get("focus_ids"):
            return qs.filter(focus_links__focus_id__in=options["focus_ids"]).distinct()
        if options.get("story_template_ids"):
            return qs.filter(
                focus_links__focus__story_template_id__in=options["story_template_ids"]
            ).distinct()
        if options.get("all"):
            return qs
        return qs.none()

    def _load_s3_config(self) -> tuple[str, str]:
        bucket_name = _trimmed_or_none(os.environ.get("AWS_STORAGE_BUCKET_NAME"))
        if not bucket_name:
            raise CommandError("AWS_STORAGE_BUCKET_NAME is required for S3 uploads.")
        media_location = _trimmed_or_none(os.environ.get("AWS_MEDIA_LOCATION")) or "media"
        return bucket_name, media_location

    def _upload_image_file(
        self,
        *,
        local_image: StoryImage,
        s3_client,
        bucket_name: str,
        media_location: str,
        dry_run: bool,
    ) -> bool:
        image_name = _trimmed_or_none(getattr(local_image.image, "name", None))
        if not image_name:
            self.stdout.write(f"StoryImage {local_image.id}: no uploaded file, skipping S3 upload.")
            return False

        s3_key = _build_s3_key(image_name, media_location)
        if dry_run:
            self.stdout.write(
                f"StoryImage {local_image.id}: would upload '{image_name}' to s3://{bucket_name}/{s3_key}"
            )
            return True

        try:
            local_image.image.open("rb")
            content_type = mimetypes.guess_type(image_name)[0] or "application/octet-stream"
            s3_client.upload_fileobj(
                local_image.image.file,
                bucket_name,
                s3_key,
                ExtraArgs={"ContentType": content_type},
            )
        except FileNotFoundError as exc:
            raise CommandError(
                f"Local file for StoryImage {local_image.id} was not found: {image_name}"
            ) from exc
        except (BotoCoreError, ClientError, OSError) as exc:
            raise CommandError(
                f"Uploading StoryImage {local_image.id} to S3 failed: {exc}"
            ) from exc
        finally:
            try:
                local_image.image.close()
            except Exception:
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"StoryImage {local_image.id}: uploaded '{image_name}' to s3://{bucket_name}/{s3_key}"
            )
        )
        return True

    def _upsert_remote_story_image(
        self,
        *,
        local_image: StoryImage,
        remote_alias: str,
        dry_run: bool,
    ) -> tuple[StoryImage, bool]:
        lookup = _story_image_lookup_kwargs(local_image)
        defaults = {
            "image": _trimmed_or_none(getattr(local_image.image, "name", None)),
            "remote_url": _trimmed_or_none(local_image.remote_url),
            "title": _trimmed_or_none(local_image.title),
            "author": _trimmed_or_none(local_image.author),
            "author_url": _trimmed_or_none(local_image.author_url),
            "license": _trimmed_or_none(local_image.license),
            "license_url": _trimmed_or_none(local_image.license_url),
            "image_source": _trimmed_or_none(local_image.image_source),
            "image_source_url": _trimmed_or_none(local_image.image_source_url),
            "image_changes": _trimmed_or_none(local_image.image_changes),
            "image_identifier_key": _trimmed_or_none(local_image.image_identifier_key),
        }
        manager = StoryImage.objects.using(remote_alias)
        exists = manager.filter(**lookup).exists()
        action = "would create" if not exists else "would update"
        if dry_run:
            self.stdout.write(
                f"StoryImage {local_image.id}: {action} remote StoryImage using lookup {lookup}"
            )
            return local_image, not exists

        with transaction.atomic(using=remote_alias):
            remote_image, created = manager.update_or_create(defaults=defaults, **lookup)
        self.stdout.write(
            self.style.SUCCESS(
                f"StoryImage {local_image.id}: {'created' if created else 'updated'} remote StoryImage"
            )
        )
        return remote_image, created

    def _ensure_remote_focus(
        self,
        *,
        local_focus: StoryTemplateFocus,
        remote_alias: str,
        dry_run: bool,
        cache: dict[int, StoryTemplateFocus],
    ) -> StoryTemplateFocus:
        cached = cache.get(local_focus.id)
        if cached is not None:
            return cached

        template_slug = _trimmed_or_none(local_focus.story_template.slug)
        if not template_slug:
            raise CommandError(
                f"StoryTemplate {local_focus.story_template_id} has no slug. Sync the template first."
            )
        remote_template = StoryTemplate.objects.using(remote_alias).filter(slug=template_slug).first()
        if remote_template is None:
            raise CommandError(
                f"Remote StoryTemplate with slug '{template_slug}' not found. Sync the template first."
            )

        filter_value = _trimmed_or_none(local_focus.filter_value)
        defaults = {
            "story_template_id": remote_template.id,
            "publish_conditions": _trimmed_or_none(local_focus.publish_conditions),
            "filter_expression": _trimmed_or_none(local_focus.filter_expression),
            "filter_value": filter_value,
            "focus_subject": _trimmed_or_none(local_focus.focus_subject),
        }

        manager = StoryTemplateFocus.objects.using(remote_alias)
        if filter_value is None:
            existing = manager.filter(story_template_id=remote_template.id).filter(
                Q(filter_value__isnull=True) | Q(filter_value="")
            ).first()
            if dry_run:
                self.stdout.write(
                    f"StoryTemplateFocus {local_focus.id}: "
                    f"{'would create' if existing is None else 'would update'} default remote focus "
                    f"for template slug '{template_slug}'"
                )
                cache[local_focus.id] = existing or local_focus
                return cache[local_focus.id]

            if existing is None:
                remote_focus = manager.create(**defaults)
            else:
                for field_name, value in defaults.items():
                    setattr(existing, field_name, value)
                existing.save(
                    update_fields=[
                        "story_template",
                        "publish_conditions",
                        "filter_expression",
                        "filter_value",
                        "focus_subject",
                    ]
                )
                remote_focus = existing
        else:
            if dry_run:
                exists = manager.filter(
                    story_template_id=remote_template.id,
                    filter_value=filter_value,
                ).exists()
                self.stdout.write(
                    f"StoryTemplateFocus {local_focus.id}: "
                    f"{'would create' if not exists else 'would update'} remote focus "
                    f"for template slug '{template_slug}' and filter_value '{filter_value}'"
                )
                cache[local_focus.id] = (
                    manager.filter(
                        story_template_id=remote_template.id,
                        filter_value=filter_value,
                    ).first()
                    or local_focus
                )
                return cache[local_focus.id]

            remote_focus, _ = manager.update_or_create(
                story_template_id=remote_template.id,
                filter_value=filter_value,
                defaults=defaults,
            )

        cache[local_focus.id] = remote_focus
        return remote_focus

    def _upsert_remote_focus_link(
        self,
        *,
        local_link: StoryTemplateFocusImage,
        remote_focus: StoryTemplateFocus,
        remote_image: StoryImage,
        remote_alias: str,
        dry_run: bool,
    ) -> bool:
        if dry_run:
            manager = StoryTemplateFocusImage.objects.using(remote_alias)
            remote_focus_id = getattr(remote_focus, "id", None)
            remote_image_id = getattr(remote_image, "id", None)
            exists = bool(
                remote_focus_id
                and remote_image_id
                and manager.filter(
                    focus_id=remote_focus_id,
                    image_id=remote_image_id,
                ).exists()
            )
            self.stdout.write(
                f"Focus/image link {local_link.id}: "
                f"{'would create' if not exists else 'would update'} remote link"
            )
            return not exists

        _, created = StoryTemplateFocusImage.objects.using(remote_alias).update_or_create(
            focus_id=remote_focus.id,
            image_id=remote_image.id,
            defaults={"sort_order": local_link.sort_order},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Focus/image link {local_link.id}: {'created' if created else 'updated'} remote link"
            )
        )
        return created
