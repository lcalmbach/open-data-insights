---
description: Render a graphic in a real browser and check it visually
---

Verify graphic $ARGUMENTS renders and behaves correctly.

Reasoning about ECharts documentation has produced wrong answers here more than
once. Check it in a browser.

1. Regenerate the chart HTML from real data, through the processor so that
   placeholders resolve the way they do in production.
2. Write a standalone page — the stored `content_html` plus the ECharts CDN
   script — to the scratchpad.
3. Drive it with Playwright (Chrome is installed):
   - assert there are no console or page errors
   - read back the live option with `echarts.getInstanceByDom(...).getOption()`
     and check series count, styles and legend
   - **sweep the plot area with the mouse** and confirm tooltips actually appear,
     reporting how many probe positions produced one
   - take a screenshot and *look at it*
4. Report the rendered size in characters. Story pages inline this HTML.
5. Confirm other charts of the same type still render unchanged.

If the stored HTML is stale, regenerate it — pages do not call the chart code.
