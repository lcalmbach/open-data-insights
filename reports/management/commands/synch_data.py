from django.core.management.base import BaseCommand
from reports.services import DatasetSyncService


class Command(BaseCommand):
    help = 'Synchronize datasets from external sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id', 
            type=int, 
            help='ID of the specific dataset to synchronize'
        )

    def handle(self, *args, **options):
        dataset_id = options.get('id')
        
        service = DatasetSyncService()
        result = service.synchronize_datasets(dataset_id=dataset_id)
        
        if result['success']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Synchronization completed successfully. "
                    f"Processed: {result['successful']}, Failed: {result['failed']}"
                )
            )
        else:
            failed_datasets = [detail['dataset_id'] for detail in result['details'] if not detail['success']]
            self.stdout.write(
                self.style.ERROR(
                    f"Synchronization completed with errors. "
                    f"Processed: {result['successful']}, Failed: {result['failed']}, "
                    f"Failed dataset IDs: {failed_datasets}"
                )
            )
            
        # Show details if verbose
        if options.get('verbosity', 1) > 1:
            for detail in result.get('details', []):
                status = "✓" if detail['success'] else "✗"
                status_text = f"  {status} ID {detail['dataset_id']}: {detail['dataset_name']}"
                if not detail['success'] and 'error' in detail:
                    status_text += f" - Error: {detail['error']}"
                self.stdout.write(status_text)
                if not detail['success'] and 'error' in detail:
                    self.stdout.write(f"    Error: {detail['error']}")
