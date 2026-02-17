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
        published_date: Optional[date] = None,  # Third argument with default
        force: bool = False,  # Fourth argument with default
    ) -> Dict[str, Any]:
        """Generate a single story from a template"""
        try:
            template = focus.story_template
            focus_id = getattr(focus, "id", None)
            focus_value = getattr(focus, "filter_value", None) or ""
            self.logger.info(
                "Generating story (template_id=%s, template_title=%s, focus_id=%s, focus_value=%s)",
                getattr(template, "id", None),
                getattr(template, "title", ""),
                focus_id,
                focus_value,
            )

            # Use provided date or default to today
            if not published_date:
                published_date = date.today() 

            # Ensure published_date is a date object, not a datetime
            if isinstance(published_date, datetime):
                published_date = published_date.date()

            story_processor = StoryProcessor(published_date, template, force, focus=focus)

            # Check if story should be generated
            if not force and not story_processor.story:
                self.logger.info(
                    "Story generation skipped (template_id=%s, focus_id=%s)",
                    getattr(template, "id", None),
                    focus_id,
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
                    "Successfully generated story (template_id=%s, focus_id=%s, story_id=%s)",
                    getattr(template, "id", None),
                    focus_id,
                    getattr(getattr(story_processor, "story", None), "id", None),
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
                    "Failed to generate story (template_id=%s, focus_id=%s)",
                    getattr(template, "id", None),
                    focus_id,
                )
                return {"success": False, "error": "Story generation failed"}

        except Exception as e:
            template = getattr(focus, "story_template", None)
            self.logger.exception(
                "Error generating story (template_id=%s, template_title=%s, focus_id=%s, focus_value=%s)",
                getattr(template, "id", None),
                getattr(template, "title", ""),
                getattr(focus, "id", None),
                getattr(focus, "filter_value", None) or "",
            )
            return {"success": False, "error": str(e)}

    def generate_stories(
        self,
        template_id: Optional[int] = None,
        published_date: Optional[date] = None,
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
            focus_id = getattr(focus, "id", None)
            focus_value = getattr(focus, "filter_value", None) or ""
            dataset_names: list[str] = []
            try:
                for relation in template.datasets.all():
                    if relation.dataset and getattr(relation.dataset, "name", None):
                        dataset_names.append(relation.dataset.name)

                self.logger.info(
                    "Processing focus (template_id=%s, template_title=%s, focus_id=%s, focus_value=%s)",
                    getattr(template, "id", None),
                    getattr(template, "title", ""),
                    focus_id,
                    focus_value,
                )

                result = self.generate_story(
                    focus=focus, published_date=published_date, force=force
                )
            except Exception as e:  # noqa: BLE001
                self.logger.exception(
                    "Unhandled error generating story (template_id=%s, template_title=%s, focus_id=%s, focus_value=%s, datasets=%s)",
                    getattr(template, "id", None),
                    getattr(template, "title", ""),
                    focus_id,
                    focus_value,
                    ", ".join(dataset_names) if dataset_names else "",
                )
                result = {"success": False, "error": str(e)}

            detail = {
                "template_id": getattr(template, "id", None),
                "template_title": getattr(template, "title", ""),
                "focus_id": focus_id,
                "focus_value": focus_value,
                "dataset_names": dataset_names,
            }

            if result.get("skipped"):
                results["skipped"] += 1
                detail.update({"status": "skipped", "message": result.get("message")})
            elif result.get("success"):
                results["successful"] += 1
                detail["status"] = "success"
            else:
                results["failed"] += 1
                detail.update({"status": "failed", "error": result.get("error", "Unknown error")})

            results["details"].append(detail)

        results["success"] = results["failed"] == 0
        return results
