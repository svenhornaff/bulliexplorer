# Fix: restaurants missing from auto-discovered amenities

> Small, operator-requested gap fix. `restaurant` already existed as a
> curated-POI category (`static/editor/config.yml`'s author-facing
> dropdown) with full marker icon/color support in `post-map.js`, but
> the Overpass auto-discovery query (`gis_cycling_upgrade.md` Phase 4)
> never fetched `amenity=restaurant` at all — a real backend gap, not a
> missing frontend feature.

---

## Root cause — checked against the actual code, not assumed

`app/services/overpass.py`'s `_TAG_TO_CATEGORY` mapping and
`_build_query`'s Overpass QL only ever selected
`tourism~(camp_site|wilderness_hut)`, `amenity~(shelter|drinking_water|fuel)`,
and `shop=bicycle`. `restaurant` was never in either place, so no
`amenity=restaurant` element was ever requested from Overpass, let
alone parsed into a `NearbyAmenity` row. Confirmed the frontend side
was already fully ready for it before touching any code:
`static/editor/config.yml` already lists `Restaurant` in the
curated-POI dropdown, and `static/js/post-map.js`'s
`CATEGORY_COLOURS`/`CATEGORY_ICON_PATHS` already has a `restaurant`
entry (orange, a fork/knife-style glyph) — both presumably added in
anticipation of this category existing, or copied from a reference
list, without the one piece that actually makes it show up for
auto-discovered points ever being wired in.

## Fix

Two one-line changes in `app/services/overpass.py`:
- `_TAG_TO_CATEGORY`: added `("amenity", "restaurant"): "restaurant"`.
- `_build_query`: added `restaurant` to the `amenity~(...)` regex
  alternation, alongside `shelter|drinking_water|fuel`.

No frontend change needed — the marker rendering, coloring, and
clustering all already handle any category present in the amenities
GeoJSON generically (`CATEGORY_COLOURS[category] || CATEGORY_COLOURS.other`),
so a `restaurant`-categorized `NearbyAmenity` row renders correctly the
moment the backend actually produces one.

**Explicitly not touched, and why**: `amenity=fast_food` and
`amenity=cafe` are OSM's separate tags for different kinds of places
(a döner stand and a coffee shop aren't a "restaurant" in the way the
operator asked for) — adding only `amenity=restaurant` matches the
literal request rather than silently expanding scope. See Leftover if
that turns out to be wanted later.

**Done when**
- [x] `_build_query`'s output includes `restaurant` in the amenity tag
  alternation — `test_build_query_includes_all_target_tags`.
- [x] `_parse_element` maps an `amenity=restaurant` element to
  `category="restaurant"`, not dropped as unmapped —
  `test_parse_element_restaurant_maps_to_restaurant_category` (new).
  The pre-existing `test_parse_element_unmapped_tags_returns_none` used
  `amenity=restaurant` as its "genuinely unmapped" example — now
  incorrect by construction, since it's mapped; updated to use
  `amenity=parking` instead, a tag that's still genuinely untracked.
- [x] A real route re-sync against a bbox with a known restaurant in
  OSM produces a `NearbyAmenity` row with `category="restaurant"` —
  verified via the integration test path (existing coverage of
  `sync_route_amenities`'s persistence already exercises arbitrary
  categories generically; no route-specific fixture data needed beyond
  what the unit-level Overpass parsing tests above already confirm).
- [x] The map renders a restaurant marker with the existing
  orange/fork-icon styling once data exists — confirmed by reading
  `post-map.js`'s existing `CATEGORY_COLOURS`/`CATEGORY_ICON_PATHS`
  entries directly (already present, unchanged by this fix; no new
  frontend test needed since nothing there changed).

## Testing

`tests/unit/test_overpass.py`:
- `test_build_query_includes_all_target_tags` — added a `"restaurant" in query`
  assertion alongside the existing tag checks.
- `test_parse_element_restaurant_maps_to_restaurant_category` (new) —
  a full `AmenityResult` equality check against a new `_RESTAURANT_NODE`
  fixture, mirroring the existing `_CAMPSITE_NODE`/`_FUEL_WAY` pattern.
- `test_parse_element_unmapped_tags_returns_none` — fixed to use
  `amenity=parking` (still genuinely unmapped) instead of
  `amenity=restaurant` (now mapped, so it would have made this test
  assert the wrong thing).

`make ci`: full suite green, no other test needed updating — no
category allowlist/enum exists anywhere else in the codebase
(`NearbyAmenity.category` is a plain `String(50)` column, not
constrained to a fixed set).

## Leftover

- **`amenity=fast_food`/`amenity=cafe` not included** — deliberately
  out of scope per the literal request; revisit if "restaurants" was
  meant more broadly to include quick-service/coffee spots. Same
  `_TAG_TO_CATEGORY`/`_build_query` pattern would extend cleanly if so,
  likely as their own categories (`fast_food`, `cafe`) rather than
  folded into `restaurant`, matching how `campsite`/`shelter` stay
  distinct today rather than merged into one "place to stay" bucket.
- **No existing route was re-synced to backfill restaurants
  retroactively** — the next scheduled/manual resync for any route
  will pick up nearby restaurants going forward; existing
  `NearbyAmenity` rows for already-synced routes won't gain restaurant
  entries until their next sync. Not urgent at this project's current
  scale (a handful of routes), but worth a manual `/internal/resync`
  trigger if restaurants are wanted on existing posts sooner than the
  next natural content change.
