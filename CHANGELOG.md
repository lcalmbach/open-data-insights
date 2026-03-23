# Changelog
All notable changes to this project are documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]
### Added
- _Nothing yet._


## [0.1.6] - 2026-03-23
### Added
- Add StoryImage image_identifier_key support

### Changed
- Render story leads as markdown and simplify story image source handling

### Fixed
- Truncate generated story titles to the model field length

## [0.1.5] - 2026-03-20
### Added
- Add management commands for commodity price imports and market event seeding

### Changed
- Include focus subject instructions in story generation prompts

### Fixed
- Render null table values as blank cells instead of literal None

## [0.1.4] - 2026-03-13
### Changed
- Add configurable line-chart reference lines with labels

### Fixed
- Resolve SQL-backed reference line positions before rendering charts

## [0.1.3] - 2026-03-11
### Notes
- Deploy UI updates for dataset preview and formatting

## [0.1.2] - 2026-03-11
### Notes
- Production deployment

## [0.1.1] - 2026-03-11
### Notes
- Set up release automation workflow

## [0.1.0] - 2026-03-11
### Added
- Migrated dependency management from `pip`/`requirements.txt` to `uv` with `pyproject.toml` and `uv.lock`.
