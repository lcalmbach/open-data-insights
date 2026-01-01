from django.core.management.base import BaseCommand
from reports.services import DatasetSyncService, StoryGenerationService, EmailService, StorySubscriptionService
from reports.models.story_template import StoryTemplate, StoryTemplateDataset
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
        parser.add_argument(
            '--stop-on-error',
            action='store_true',
            help='Stop pipeline execution if previous steps fail (default continues automatically)'
        )

    def handle(self, *args, **options):
        # Parse the date if provided
        anchor_date = None
        if options.get('date'):
            try:
                anchor_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid date format. Use YYYY-MM-DD format."
                    )
                )
                return
        else:
            anchor_date = date.today() 
            
        force = options.get('force', False)
        stop_on_error = options.get('stop_on_error', False)
        continue_on_error = not stop_on_error
        email_service = EmailService()
        anchor_date_label = anchor_date.strftime("%Y-%m-%d") if anchor_date else "unknown date"
        failed_dataset_ids = []
        failed_dataset_names = []
        blocked_template_ids = set()
        blocked_template_titles = []
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting ETL pipeline for date: {anchor_date or 'yesterday'}"
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
                failure_message = (
                    f"✗ Dataset sync failed. "
                    f"Success: {sync_result['successful']}, Failed: {sync_result['failed']}, "
                    f"Failed dataset IDs: {failed_datasets}"
                )
                failed_dataset_entries = [
                    detail for detail in sync_result['details'] if not detail['success']
                ]
                failed_dataset_ids = [
                    detail.get('dataset_id') for detail in failed_dataset_entries if detail.get('dataset_id') is not None
                ]
                failed_dataset_names = [
                    f"{detail.get('dataset_name') or 'Unknown dataset'} (ID {detail.get('dataset_id')})"
                    for detail in failed_dataset_entries
                ]
                if failed_dataset_names:
                    failure_message += " Failed datasets: " + "; ".join(failed_dataset_names)
                self.stdout.write(self.style.ERROR(failure_message))
                email_service.send_admin_alert(
                    subject=f"ETL pipeline failure: Dataset sync ({anchor_date_label})",
                    body=failure_message,
                )
                if not force and not continue_on_error:
                    self.stdout.write("Stopping pipeline because --stop-on-error was set. Remove that flag or add --force to continue.")
                    return
        else:
            self.stdout.write("Skipping dataset synchronization...")

        if failed_dataset_ids:
            blocked_template_ids = set(
                StoryTemplateDataset.objects.filter(dataset_id__in=failed_dataset_ids)
                .values_list("story_template_id", flat=True)
            )
            if blocked_template_ids:
                blocked_template_titles = list(
                    StoryTemplate.objects.filter(id__in=blocked_template_ids).values_list("title", flat=True)
                )
        if blocked_template_titles:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping {len(blocked_template_titles)} templates because their datasets failed to sync: "
                    f"{', '.join(blocked_template_titles)}"
                )
            )
        
        # Step 2: Generate stories
        if not options.get('skip_generation'):
            self.stdout.write("Step 2: Generating stories...")
            story_service = StoryGenerationService()
            story_result = story_service.generate_stories(
                anchor_date=anchor_date,
                force=force,
                exclude_template_ids=list(blocked_template_ids) if blocked_template_ids else None,
            )
            summary_message = (
                f"Generated: {story_result['successful']}, Failed: {story_result['failed']}, Skipped: {story_result['skipped']}"
            )
            if story_result['failed']:
                failure_entries = [
                    detail for detail in story_result['details'] if detail['status'] == 'failed'
                ]
                detail_lines = []
                for detail in failure_entries:
                    dataset_desc = ", ".join(detail.get("dataset_names") or ["no dataset"])
                    error_desc = detail.get("error", "Unknown error")
                    detail_lines.append(
                        f"{detail['template_title']} (datasets: {dataset_desc}) - {error_desc}"
                    )
                failure_details = "; ".join(detail_lines) if detail_lines else "No detail available"
                failure_message = (
                    f"✗ Story generation encountered failures. {summary_message}. Failures: {failure_details}"
                )
                self.stdout.write(self.style.ERROR(failure_message))
                email_service.send_admin_alert(
                    subject=f"ETL pipeline failure: Story generation ({anchor_date_label})",
                    body=failure_message,
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Story generation completed. {summary_message}"
                    )
                )
        else:
            self.stdout.write("Skipping story generation...")

        # Step 3: subscribe users with the autosubscribe flag set to true to new stories (templates where is_published changed from False to True)
        self.stdout.write("Step 3: Subscribing users to new stories...")
        subscribe_service = StorySubscriptionService()
        subscribe_result = subscribe_service.subscribe_users_to_new_stories()

        if subscribe_result['success']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ User subscription completed. "
                    f"Subscribed: {subscribe_result['successful']}, Failed: {subscribe_result['failed']}"
                )
            )
        else:
            failure_message = (
                f"✗ User subscription failed. "
                f"Subscribed: {subscribe_result['successful']}, Failed: {subscribe_result['failed']}"
            )
            self.stdout.write(self.style.ERROR(failure_message))
            email_service.send_admin_alert(
                subject=f"ETL pipeline failure: Subscriptions ({anchor_date_label})",
                body=failure_message,
            )
            if not force and not continue_on_error:
                self.stdout.write("Stopping pipeline because --stop-on-error was set. Remove that flag or add --force to continue.")
                return

        # Step 4: Send emails
        if not options.get('skip_email'):
            self.stdout.write("Step 3: Sending emails...")
            email_result = email_service.send_stories_for_date(send_date=anchor_date)
            
            if email_result['success']:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Email sending completed. "
                        f"Sent: {email_result.get('successful', 0)}, Failed: {email_result.get('failed', 0)}"
                    )
                )
            else:
                failure_message = (
                    f"✗ Email sending failed. "
                    f"Sent: {email_result.get('successful', 0)}, Failed: {email_result.get('failed', 0)}"
                )
                self.stdout.write(self.style.ERROR(failure_message))
                email_service.send_admin_alert(
                    subject=f"ETL pipeline failure: Email sending ({anchor_date_label})",
                    body=failure_message,
                )
                if not continue_on_error:
                    self.stdout.write("Stopping pipeline because --stop-on-error was set. Remove that flag or rerun with --force to ignore failures.")
                    return
        else:
            self.stdout.write("Skipping email sending...")
        
        self.stdout.write(
            self.style.SUCCESS("ETL pipeline completed!")
        )
