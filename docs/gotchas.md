# Gotchas

Things that already cost time. Each one looked like something else first.

## Stored HTML, not live rendering

Story pages render `Graphic.content_html` and `StoryTable.data` from the
database. A code fix changes nothing on an existing story until the graphic is
regenerated. If a chart change "does not work", check the stored HTML before
debugging the code.

## Settings live in the database

Template, graphic and press review configuration is data, not code. Local and
production diverge freely, and a deploy does not carry them. Before concluding a
change had no effect on production, confirm the object exists there at all.

## ECharts tooltips need a hit area

`symbol: "none"` and `showSymbol: false` both remove the symbol, and an item
tooltip then never fires anywhere on the plot. Transparent full-size symbols are
hoverable; 1px symbols work too but make lines look dotted.

## Legends read `itemStyle`

Series that only set `lineStyle` get legend swatches from the default palette —
colours that appear nowhere on the chart. And ECharts' default line legend icon
includes a marker even when the series plots none.

## Decimal is not JSON serialisable

psycopg returns numeric columns as `Decimal`. Passing them into a chart option
renders a visible `chart-error`. Coerce before serialising.

## Publisher feeds die silently

CNN's RSS endpoints return HTTP 200 with valid XML and have not updated in two to
three years. **Validate freshness, not status codes.** Their Google News sitemap
(`/sitemap/news.xml`) was 30 minutes old — publishers maintain sitemaps because
Google News depends on them, and nothing obliges them to maintain RSS.

Some publishers (Blick, BZ Basel) return 403 from Heroku while working locally —
datacentre IP or user-agent blocking. Production-only failures.

## Language prefix redirects

`LanguagePrefixMiddleware` redirects unprefixed URLs to `/en/...`. In tests use
`follow=True` for GETs; for POSTs the redirect discards the body, so target the
prefixed URL.

## Two keyword layers in press review

Global keywords decide what is *collected*; a user's topics decide how collected
articles are *ranked*. A personal topic can only surface articles the harvest
already stored — which is why user topics are unioned into the harvest filter.

## Empty means all

An empty press review source selection means *all active sources*. Ticking every
box stores that specific list and therefore excludes anything added later —
unticking everything gives you more, not less.

## Long jobs and deploys share a slug

Deploying during a long dataset sync kills it. A 5 GB download took 57 minutes.

## Sequences and explicit ids

Inserting rows with explicit primary keys does not advance a Postgres sequence,
and sequences are not rolled back between tests. Collisions appear only in
full-suite runs, never when running a test alone.
