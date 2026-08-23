---
description: Scaffold a new insight (StoryTemplate) end to end
---

Create a new insight: $ARGUMENTS

Work through this in order, checking with me at the marked points.

1. **Data.** Find the dataset(s) in the `opendata` schema. Report row count, date
   range and the columns that matter. If nothing suitable exists, say so and stop
   rather than inventing a query.
2. **Context SQL.** Draft the query producing the JSON context for the LLM.
   Aggregate — do not hand the model raw rows. Use `:reference_period_*`
   placeholders rather than hardcoded dates.
3. **Publication logic.** Decide the reference period and direction, and the
   condition under which the story is due. State it explicitly.
4. → **Check with me before writing anything to the database.**
5. **Prompt.** Draft the story prompt. Prompts live in the database, not in code.
   Follow the tone of existing templates: neutral, no bullet lists, no emojis,
   suitable for an interested lay reader.
6. **Charts.** Propose graphics with their settings; see `docs/charts.md`. Verify
   each renders against real data before saving.
7. **Dry run.** Generate the story for a specific date with `--force` and show me
   the output before anything is scheduled or emailed.

Do not subscribe users or enable the template until I say so.
