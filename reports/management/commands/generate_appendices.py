from django.core.management.base import BaseCommand
from reports.models import StoryTemplate
from reports.services.story_processor import StoryProcessor
from datetime import datetime, date

class Command(BaseCommand):
    help = 'Generate tables and/or graphics for a given story template and date'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, required=True, help='StoryTemplate ID')
        parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD)')
        parser.add_argument('--tables', action='store_true', help='Generate tables')
        parser.add_argument('--graphics', action='store_true', help='Generate graphics')

    def handle(self, *args, **options):
        template_id = options['id']
        run_date = date.today()
        if options.get('date'):
            try:
                run_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD."))
                return

        try:
            template = StoryTemplate.objects.get(id=template_id)
        except StoryTemplate.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"StoryTemplate with id={template_id} does not exist."))
            return

        processor = StoryProcessor(template, run_date)
        if options['tables']:
            processor.generate_tables()
            self.stdout.write(self.style.SUCCESS("Tables generated successfully."))
        if options['graphics']:
            processor.generate_graphics()
            self.stdout.write(self.style.SUCCESS("Graphics generated successfully."))
        if not options['tables'] and not options['graphics']:
            self.stdout.write(self.style.WARNING("No action specified. Use --tables and/or --graphics."))