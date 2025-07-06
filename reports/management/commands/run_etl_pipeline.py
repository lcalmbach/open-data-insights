from django.core.management.base import BaseCommand
from reports.services import DatasetSyncService, StoryGenerationService, EmailService
from datetime import date, datetime


class Command(BaseCommand):
    help = 'Run the complete ETL pipeline: sync datasets, generate stories, and send emails'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to process (YYYY-MM-DD format). Defaults to yesterday.'
        )
        parser.add_argument(
            '--skip-sync',
            action='store_true',
            help='Skip dataset synchronization step'
        )
        parser.add_argument(
            '--skip-generation',
            action='store_true',
            help='Skip story generation step'
        )
        parser.add_argument(
            '--skip-email',
            action='store_true',
            help='Skip email sending step'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force story generation even if conditions are not met'
        )

    def handle(self, *args, **options):
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
        
        force = options.get('force', False)
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting ETL pipeline for date: {run_date or 'yesterday'}"
            )
        )
        
        # Step 1: Sync datasets
        if not options.get('skip_sync'):
            self.stdout.write("Step 1: Synchronizing datasets...")
            sync_service = DatasetSyncService()
            sync_result = sync_service.synchronize_datasets()
            
            if sync_result['success']:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Dataset sync completed. "
                        f"Success: {sync_result['successful']}, Failed: {sync_result['failed']}"
                    )
                )
            else:
                failed_datasets = [detail['dataset_id'] for detail in sync_result['details'] if not detail['success']]
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Dataset sync failed. "
                        f"Success: {sync_result['successful']}, Failed: {sync_result['failed']}, "
                        f"Failed dataset IDs: {failed_datasets}"
                    )
                )
                if not force:
                    self.stdout.write("Stopping pipeline due to sync failures. Use --force to continue.")
                    return
        else:
            self.stdout.write("Skipping dataset synchronization...")
        
        # Step 2: Generate stories
        if not options.get('skip_generation'):
            self.stdout.write("Step 2: Generating stories...")
            story_service = StoryGenerationService()
            story_result = story_service.generate_stories(run_date=run_date, force=force)
            
            if story_result['success']:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Story generation completed. "
                        f"Generated: {story_result['successful']}, Failed: {story_result['failed']}, Skipped: {story_result['skipped']}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Story generation failed. "
                        f"Generated: {story_result['successful']}, Failed: {story_result['failed']}, Skipped: {story_result['skipped']}"
                    )
                )
                if not force:
                    self.stdout.write("Stopping pipeline due to story generation failures. Use --force to continue.")
                    return
        else:
            self.stdout.write("Skipping story generation...")
        
        # Step 3: Send emails
        if not options.get('skip_email'):
            self.stdout.write("Step 3: Sending emails...")
            email_service = EmailService()
            email_result = email_service.send_stories_for_date(send_date=run_date)
            
            if email_result['success']:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Email sending completed. "
                        f"Sent: {email_result.get('successful', 0)}, Failed: {email_result.get('failed', 0)}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Email sending failed. "
                        f"Sent: {email_result.get('successful', 0)}, Failed: {email_result.get('failed', 0)}"
                    )
                )
        else:
            self.stdout.write("Skipping email sending...")
        
        self.stdout.write(
            self.style.SUCCESS("ETL pipeline completed!")
        )
