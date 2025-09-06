from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from reports.models import Story, StoryTemplate
from reports.services.story_processor import StoryProcessor


class Command(BaseCommand):
    help = "Regenerate titles for existing stories. Use --template-id to process all stories for a template, --id for a single story, or --all to process every story."

    def add_arguments(self, parser):
        parser.add_argument("--template-id", type=int, help="StoryTemplate id: regenerate titles for all stories of this template")
        parser.add_argument("--id", type=int, dest="story_id", help="Story id: regenerate title for this specific story")
        parser.add_argument("--all", action="store_true", help="Regenerate titles for all stories")
        parser.add_argument("--dry-run", action="store_true", help="Do not save changes, just show what would be done")

    def handle(self, *args, **options):
        template_id = options.get("template_id")
        story_id = options.get("story_id")
        all_flag = options.get("all", False)
        dry_run = options.get("dry_run", False)

        # Require exactly one selector
        selectors = [bool(template_id), bool(story_id), bool(all_flag)]
        if sum(selectors) == 0:
            raise CommandError("Provide one of --template-id, --id, or --all to select stories to process.")
        if sum(selectors) > 1:
            raise CommandError("Provide only one of --template-id, --id, or --all (not multiple).")

        if template_id:
            try:
                template = StoryTemplate.objects.get(id=template_id)
            except StoryTemplate.DoesNotExist:
                raise CommandError(f"StoryTemplate with id={template_id} does not exist.")
            qs = Story.objects.filter(template=template)
            self.stdout.write(f"Processing {qs.count()} stories for template id={template_id} ({template.title})")
        elif story_id:
            qs = Story.objects.filter(id=story_id)
            if not qs.exists():
                raise CommandError(f"Story with id={story_id} does not exist.")
            self.stdout.write(f"Processing story id={story_id}")
        else:  # all_flag
            qs = Story.objects.all()
            self.stdout.write(f"Processing all stories ({qs.count()})")

        updated = 0
        skipped = 0
        errors = 0

        for story in qs.iterator():
            try:
                if not story.content:
                    self.stdout.write(self.style.WARNING(f"Skipping story id={story.id} (empty content)"))
                    skipped += 1
                    continue

                processor = StoryProcessor(story.template, story.published_date)
                new_title = processor.generate_summary(story.content, kind="title")

                if not new_title:
                    self.stdout.write(self.style.WARNING(f"No title generated for story id={story.id}"))
                    skipped += 1
                    continue

                if new_title.strip() == (story.title or "").strip():
                    self.stdout.write(f"No change for story id={story.id} (title unchanged)")
                    skipped += 1
                    continue

                self.stdout.write(f"Updating story id={story.id}: '{story.title}' -> '{new_title}'")
                if not dry_run:
                    with transaction.atomic():
                        story.title = new_title
                        story.save(update_fields=["title"])
                    updated += 1
                else:
                    self.stdout.write(self.style.NOTICE("Dry-run: no DB changes made"))
            except Exception as exc:
                self.stderr.write(f"Error processing story id={getattr(story, 'id', 'unknown')}: {exc}")
                errors += 1

        self.stdout.write(self.style.SUCCESS(f"Done. updated={updated} skipped={skipped} errors={errors}"))