# BulliExplorer Experience — from blog to map-driven travel journal

> Adopts an external senior-engineer review's core repositioning:
> *"Explore the journey, not just the post."* The strategic direction is
> sound and builds directly on what's already invested (MapLibre,
> routes, POIs, elevation, the amenity overlay) rather than requiring a
> rewrite — genuinely the right next arc for this project, not a
> different one. This doc keeps the review's own priority tiers
> (P0-P3), adds real verification against current code and Sveltia's
> actual capabilities where a claim needed checking, and defers the
> largest items into their own later phases rather than designing
> everything in one document.

---

## The repositioning, and why it fits rather than fights what exists

Today's mental model: *Home → post list → article → map somewhere
inside*. The proposed model: *Explore → Trip → Story / Route / Places /
Photos*. This isn't a new architecture — it's making the map, route,
and POI data (already real, already rendered, already the most
invested-in part of the codebase) the organizing structure instead of
a component embedded inside an article. Confirmed against the review's
own two most-checkable claims before building on either:

- **The route-line contrast gap it cites (2.2:1) is already fixed** —
  `#e87722` → `#b85c00`, shipped earlier this session specifically to
  pass WCAG 1.4.11. Good independent confirmation the instinct was
  right, even though the specific number is now stale.
- **The "your `post_blocks.py` is already halfway to typed blocks"
  claim is accurate** — its own docstring confirms it already produces
  *"an ordered list of block dicts that `post.html` loops over and
  dispatches by type."* The dispatch architecture exists; what's
  missing is authoring that list directly instead of deriving it from
  Markdown markers. Real work, but a smaller lift than it could have
  been.

**Explicitly kept from the review, not revisited**: no React/Next/
Astro migration. FastAPI + Jinja + progressive JS is the right fit for
a content-heavy personal journal, and every existing investment (SSR,
minimal client JS, no build step) stays intact under this repositioning
rather than being thrown away for it.

## Phase 0 — Verify before committing to CMS-side specifics ✅ done

Two of the review's more specific implementation suggestions depend on
Sveltia capabilities this project has been burned by assuming before
(the `media_libraries` schema and `auth_type` mismatches earlier this
project) — worth the same five-minute check this time, not adversarial,
just consistent with how every other doc here operates.

The actual vendored version is pinned and recorded in
`static/vendor/sveltia-cms.source.md`: **Sveltia CMS 0.208.0**. All
three answers below are checked against that version's real docs
(`sveltiacms.app`) and its own roadmap page, not the review's prose,
and cross-checked against the vendored bundle itself
(`static/vendor/sveltia-cms.js`) where that was the faster/more direct
check.

**Scope**
- [x] Field grouping/sections/tabs in `config.yml` — **not available**.
  Confirmed directly on Sveltia's own roadmap page
  (`sveltiacms.app/en/docs/roadmap`): "Tabbed interface for field
  groups" is listed under **TBD**, in the same bucket as "MDX support"
  and "offline support" — explicitly *not* in the v1.0 scope (expected
  late 2026), tracked at `sveltia/sveltia-cms#592`. The review's own
  hedge ("community-requested … planned after 1.0") was the correct
  read. Phase 2's field reorganization (if it proceeds — see that
  phase's own scope note below) uses plain field ordering/labels/
  `hint`s, not native sections — the fallback this Phase already
  flagged as the likely outcome.
- [x] `slug: "{{fields.slug}}"` vs. templating off `title` directly —
  **both are real, and the current config's choice is already the
  more deliberate one, not an accident**. Confirmed from Sveltia's own
  slug docs (`sveltiacms.app/en/docs/collections/entries/slugs`):
  the *actual* default with zero `slug` option set is `{{title}}`
  (auto-slugified, no field required at all — a field named `title`
  is automatically the identifier). This project's `config.yml`
  instead defines an explicit, required `slug` field with a
  `^[a-z0-9-]+$` pattern and templates `slug: "{{fields.slug}}"` off
  it — the `fields.` prefix is required specifically because `slug`
  collides with Sveltia's own predefined template tag of the same
  name (confirmed on the same docs page), not a Decap-era quirk that
  no longer applies. Net finding: auto-slug-from-title needs no new
  mechanism to exist — it's the literal zero-config default — so
  Phase 2's "auto-slug from title, with manual override preserved"
  is implementable by *removing* the explicit field rather than
  building new templating, if that phase proceeds.
