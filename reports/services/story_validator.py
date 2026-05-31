"""
Story validation service.

Tier 1 — heuristic checks (always run, free):
  - Content too short
  - "No data" phrases that indicate the LLM gave up
  - Empty context data

Tier 2 — LLM judge (optional per template, controlled by run_validation_tier2):
  - Sends context_values + story content to the configured LLM
  - Asks for a faithfulness and completeness score (1–5 each)
  - Fails the story if either score < 3
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Phrases that indicate the LLM couldn't find or use the data
_NO_DATA_PATTERNS = re.compile(
    r"""(
        no\s+data\s+(available|found|provided|exist)|
        could\s+not\s+find|
        unable\s+to\s+find|
        i\s+(don'?t|do\s+not)\s+have\s+(the\s+)?(data|information|access)|
        insufficient\s+data|
        not\s+enough\s+data|
        data\s+(is\s+)?not\s+available|
        data\s+(is\s+)?unavailable|
        i\s+cannot\s+(provide|generate|write|find)|
        i\s+was\s+unable\s+to|
        no\s+information\s+(is\s+)?available|
        keine\s+daten|
        keine\s+angaben|
        kein\s+datensatz|
        keine\s+informationen
    )""",
    re.VERBOSE | re.IGNORECASE,
)

_MIN_CONTENT_LENGTH = 150

_JUDGE_PROMPT = """You are a strict fact-checker for data journalism.

A data story was generated from the JSON context below. Evaluate it on two criteria:

1. **Faithfulness** (1–5): Do all factual claims in the story match the numbers in the context?
   - 5 = every claim is directly supported
   - 3 = minor extrapolation but nothing contradictory
   - 1 = invents facts or contradicts the data

2. **Completeness** (1–5): Does the story contain substantive insight?
   - 5 = clear, specific insight about the data
   - 3 = vague but not empty
   - 1 = says "no data found" or is essentially empty

Return ONLY valid JSON in this exact format (no explanation, no markdown):
{{"faithfulness": <int>, "completeness": <int>, "issues": "<one sentence or empty string>"}}

CONTEXT DATA:
{context}

STORY:
{story}"""


@dataclass
class ValidationResult:
    passed: bool
    notes: str = ""


class StoryValidator:
    """Validates a generated story and sets validation_status / validation_notes."""

    def validate(self, story, ai_client) -> ValidationResult:
        """
        Run tier 1 then (if the template allows) tier 2.
        Updates story.validation_status and story.validation_notes in memory —
        the caller must save() the story.
        """
        from reports.models.story import Story

        result = self._tier1(story)
        if not result.passed:
            story.validation_status = Story.VALIDATION_FAILED
            story.validation_notes = result.notes
            return result

        run_tier2 = getattr(
            getattr(getattr(story, "templatefocus", None), "story_template", None),
            "run_validation_tier2",
            False,
        )
        if run_tier2 and ai_client is not None:
            result = self._tier2(story, ai_client)

        story.validation_status = (
            Story.VALIDATION_PASSED if result.passed else Story.VALIDATION_FAILED
        )
        story.validation_notes = result.notes or None
        return result

    # ── Tier 1 ────────────────────────────────────────────────────────────────

    def _tier1(self, story) -> ValidationResult:
        content = (story.content or "").strip()

        if len(content) < _MIN_CONTENT_LENGTH:
            return ValidationResult(
                passed=False,
                notes=f"Content too short ({len(content)} chars, minimum {_MIN_CONTENT_LENGTH}).",
            )

        match = _NO_DATA_PATTERNS.search(content)
        if match:
            return ValidationResult(
                passed=False,
                notes=f'Story indicates missing data: "{match.group(0).strip()}".',
            )

        if self._context_is_empty(story):
            return ValidationResult(
                passed=False,
                notes="Context data is empty or contains no rows.",
            )

        return ValidationResult(passed=True)

    def _context_is_empty(self, story) -> bool:
        cv = story.context_values
        if not cv:
            return False  # no context = non-data story, don't penalise
        if isinstance(cv, str):
            try:
                cv = json.loads(cv)
            except Exception:
                return False
        if not isinstance(cv, dict):
            return False
        context_data = cv.get("context_data", {})
        if not context_data:
            return True
        # Check that at least one key has a non-empty data list
        for item in context_data.values():
            if isinstance(item, dict):
                data = item.get("data")
                if data:
                    return False
        return True

    # ── Tier 2 ────────────────────────────────────────────────────────────────

    def _tier2(self, story, ai_client) -> ValidationResult:
        try:
            context_str = self._summarise_context(story)
            prompt = _JUDGE_PROMPT.format(
                context=context_str,
                story=(story.content or "")[:4000],
            )
            raw = self._call_judge(ai_client, story, prompt)
            return self._parse_judge_response(raw)
        except Exception as exc:
            logger.warning("Tier-2 validation failed with exception: %s", exc, exc_info=True)
            # Don't block publishing if the judge itself errors
            return ValidationResult(passed=True, notes=f"Tier-2 check skipped: {exc}")

    def _summarise_context(self, story) -> str:
        cv = story.context_values
        if not cv:
            return "(no context data)"
        if isinstance(cv, str):
            try:
                cv = json.loads(cv)
            except Exception:
                return str(cv)[:2000]
        return json.dumps(cv, ensure_ascii=False)[:3000]

    def _call_judge(self, ai_client, story, prompt: str) -> str:
        import anthropic
        from openai import OpenAI

        model = getattr(story, "ai_model", None) or "gpt-4o-mini"

        if isinstance(ai_client, anthropic.Anthropic):
            response = ai_client.messages.create(
                model=model,
                max_tokens=256,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            return (response.content[0].text or "").strip()
        else:
            response = ai_client.chat.completions.create(
                model=model,
                max_tokens=256,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            return (response.choices[0].message.content or "").strip()

    def _parse_judge_response(self, raw: str) -> ValidationResult:
        try:
            # Strip markdown code fences if present
            cleaned = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
            data = json.loads(cleaned)
            faithfulness = int(data.get("faithfulness", 5))
            completeness = int(data.get("completeness", 5))
            issues = (data.get("issues") or "").strip()

            if faithfulness < 3 or completeness < 3:
                parts = [f"faithfulness={faithfulness}/5, completeness={completeness}/5"]
                if issues:
                    parts.append(issues)
                return ValidationResult(passed=False, notes=" — ".join(parts))

            notes = f"faithfulness={faithfulness}/5, completeness={completeness}/5"
            if issues:
                notes += f" — {issues}"
            return ValidationResult(passed=True, notes=notes)
        except Exception as exc:
            logger.warning("Could not parse LLM judge response %r: %s", raw, exc)
            return ValidationResult(passed=True, notes=f"Judge response unparseable: {raw[:200]}")
