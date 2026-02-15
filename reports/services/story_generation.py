"""
Story Generation Service
Handles generating data insights and stories from templates
"""

import logging
import pandas as pd
from datetime import date, timedelta, datetime
from typing import Optional, Dict, Any, List

from reports.services.base import ETLBaseService
from reports.services.story_processor import StoryProcessor
from reports.models.story_template import StoryTemplate, StoryTemplateFocus


class StoryGenerationService(ETLBaseService):
    """Service for generating data insights and stories"""

    def __init__(self):
        super().__init__("StoryGeneration")

    def generate_story(
        self,  # This is the first argument (self)
        focus: StoryTemplateFocus,  # Second argument
        anchor_date: Optional[date] = None,  # Third argument with default
        force: bool = False,  # Fourth argument with default
    ) -> Dict[str, Any]:
        """Generate a single story from a template"""
        try:
            template = focus.story_template
            self.logger.info(
                f"Generating story for template: {template.title} (focus={getattr(focus, 'id', None)})"
            )

            # Use provided date or default to yesterday
            if not anchor_date:
                anchor_date = date.today() - timedelta(days=1)

            # Ensure anchor_date is a date object, not a datetime
            if isinstance(anchor_date, datetime):
                anchor_date = anchor_date.date()

            story_processor = StoryProcessor(anchor_date, template, force, focus=focus)

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
                    "story_id": story_processor.story.id
                    if story_processor.story
                    else None,
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
        exclude_template_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Generate multiple stories from templates"""
        focuses = StoryTemplateFocus.objects.select_related("story_template").filter(
            story_template__active=True
        )
        if template_id:
            focuses = focuses.filter(story_template_id=template_id)
        if exclude_template_ids:
            focuses = focuses.exclude(story_template_id__in=exclude_template_ids)

        if not focuses.exists():
            if template_id:
                self.logger.error(
                    f"No active story template found with ID: {template_id}"
                )
                return {
                    "success": False,
                    "message": f"Template ID {template_id} not found",
                    "total_templates": 0,
                    "successful": 0,
                    "failed": 0,
                    "skipped": 0,
                    "details": [],
                }
            else:
                self.logger.info("No active story templates found")
                return {
                    "success": True,
                    "message": "No active templates to process",
                    "total_templates": 0,
                    "successful": 0,
                    "failed": 0,
                    "skipped": 0,
                    "details": [],
                }

        focuses = focuses.prefetch_related("story_template__datasets__dataset")
        results = {
            "success": True,
            "total_templates": focuses.count(),
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        for focus in focuses:
            template = focus.story_template
            dataset_names = []
            for relation in template.datasets.all():
                if relation.dataset and getattr(relation.dataset, "name", None):
                    dataset_names.append(relation.dataset.name)

            result = self.generate_story(
                focus=focus, anchor_date=anchor_date, force=force
            )
            detail = {
                "template_id": template.id,
                "template_title": template.title,
                "focus_id": focus.id,
                "focus_value": focus.filter_value or "",
                "dataset_names": dataset_names,
            }

            if result.get("skipped"):
                results["skipped"] += 1
                detail.update(
                    {
                        "status": "skipped",
                        "message": result.get("message"),
                    }
                )
            elif result.get("success"):
                results["successful"] += 1
                detail["status"] = "success"
            else:
                results["failed"] += 1
                detail.update(
                    {
                        "status": "failed",
                        "error": result.get("error", "Unknown error"),
                    }
                )
            results["details"].append(detail)

        results["success"] = results["failed"] == 0
        return results
