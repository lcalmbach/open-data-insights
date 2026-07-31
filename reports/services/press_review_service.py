"""
Press Review Services
RSS harvesting with two-tier keyword filtering, per-user LLM relevance scoring, and
digest email delivery — a feature parallel to (not part of) the Story/StoryTemplate
insight pipeline.

Ported from the work/pressreview proof-of-concept (harvester.py, rater.py, mailer.py),
adapted to the Django ORM and this app's existing AI-client provider conventions
(see StoryProcessor.get_ai_client in reports/services/story_processor.py).
"""

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from typing import Dict, List, Optional, Tuple

import anthropic
import feedparser
import markdown
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone as django_timezone
from openai import OpenAI

from reports.models.press_review import (
    PressReviewArticle,
    PressReviewHarvestLog,
    PressReviewKeyword,
    PressReviewSource,
    UserPressReviewArticleScore,
    UserPressReviewKeyword,
)
from reports.services.base import ETLBaseService

REQUEST_TIMEOUT = 10
USER_AGENT = "OpenDataInsights-PressReview/1.0"

_IMG_TAG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)


def parse_entry_datetime(entry) -> Optional[datetime]:
    for key in ("published", "updated"):
        value = entry.get(key)
        if not value:
            continue
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            try:
                iso_value = value.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso_value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
    return None


def extract_summary(entry) -> str:
    content_list = entry.get("content") or []
    content_encoded = content_list[0].get("value", "") if content_list else ""
    raw = entry.get("summary") or entry.get("description") or content_encoded
    return _IMG_TAG_RE.sub("", raw).strip()


SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


def parse_news_sitemap(content: bytes) -> List[Dict[str, object]]:
    """Parse a Google News sitemap into the same shape as a feed entry.

    Publishers that dropped RSS still maintain these, because Google News depends on
    them — but they carry no article body, so `summary` is always empty and both the
    keyword filter and the LLM scorer work from the headline alone.
    """
    entries: List[Dict[str, object]] = []
    root = ElementTree.fromstring(content)
    for url_node in root.findall("sm:url", SITEMAP_NS):
        link_node = url_node.find("sm:loc", SITEMAP_NS)
        news_node = url_node.find("news:news", SITEMAP_NS)
        if link_node is None or news_node is None:
            continue

        title_node = news_node.find("news:title", SITEMAP_NS)
        date_node = news_node.find("news:publication_date", SITEMAP_NS)
        keywords_node = news_node.find("news:keywords", SITEMAP_NS)

        published = None
        if date_node is not None and date_node.text:
            try:
                published = datetime.fromisoformat(
                    date_node.text.strip().replace("Z", "+00:00")
                )
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except ValueError:
                published = None

        entries.append(
            {
                "title": (title_node.text or "").strip() if title_node is not None else "",
                "link": (link_node.text or "").strip(),
                "summary": "",
                "published_dt": published,
                # Some publishers do supply news:keywords; fold them into the text the
                # keyword filter sees, exactly as RSS <tags> are used.
                "tags_text": (keywords_node.text or "").strip()
                if keywords_node is not None
                else "",
            }
        )
    return entries