- [x] Custom-widget API (`registerWidget`/`registerFieldType`) —
  **real and present in the pinned 0.208.0 bundle**, confirmed two
  ways: (1) both names appear in `static/vendor/sveltia-cms.js`
  (`registerFieldType` ×6, `registerWidget` ×3 — the latter is kept as
  a backward-compatible alias, not dead code); (2) Sveltia's own API
  docs (`sveltiacms.app/en/docs/api/field-types`) describe a complete,
  documented contract — control/preview React class components, a
  JSON-schema-validated options block, `addFile`/`pickFile` helpers for
  file-picker reuse, `isValid` for custom validation. Real caveat from
  the same docs, worth carrying into Phase 4 if it's scoped: Sveltia's
  own compatibility note says it hasn't verified every Netlify/Decap
  custom-widget example actually works unmodified, since Netlify/Decap
  itself under-documented the original API — a POI/location widget
  should be built and tested directly against 0.208.0, not assumed
  from a Decap-era tutorial.

**Done when**: each of the three has a real yes/no/partial answer,
checked against the actual vendored Sveltia version and its real docs
— not inferred from the review's prose, the same discipline that
already corrected two Sveltia assumptions this project. **Met** — all
three above are real yes/partial answers with a cited source, checked
against 0.208.0 specifically (the version actually running in
`static/vendor/`), not a generic "Sveltia CMS" assumption.

## Phase 1 (review's P0) — Homepage and trip-page restructure ✅ done (scoped, see notes)

The review's highest-priority tier, and the one with the clearest,
lowest-risk path: presentation and information architecture changes on
top of data that already exists, no new backend work.

**Reconciled against real code before building anything new** — the
first finding changed this phase's actual scope. `home.html` (shipped
in `ui_ux_refresh.md` Phase 3) *already* has a hero + "latest journey"
treatment + a journal grid, not a flat post-list — the review's own
P0 homepage ask was largely already met before this phase started.
Restructuring it again to satisfy the concept doc's prose, when the
real thing it describes already exists, would have been changing
working code to match a document instead of the other way around. The
second finding was the opposite: a real, previously-undocumented gap.

**Scope**
- [x] ~~Homepage: hero + "latest journey" feature + a large interactive
  map + a journal grid~~ — **already shipped**, verified directly
  against `templates/home.html` and `ui_ux_refresh.md`'s own record,
  not re-done. What *was* missing and is now added: the "large
  interactive map" on the homepage itself (as opposed to the trip
  page) is a genuinely new, larger scope item — explicitly deferred to
  Phase 4 alongside map/story sync, not attempted here (see that
  phase's scope and this phase's Leftover).
- [x] Trip page: promote the map, route stats, and elevation chart
  above the fold, ahead of prose. **Real gap, confirmed in code, now
  fixed.** None of the 3 real posts (`content/posts/*.md`) author an
  explicit `[[route-map]]` marker, which means every one of them was
  hitting `post.html`'s fallback path — and that fallback rendered
  the map/stats/elevation-chart block *after* the entire body-blocks
  loop, i.e. after all prose. Exactly the inverted hierarchy the review
  named, confirmed by reading the actual template logic and the actual
  post frontmatter, not assumed from the review's own LCP-based
  inference. Fixed by computing whether an explicit marker exists
  *before* the render loop and moving the fallback's `route_stats.html`
  include to render first when it doesn't — an author who does place
  `[[route-map]]` mid-body keeps that placement untouched (verified
  with a dedicated regression test), so this changes the *default* for
  the common case without taking away marker-based control for anyone
  who uses it later.
- [x] Card redesign: replace generic "post + date" cards with
  trip-relevant metadata. **Partially done, honestly scoped**: distance,
  elevation gain, and duration now render as compact stat chips on
  every "more rides" grid card that has a `Route` (`route-stats--compact`
  class, reusing the existing hero chip markup/CSS at a smaller size) —
  this data already existed on every `Route` row, so the only real work
  was extending `post_list`'s query from "the latest post's route only"
  to "every listed post's route, one `IN`-scoped query" and passing the
  resulting `post.id → Route` map to the template. **`terrain type` from
  the review's own sketch is explicitly not included** — no such column
  exists on `Route` (checked directly against `app/models/route.py`),
  and inventing one wasn't in scope for a card-metadata pass; noted in
  this doc's Leftover rather than silently dropped.
