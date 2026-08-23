# Charts

Chart builders live in `reports/visualizations/plotting.py`. Each returns a plain
ECharts option dict (plus `_width`, `_height`, optional `__js_functions__`), which
`_chart_to_html()` serialises. Leaflet maps and the word cloud return HTML
directly and are listed in `NON_ECHARTS_TYPES`.

**The rendered HTML is stored** in `Graphic.content_html` at story-generation
time. Story pages render that stored string — they do not call the chart code.
Changing a builder therefore changes nothing on an existing story until the
graphic is regenerated (`regenerate_graphics`, or re-running generation).

## Types in use

`line` 80, `bar_stacked` 19, `heatmap` 14, `bar` 10, `chloropleth` 6,
`map_markers` 5, `histogram` 3, `ranking_bar` 2, `simulation` 2, `wordcloud` 1,
`radar` 1.

## Placeholders

Available in graphic SQL **and** in settings values and keys:
`:reference_period_start`, `:reference_period_end`, `:reference_period_year`,
`:reference_period_previous_year`, `:reference_period_month`,
`:reference_period_season`, `:reference_period_season_year`,
plus `:filter_value` and `:filter_expression` from the focus.

Both sides are substituted. If a settings value names something the SQL also
produces — a series group, a legend entry — use the same placeholder in both or
the setting silently stops matching the data.

## Line charts: one series per value

Use `series_by` when each row group should be its own line, styled by the group
it belongs to. Setting only `color` pivots on that column and merges every member
into a single line.

    "series_by": "year",
    "series_group": "year_group",
    "legend_order": [":reference_period_year", "≥ 2000", "< 2000"],
    "series_group_styles": {
      ":reference_period_year": {"z": 3, "color": "#1f77b4", "width": 4, "opacity": 1},
      "≥ 2000":  {"z": 2, "color": "#ff7f0e", "width": 1.5, "opacity": 0.5},
      "< 2000":  {"z": 1, "width": 1, "opacity": 0.5,
                  "gradient": ["#c8c8c8", "#4a4a4a"], "legend_color": "#7a7a7a"}
    }

- Series in a group share a `name`, because ECharts dedupes the legend by name —
  163 lines, three legend entries.
- `z` controls draw order; the current year goes on top.
- `gradient` shades members across the group's range so a mass of similar lines
  still shows a trend. `legend_color` picks the swatch, since the first member of
  a gradient is its palest.
- The legend icon is a thin `roundRect`, because ECharts' default line legend
  draws a *marker* the chart may not plot.

### Tooltips must have something to hover

`symbol: "none"` and `showSymbol: false` both remove the symbol's hit area, and an
item tooltip then never fires anywhere. Verified in a browser. Symbols are
therefore present, full size, and fully transparent — invisible but hoverable.
The legend overrides opacity so its swatches survive.

Columns named in `tooltips` that merely repeat the series key, x or y are
resolved in the browser instead of stored per point — 7 bytes a point instead of
97, which took one chart from 6.0 MB to 759 KB with identical output. Name a
genuinely extra column and it is still stored.

## Maps (`map_markers`)

Leaflet. `marker_color` names a field whose value is used directly as a CSS
colour; `color_bins` maps a numeric field onto a palette instead:

    "marker_color": "change_5y",
    "color_bins": {"thresholds": [-1.2, -0.8, -0.4, 0, 0.4, 0.8, 1.2],
                   "colors": ["#b2182b", "...", "#2166ac"]},
    "legend": true

N thresholds need N+1 colours; bins are half-open `[lower, upper)`. Invalid specs
render a visible `chart-error` rather than silently defaulting. `marker_style`
must be `circle` for colours to apply; `radius`, `weight` and `stroke` control
size — Leaflet's default 3px stroke dominates small radii.

## Sizes

Story pages inline this HTML, so chart size is page size. Largest offenders are
worth watching: "Neighbourhood Profiles" averages 168 KB per graphic across 236
graphics.
