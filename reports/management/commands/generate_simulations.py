from django.core.management.base import BaseCommand, CommandError
from reports.models.simulation import SimulationTemplate
from reports.services.simulation_processor import generate_simulation


class Command(BaseCommand):
    help = "Generate (or regenerate) simulation HTML for one or all SimulationTemplates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--id",
            type=int,
            help="SimulationTemplate ID to regenerate. Omit to regenerate all.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all available SimulationTemplates and exit.",
        )

    def handle(self, *args, **options):
        if options["list"]:
            templates = SimulationTemplate.objects.all()
            if not templates:
                self.stdout.write(self.style.WARNING("No SimulationTemplates found."))
                return
            for t in templates:
                self.stdout.write(f"  id={t.id}  {t.title}")
            return

        template_id = options.get("id")
        if template_id:
            try:
                templates = [SimulationTemplate.objects.get(pk=template_id)]
            except SimulationTemplate.DoesNotExist:
                raise CommandError(f"SimulationTemplate id={template_id} not found.")
        else:
            templates = list(SimulationTemplate.objects.all())
            if not templates:
                self.stdout.write(self.style.WARNING("No SimulationTemplates found."))
                return

        total = len(templates)
        processed = 0
        failed = []

        for t in templates:
            try:
                sim = generate_simulation(t.id)
                processed += 1
                self.stdout.write(
                    f"  OK  template id={t.id} '{t.title}' → simulation id={sim.id}"
                )
            except Exception as exc:
                failed.append((t, exc))
                self.stdout.write(
                    self.style.ERROR(f"  ERR template id={t.id} '{t.title}': {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. processed={processed}/{total} errors={len(failed)}")
        )
        if failed:
            self.stdout.write(self.style.ERROR("\nFailed simulations:"))
            for t, exc in failed:
                self.stdout.write(self.style.ERROR(f"  id={t.id}  '{t.title}'  error={exc}"))
