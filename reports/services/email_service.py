"""
Email Service
Handles sending generated stories and reports via email
"""

import logging
import time
from typing import Optional, Dict, Any, List
from datetime import date, timedelta
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
import markdown
import pandas as pd
from django.contrib.auth import get_user_model
from reports.models import Story, StoryTemplateSubscription, StoryTemplate, CustomUser
from django.urls import reverse

from reports.services.base import ETLBaseService
from reports.services.database_client import DjangoPostgresClient


class EmailService(ETLBaseService):
    """Service for sending emails with generated stories and reports"""

    def __init__(self):
        super().__init__("EmailService")
        self.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
        self.dbclient = DjangoPostgresClient()

    def send_story_email(
        self,
        story_content: str,
        recipients: List[str],
        subject: str = None,
        send_date: date = None,
    ) -> Dict[str, Any]:
        """Send a story via email"""
        try:
            if not recipients:
                return {"success": False, "message": "No recipients specified"}

            # Redirect all emails to developer in development/local
            if hasattr(settings, "EMAIL_REDIRECT_TO"):
                recipients = settings.EMAIL_REDIRECT_TO

            # Default subject if not provided
            if not subject:
                subject = f"Data Insights - {send_date or date.today()}"

            # Convert markdown to HTML
            html_content = markdown.markdown(
                story_content, extensions=["markdown.extensions.tables"]
            )

            # Create email with both text and HTML versions using Django
            email = EmailMultiAlternatives(
                subject=subject,
                body=story_content,  # Plain text version
                from_email=self.from_email,
                to=recipients,
            )
            email.attach_alternative(html_content, "text/html")
            email.send()

            self.logger.info(f"Email sent successfully to {len(recipients)} recipients")
            return {
                "success": True,
                "recipients": recipients,
                "message": "Email sent successfully",
            }

        except Exception as e:
            self.logger.error(f"Error sending story email: {str(e)}")
            return {"success": False, "error": str(e)}

    def send_stories_for_date(self, send_date: date = None) -> Dict[str, Any]:
        """Send all stories for a specific date using Django ORM and new template"""
        try:
            if not send_date:
                send_date = date.today()

            self.logger.info(f"Starting sending mails for {send_date}...")

            User = get_user_model()
            users = User.objects.filter(is_active=True)
            total_sent = 0
            details = []

            for user in users:
                # Find subscriptions for this user
                subscriptions = StoryTemplateSubscription.objects.filter(user=user)
                # Get all templates the user is subscribed to
                template_ids = subscriptions.values_list('story_template_id', flat=True)
                # Find stories published on send_date for these templates
                stories = Story.objects.filter(
                    template_id__in=template_ids,
                    published_date=send_date
                ).select_related('template')

                if not stories.exists():
                    continue

                # Build insights list for email
                insights = []
                for story in stories:
                    insight_html = f"{story.title} + <>"
                    insights.append({
                        "summary": story.get_email_list_entry(),
                        "url": story.get_absolute_url(),
                        "title": story.title
                    })

                # Render email body
                email_body = self._render_insights_email(user, insights)
                subject = f"Open Data Insights for {send_date.strftime('%Y-%m-%d')}"
                result = self.send_story_email(
                    story_content=email_body,
                    recipients=[user.email],
                    subject=subject,
                    send_date=send_date
                )
                details.append({
                    "user": user.first_name,
                    "email": user.email,
                    "success": result.get("success"),
                    "error": result.get("error"),
                })
                if result.get("success"):
                    total_sent += 1

            return {
                "success": True,
                "total_sent": total_sent,
                "details": details,
            }

        except Exception as e:
            self.logger.error(f"Error sending stories for date {send_date}: {str(e)}")
            return {"success": False, "error": str(e)}

    def _render_insights_email(self, user, insights):
        """Render the email body for a user and their insights"""
        lines = [
            f"Hello {user.first_name},",
            "",
            "We’ve just published new insights from your subscribed topics:",
            "",
        ]
        for insight in insights:
            lines.append(f"- {insight['summary']}\n  [View the full story with tables and graphs]({insight['url']})")
        lines.append("")
        lines.append("Best regards,\nThe Open Data Insights Team")
        return "\n".join(lines)

    def _cleanup_empty_stories(self):
        """Remove stories with empty content"""
        try:
            cmd = "DELETE FROM report_generator.reports_story WHERE content IS NULL"
            self.dbclient.run_action_query(cmd)
            self.logger.info("Cleaned up empty stories")
        except Exception as e:
            self.logger.error(f"Error cleaning up empty stories: {e}")

    def _mark_stories_as_sent(self):
        """Mark all stories as sent"""
        try:
            cmd = "UPDATE report_generator.reports_story SET is_sent = true"
            self.dbclient.run_action_query(cmd)
            self.logger.info("Updated all records to is_sent = true")
        except Exception as e:
            self.logger.error(f"Error marking stories as sent: {e}")

    def _send_single_email(
        self, subject: str, html_body: str, to_email: str
    ) -> Dict[str, Any]:
        """Send a single email"""
        try:
            # Create email with HTML content using Django
            email = EmailMultiAlternatives(
                subject=subject,
                body="Please view this email in HTML format.",  # Fallback text
                from_email=self.from_email,
                to=[to_email],
            )
            email.attach_alternative(html_body, "text/html")

            # Send email
            email.send()

            self.logger.info(f"Email sent to {to_email}")
            return {"success": True, "recipient": to_email}

        except Exception as e:
            self.logger.error(f"Error sending email to {to_email}: {e}")
            return {"success": False, "error": str(e), "recipient": to_email}

    def test_email_connection(self) -> Dict[str, Any]:
        """Test email connection and configuration"""
        try:
            # Use Django's test email functionality
            from django.core.mail import get_connection

            connection = get_connection()
            connection.open()
            connection.close()

            return {"success": True, "message": "Email connection test successful"}

        except Exception as e:
            return {"success": False, "error": str(e)}