- [x] Mobile trip-page pass — the *visual* half (does the map-first
  reorder actually read well on a real small screen, not just render
  in the right DOM order). **Done, verified with a real browser**
  (Chromium via Playwright, 390×844 viewport, screenshots reviewed
  directly — see "done when" below for the full account). One
  pre-existing, out-of-scope cosmetic issue found and logged in
  Leftover, not fixed here. The *interaction*-level half (touch-target
  sizing, tapping the map toggle on an actual touch device) is a
  different kind of check and stays in Leftover/Phase 4.

**Done when**: a real trip page (Feldberg or Dream of North) reads as
map-first on both mobile and desktop, verified visually — same
reasoning as every other MapLibre-rendering phase in this project's
docs, not unit-testable. **Ordering: met and live-verified** — unlike
most other MapLibre-touching docs in this directory, this sandbox did
have production SSH access this session, so `make deploy` actually ran
(image rebuilt, `alembic upgrade head` applied, containers recreated)
and the result was checked directly against the live site with `curl`,
not left as a code-only claim:
  - `https://bulliexplorer.com/posts/feldberg-summit-loop` — the
    `route-stats` div appears at line 175 and `#post-map` at line 294
    of the served HTML, both *before* the rendered prose's own `<h1>`
    at line 320 (the post body's own Markdown `# Feldberg Summit Loop`
    heading) and its first paragraph.
  - `https://bulliexplorer.com/posts/dream-of-north` — identical shape:
    `route-stats` at line 175, `#post-map` at line 294, prose `<h1>`
    at line 320.
  - `https://bulliexplorer.com/posts/` — both "more rides" grid cards
    render a `route-stats route-stats--compact` chip row with real
    stat spans, confirming the new `IN`-scoped routes query and the
    template change both work end-to-end against the real production
    DB, not just the mocked unit-test session.
  This closes the gap every other doc in this directory has had to
  leave open ("not yet verified live — no browser access from this
  sandbox") for the *ordering* claim specifically, since `curl` against
  the real rendered HTML is a legitimate, sufficient check for DOM
  *order* (unlike WebGL rendering/clustering/theme-swap behavior, which
  genuinely needs a browser and remains unverified elsewhere in this
  project). **Visual/mobile: now also verified, with a real browser.**
  This sandbox's pip `playwright` (already a project dependency, for
  `docs/dev/playwright_e2e_smoke_tests.md`) had its expected Chromium
  revision fail to download (network-restricted), but an older cached
  Chromium build (`chromium-1208`) was already present locally and
  launched fine via an explicit `executable_path` — a real Chromium
  renderer, not an emulation shortcut. Screenshotted both live posts
  at a 390×844 (iPhone-sized) mobile viewport:
  - Both pages read exactly as intended above the fold: hero → stat
    chips (wrap cleanly into two rows at this width — distance/ascent/
    descent, then duration + route name — not truncated or overlapping)
    → map, all before the article title or a single word of prose.
  - Full-page screenshots confirm the rest of the mobile layout holds
    up too: elevation chart, the amenity/CyclOSM toggle checkboxes,
    and the prose below are all appropriately sized, nothing
    overflowing the 390px viewport.
  - One pre-existing, out-of-scope cosmetic issue spotted on
    `feldberg-summit-loop`'s hero at this viewport: the large
    background watermark text ("FELDBERG SUMMIT LOOP") visually
    overlaps the actual `<h1>` title rendered on top of it. This
    predates this phase (the hero/cover-image design is from
    `ui_ux_refresh.md`, untouched here) and is unrelated to the
    map-first restructure this phase is scoped to — flagged in
    Leftover rather than fixed under this phase's banner.
  This closes the mobile-visual half of "done when" for real — an
  actual rendered screenshot reviewed directly, not code-inference.

