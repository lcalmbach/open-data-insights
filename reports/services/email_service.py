"""
Email Service
Handles sending generated stories and reports via email
"""

import logging
import time
from django.urls import reverse
from typing import Optional, Dict, Any, List
from datetime import date, timedelta
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
import markdown
from django.contrib.auth import get_user_model
from openai import OpenAI
from reports.models.story import Story
from reports.models.subscription import StoryTemplateSubscription
from reports.models.story_template import StoryTemplate
from reports.models.lookups import Language

from reports.services.base import ETLBaseService
from reports.services.database_client import DjangoPostgresClient
from reports.language import (
    ENGLISH_LANGUAGE_ID,
    get_language_code_for_id,
    rewrite_url_language,
)


class EmailService(ETLBaseService):
    """Service for sending emails with generated stories and reports"""

    def __init__(self):
        super().__init__("EmailService")
        self.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
        self.dbclient = DjangoPostgresClient()
        self.ai_model = getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o")
        if self.ai_model == "deepseek-chat":
            api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
            self.ai_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        else:
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            self.ai_client = OpenAI(api_key=api_key)

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

            self.logger.info("Starting sending mails for %s...", send_date)

            redirect_recipients = getattr(settings, "EMAIL_REDIRECT_TO", None)
            redirect_max_emails = getattr(settings, "EMAIL_REDIRECT_MAX_EMAILS", None)
            redirect_active = bool(redirect_recipients)
            emails_attempted = 0

            if (
                redirect_active
                and isinstance(redirect_max_emails, int)
                and redirect_max_emails == 0
            ):
                self.logger.info(
                    "EMAIL_REDIRECT_TO is enabled; not sending any emails (EMAIL_REDIRECT_MAX_EMAILS=0)."
                )
                return {"success": True, "total_sent": 0, "failed": 0, "details": []}

            User = get_user_model()
            users = (
                User.objects.filter(is_active=True)
                .select_related("preferred_language")
                .order_by("id")
            )
            total_sent = 0
            total_errors = 0
            details = []
            translation_cache: dict[tuple[int, str], str] = {}
            language_name_by_id = dict(
                Language.objects.values_list("id", "value")
            )

            # fetch templates that are not yet published for creation (one query)
            new_templates_qs = StoryTemplate.objects.filter(is_published=False)
            root = settings.APP_ROOT.rstrip("/")
            new_template_records = [{"id": t.id, "title": t.title} for t in new_templates_qs]

            for user in users:
                preferred_language_id = getattr(user, "preferred_language_id", None) or ENGLISH_LANGUAGE_ID
                preferred_language_id = int(preferred_language_id)
                language_code = get_language_code_for_id(preferred_language_id)
                preferred_language_name = language_name_by_id.get(preferred_language_id, "English")
                translated = preferred_language_id != ENGLISH_LANGUAGE_ID

                # Find subscriptions for this user
                subscriptions = StoryTemplateSubscription.objects.filter(user=user)
                # Get subscribed templates the user can access based on organisation
                template_ids = (
                    StoryTemplate.objects.accessible_to(user)
                    .filter(id__in=subscriptions.values_list("story_template_id", flat=True))
                    .values_list("id", flat=True)
                )
                # Find stories published on send_date for these templates
                stories = Story.objects.filter(
                    templatefocus__story_template_id__in=template_ids,
                    published_date=send_date,
                    language_id=ENGLISH_LANGUAGE_ID,
                ).select_related("templatefocus__story_template")

                if not stories.exists():
                    continue

                # Build insights list for email
                insights = []
                for story in stories:
                    story_url = (
                        story.get_absolute_url()
                        if hasattr(story, "get_absolute_url")
                        else f"{settings.APP_ROOT.rstrip('/')}/story/{story.id}/"
                    )
                    insights.append(
                        {
                            "title": story.title,
                            "summary": story.summary,
                            "url": rewrite_url_language(story_url, language_code),
                        }
                    )

                english_subject = f"Open Data Insights for {send_date.strftime('%Y-%m-%d')}"

                # Build language-prefixed template links per recipient.
                new_templates = [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "url": rewrite_url_language(f"{root}/templates/?template={t['id']}", language_code),
                    }
                    for t in new_template_records
                ]

                if preferred_language_id == ENGLISH_LANGUAGE_ID:
                    subject = english_subject
                    email_body = self._render_insights_email(
                        insights,
                        new_templates=new_templates,
                        profile_url=rewrite_url_language(f"{root}/account/profile/", language_code),
                    )
                else:
                    subject = self._translate_text_cached(
                        english_subject,
                        preferred_language_id,
                        preferred_language_name,
                        translation_cache,
                        max_tokens=120,
                    )
                    localized_english_email_body = self._render_insights_email(
                        insights,
                        new_templates=new_templates,
                        profile_url=rewrite_url_language(f"{root}/account/profile/", language_code),
                    )
                    email_body = self._translate_text_cached(
                        localized_english_email_body,
                        preferred_language_id,
                        preferred_language_name,
                        translation_cache,
                        max_tokens=3000,
                    )
                self.logger.info(
                    "Prepared localized email (user_email=%s, preferred_language_id=%s, preferred_language=%s, translated=%s)",
                    user.email,
                    preferred_language_id,
                    preferred_language_name,
                    translated,
                )
                result = self.send_story_email(
                    story_content=email_body,
                    recipients=[user.email],
                    subject=subject,
                    send_date=send_date,
                )

                emails_attempted += 1
                details.append(
                    {
                        "user": user.first_name,
                        "email": user.email,
                        "preferred_language_id": preferred_language_id,
                        "preferred_language": preferred_language_name,
                        "translated": translated,
                        "success": result.get("success"),
                        "error": result.get("error"),
                    }
                )
                if result.get("success"):
                    total_sent += 1
                else:
                    total_errors += 1

                if (
                    redirect_active
                    and isinstance(redirect_max_emails, int)
                    and redirect_max_emails > 0
                    and emails_attempted >= redirect_max_emails
                ):
                    self.logger.info(
                        "EMAIL_REDIRECT_TO is enabled; stopping after %s email(s) (EMAIL_REDIRECT_MAX_EMAILS=%s).",
                        emails_attempted,
                        redirect_max_emails,
                    )
                    break

            # mark templates as published if we sent at least one email
            if new_templates_qs.exists() and total_sent > 0:
                try:
                    count = new_templates_qs.update(is_published=True)
                    self.logger.info(
                        "Marked %s new templates as is_published=True", count
                    )
                except Exception as e:
                    self.logger.error("Failed to mark new templates as published: %s", e)

            return {
                "success": True,
                "total_sent": total_sent,
                "failed": total_errors,
                "details": details,
            }

        except Exception as e:
            self.logger.error("Error sending stories for date %s: %s", send_date, e)
            return {"success": False, "error": str(e)}

    def _get_new_templates(self) -> list:
        """Return list of templates not yet published for creation (title + full url)."""
        templates = StoryTemplate.objects.filter(is_published=False)
        if not templates.exists():
            return []
        root = settings.APP_ROOT.rstrip("/")
        result = []
        for t in templates:
            result.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "url": f"{root}/templates/?template={t.id}",
                }
            )
        return result

    def _render_insights_email(
        self,
        insights: list,
        new_templates: list | None = None,
        profile_url: str | None = None,
    ):
        """Render the email body for a user, their insights and optional new-template section."""
        lines = [
            "Hello,",
            "",
            "",
            "We’ve just published new insights from your subscribed topics:",
            "",
            "",
        ]
        for insight in insights:
            lines.append(f"**{insight['title']}**: {insight['summary']} ")
            lines.append(
                f"[View the full story with tables and graphs]({insight['url']})"
            )
            lines += ["", ""]  # spacer# spacer
        # New templates / subscription prompt
        if new_templates:
            lines.append("🔥We’ve uncovered new insights — discover them now:")
            lines.append("")
            for t in new_templates:
                lines.append(f"- [{t['title']}]({t['url']})")
            lines.append("")  # spacer
            # subscription prompt linking to account/profile
            if not profile_url:
                root = settings.APP_ROOT.rstrip("/")
                profile_url = f"{root}/account/profile/"
            lines.append(
                f"Interested? Subscribe to new insights [here]({profile_url})"
            )
        lines += ["", "", "Best regards,", "your **O**pen **D**ata **I**nsights Team"]

        return "\n".join(lines)

    def _translate_text(self, text: str, target_language_name: str, max_tokens: int = 3000) -> str:
        if not text:
            return text

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a professional translator. Translate the input text to {target_language_name}. "
                    "Preserve meaning, numbers, dates, links, and markdown structure. Return only the translated text."
                ),
            },
            {"role": "user", "content": text},
        ]
        response = self.ai_client.chat.completions.create(
            model=self.ai_model,
            messages=messages,
            temperature=0.0,
            max_tokens=max_tokens,
        )
        translated = (response.choices[0].message.content or "").strip()
        return translated or text

    def _translate_text_cached(
        self,
        text: str,
        language_id: int,
        language_name: str,
        cache: dict[tuple[int, str], str],
        *,
        max_tokens: int = 3000,
    ) -> str:
        key = (int(language_id), text)
        cached = cache.get(key)
        if cached:
            return cached
        try:
            translated = self._translate_text(
                text,
                target_language_name=language_name,
                max_tokens=max_tokens,
            )
        except Exception:
            self.logger.exception(
                "Failed to translate email text (language_id=%s, language=%s); falling back to English",
                language_id,
                language_name,
            )
            translated = text
        cache[key] = translated
        return translated

    def send_admin_alert(self, subject: str, body: str) -> Dict[str, Any]:
        """Send a plain-text alert to all active staff admins."""
        User = get_user_model()
        recipients = list(
            User.objects.filter(is_active=True, is_staff=True).values_list("email", flat=True)
        )
        if not recipients:
            self.logger.warning("No admin recipients found for alert email")
            return {"success": False, "message": "No admin recipients available"}

        if hasattr(settings, "EMAIL_REDIRECT_TO"):
            recipients = settings.EMAIL_REDIRECT_TO

        try:
            send_mail(subject, body, self.from_email, recipients)
            self.logger.info("Sent admin alert email to %s recipients", len(recipients))
            return {"success": True, "recipients": recipients}
        except Exception as exc:
            self.logger.error("Error sending admin alert: %s", exc)
            return {"success": False, "error": str(exc)}

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
