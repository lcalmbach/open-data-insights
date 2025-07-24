from django.core.management.base import BaseCommand
from reports.services import StoryGenerationService
from datetime import date, datetime


class Command(BaseCommand):
    help = 'Generate data insights and stories from templates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id', 
            type=int, 
            help='ID of the specific story template to process'
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Date to generate stories for (YYYY-MM-DD format). Defaults to yesterday.'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force generation even if conditions are not met'
        )

    def handle(self, *args, **options):
        template_id = options.get('id')
        force = options.get('force', False)
        
        # Parse the date if provided
        run_date = None
        if options.get('date'):
            try:
                run_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid date format. Use YYYY-MM-DD format."
                    )
                )
                return
        else:
            run_date = date.today() 
        service = StoryGenerationService()
        result = service.generate_stories(template_id=template_id, run_date=run_date, force=force)
        
        if result.get('success', False):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Story generation completed successfully. "
                    f"Generated: {result.get('successful', 0)}, Failed: {result.get('failed', 0)}, Skipped: {result.get('skipped', 0)}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Story generation completed with errors. "
                    f"Generated: {result.get('successful', 0)}, Failed: {result.get('failed', 0)}, Skipped: {result.get('skipped', 0)}"
                )
            )
            if 'message' in result:
                self.stdout.write(f"  Message: {result['message']}")
            if 'error' in result:
                self.stdout.write(f"  Error: {result['error']}")
        
        # Show details if verbose
        if options.get('verbosity', 1) > 1:
            for detail in result.get('details', []):
                if detail.get('skipped'):
                    status = "⊘"
                    action = "skipped"
                elif detail.get('success'):
                    status = "✓"
                    action = "generated"
                else:
                    status = "✗"
                    action = "failed"
                
                self.stdout.write(f"  {status} {detail['template_id']} ({action})")
                if not detail['success'] and 'error' in detail:
                    self.stdout.write(f"    Error: {detail['error']}")