**Note on LCP, since this phase touches the same map-heavy pages**:
the review's own measurement (~6.2s) is in the same ballpark as this
project's own documented, still-open finding in
`fix_lcp_image_and_static_cache.md` (a genuine FCP regression on
route/map pages, plausibly the render-blocking `maplibre-gl.css`,
explicitly flagged there as investigated but not yet confirmed). This
phase should not make that worse — worth re-measuring after this
phase's changes, not just before.

## Phase 2 (review's P1/P2) — CMS field UX ✅ done (scoped, see notes)

Phase 0's findings cleared the path: no native sections/tabs available
in the pinned 0.208.0, so the field-grouping item uses
ordering/labels/`hint`s (comment banners per group, not a real
collapsible UI); auto-slug is Sveltia's literal zero-config default
(`{{title}}`) — relevant only because the operator was asked directly
whether to switch to it, and chose not to (see below).

**The one real product decision, asked directly rather than assumed**:
keep the current explicit, pattern-validated `slug` field (manual,
regex-enforced) instead of dropping it for Sveltia's bare `{{title}}`
default. Operator's call, 2026-09-20: **keep it** — editing a post's
title after publishing must not silently change its URL (Sveltia's
auto-slug only fires at entry creation, not on later title edits, so
it isn't actually an ongoing safety net either way), and URL stability
matters more here than saving a few keystrokes per post. No config
change results from this — the field stays exactly as it was,
deliberately, not by default inertia.

**Scope**
- [x] Group `config.yml` fields conceptually (Content / Trip / Places /
  Story Elements / Publishing) — done via ordering + a comment banner
  per group (no native sections in 0.208.0, per Phase 0). Order is now:
  Content (title, slug, summary, cover_image, body) → Trip (route) →
  Places (points_of_interest) → Story Elements (galleries, callouts) →
  Publishing (date, tags, draft). Regression-tested (exact field-order
  assertion in `tests/unit/test_editor.py`) and live-verified: deployed
  and fetched via `curl https://bulliexplorer.com/editor/config.yml`,
  parses as valid YAML with the groups/banners in the right place and
  the R2 `media_libraries` block still correctly appended by
  `app/routes/internal.py`'s dynamic route.
- [x] ~~Auto-slug from title, with manual override preserved~~ —
  **decided against**, per the product decision above. Not a
  technical gap; a deliberate choice, documented rather than silently
  dropped.
- [ ] Move latitude/longitude to an "Advanced" fallback under a
  primary place-search/category-picker flow for POI entry. **Not done,
  scoped out on inspection**: Sveltia's `List`/`Object` `collapsed`
  option is real (confirmed in Phase 0), but nesting `lat`/`lng` under
  a collapsed sub-object would rename the frontmatter shape
  (`points_of_interest[].lat` → `points_of_interest[].advanced.lat`)
  read by `PointOfInterestFrontmatter` (`app/models/post_schema.py`)
  and written by all 3 existing posts' `content/posts/*.md` — a real
  schema change (per this project's own AGENTS.md rule: any frontmatter
  field add/remove/rename needs the Pydantic schema *and every existing
  post* updated in the same change), not a field-ordering tweak. Left
  flat with an explicit "(manual override)" label instead —
  regression-tested (`test_config_yml_lat_lng_stay_flat_not_nested`)
  so a future pass can't silently restructure this without noticing.
  The existing category list (`campsite`, `restaurant`, `viewpoint`,
  etc.) was already reused as-is, not reinvented — already true before
  this phase, unchanged.

**Done when**: creating a new post's frontmatter requires fewer
manually-typed technical fields than today, verified by an actual
authoring pass, not just a shorter YAML file. **Partially met, honestly
scoped down**: the field count is unchanged (the two items that would
have reduced it — auto-slug and the lat/lng advanced-toggle — were
each decided against or scoped out above, for reasons specific to this
project rather than effort). What *is* met: the CMS now visibly reads
as five conceptual groups instead of one flat list, live-verified
against the real deployed `/editor/config.yml` — the actual, narrower
claim this phase's title ("CMS field UX") supports, not the broader
"fewer fields" framing the original review sketch implied.

## Phase 3 (review's P1) — Typed content blocks ⏸️ not started this pass

The real architectural evolution, building directly on the confirmed
"already halfway there" foundation. Not attempted this pass —
genuinely the largest single item pulled forward from the review, and
this session's own scoping decision (see the advisor consultation this
doc's Phase 0/1 work was checked against) was to land a smaller,
fully-verified slice rather than a partial extension of
`post_blocks.py`'s data model that couldn't also get its own real
authoring-pass verification in the same change. Still next in line
after Phase 2, unchanged from the original plan.

**Scope**
- [ ] Extend `post_blocks.py`'s block-dict model so blocks can be
  authored directly (as structured frontmatter/YAML) instead of solely
  derived from `[[marker]]` parsing — Markdown stays as the format
  *inside* prose blocks, per the review's own framing, not replaced
  wholesale.
- [ ] Existing marker-based posts keep working unchanged — this is an
  additive authoring path, not a breaking migration, matching the
  non-destructive posture every other change in this project has taken
  toward existing content.
- [ ] New block types beyond the current gallery/callout/route-map set,
  as the review sketches: `quote`, `stats`, `poi` — added incrementally,
  not all at once.

**Done when**: a new post can be authored entirely in typed blocks with
zero `[[marker]]` syntax, while every existing post continues rendering
exactly as before.

## Phase 4 (review's P2/P3) — Photo metadata, map/story sync, filtering

The longest-horizon tier — real, valuable, and explicitly sequenced
last because each depends on Phases 1-3 landing first (richer photo
layout needs the block system; map/story scroll-sync needs the
map-first trip page; filtering needs enough posts to matter, per this
project's own already-documented "2 posts, don't build for 20 yet"
principle in `buckets.md`).

**Scope, not yet phased in detail — revisit once Phases 1-3 ship**
- [ ] Photo metadata (`location`, `taken_at`, `featured`) and full-
  bleed/mosaic/filmstrip rendering styles.
- [ ] Scroll-driven map/story synchronization (photo → marker highlight,
  POI hover → marker, marker click → story section) — genuinely the
  most technically ambitious item in the whole review; worth its own
  dedicated concept doc with real MapLibre feasibility verification
  when it's actually next, not designed speculatively here.
- [ ] Lightweight filtering (activity, region, duration) — explicitly
  gated on post count actually growing past the point where filtering
  adds value, not built ahead of the content that would use it.
- [ ] Custom Sveltia POI/location widget — gated on Phase 0's
  custom-widget-API finding.

## Explicitly out of scope

- **Any React/Next/Astro migration** — the review itself argues against
  this, and it matches this project's own established architecture
  values; not revisited here or later.
- **Designing Phase 4 in full detail now** — each item there is real
  and worth doing, but sequencing them behind Phases 1-3 and giving the
  map/story-sync feature its own dedicated doc when it's actually next
  avoids designing against assumptions that Phases 1-3 will themselves
  likely change.
- **A full CMS content-model rewrite in one pass** — Phase 3 is
  additive and non-breaking by design; a wholesale migration of every
  existing post to typed blocks is not required for this to succeed and
  isn't planned.

## Leftover

- ~~**Live/mobile visual verification of the map-first reorder**~~
  (Phase 1) — **done**. Screenshotted both real posts at a 390×844
  mobile viewport with a real Chromium instance (see Phase 1's "done
  when" section above for the full account); the map-first block reads
  cleanly above the fold on both, chips wrap into two rows without
  breaking. One pre-existing, out-of-scope cosmetic issue found on the
  way (Feldberg hero title/watermark text overlap) — tracked as its
  own item below rather than fixed under this phase.
- **Feldberg Summit Loop hero: title text overlaps the background
  watermark text at mobile widths** — spotted during the mobile
  screenshot pass above, pre-existing (the hero/cover-image treatment
  is from `ui_ux_refresh.md`, not touched by this phase), out of this
  phase's scope (cosmetic hero layout, not map-first restructuring).
  Worth a dedicated small fix: either constrain the watermark text's
  width/opacity at narrow viewports, or move the `<h1>` to a position
  that doesn't overlap it on `feldberg-summit-loop`'s specific cover
  image.
- **Deeper mobile trip-page responsive/accessibility pass** (explicitly
  named in Phase 4 already, unchanged) — touch-target sizing on
  `.map-toggle-btn`/`.amenity-toggle`/`.cyclosm-toggle`, and any
  interaction-level (not just visual) mobile issues, e.g. actually
  tapping the map fullscreen toggle on a touch device. The visual
  above-the-fold read is now verified (previous item); interaction
  testing on a touch device is a different kind of check and still
  open.
- **Homepage large interactive map** (Phase 1's original scope, now
  explicitly folded into Phase 4) — the review's homepage sketch
  includes a map showing all trips, not just the current hero+grid;
  real, but needs its own MapLibre-source design (aggregating every
  route/POI across posts into one map) and belongs with the other
  map/story-sync work in Phase 4, not bolted onto this pass.
- **Phase 2 (CMS field UX)** — Phase 0's findings are in and clear the
  path (no native sections; auto-slug is Sveltia's zero-config default,
  implementable by removing the explicit `slug` field rather than
  adding templating). Concrete next steps once picked up: (1) reorder
  `config.yml`'s fields into the review's five conceptual groups using
  labels/`hint`s only, since native sections don't exist in 0.208.0;
  (2) decide whether to keep the current explicit, pattern-validated
  `slug` field (deliberate collision-safety/override control) or drop
  it for Sveltia's bare `{{title}}` default — this is a real product
  decision about whether manual slug override should stay available at
  all, not just a technical toggle, and should be asked of the
  operator rather than assumed; (3) place `latitude`/`longitude` behind
  an "Advanced" toggle for POI entry — verify Sveltia's `List`/`Object`
  field `collapsed` option (confirmed present in 0.208.0, see Phase 0)
  actually supports this shape before assuming it does.
- **Phase 3 (typed content blocks)** — unchanged from the original
  plan, next after Phase 2. `post_blocks.py`'s own docstring already
  documents the target shape; the actual extension (accepting a
  structured `blocks:` frontmatter list alongside the existing marker
  parsing) is real implementation work deliberately not started this
  pass, per this doc's own scoping.
- **Phase 4 (photo metadata, map/story sync, filtering, homepage map,
  custom POI widget)** — unchanged from the original plan; each item
  gated on the phases before it, per the doc's existing reasoning.
- **Re-measure LCP/FCP after Phase 1's reorder** — `fix_lcp_image_and_
  static_cache.md`'s open FCP-regression finding on route/map pages is
  still unconfirmed-not-fixed; this phase moved the map earlier in the
  DOM, which could plausibly interact with that render-blocking-CSS
  hypothesis in either direction. Worth a real before/after Lighthouse
  pair against production once deployed, not assumed neutral.

## Summary

Phase 0 (Sveltia capability verification) done — all three questions
answered against the actual pinned 0.208.0 bundle and its real docs,
not the review's prose: no native field-grouping/tabs (roadmap TBD,
`sveltia-cms#592`); auto-slug-from-title is Sveltia's literal
zero-config default, so this project's explicit `slug` field is a
deliberate override, not a gap; the custom-widget API
(`registerFieldType`/`registerWidget`) is real and present in the
vendored bundle.

Phase 1 (homepage/trip-page restructure) partly done, scoped down from
the review's original sketch after reconciling it against real code:
the homepage hero+grid the review asked for already shipped in
`ui_ux_refresh.md` Phase 3, so nothing was redone there. The real,
previously-undocumented gap found and fixed: none of the 3 real posts
author an explicit `[[route-map]]` marker, so all of them were hitting
`post.html`'s fallback path, which rendered the map/stats/elevation
chart *after* all prose — the inverse of "map-first." Fixed by moving
the fallback's render position ahead of the body-blocks loop, with
author-placed markers (verified via a dedicated regression test)
unaffected. Card metadata (distance/elevation gain/duration) now also
renders on "more rides" grid cards, not just the hero, via a query
change (`post_list` now fetches routes for every listed post in one
`IN`-scoped query instead of only the latest post's route — same
number of DB round trips, more coverage). Mobile-specific verification
and the homepage's own large interactive map are explicitly deferred
(see Leftover). Phases 2-4 not started this pass, each with concrete
next steps recorded above rather than left as bare unchecked boxes.

`make ci`: 447 tests passing (5 new: 3 grid-card-metadata tests plus
the map-first-ordering regression pair — see `tests/unit/test_
templates.py`), 96.41% coverage, security checks unchanged/clean. No
schema/migration changes — `post_list`'s query change and the two
template reorders are the only runtime code touched.