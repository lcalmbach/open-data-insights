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
        """Send all stories for a specific date"""
        try:
            if not send_date:
                send_date = date.today()

            self.logger.info(f"Starting sending mails for {send_date}...")

            # Clean up empty stories first
            self._cleanup_empty_stories()

            # Get stories to send using the view from the original code
            cmd = "SELECT * FROM report_generator.v_insights2send"
            df = self.dbclient.run_query(cmd, [send_date])

            if df.empty:
                self.logger.info(f"No insights found for {send_date}")
                return {
                    "success": True,
                    "message": f"No stories to send for {send_date}",
                    "total_stories": 0,
                    "successful": 0,
                    "failed": 0,
                }

            self.logger.info(f"Found {len(df)} stories to send.")

            results = {
                "success": True,
                "total_stories": len(df),
                "successful": 0,
                "failed": 0,
                "details": [],
            }

            for _, row in df.iterrows():
                try:
                    if row["story"]:  # Check if story content exists
                        subject = f"Open Data Story: {row['title']}"
                        html_body = markdown.markdown(
                            row["story"], extensions=["markdown.extensions.tables"]
                        )

                        # Send email
                        email_result = self._send_single_email(
                            subject=subject, html_body=html_body, to_email=row["email"]
                        )

                        if email_result["success"]:
                            results["successful"] += 1
                        else:
                            results["failed"] += 1
                            results["success"] = False

                        results["details"].append(
                            {
                                "story_title": row["title"],
                                "recipient": row["email"],
                                "success": email_result["success"],
                                "error": email_result.get("error"),
                            }
                        )

                        # Small delay between emails to avoid overwhelming the SMTP server
                        time.sleep(2)

                    else:
                        self.logger.info(
                            f"Story for {row['title']} is empty, not sending email to {row['email']}"
                        )
                        results["details"].append(
                            {
                                "story_title": row["title"],
                                "recipient": row["email"],
                                "success": False,
                                "error": "Story content is empty",
                            }
                        )
                        results["failed"] += 1

                except Exception as e:
                    self.logger.error(
                        f"Error processing story for {row.get('email', 'unknown')}: {e}"
                    )
                    results["failed"] += 1
                    results["success"] = False
                    results["details"].append(
                        {
                            "story_title": row.get("title", "Unknown"),
                            "recipient": row.get("email", "Unknown"),
                            "success": False,
                            "error": str(e),
                        }
                    )

            # Mark all stories as sent
            if results["successful"] > 0:
                self._mark_stories_as_sent()

            self.logger.info(
                f"Email sending completed. Success: {results['successful']}, Failed: {results['failed']}"
            )
            return results

        except Exception as e:
            self.logger.error(f"Error sending stories for date {send_date}: {str(e)}")
            return {"success": False, "error": str(e)}

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
