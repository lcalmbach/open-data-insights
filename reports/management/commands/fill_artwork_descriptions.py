from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from openai import OpenAI


BODY_STOP_MARKERS = (
    "Zu den Künstlern",
    "Zum Künstler",
    "Zur Künstlerin",
    "Zur Kunstlerin",
    "Literatur und Quellen",
    "Impressum",
)


@dataclass(slots=True)
class ArtworkRow:
    id_invnr: str
    ku_name: str
    werktitel: str
    standort: str
    pdf: str


@dataclass(slots=True)
class PdfContent:
    address: str
    artist: str
    location: str
    body_text: str
    full_text: str


class Command(BaseCommand):
    help = (
        "Populate opendata.ds_100214.description from linked artwork PDFs "
        "using structured AI summaries."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Generate summaries without writing them to the database.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Rewrite descriptions even when a row already has one.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Process only the first N matching rows.",
        )
        parser.add_argument(
            "--inventory-id",
            type=str,
            help="Process only one artwork row by id_invnr.",
        )
        parser.add_argument(
            "--model",
            type=str,
            default=getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o-mini"),
            help="Model name to use for the structured summary.",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "OPENAI_API_KEY", None) and not getattr(
            settings, "DEEPSEEK_API_KEY", None
        ):
            raise CommandError("No AI API key configured.")

        if not shutil_which("pdftotext"):
            raise CommandError("The 'pdftotext' command is required but not installed.")

        dry_run = bool(options.get("dry_run"))
        overwrite = bool(options.get("overwrite"))
        inventory_id = (options.get("inventory_id") or "").strip()
        limit = options.get("limit")
        model_name = options.get("model") or getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o-mini")

        rows = self._load_rows(overwrite=overwrite, inventory_id=inventory_id, limit=limit)
        if not rows:
            self.stdout.write(self.style.WARNING("No matching artwork rows found."))
            return

        client = self._get_client(model_name)
        pdf_cache: dict[str, PdfContent] = {}
        processed = 0
        updated = 0
        failed = 0

        for row in rows:
            processed += 1
            self.stdout.write(f"[{processed}/{len(rows)}] {row.id_invnr} {row.ku_name} - {row.werktitel}")
            try:
                pdf_content = pdf_cache.get(row.pdf)
                if pdf_content is None:
                    pdf_content = self._fetch_pdf_content(row.pdf)
                    pdf_cache[row.pdf] = pdf_content

                summary = self._build_summary(
                    client=client,
                    model_name=model_name,
                    row=row,
                    pdf_content=pdf_content,
                )
                formatted = self._format_description(summary)

                if dry_run:
                    preview = formatted.replace("\n", " ")[:220]
                    self.stdout.write(f"  DRY RUN: {preview}...")
                else:
                    self._update_description(row.id_invnr, formatted)
                    updated += 1
                    self.stdout.write("  updated")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.stderr.write(f"  failed: {exc}")

        message = (
            f"Processed {processed} row(s). "
            f"Updated {updated} row(s). "
            f"Failed {failed} row(s)."
        )
        if failed:
            self.stdout.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(message))

    def _load_rows(
        self,
        *,
        overwrite: bool,
        inventory_id: str,
        limit: int | None,
    ) -> list[ArtworkRow]:
        conditions = ["nullif(trim(pdf), '') is not null"]
        params: list[Any] = []

        if not overwrite:
            conditions.append("nullif(trim(description), '') is null")
        if inventory_id:
            conditions.append("id_invnr = %s")
            params.append(inventory_id)

        sql = f"""
            select id_invnr, coalesce(ku_name, ''), coalesce(werktitel, ''),
                   coalesce(standort, ''), pdf
            from opendata.ds_100214
            where {' and '.join(conditions)}
            order by id_invnr
        """
        if limit:
            sql += " limit %s"
            params.append(limit)

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [
                ArtworkRow(
                    id_invnr=row[0],
                    ku_name=row[1],
                    werktitel=row[2],
                    standort=row[3],
                    pdf=row[4],
                )
                for row in cursor.fetchall()
            ]

    def _get_client(self, model_name: str) -> OpenAI:
        if model_name == "deepseek-chat":
            return OpenAI(
                api_key=getattr(settings, "DEEPSEEK_API_KEY", None),
                base_url="https://api.deepseek.com",
            )
        return OpenAI(api_key=getattr(settings, "OPENAI_API_KEY", None))

    def _fetch_pdf_content(self, pdf_url: str) -> PdfContent:
        response = requests.get(pdf_url, timeout=(15, 90))
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(response.content)

        try:
            completed = subprocess.run(
                ["pdftotext", str(temp_path), "-"],
                capture_output=True,
                text=True,
                check=True,
            )
        finally:
            temp_path.unlink(missing_ok=True)

        full_text = self._normalize_text(completed.stdout)
        if not full_text:
            raise CommandError(f"Unable to extract text from {pdf_url}")

        return PdfContent(
            address=self._extract_section(full_text, "Adresse:", ("Künstler:",)),
            artist=self._extract_section(full_text, "Künstler:", ("Werktitel / Datierung:",)),
            location=self._extract_section(
                full_text,
                "Standort:",
                ("Entstehungsbedingungen:", "Entstehung:", "Entstehungsbedingung:"),
            ),
            body_text=self._extract_body_text(full_text),
            full_text=full_text,
        )

    def _build_summary(
        self,
        *,
        client: OpenAI,
        model_name: str,
        row: ArtworkRow,
        pdf_content: PdfContent,
    ) -> dict[str, str]:
        row_address = self._extract_address_from_location(row.standort)
        artist_mismatch = self._artists_overlap(row.ku_name, pdf_content.artist) is False
        fallback = {
            "address": row_address or pdf_content.address,
            "artist": row.ku_name or pdf_content.artist,
            "location": row.standort or pdf_content.location,
            "description": self._fallback_description(pdf_content.body_text),
        }

        if not pdf_content.body_text:
            return fallback
        if artist_mismatch:
            return {
                "address": fallback["address"],
                "artist": fallback["artist"],
                "location": fallback["location"],
                "description": self._build_mismatch_description(row=row, pdf_content=pdf_content),
            }

        prompt = self._build_prompt(row=row, pdf_content=pdf_content)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract artwork metadata and write short object descriptions. "
                        "Return JSON only with the keys address, artist, location, description. "
                        "The description must be 3 to 4 sentences, based only on the object's "
                        "descriptive section in the PDF, not on biography, bibliography, or imprint text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=500,
        )

        content = (response.choices[0].message.content or "").strip()
        parsed = self._parse_json_response(content)
        if not parsed:
            return fallback

        description = self._normalize_description(parsed.get("description") or "")
        if not description:
            description = fallback["description"]

        return {
            "address": (parsed.get("address") or "").strip() or fallback["address"],
            "artist": (parsed.get("artist") or "").strip() or fallback["artist"],
            "location": (parsed.get("location") or "").strip() or fallback["location"],
            "description": description,
        }

    def _build_prompt(self, *, row: ArtworkRow, pdf_content: PdfContent) -> str:
        return (
            "Create a structured summary for this artwork row.\n\n"
            f"Row context:\n"
            f"- inventory_id: {row.id_invnr}\n"
            f"- artist_in_row: {row.ku_name}\n"
            f"- title_in_row: {row.werktitel}\n"
            f"- location_in_row: {row.standort}\n\n"
            "Values extracted from the PDF:\n"
            f"- address_in_pdf: {pdf_content.address}\n"
            f"- artist_in_pdf: {pdf_content.artist}\n"
            f"- location_in_pdf: {pdf_content.location}\n\n"
            "Instructions:\n"
            "- If artist_in_row is present, the artist field must match it exactly.\n"
            "- If location_in_row is present, the location field must match it exactly.\n"
            "- Prefer the address from the row location when it is present; otherwise use the PDF address.\n"
            "- If the PDF covers multiple artworks or artists, use the row values to disambiguate.\n"
            "- If the linked PDF does not clearly describe this specific row's artwork, say so explicitly in the description and only summarize the site context that is actually supported by the PDF.\n"
            "- Never describe another artist's work as if it belonged to this row.\n"
            "- Keep address, artist, and location concise plain text values.\n"
            "- Write the description in English.\n"
            "- Use only the object description text, not artist biography or literature lists.\n\n"
            "Object description text from the PDF:\n"
            f"{pdf_content.body_text}"
        )

    def _format_description(self, summary: dict[str, str]) -> str:
        address = self._clean_inline(summary.get("address") or "")
        artist = self._clean_inline(summary.get("artist") or "")
        location = self._clean_inline(summary.get("location") or "")
        description = self._normalize_description(summary.get("description") or "")
        return (
            f"Address: {address}\n"
            f"Artist: {artist}\n"
            f"Location: {location}\n\n"
            f"{description}"
        ).strip()

    def _update_description(self, inventory_id: str, description: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update opendata.ds_100214
                set description = %s
                where id_invnr = %s
                """,
                [description, inventory_id],
            )

    def _extract_section(self, text: str, label: str, stop_labels: tuple[str, ...]) -> str:
        stop_pattern = "|".join(re.escape(item) for item in stop_labels)
        pattern = re.compile(
            rf"{re.escape(label)}\s*(.*?)\s*(?={stop_pattern})",
            flags=re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            return ""
        return self._clean_inline(match.group(1))

    def _extract_body_text(self, text: str) -> str:
        stop_positions = [text.find(marker) for marker in BODY_STOP_MARKERS if marker in text]
        cutoff = min(stop_positions) if stop_positions else len(text)
        head = text[:cutoff]

        photo_matches = list(re.finditer(r"(?m)^Fotos?.*$", head))
        if photo_matches:
            body = head[photo_matches[-1].end():]
        else:
            location_match = re.search(
                r"(Entstehungsbedingungen:|Entstehung:|Entstehungsbedingung:).*",
                head,
                flags=re.DOTALL,
            )
            body = head[location_match.end():] if location_match else head

        paragraphs = [
            self._clean_inline(part)
            for part in re.split(r"\n\s*\n", body)
            if self._clean_inline(part)
        ]
        if paragraphs and not re.search(r"[.!?]$", paragraphs[0]) and len(paragraphs[0].split()) <= 12:
            paragraphs = paragraphs[1:]

        return "\n\n".join(paragraphs).strip()

    def _fallback_description(self, body_text: str) -> str:
        normalized = self._clean_inline(body_text)
        if not normalized:
            return ""

        sentences = self._split_sentences(normalized)
        if len(sentences) >= 4:
            return " ".join(sentences[:4])
        if len(sentences) >= 3:
            return " ".join(sentences[:3])
        if len(sentences) >= 1:
            return " ".join(sentences)
        return normalized

    def _normalize_description(self, text: str) -> str:
        cleaned = self._clean_inline(text)
        if not cleaned:
            return ""
        sentences = self._split_sentences(cleaned)
        if len(sentences) > 4:
            return " ".join(sentences[:4])
        return " ".join(sentences) if sentences else cleaned

    def _split_sentences(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9ÄÖÜ])", text)
        return [sentence.strip() for sentence in sentences if sentence.strip()]

    def _parse_json_response(self, content: str) -> dict[str, str] | None:
        if not content:
            return None

        raw = content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict):
            return None
        return {str(key): str(value).strip() for key, value in data.items() if value is not None}

    def _extract_address_from_location(self, location: str) -> str:
        location = self._clean_inline(location)
        if not location:
            return ""

        match = re.search(r"([A-ZÄÖÜa-zäöüß./' -]+\d+[A-Za-z]?,\s*\d{4}\s+[A-ZÄÖÜa-zäöüß -]+)", location)
        if match:
            return self._clean_inline(match.group(1))
        return location

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\x0c", "\n")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _clean_inline(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _artists_overlap(self, row_artist: str, pdf_artist: str) -> bool:
        row_tokens = self._name_tokens(row_artist)
        pdf_tokens = self._name_tokens(pdf_artist)
        if not row_tokens or not pdf_tokens:
            return True
        return bool(row_tokens & pdf_tokens)

    def _name_tokens(self, value: str) -> set[str]:
        tokens = re.findall(r"[A-Za-zÀ-ÿ]+", value.lower())
        return {token for token in tokens if len(token) > 2}

    def _build_mismatch_description(self, *, row: ArtworkRow, pdf_content: PdfContent) -> str:
        site = row.standort or pdf_content.location or pdf_content.address
        pdf_artist = pdf_content.artist or "another artist"
        mentions_row_artist = row.ku_name and row.ku_name.lower() in pdf_content.full_text.lower()

        if mentions_row_artist:
            return (
                f"The linked PDF does not contain a specific description of an artwork by {row.ku_name}. "
                f"It provides site context for {site} and notes that {row.ku_name} was involved in the artistic program there. "
                f"The detailed object description in the document concerns work by {pdf_artist}, so it should not be reassigned to this row. "
                "Because of that, this record preserves only the site context supported by the linked PDF."
            )
        return (
            f"The linked PDF does not appear to describe the specific artwork recorded here for {row.ku_name}. "
            f"It instead focuses on work by {pdf_artist} at {site}. "
            "No reliable object-level description for this row can be taken from the linked document without inventing details. "
            "This summary therefore records the mismatch rather than attributing another artwork's description to this record."
        )


def shutil_which(command: str) -> str | None:
    completed = subprocess.run(
        ["bash", "-lc", f"command -v {command}"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = (completed.stdout or "").strip()
    return value or None
