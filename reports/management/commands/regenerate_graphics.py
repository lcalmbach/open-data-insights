from django.core.management.base import BaseCommand, CommandError
from reports.models.graphic import Graphic
from reports.services.story_processor import StoryProcessor

NON_PLOT_TYPES = {"chloropleth", "map_markers", "wordcloud"}


class Command(BaseCommand):
    help = "Regenerate stored graphic HTML for ECharts chart types."

    def add_arguments(self, parser):
        parser.add_argument(
            "--chart_type",
            type=str,
            help=(
                "Comma-separated chart type(s) to regenerate, e.g. 'line' or 'bar,pie' or 'simulation'. "
                "Omit to regenerate all plot types (maps and word clouds are always skipped)."
            ),
        )
        parser.add_argument(
            "--story_id",
            type=int,
            help="Limit regeneration to a single story.",
        )
        parser.add_argument(
            "--story_template_id",
            type=int,
            help="Limit regeneration to all stories of a story template.",
        )
        parser.add_argument(
            "--dry_run",
            action="store_true",
            help="Print what would be regenerated without saving.",
        )

    def handle(self, *args, **options):
        chart_type_arg = options.get("chart_type")
        story_id = options.get("story_id")
        story_template_id = options.get("story_template_id")
        dry_run = options.get("dry_run", False)

        requested_types = None
        if chart_type_arg:
            requested_types = {t.strip().lower() for t in chart_type_arg.split(",")}
            bad = requested_types & NON_PLOT_TYPES
            if bad:
                raise CommandError(
                    f"Chart type(s) {bad} are maps/wordcloud and cannot be regenerated here."
                )

        qs = Graphic.objects.select_related(
            "graphic_template__graphic_type", "story"
        )

        if story_id:
            qs = qs.filter(story_id=story_id)
        elif story_template_id:
            qs = qs.filter(story__templatefocus__story_template_id=story_template_id)

        # Always exclude maps and word clouds
        qs = qs.exclude(graphic_template__graphic_type__value__in=NON_PLOT_TYPES)

        if requested_types:
            qs = qs.filter(graphic_template__graphic_type__value__in=requested_types)

        graphics = list(qs)
        total = len(graphics)

        if total == 0:
            self.stdout.write(self.style.WARNING("No matching graphics found."))
            return

        type_filter_msg = f" (type filter: {', '.join(sorted(requested_types))})" if requested_types else ""
        self.stdout.write(f"Found {total} graphic(s) to regenerate{type_filter_msg}.")

        if dry_run:
            for g in graphics:
                self.stdout.write(
                    f"  [dry-run] graphic id={g.id} "
                    f"type={g.graphic_template.graphic_type.value} "
                    f"story_id={g.story_id}"
                )
            return

        processed = 0
        failed = []
        for g in graphics:
            gtype = g.graphic_template.graphic_type.value
            processor = StoryProcessor(
                published_date=g.story.published_date, template=None, force_generation=False, story=g.story
            )
            ok = processor.generate_graphic(g)
            if ok:
                processed += 1
                self.stdout.write(f"  OK  graphic id={g.id} type={gtype} story_id={g.story_id}")
            else:
                failed.append(g)
                self.stdout.write(
                    self.style.ERROR(f"  ERR graphic id={g.id} type={gtype} story_id={g.story_id}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. processed={processed}/{total} errors={len(failed)}")
        )
        if failed:
            self.stdout.write(self.style.ERROR("\nFailed graphics:"))
            for g in failed:
                self.stdout.write(
                    self.style.ERROR(
                        f"  id={g.id}  type={g.graphic_template.graphic_type.value}"
                        f"  title={g.graphic_template.title!r}"
                        f"  story_id={g.story_id}"
                    )
                )
