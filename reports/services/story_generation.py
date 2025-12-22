"""
Story Generation Service
Handles generating data insights and stories from templates
"""

import logging
import pandas as pd
from datetime import date, timedelta, datetime
from typing import Optional, Dict, Any

from reports.services.base import ETLBaseService
from reports.services.story_processor import StoryProcessor
from reports.models.story_template import StoryTemplate


class StoryGenerationService(ETLBaseService):
    """Service for generating data insights and stories"""

    def __init__(self):
        super().__init__("StoryGeneration")

    def generate_story(
        self,  # This is the first argument (self)
        template: StoryTemplate,  # Second argument
        anchor_date: Optional[date] = None,  # Third argument with default
        force: bool = False,  # Fourth argument with default
    ) -> Dict[str, Any]:
        """Generate a single story from a template"""
        try:
            self.logger.info(f"Generating story for template: {template.title}")

            # Use provided date or default to yesterday
            if not anchor_date:
                anchor_date = date.today() - timedelta(days=1)

            # Ensure anchor_date is a date object, not a datetime
            if isinstance(anchor_date, datetime):
                anchor_date = anchor_date.date()

            story_processor = StoryProcessor(anchor_date, template, force)

            # Check if story should be generated
            if not force and not story_processor.story_is_due():
                self.logger.info(
                    f"Story generation skipped for template: {template.title}"
                )
                return {
                    "success": True,
                    "skipped": True,
                    "message": "Story generation conditions not met",
                }

            # Generate the story
            success = story_processor.generate_story()

            if success:
                self.logger.info(
                    f"Successfully generated story for template: {template.title}"
                )
                return {
                    "success": True,
                    "story_id": story_processor.id,
                    "message": "Story generated successfully",
                }
            else:
                self.logger.error(
                    f"Failed to generate story for template: {template.title}"
                )
                return {"success": False, "error": "Story generation failed"}

        except Exception as e:
            self.logger.error(
                f"Error generating story for template {template.title}: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def generate_stories(
        self,
        template_id: Optional[int] = None,
        anchor_date: Optional[date] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Generate multiple stories from templates"""
        # Use Django ORM to fetch templates
        if template_id:
            templates = StoryTemplate.objects.filter(id=template_id, active=True)
        else:
            templates = StoryTemplate.objects.filter(active=True).order_by("id")

        if not templates.exists():
            if template_id:
                self.logger.error(
                    f"No active story template found with ID: {template_id}"
                )
                return {
                    "success": False,
                    "message": f"Template ID {template_id} not found",
                }
            else:
                self.logger.info("No active story templates found")
                return {"success": True, "message": "No active templates to process"}

        results = {
            "success": True,
            "total_templates": templates.count(),
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        for template in templates:
            print(f"Processing template ID {template.id}: {template.title}")
            service = StoryProcessor(anchor_date, template, force)

            if service.story_is_due():
                try:
                    result = service.generate_story()

                    if result:
                        results["successful"] += 1
                        results["details"].append(
                            {
                                "template_id": template.id,
                                "status": "success",
                            }
                        )
                    else:
                        results["failed"] += 1
                        results["details"].append(
                            {
                                "template_id": template.id,
                                "status": "failed",
                                "error": result.get("error", "Unknown error"),
                            }
                        )
                except Exception as e:
                    self.logger.error(
                        f"Error processing template {template.id}: {str(e)}"
                    )
                    results["failed"] += 1
                    results["details"].append(
                        {
                            "template_id": template.id,
                            "status": "error",
                            "error": str(e),
                        }
                    )
            else:
                self.logger.info(f"Skipping template {template.id} - not due")
                results["skipped"] += 1
                results["details"].append(
                    {
                        "template_id": template.id,
                        "status": "skipped",
                        "message": "Story generation conditions not met",
                    }
                )
        return results
