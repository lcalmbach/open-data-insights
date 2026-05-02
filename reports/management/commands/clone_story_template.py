from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reports.models.story_template import StoryTemplate, StoryTemplateFocus
from reports.models.graphic_template import StoryTemplateGraphic
from reports.models.story_context import StoryTemplateContext
from reports.models.story_table_template import StoryTemplateTable


class Command(BaseCommand):
    help = (
        "Clone a StoryTemplate (by id or slug) with all related focus areas, "
        "graphic templates, context templates, and table templates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            help="ID (integer) or slug of the StoryTemplate to clone.",
        )
        parser.add_argument(
            "--title",
            help="Title for the new template. Defaults to 'Copy of <original title>'.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to the database.",
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_source(self, source_arg: str) -> StoryTemplate:
        try:
            source_id = int(source_arg)
            return StoryTemplate.objects.get(pk=source_id)
        except ValueError:
            pass
        try:
            return StoryTemplate.objects.get(slug=source_arg)
        except StoryTemplate.DoesNotExist:
            raise CommandError(f"StoryTemplate with slug '{source_arg}' not found.")

    def _clone_focus_areas(
        self,
        src: StoryTemplate,
        dst: StoryTemplate,
        dry: bool,
    ) -> int:
        count = 0
        for focus in src.focus_areas.all():
            if dry:
                self.stdout.write(
                    f"  [focus] filter_value={focus.filter_value!r} "
                    f"filter_expression={focus.filter_expression!r}"
                )
            else:
                new_focus = StoryTemplateFocus.objects.create(
                    story_template=dst,
                    default_title=focus.default_title,
                    default_lead=focus.default_lead,
                    filter_value=focus.filter_value,
                    filter_expression=focus.filter_expression,
                    publish_conditions=focus.publish_conditions,
                    focus_subject=focus.focus_subject,
                )
                # Copy M2M images via the through model
                for link in focus.focus_image_links.all():
                    new_focus.focus_image_links.create(
                        image=link.image,
                        sort_order=link.sort_order,
                    )
            count += 1
        return count

    def _clone_graphics(
        self,
        src: StoryTemplate,
        dst: StoryTemplate,
        dry: bool,
    ) -> int:
        count = 0
        for g in src.graphic_templates.all():
            if dry:
                self.stdout.write(f"  [graphic] title={g.title!r} type={g.graphic_type}")
            else:
                StoryTemplateGraphic.objects.create(
                    story_template=dst,
                    title=g.title,
                    settings=g.settings,
                    sql_command=g.sql_command,
                    graphic_type=g.graphic_type,
                    sort_order=g.sort_order,
                )
            count += 1
        return count

    def _clone_contexts(
        self,
        src: StoryTemplate,
        dst: StoryTemplate,
        dry: bool,
    ) -> int:
        count = 0
        for ctx in src.contexts.all():
            if dry:
                self.stdout.write(f"  [context] key={ctx.key!r}")
            else:
                StoryTemplateContext.objects.create(
                    story_template=dst,
                    description=ctx.description,
                    key=ctx.key,
                    sql_command=ctx.sql_command,
                    sort_order=ctx.sort_order,
                )
            count += 1
        return count

    def _clone_tables(
        self,
        src: StoryTemplate,
        dst: StoryTemplate,
        dry: bool,
    ) -> int:
        count = 0
        for tbl in src.story_template_tables.all():
            if dry:
                self.stdout.write(f"  [table] title={tbl.title!r}")
            else:
                StoryTemplateTable.objects.create(
                    story_template=dst,
                    title=tbl.title,
                    sql_command=tbl.sql_command,
                    sort_order=tbl.sort_order,
                )
            count += 1
        return count

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        src = self._get_source(options["source"])
        dry: bool = options["dry_run"]
        new_title: str = options["title"] or f"Copy of {src.title}"

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Cloning StoryTemplate id={src.id} slug={src.slug!r} → '{new_title}'"
                + (" [DRY RUN]" if dry else "")
            )
        )

        if not dry and StoryTemplate.objects.filter(title=new_title).exists():
            raise CommandError(
                f"A StoryTemplate with title '{new_title}' already exists. "
                "Use --title to specify a different title."
            )

        with transaction.atomic():
            if dry:
                dst = None
            else:
                dst = StoryTemplate(
                    title=new_title,
                    active=src.active,
                    most_recent_day_sql=src.most_recent_day_sql,
                    default_title=src.default_title,
                    default_lead=src.default_lead,
                    summary=src.summary,
                    description=src.description,
                    reference_period=src.reference_period,
                    period_direction=src.period_direction,
                    data_source=src.data_source,
                    other_ressources=src.other_ressources,
                    story_source=src.story_source,
                    prompt_text=src.prompt_text,
                    temperature=src.temperature,
                    system_prompt=src.system_prompt,
                    title_prompt=src.title_prompt,
                    lead_prompt=src.lead_prompt,
                    post_publish_command=src.post_publish_command,
                    create_title=src.create_title,
                    create_lead=src.create_lead,
                    is_published=False,
                    organisation=src.organisation,
                    region=src.region,
                    ai_model=src.ai_model,
                    generation_mode=src.generation_mode,
                )
                dst.save()
                # Copy M2M topics
                dst.topics.set(src.topics.all())

            n_focus = self._clone_focus_areas(src, dst, dry)
            n_graphics = self._clone_graphics(src, dst, dry)
            n_contexts = self._clone_contexts(src, dst, dry)
            n_tables = self._clone_tables(src, dst, dry)

            if not dry:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created StoryTemplate id={dst.id} slug={dst.slug!r} '{dst.title}'\n"
                        f"  focus areas : {n_focus}\n"
                        f"  graphics    : {n_graphics}\n"
                        f"  contexts    : {n_contexts}\n"
                        f"  tables      : {n_tables}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Dry-run complete — would create:\n"
                        f"  focus areas : {n_focus}\n"
                        f"  graphics    : {n_graphics}\n"
                        f"  contexts    : {n_contexts}\n"
                        f"  tables      : {n_tables}"
                    )
                )
