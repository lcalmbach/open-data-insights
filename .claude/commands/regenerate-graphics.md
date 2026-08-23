---
description: Regenerate stored chart HTML after a chart or settings change
---

Regenerate the stored graphics for $ARGUMENTS.

Story pages render `Graphic.content_html` from the database, so a code or
settings change has no effect until this runs.

For each affected `Graphic`, go through the processor rather than calling
`generate_chart` directly, so SQL and settings placeholders resolve exactly as
they do in production:

    p = StoryProcessor(published_date=g.story.published_date, story=g.story)
    sql = p._replace_sql_expressions(gt.sql_command)
    settings = p._replace_placeholders_deep(dict(gt.settings))

Refuse to save anything containing `chart-error`, report the size before and
after, and verify one of them in a browser (`/verify-chart`).

Remember production has its own database: regenerate there too if the change
should be visible on the live site.
