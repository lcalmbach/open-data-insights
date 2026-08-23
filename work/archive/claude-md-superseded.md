> SUPERSEDED. Replaced by /CLAUDE.md and docs/ (this file was never auto-loaded;
> Claude Code reads CLAUDE.md from the repo root). Kept for reference only.

# Open Data Insights (ODI) — Project Context

## What this project is
An automated data storytelling platform that generates multilingual stories 
from Swiss open datasets. Stories are generated in English, then translated 
to German and French. Published at open-data-insights.org.

## Tech Stack
- **Backend:** Python, Django
- **Database:** PostgreSQL (production), 
- **LLM:** DeepSeek-chat API for story generation
- **Frontend:** iommi for UI components
- **Hosting:** Ubuntu Linux server

## Project Structure
- Stories are generated from SQL queries against PostgreSQL
- Each story template has a prompt, context data query, and publication logic
- Two content types: automated data stories and curated editorial content (concepts table)
- Concepts table stores bias/fallacy articles published as a Thursday series

## Key Models
- Story — published stories with lead, title, text in EN/DE/FR
- StoryTemplate — templates with prompts and SQL queries
- Concepts — editorial content (Biases and Fallacies series)

## Story Generation Pipeline
1. SQL query retrieves aggregated context data as JSON
2. Optional web search for current context (flag_context_research)
3. LLM generates story text from prompt + context
4. Lead and title generated as summaries
5. Translated to DE and FR
6. HTML generated and saved to DB
7. Charts and figures generated separately via SQL

## Coding Conventions
- Always use Django ORM where possible
- SQL queries for analytics go in separate .sql files or as strings in views
- Keep LLM prompts in the database, not hardcoded
- Follow existing multilingual patterns for any new content

## Current Focus
- Improving story quality — leading with the most surprising finding
- SEO improvements — sitemap, Google Search Console
- Readership tracking via Django middleware
- Train delays story using DuckDB on 4 billion SBB records
- Teenage mothers demographic story

## Data Sources
- opendata.swiss API
- Basel-Stadt open data portal
- MeteoSwiss temperature data (since 1865)
- SBB train departure/arrival data (since 2018)

## Important Notes
- DeepSeek API is cheap — use it for iteration
- Production server is Ubuntu — no Windows-specific solutions
- All stories must work in EN, DE and FR
- The bias and fallacy series publishes every Thursday