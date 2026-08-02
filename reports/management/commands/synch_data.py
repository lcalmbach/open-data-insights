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
        parser.add_argument(
            '--keep-files',
            action='store_true',
            help='Do not delete the ./files working folder after run'
        )
        parser.add_argument(
            '--keep-csv', '--keep_csv',
            dest='keep_csv',
            action='store_true',
            help=(
                'Do not delete CSVs downloaded from URL sources. Use for large '
                'downloads so a failed load can be retried without re-fetching. '
                'The path is written to the log.'
            )
        )

    def handle(self, *args, **options):
        dataset_id = options.get('id')
        keep_files = options.get('keep_files', False)
        keep_csv = options.get('keep_csv', False)
        service = DatasetSyncService()
        result = service.synchronize_datasets(
            dataset_id=dataset_id,
            keep_files=keep_files,
            keep_csv=keep_csv,
        )
        
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
        
       