def keyword_matches(text: str, keywords: List[str]) -> List[str]:
    def normalize(value: str) -> str:
        lower = value.lower()
        lower = (
            lower.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        return "".join(
            c for c in unicodedata.normalize("NFKD", lower) if not unicodedata.combining(c)
        )

    normalized_text = normalize(text)
    return [
        kw for kw in keywords
        if re.search(r"\b" + re.escape(normalize(kw)) + r"\b", normalized_text)
    ]


class PressReviewHarvestService(ETLBaseService):
    """Fetches active PressReviewSources and stores articles matching the global keyword filter."""

    def __init__(self):
        super().__init__("PressReviewHarvestService")

    def harvest(
        self,
        extra_keywords: Optional[List[str]] = None,
        only_source_ids: Optional[List[int]] = None,
        min_interval_minutes: Optional[int] = None,
    ) -> Dict[str, object]:
        """Fetch active sources and store entries matching the keyword filter.

        `extra_keywords` lets the tool page harvest for topics a user is still trying
        out (not yet saved), so exploring a new topic finds articles immediately rather
        than waiting for the next scheduled run. `min_interval_minutes` skips sources
        fetched very recently, so repeated Apply clicks can't hammer publishers.
        """
        keyword_rows = PressReviewKeyword.objects.filter(active=True)
        required_kws = list(keyword_rows.filter(required=True).values_list("keyword", flat=True))
        regular_kws = list(keyword_rows.filter(required=False).values_list("keyword", flat=True))

        # Users' own topics widen the harvest filter as well. Without this a personal
        # topic can only re-rank articles the global list already collected, so adding
        # a topic nobody curated globally silently returns nothing.
        user_topics = list(
            UserPressReviewKeyword.objects.filter(user__is_active=True)
            .values_list("keyword", flat=True)
            .distinct()
        )
        seen = {kw.casefold() for kw in regular_kws}
        for topic in user_topics + list(extra_keywords or []):
            if topic and topic.casefold() not in seen:
                seen.add(topic.casefold())
                regular_kws.append(topic)

        sources = PressReviewSource.objects.filter(active=True)
        if only_source_ids:
            sources = sources.filter(id__in=only_source_ids)
        sources = list(sources)

        if min_interval_minutes:
            fresh_cutoff = django_timezone.now() - timedelta(minutes=min_interval_minutes)
            skipped_sources = [
                s for s in sources if s.last_fetched_at and s.last_fetched_at > fresh_cutoff
            ]
            if skipped_sources:
                self.logger.info(
                    "Skipping %s source(s) fetched within the last %s minutes.",
                    len(skipped_sources), min_interval_minutes,
                )
            sources = [
                s for s in sources
                if not (s.last_fetched_at and s.last_fetched_at > fresh_cutoff)
            ]

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=settings.PRESSREVIEW_HARVEST_MAX_AGE_DAYS)

        errors: List[str] = []
        new_count = 0
        skipped_count = 0

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        for source in sources:
            try:
                response = session.get(source.rss_url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                # Both branches normalise to the same entry shape so the keyword filter
                # and storage below stay identical regardless of source format.
                if source.feed_type == PressReviewSource.FEED_TYPE_NEWS_SITEMAP:
                    entries = parse_news_sitemap(response.content)
                else:
                    entries = [
                        {
                            "title": (entry.get("title") or "").strip(),
                            "link": (entry.get("link") or "").strip(),
                            "summary": extract_summary(entry),
                            "published_dt": parse_entry_datetime(entry),
                            "tags_text": " ".join(
                                t.get("term", "") for t in (entry.get("tags") or [])
                            ),
                        }
                        for entry in feedparser.parse(response.content).entries
                    ]
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
                continue

            for entry in entries:
                title = entry["title"]
                summary = entry["summary"]
                link = entry["link"]
                if not link:
                    skipped_count += 1
                    continue

                published_dt = entry["published_dt"]
                if published_dt and published_dt < cutoff:
                    continue

                tags_text = entry["tags_text"]
                text_blob = f"{title} {summary} {tags_text}".strip()
                required_matches = (
                    keyword_matches(text_blob, required_kws)
                    if (required_kws and not source.local)
                    else None
                )
                regular_matches = keyword_matches(text_blob, regular_kws)
                if required_kws and not source.local and not required_matches:
                    continue
                if not regular_matches:
                    continue
                matches = (required_matches or []) + regular_matches

                _, created = PressReviewArticle.objects.get_or_create(
                    link=link,
                    defaults={
                        "source": source,
                        "title": title or "(ohne Titel)",
                        "summary": summary,
                        "published_date": published_dt,
                        "matched_keywords": ", ".join(sorted(set(matches))),
                    },
                )
                if created:
                    new_count += 1
                else:
                    skipped_count += 1

            source.last_fetched_at = django_timezone.now()
            source.save(update_fields=["last_fetched_at"])

        pruned = self.prune_stale_articles()["deleted_articles"]

        run_at = django_timezone.now()
        PressReviewHarvestLog.objects.create(
            run_date=run_at,
            sources_checked=len(sources),
            articles_new=new_count,
            articles_skipped=skipped_count,
            errors=json.dumps(errors) if errors else None,
        )

        result = {
            "run_at": run_at.isoformat(timespec="seconds"),
            "sources_checked": len(sources),
            "articles_new": new_count,
            "articles_skipped": skipped_count,
            "articles_pruned": pruned,
            "errors": errors,
        }
        self.logger.info(
            "Harvest complete: sources=%s new=%s skipped=%s pruned=%s errors=%s",
            result["sources_checked"], result["articles_new"],
            result["articles_skipped"], pruned, len(errors),
        )
        return result

    def prune_stale_articles(
        self, retention_days: Optional[int] = None, dry_run: bool = False
    ) -> Dict[str, object]:
        """Delete harvested articles older than the retention window.

        Bounds table growth at the source: without it articles accumulate forever, and
        a user lowering their relevance threshold could pull months of backlog into one
        digest. Cutoff is on `harvested_date` — always set, unlike `published_date`.

        Per-user scores cascade-delete with their article. That is intended: scores are
        derived data, cheap to recompute, and meaningless once the article is gone.
        """
        if retention_days is None:
            retention_days = settings.PRESSREVIEW_ARTICLE_RETENTION_DAYS

        if retention_days <= 0:
            self.logger.info("Article pruning disabled (retention_days=%s).", retention_days)
            return {
                "enabled": False,
                "retention_days": retention_days,
                "deleted_articles": 0,
                "deleted_scores": 0,
            }

        cutoff = django_timezone.now() - timedelta(days=retention_days)
        stale = PressReviewArticle.objects.filter(harvested_date__lt=cutoff)
        article_count = stale.count()
        score_count = UserPressReviewArticleScore.objects.filter(article__in=stale).count()

        if article_count and not dry_run:
            stale.delete()

        result = {
            "enabled": True,
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(timespec="seconds"),
            "deleted_articles": 0 if dry_run else article_count,
            "deleted_scores": 0 if dry_run else score_count,
            "would_delete_articles": article_count,
            "would_delete_scores": score_count,
            "dry_run": dry_run,
        }
        self.logger.info(
            "Article pruning %s: %s article(s) and %s score(s) older than %s day(s).",
            "would remove" if dry_run else "removed",
            article_count, score_count, retention_days,
        )
        return result


DEFAULT_SYSTEM_PROMPT = (
    "You are a relevance judge for a press review digest. "
    "You rate articles on how relevant they are to the reader's topics of interest. "
    "Articles and topics are often in German; always write the reason in English "
    "regardless of the language of the article or the topics. "
    "Respond only with a valid JSON object."
)

USER_PROMPT = """Rate the relevance of this article on a scale from 1 to 10.

Title: {title}
Summary: {summary}
Matched keywords: {keywords}
Reader's topics of interest: {topics}

Scoring guide:
- 9-10: Directly about the reader's topics or major local decisions
- 7-8: Clearly relevant to the reader
- 5-6: Loosely related, mentioned in passing
- 1-4: Not relevant

Respond with JSON only:
{{"score": <integer 1-10>, "reason": "<one short sentence, in English>"}}"""


def _parse_response(text: str) -> Tuple[int, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {text!r}")
    data = json.loads(match.group())
    score = int(data["score"])
    if not 1 <= score <= 10:
        raise ValueError(f"Score out of range: {score}")
    return score, str(data["reason"])


class PressReviewRelevanceService(ETLBaseService):
    """Scores harvested articles for relevance against each user's press review keywords."""

    def __init__(self, model: Optional[str] = None):
        super().__init__("PressReviewRelevanceService")
        # Not DEFAULT_AI_MODEL: that drives story generation, where a reasoning model
        # earns its cost. Relevance scoring is short-text classification.
        self.ai_model = model or getattr(
            settings, "PRESSREVIEW_AI_MODEL", "claude-haiku-4-5"
        )

    def _is_anthropic_model(self) -> bool:
        return (self.ai_model or "").startswith("claude-")

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        # Reasoning models (e.g. deepseek-v4-pro/flash) spend a variable, sometimes
        # large share of the completion budget on hidden reasoning tokens before
        # emitting the JSON answer — 256 tokens (enough for non-reasoning models)
        # leaves them no room and the response comes back truncated/empty. See
        # StoryProcessor's title generation for the same issue and fix.
        max_tokens = 1024 if (self.ai_model or "").startswith("deepseek") else 256

        if self._is_anthropic_model():
            api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=self.ai_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        elif (self.ai_model or "").startswith("deepseek"):
            api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        else:
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=self.ai_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    def rate_user(self, user, limit: Optional[int] = None) -> Dict[str, object]:
        """Score articles that have no score yet for this user.

        Scores every candidate article regardless of the user's relevance threshold —
        the threshold is applied later, at display and send time. That is what lets a
        user lower it and immediately see older articles without any new LLM calls.

        `limit` caps how many are scored in one call (newest first) so a web request
        can stay responsive; anything left unscored is picked up by the next scheduled
        run, which looks for exactly that.
        """
        topics = ", ".join(user.press_review_keywords.values_list("keyword", flat=True))
        if not topics:
            return {"rated": 0, "skipped": 0, "remaining": 0, "errors": []}

        already_scored_ids = UserPressReviewArticleScore.objects.filter(
            user=user
        ).values_list("article_id", flat=True)
        articles = PressReviewArticle.objects.exclude(id__in=already_scored_ids)
        # An empty source selection means "all active sources".
        selected_source_ids = list(user.press_review_sources.values_list("id", flat=True))
        if selected_source_ids:
            articles = articles.filter(source_id__in=selected_source_ids)

        articles = articles.order_by("-published_date", "-harvested_date")
        candidate_count = articles.count()
        if limit is not None:
            articles = articles[:limit]

        rated = 0
        skipped = 0
        errors: List[str] = []

        for article in articles:
            prompt = USER_PROMPT.format(
                title=article.title or "",
                summary=article.summary or "",
                keywords=article.matched_keywords or "",
                topics=topics,
            )
            try:
                text = self._call_llm(DEFAULT_SYSTEM_PROMPT, prompt)
                score, reason = _parse_response(text)
                UserPressReviewArticleScore.objects.update_or_create(
                    user=user,
                    article=article,
                    defaults={"score": score, "reason": reason},
                )
                rated += 1
            except Exception as exc:
                title_short = (article.title or "")[:40]
                errors.append(f"[{user.email}] Article {article.id} ({title_short}...): {exc}")
                skipped += 1

        return {
            "rated": rated,
            "skipped": skipped,
            "remaining": max(0, candidate_count - rated - skipped),
            "errors": errors,
        }

    def score_articles_preview(self, topics: str, articles) -> List[Dict[str, object]]:
        """Score articles against ad-hoc topics WITHOUT persisting the results.

        Deliberately does not touch UserPressReviewArticleScore: exploring a topic set
        must not change the stored scores that drive the user's email digest. The cost
        is one LLM call per article per preview, so callers must bound `articles`.
        """
        previewed: List[Dict[str, object]] = []
        for article in articles:
            prompt = USER_PROMPT.format(
                title=article.title or "",
                summary=article.summary or "",
                keywords=article.matched_keywords or "",
                topics=topics,
            )
            try:
                text = self._call_llm(DEFAULT_SYSTEM_PROMPT, prompt)
                score, reason = _parse_response(text)
            except Exception as exc:
                self.logger.warning(
                    "Preview scoring failed for article %s: %s", article.id, exc
                )
                continue
            previewed.append({"article": article, "score": score, "reason": reason})
        return previewed

    def rescore_user(self, user, limit: Optional[int] = None) -> Dict[str, object]:
        """Discard this user's scores and judge their articles against current topics.

        Needed because `rate_user` only scores articles that have no score yet, so
        editing topics would otherwise leave existing articles judged against the old
        ones. Clearing first makes every article a candidate again.
        """
        if limit is None:
            limit = settings.PRESSREVIEW_RESCORE_MAX_ARTICLES

        cleared, _ = UserPressReviewArticleScore.objects.filter(user=user).delete()
        result = self.rate_user(user, limit=limit)
        result["cleared"] = cleared
        self.logger.info(
            "Rescored press review for %s: cleared=%s rated=%s remaining=%s",
            user.email, cleared, result["rated"], result["remaining"],
        )
        return result

    def rate_all_users(self) -> Dict[str, object]:
        User = get_user_model()
        # Skip users opted out of the digest entirely — scoring them burns LLM calls
        # on articles that would never be sent.
        users = (
            User.objects.filter(is_active=True, press_review_keywords__isnull=False)
            .exclude(press_review_frequency=User.PRESS_REVIEW_FREQUENCY_NONE)
            .distinct()
        )

        total_rated = 0
        total_skipped = 0
        errors: List[str] = []

        for user in users:
            user_result = self.rate_user(user)
            total_rated += user_result["rated"]
            total_skipped += user_result["skipped"]
            errors.extend(user_result["errors"])

        result = {
            "rated": total_rated,
            "skipped": total_skipped,
            "default_threshold": settings.PRESSREVIEW_RELEVANCE_THRESHOLD,
            "model": self.ai_model,
            "errors": errors,
        }
        self.logger.info(
            "Relevance rating complete: rated=%s skipped=%s model=%s",
            total_rated, total_skipped, self.ai_model,
        )
        return result


class PressReviewMailer(ETLBaseService):
    """Sends the press review digest — standalone, parallel to EmailService's story digest."""

    def __init__(self):
        super().__init__("PressReviewMailer")
        self.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")

    def _render_digest(self, articles: List[Dict[str, str]], weekly: bool = False) -> str:
        lines = [
            "Hello,",
            "",
            "Here is your press review for the past week:" if weekly
            else "Here is your press review for today:",
            "",
        ]
        for art in articles:
            lines.append(f"**{art['title']}** ({art['source']})")
            if art.get("summary"):
                lines.append(art["summary"])
            lines.append(f"[Read the full article]({art['url']})")
            lines += ["", ""]
        lines += ["Best regards,", "your **O**pen **D**ata **I**nsights Team"]
        return "\n".join(lines)

    def send_digests_for_date(self, send_date=None, frequency=None) -> Dict[str, object]:
        """Send digests to users on the given cadence ('daily' or 'weekly').

        Frequency is a single per-user choice, so the unsent `digest_sent` flag alone
        determines what goes out: a weekly user simply accumulates unsent scores for a
        week before their run picks them up. No date-window filtering is needed, and an
        article can never be delivered twice.
        """
        User = get_user_model()
        redirect_recipients = getattr(settings, "EMAIL_REDIRECT_TO", None)
        frequency = frequency or User.PRESS_REVIEW_FREQUENCY_DAILY
        weekly = frequency == User.PRESS_REVIEW_FREQUENCY_WEEKLY
        max_items = settings.PRESSREVIEW_DIGEST_MAX_ITEMS

        total_sent = 0
        total_articles = 0
        total_held_back = 0
        errors: List[str] = []

        users = (
            User.objects.filter(is_active=True, press_review_frequency=frequency)
            .order_by("id")
        )
        for user in users:
            score_rows = (
                UserPressReviewArticleScore.objects.filter(
                    user=user, score__gte=user.press_review_threshold, digest_sent=False
                )
                .select_related("article", "article__source")
                .order_by("article__published_date")
            )
            # Re-apply the source selection: it may have been narrowed after scoring.
            selected_source_ids = list(user.press_review_sources.values_list("id", flat=True))
            if selected_source_ids:
                score_rows = score_rows.filter(article__source_id__in=selected_source_ids)

            eligible_count = score_rows.count()
            if not eligible_count:
                continue

            # Articles are never pruned, so lowering a threshold can make a large
            # backlog eligible at once. Send the highest-scoring slice; the rest stays
            # unsent and goes out on subsequent runs rather than being dropped.
            held_back = max(0, eligible_count - max_items)
            if held_back:
                keep_ids = list(
                    score_rows.order_by("-score", "-article__published_date")
                    .values_list("id", flat=True)[:max_items]
                )
                score_rows = score_rows.filter(id__in=keep_ids)
                total_held_back += held_back
                self.logger.info(
                    "Capping digest for %s at %s of %s eligible articles; %s held back "
                    "for the next run.",
                    user.email, max_items, eligible_count, held_back,
                )

            articles = [
                {
                    "title": row.article.title,
                    "summary": row.article.summary or "",
                    "url": row.article.link,
                    "source": row.article.source.name,
                }
                for row in score_rows
            ]
            body_markdown = self._render_digest(articles, weekly=weekly)
            html_content = markdown.markdown(body_markdown)

            recipients = redirect_recipients or [user.email]
            subject_prefix = "Weekly Press Review" if weekly else "Press Review"

            try:
                email = EmailMultiAlternatives(
                    subject=f"{subject_prefix} - {send_date or django_timezone.now().date()}",
                    body=body_markdown,
                    from_email=self.from_email,
                    to=recipients,
                )
                email.attach_alternative(html_content, "text/html")
                email.send()
                score_rows.update(digest_sent=True)
                total_sent += 1
                total_articles += len(articles)
            except Exception as exc:
                errors.append(f"[{user.email}] {exc}")
                self.logger.error("Error sending press review digest to %s: %s", user.email, exc)

        result = {
            "success": not errors,
            "frequency": frequency,
            "total_sent": total_sent,
            "total_articles": total_articles,
            "total_held_back": total_held_back,
            "errors": errors,
        }
        self.logger.info(
            "Press review digest send complete: frequency=%s sent=%s articles=%s "
            "held_back=%s errors=%s",
            frequency, total_sent, total_articles, total_held_back, len(errors),
        )
        return result
