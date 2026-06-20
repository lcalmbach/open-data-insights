import json
import logging

from django.db import connection

from reports.models.simulation import Simulation, SimulationTemplate

logger = logging.getLogger(__name__)


def generate_simulation(simulation_id: int) -> Simulation:
    """
    Resolve all parameters for a SimulationTemplate, inject them as a JS
    `const BASELINE = {...};` block, and store the result as a new Simulation row.
    Returns the new Simulation instance.
    """
    template = SimulationTemplate.objects.prefetch_related("parameters").get(pk=simulation_id)

    resolved = {}
    with connection.cursor() as cursor:
        for param in template.parameters.order_by("sort_order", "parameter_name"):
            try:
                resolved[param.parameter_name] = param.resolve(cursor)
            except Exception as exc:
                logger.error(
                    "Failed to resolve parameter '%s' for simulation '%s': %s",
                    param.parameter_name, template.title, exc,
                )
                raise

    baseline_js = f"<script>const BASELINE = {json.dumps(resolved)};</script>\n"
    html = baseline_js + template.js_template

    sim = Simulation.objects.create(
        simulation_template=template,
        html=html,
        parameters_used=resolved,
    )
    logger.info(
        "Generated simulation '%s' (id=%d) with %d parameters.",
        template.title, sim.id, len(resolved),
    )
    return sim


def get_latest_simulation(simulation_template_id: int) -> Simulation | None:
    """Return the most recently generated Simulation for a template, or None."""
    return (
        Simulation.objects
        .filter(simulation_template_id=simulation_template_id)
        .order_by("-generated_at")
        .first()
    )
