from django.core.management.base import BaseCommand
from reports.services import EmailService
from datetime import date, datetime


class Command(BaseCommand):
    help = 'Send generated stories and reports via email'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to send stories for (YYYY-MM-DD format). Defaults to yesterday.'
        )
        parser.add_argument(
            '--test',
            action='store_true',
            help='Test email connection without sending emails'
        )

    def handle(self, *args, **options):
        # Handle test mode
        if options.get('test'):
            service = EmailService()
            result = service.test_email_connection()
            
            if result['success']:
                self.stdout.write(
                    self.style.SUCCESS("Email connection test successful")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"Email connection test failed: {result['error']}")
                )
            return
        
        # Parse the date if provided
        send_date = today = date.today()
        if options.get('date'):
            try:
                send_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid date format. Use YYYY-MM-DD format."
                    )
                )
                return
        
        service = EmailService()
        result = service.send_stories_for_date(send_date=send_date)
        print(result)
        if result['success']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Email sending completed successfully. "
                    f"Sent: {result.get('total_sent', 0)}, Failed: {result.get('failed', 0)}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Email sending completed with errors. "
                    f"Sent: {result.get('total_sent', 0)}, Failed: {result.get('failed', 0)}"
                )
            )
            
        # Show details if verbose
        if options.get('verbosity', 1) > 1 and 'details' in result:
            for detail in result['details']:
                status = "✓" if detail['success'] else "✗"
                self.stdout.write(f"  {status} {detail.get('recipient', 'Unknown')}")
                if not detail['success'] and 'error' in detail:
                    self.stdout.write(f"    Error: {detail['error']}")
