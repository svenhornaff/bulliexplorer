# Fix: elevation profile chart placement — below the map, not above it

> Small, operator-requested layout fix. The elevation chart
> (`elevation_profile_chart.md`, fully built across Tiers 1-3) rendered
> above the map in `templates/partials/route_stats.html`'s source
> order; the operator wants it below instead, so the map is the first
> thing a reader sees on a post, with the chart as a supporting detail
> underneath it.

---

## Root cause — source order, not CSS

Both blocks are independently gated (`{% if route.elevation_profile %}`
for the chart, `{% if route_geojson and tiles_url %}` for the map) and
laid out as plain block-level elements in normal document flow — no
flex/grid ordering property was overriding visual order away from
source order. The chart block simply appeared first in the template
file, so it rendered first.

## Fix

Swapped the two blocks' order in `templates/partials/route_stats.html`
— map block now first, elevation chart block second. No CSS changed,
no JS changed: both blocks' internal content, gating conditions, and
IDs (`#post-map`, `#elevation-chart`) are untouched, so
`static/js/post-map.js` and `static/js/elevation-chart.js` (which
select these elements by ID, not by position) needed no changes.

**Done when**
- [x] On a post with both a route map and an elevation chart
  (`dream-of-north`, `feldberg-summit-loop`), the map renders above the
  chart in the page — verified via a live server render's HTML source
  order and confirmed in production after deploy.
- [x] A post with a chart but no map-tiles configured, or a map but no
  elevation data, still renders correctly (only the applicable block
  appears) — the two conditionals stayed independent, unchanged from
  before this fix; the "not folded together" design note from
  `elevation_profile_chart.md` Tier 1 still holds.
- [x] No regression to the amenity-toggle control, which lives inside
  the map's own `{% if route_geojson and tiles_url %}` block and had to
  move with it as a unit, not get separated from its map.

## Testing

`tests/unit/test_templates.py` — new
`test_route_stats_renders_map_before_elevation_chart` renders
`route_stats.html` directly with both a route with `elevation_profile`
and `route_geojson`/`tiles_url` present, and asserts
`route_stats.html`'s output has `#map-wrap` appearing before
`#elevation-chart` in the rendered string (`str.index()` comparison) —
a genuine regression test for source order, not just presence of both
elements.

## Leftover

- **No CSS reordering considered** — a pure source-order swap was
  sufficient and matches the operator's actual ask (chart below the
  map, not "chart visually below the map but before it in the DOM for
  some other reason"). If a future responsive-layout change ever needs
  order to differ from source order (e.g. a side-by-side desktop
  layout), revisit with an explicit `order` CSS property rather than
  another source-order swap.
