from django.core.management.base import BaseCommand, CommandError
from reports.models import StoryTemplate, Story
from reports.services.story_processor import StoryProcessor
from datetime import datetime, date

class Command(BaseCommand):
    help = 'Generate tables and/or graphics for a given story template and date'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, help='StoryTemplate ID')
        parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD)')
        parser.add_argument('--tables', action='store_true', help='Generate tables')
        parser.add_argument('--graphics', action='store_true', help='Generate graphics')
        parser.add_argument('--all', action='store_true', help='Process all story templates')

    def handle(self, *args, **options):
        template_id = options.get('id')
        all_flag = options.get('all', False)
        run_date = date.today()
        if options.get('date'):
            try:
                run_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD."))
                return

        # validation: require either --id or --all
        if not all_flag and not template_id:
            raise CommandError("Provide --id or --all to select templates to process.")
        if all_flag and template_id:
            raise CommandError("Provide only one of --id or --all (not both).")

        if not options.get('tables') and not options.get('graphics'):
            self.stdout.write(self.style.WARNING("No action specified. Use --tables and/or --graphics."))
            return

        templates_qs = None
        if all_flag:
            templates_qs = StoryTemplate.objects.all()
            self.stdout.write(f"Processing all {templates_qs.count()} story templates for date {run_date}")
        else:
            try:
                tpl = StoryTemplate.objects.get(id=template_id)
            except StoryTemplate.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"StoryTemplate with id={template_id} does not exist."))
                return
            templates_qs = StoryTemplate.objects.filter(id=template_id)
            self.stdout.write(f"Processing StoryTemplate id={template_id} ({tpl.title}) for date {run_date}")

        total = templates_qs.count()
        processed = 0
        errors = 0

        for template in templates_qs.iterator():
            try:
                processor = StoryProcessor(template, run_date)
                if options.get('tables'):
                    self.stdout.write(f"Generating tables for template id={template.id} ({template.title})...")
                    processor.generate_tables()
                    self.stdout.write(self.style.SUCCESS(f"Tables generated for template id={template.id}"))
                if options.get('graphics'):
                    self.stdout.write(f"Generating graphics for template id={template.id} ({template.title})...")
                    processor.generate_graphics()
                    self.stdout.write(self.style.SUCCESS(f"Graphics generated for template id={template.id}"))
                processed += 1
            except Exception as exc:
                self.stderr.write(f"Error processing template id={getattr(template, 'id', 'unknown')}: {exc}")
                errors += 1

        self.stdout.write(self.style.SUCCESS(f"Done. processed={processed}/{total} errors={errors}"))