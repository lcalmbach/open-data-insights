#!/usr/bin/env python3
"""Bump project version and create a changelog release entry."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

PYPROJECT_PATH = Path("pyproject.toml")
CHANGELOG_PATH = Path("CHANGELOG.md")
VERSION_RE = re.compile(r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)(")\s*$')

CHANGELOG_HEADER = """# Changelog
All notable changes to this project are documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.
"""

UNRELEASED_TEMPLATE = """## [Unreleased]
### Added
- _Nothing yet._
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bump semantic version in pyproject.toml and create a dated "
            "release entry in CHANGELOG.md."
        )
    )
    version_group = parser.add_mutually_exclusive_group(required=True)
    version_group.add_argument(
        "--bump",
        choices=("major", "minor", "patch"),
        help="SemVer part to increment.",
    )
    version_group.add_argument(
        "--set-version",
        metavar="X.Y.Z",
        help="Set an explicit version.",
    )

    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Release date in YYYY-MM-DD format (default: today).",
    )
    parser.add_argument("--added", action="append", default=[], help="Added entry.")
    parser.add_argument("--changed", action="append", default=[], help="Changed entry.")
    parser.add_argument("--fixed", action="append", default=[], help="Fixed entry.")
    parser.add_argument(
        "--notes",
        action="append",
        default=[],
        help="General notes under a Notes section.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resulting version and changelog section without writing files.",
    )
    return parser.parse_args()


def read_current_version(pyproject_text: str) -> str:
    for line in pyproject_text.splitlines():
        match = VERSION_RE.match(line)
        if match:
            return ".".join(match.group(i) for i in (2, 3, 4))
    raise RuntimeError("Could not find project version in pyproject.toml")


def bump_version(current: str, bump: str) -> str:
    major, minor, patch = (int(x) for x in current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def validate_version(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Invalid version '{version}'. Expected X.Y.Z.")


def update_pyproject_version(pyproject_text: str, new_version: str) -> str:
    lines = pyproject_text.splitlines()
    for idx, line in enumerate(lines):
        match = VERSION_RE.match(line)
        if not match:
            continue
        lines[idx] = f'{match.group(1)}{new_version}{match.group(5)}'
        return "\n".join(lines) + "\n"
    raise RuntimeError("Failed to update version in pyproject.toml")


def parse_unreleased(changelog_text: str) -> tuple[str, str, str]:
    marker = "## [Unreleased]"
    start = changelog_text.find(marker)
    if start == -1:
        raise RuntimeError("CHANGELOG.md is missing '## [Unreleased]' section")

    next_release = changelog_text.find("\n## [", start + len(marker))
    if next_release == -1:
        unreleased_block = changelog_text[start:].strip()
        prefix = changelog_text[:start].rstrip()
        suffix = ""
    else:
        unreleased_block = changelog_text[start:next_release].strip()
        prefix = changelog_text[:start].rstrip()
        suffix = changelog_text[next_release:].lstrip("\n")
    return prefix, unreleased_block, suffix


def clean_unreleased_body(unreleased_block: str) -> str:
    lines = unreleased_block.splitlines()
    body_lines = lines[1:] if lines and lines[0].startswith("## [Unreleased]") else lines

    cleaned = []
    for line in body_lines:
        stripped = line.strip()
        if stripped == "- _Nothing yet._":
            continue
        cleaned.append(line)

    # Drop empty section headings (for example "### Added" with no bullets).
    compact: list[str] = []
    i = 0
    while i < len(cleaned):
        line = cleaned[i]
        if line.startswith("### "):
            section_lines = [line]
            i += 1
            while i < len(cleaned) and not cleaned[i].startswith("### "):
                section_lines.append(cleaned[i])
                i += 1
            has_items = any(l.strip().startswith("- ") for l in section_lines[1:])
            if has_items:
                compact.extend(section_lines)
        else:
            compact.append(line)
            i += 1

    body = "\n".join(compact).strip()
    return body


def render_sections(title: str, items: list[str]) -> str:
    if not items:
        return ""
    section = [f"### {title}"]
    section.extend(f"- {item}" for item in items)
    return "\n".join(section)


def build_release_body(args: argparse.Namespace, unreleased_body: str) -> str:
    sections = []
    if unreleased_body:
        sections.append(unreleased_body)

    for title, items in (
        ("Added", args.added),
        ("Changed", args.changed),
        ("Fixed", args.fixed),
        ("Notes", args.notes),
    ):
        rendered = render_sections(title, items)
        if rendered:
            sections.append(rendered)

    if not sections:
        sections.append("### Changed\n- Maintenance release.")
    return "\n\n".join(sections)


def ensure_changelog_exists() -> None:
    if CHANGELOG_PATH.exists():
        return
    CHANGELOG_PATH.write_text(
        f"{CHANGELOG_HEADER}\n\n{UNRELEASED_TEMPLATE}\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    try:
        dt.date.fromisoformat(args.date)
    except ValueError as exc:
        print(f"Invalid --date value: {args.date}. Expected YYYY-MM-DD.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2

    if not PYPROJECT_PATH.exists():
        print("pyproject.toml not found.", file=sys.stderr)
        return 2

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    current_version = read_current_version(pyproject_text)
    new_version = args.set_version or bump_version(current_version, args.bump)

    try:
        validate_version(new_version)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    ensure_changelog_exists()
    changelog_text = CHANGELOG_PATH.read_text(encoding="utf-8")
    prefix, unreleased_block, suffix = parse_unreleased(changelog_text)
    unreleased_body = clean_unreleased_body(unreleased_block)
    release_body = build_release_body(args, unreleased_body)
    release_section = f"## [{new_version}] - {args.date}\n{release_body}"

    new_changelog = (
        f"{prefix}\n\n{UNRELEASED_TEMPLATE}\n\n{release_section}"
        + (f"\n\n{suffix}" if suffix else "\n")
    ).strip() + "\n"

    if args.dry_run:
        print(f"Current version: {current_version}")
        print(f"Next version:    {new_version}")
        print("\n--- Release section preview ---\n")
        print(release_section)
        return 0

    updated_pyproject = update_pyproject_version(pyproject_text, new_version)
    PYPROJECT_PATH.write_text(updated_pyproject, encoding="utf-8")
    CHANGELOG_PATH.write_text(new_changelog, encoding="utf-8")

    print(f"Bumped version: {current_version} -> {new_version}")
    print(f"Updated {PYPROJECT_PATH} and {CHANGELOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
