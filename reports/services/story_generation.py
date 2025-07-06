"""
Story Generation Service
Handles generating data insights and stories from templates
"""

import logging
import pandas as pd
from datetime import date, timedelta
from typing import Optional, Dict, Any, List
from django.db import transaction
from django.utils import timezone

from reports.models import StoryTemplate, Dataset
from reports.services.base import ETLBaseService
from reports.services.story_processor import StoryProcessor
from reports.models import StoryTemplate


class StoryGenerationService(ETLBaseService):
    """Service for generating data insights and stories"""

    def __init__(self):
        super().__init__("StoryGeneration")

    def generate_story(
        self,
        template: StoryTemplate,
        run_date: Optional[date] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Generate a single story from a template"""
        try:
            self.logger.info(f"Generating story for template: {template.title}")

            # Use provided date or default to yesterday
            if not run_date:
                run_date = date.today() - timedelta(days=1)

            # Convert template to dict format expected by StoryProcessor
            template_dict = {
                "id": template.id,
                "title": template.title,
                "description": template.description,
                "reference_period_id": template.reference_period.id,
                "prompt_text": template.prompt_text,
                "temperature": template.temperature,
                "has_data_sql": template.has_data_sql,
                "publish_conditions": template.publish_conditions,
                "most_recent_day_sql": template.most_recent_day_sql,
                "post_publish_command": template.post_publish_command,
            }

            # Create story processor
            story_processor = StoryProcessor(template_dict, run_date, force)

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
        run_date: Optional[date] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Generate multiple stories from templates"""
        # Use Django ORM to fetch templates
        if template_id:
            templates = StoryTemplate.objects.filter(id=template_id)
        else:
            templates = StoryTemplate.objects.filter(active=True)

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
            try:
                with transaction.atomic():
                    result = self.generate_story(template, run_date, force)

                    if result["success"]:
                        if result.get("skipped"):
                            results["skipped"] += 1
                        else:
                            results["successful"] += 1
                    else:
                        results["failed"] += 1
                        results["success"] = False

                    results["details"].append(
                        {
                            "template_id": template.id,
                            "template_title": template.title,
                            "success": result["success"],
                            "skipped": result.get("skipped", False),
                            "error": result.get("error"),
                            "story_id": result.get("story_id"),
                        }
                    )

            except Exception as e:
                self.logger.error(
                    f"Transaction failed for template {template.title}: {str(e)}"
                )
                results["failed"] += 1
                results["success"] = False
                results["details"].append(
                    {
                        "template_id": template.id,
                        "template_title": template.title,
                        "success": False,
                        "error": str(e),
                    }
                )

        self.logger.info(
            f"Story generation completed. Success: {results['successful']}, Failed: {results['failed']}, Skipped: {results['skipped']}"
        )
        return results
