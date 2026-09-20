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

## Phase 2b (elevated from Phase 4 — operator-confirmed top priority) — Homepage "Explore the map" 📋 researched, not implemented

A second, follow-up review reaffirmed the same repositioning and
specifically re-flagged the homepage's own large interactive map as
the highest-value item still missing. Asked directly, the operator
confirmed this is the one thing most wanted and not yet built — not a
speculative nice-to-have buried behind Phases 3-4, which is where the
original review's version of this item was previously filed (see this
doc's original Phase 4 scope and its Leftover entry, both superseded
by this section). Per the advisor consulted for this doc's own
scoping: this gets its own phase, inserted between Phase 2 and Phase 3
rather than renumbering anything (`app/routes/posts.py`, `templates/
post.html`, and `templates/home.html` all carry inline comments
referencing this doc's "Phase 1"/"Phase 2" by number; renumbering would
strand those references for no real benefit) — **this section is
research and scoping only, per explicit instruction; nothing below is
implemented yet.**

**Verified current-state evidence** (so the next pass starts from real
code, not the review's prose):
- No aggregate "all trips" GeoJSON endpoint exists. `app/routes/
  posts.py` has per-post `route_geojson`/`pois_geojson` (built inline
  in `post_detail`) and a separate `/posts/{slug}/amenities.geojson`
  route — nothing that returns every post's route/POIs in one
  response.
- No `/explore` route or page exists. Confirmed via `grep` across
  `app/routes/*.py` — the only routes are `/`, `/posts/`,
  `/posts/{slug}`, the two legal pages, and SEO/feed endpoints.
- `templates/home.html` (Phase 1, done) has a hero, the latest post's
  stat chips, and a "more rides" grid — confirmed by direct read,
  zero map presence anywhere on the page today.
- Navigation is minimal on purpose: `templates/base.html`'s nav is a
  `<details>/<summary>` menu with a single "Home" link plus footer
  legal links. The second review's "Explore / Journal" two-mode nav
  sketch is real and reasonable but is its own, smaller, separable
  decision from the map itself — not bundled into this phase (see
  Non-goals below).
- **The real, load-bearing prerequisite risk**: MapLibre currently
  initializes eagerly on trip pages (confirmed in `static/js/
  post-map.js` — no `IntersectionObserver` or any other lazy-init
  gate, the map constructor runs on page load), and this project's own
  `fix_lcp_image_and_static_cache.md` already documents an *unresolved*
  LCP/FCP regression specific to route/map pages (LCP ~10.4-10.8s vs.
  this project's own <2.5s target; FCP regressed specifically on
  MapLibre-carrying pages, with the render-blocking `maplibre-gl.css`
  named as a *plausible but not confirmed* mechanism — that doc is
  explicit about the distinction). The homepage today has a healthy
  ~1.45s FCP with zero MapLibre on it. Adding a second full MapLibre
  instance naively would risk reproducing the same regression on the
  site's single most-visited page — this is a go/no-go gate for this
  phase, not a sub-task to fit in afterward (see "Riskiest unknowns"
  below).

**Goal**: the homepage gains a section where every trip's route
appears on one interactive map, so a visitor can discover trips
geographically, not just chronologically — the second review's
"Explore the map" section in its homepage sketch, scoped to *just*
that section on the existing homepage, not a new page.

**Explicit non-goals for this phase** (each is real, each is a
separable decision, none of them block shipping the homepage map on
its own):
- A dedicated `/explore` route/page, distinct from the homepage —
  still deferred; the nav decision below resolves to a same-page
  anchor, not a new page.
- Nav simplification into "Explore" / "Journal" modes — **decided**:
  add a same-page "Explore" anchor link into `templates/base.html`'s
  header nav, placed before the dark-mode toggle. Still filed as a
  non-goal *of this phase specifically* because it's a template/nav
  change independent of the map itself and can ship on its own
  timeline; "Journal" (as a second nav mode) isn't decided or scoped
  — only the "Explore" anchor was.
- Marker clustering, vector tiles, or any dedicated spatial
  infrastructure — at 3 real posts today, a plain `FeatureCollection`
  built from the existing `Route`/`PointOfInterest` tables is more
  than sufficient; this project's own established "2 posts, don't
  build for 20 yet" principle (`buckets.md`) applies directly.
- Filtering (activity/region/duration chips from the second review's
  sketch) — already correctly gated in this doc's Phase 4 on post
  count actually growing; unchanged, not pulled forward.

**Product decisions — resolved by the operator** (recorded here per
the pattern this doc already used for the slug-field decision in
Phase 2; see also the Open questions & decisions table at the end of
this doc):
1. **Which posts appear on the map**: route+POI posts and POI-only
   posts both appear; a post with neither a route nor any POI is
   never on the map (grid-only). Ordering/sort tiers for the map's own
   post list: route+POI posts first, then POI-only posts, then
   everything else by `published_date` newest-first. The originally
   proposed "most comments/likes" top tier was dropped — no
   comments/likes/engagement-count feature exists anywhere in this
   codebase (confirmed by `grep`), and building one is explicitly out
   of scope for this phase; the sort is 3-tier, not 4.
2. **Click behavior**: navigate straight to the post the marker/route
   belongs to. No inline popup — decided against this doc's own
   recommendation (an inline popup matching the trip-page POI-popup
   pattern), operator preference for direct navigation instead.
3. **Section placement**: **above** the "more rides" grid — also
   decided against this doc's own recommendation (which favored
   below, to protect the homepage's LCP element). This needs to be
   accounted for explicitly in the load-timing spike (risk item 1
   below): a map placed above the grid is closer to the viewport on
   page load, which changes how much runway an `IntersectionObserver`
   gate actually has before the map enters view.
4. **Grid rename**: the "more rides" grid becomes **"More stories"** —
   the site's content scope is broadening beyond van/gravel trips (the
   operator named hiking and cooking as real near-term post
   categories, not hypothetical), so the heading needed to stop
   presupposing "rides." This is a small, independent template change
   that can ship on its own, ahead of the rest of this phase.

**Technical approach candidates — not yet chosen, deliberately left
open** (per the advisor's guidance: don't prematurely commit to one
before a real performance spike):
- **Data delivery**: a new `GET /trips.geojson`-style endpoint
  (mirrors the existing per-post GeoJSON pattern, cacheable, small at
  this post count) vs. serializing the aggregate directly into the
  homepage's own HTML (avoids a second request, but couples the
  homepage response size to trip count as it grows). Either is
  reasonable at 3 posts; the tradeoff should be documented when this
  is actually built, not guessed now.
- **Load timing**: `IntersectionObserver`-gated construction (defer
  `new maplibregl.Map(...)` until the section scrolls near-viewport)
  is necessary but likely *not sufficient* on its own — it defers
  construction, not necessarily the `maplibre-gl.css`/`maplibre-gl.js`
  *download*, which is what the existing trip-page regression
  implicates. A real spike needs to check whether the `<link>`/
  `<script>` tags themselves can be deferred too (e.g. the
  `media="print"` + `onload`-swap technique for the stylesheet,
  dynamically injecting the `<script src>` only when the
  `IntersectionObserver` fires) — not just the map object.
  Alternative worth spiking as a comparison: a static server-rendered
  route-overview image/poster as the initial paint, with the real
  interactive map swapped in only after the visitor scrolls to it or
  interacts — closer to the second review's own "server-render route
  preview / poster" suggestion.

**Riskiest unknowns, worth spiking before committing to an
implementation, not just listed as sub-tasks**:
1. **Whether lazy-loading actually fixes the homepage's LCP/FCP risk,
   not just the trip-page one** — the existing regression's root
   cause is still only "plausible, not confirmed" per this project's
   own LCP doc; the homepage's baseline (1.45s FCP, no MapLibre today)
   is different enough from a trip page's that this needs its own
   independent before/after measurement, not an assumption that
   whatever fixes trip pages (if anything does) also fixes this.
2. **The aggregate data contract**, specifically: how empty/malformed
   states render (zero routes, a route with no valid geometry, a post
   with POIs but no route) — undefined today, and this project's own
   "never silently drop a post's map" precedent (from Phase 1's fix)
   argues for deciding this deliberately rather than letting whatever
   the first implementation happens to do become the de facto answer.
3. **Mobile/touch and no-JS fallback behavior for a large map on the
   homepage specifically** — a full-bleed interactive map is more
   prone to scroll-trapping on touch devices than the existing
   trip-page maps (which are lower on the page, past the point a
   visitor has already committed to reading that trip); this needs an
   explicit interaction design, not an inherited default from the
   trip-page map component.

**Acceptance criteria for when this is actually implemented** (defined
now, per this doc's own established pattern, so "done when" isn't
invented after the fact):
- Real before/after Lighthouse/PageSpeed runs against the live
  homepage (same methodology as `fix_lcp_image_and_static_cache.md`'s
  own measurements) show no material regression in LCP/FCP versus the
  current ~1.45s FCP baseline — this is the go/no-go gate, checked
  *before* considering the feature shippable, not after.
- Every published post with a valid route appears on the map,
  confirmed against the real production DB (not just a mocked test
  fixture) the same way Phase 1's card-metadata change was verified.
- Unit tests for the new endpoint/serialization (if that's the chosen
  approach) and an integration test round-tripping real `Route`/
  `PointOfInterest` geometry through it, per this project's own
  PostGIS-testing rule in `AGENTS.md`.
- A real-browser mobile screenshot pass (same Playwright-with-cached-
  Chromium technique already used for Phase 1's mobile verification)
  confirming the section doesn't trap scroll or overflow on a phone-
  sized viewport.

**Recommended implementation sequence, once this phase is picked up**:
1. ~~Resolve the open product decisions above with the operator~~ —
   **done**, recorded above and in the Open questions & decisions
   table.
2. Spike the load-timing approach in isolation and measure it against
   the acceptance criteria's performance gate *before* building the
   rest — if it fails, that's new information worth its own decision
   point, not a reason to ship the feature anyway. The spike must
   specifically account for the section now sitting **above** the
   grid (decided), not below as this doc originally recommended —
   less scroll runway before the map enters view than the deferred
   recommendation assumed.
3. Only then build the data contract (endpoint or embedded, per the
   spike's findings) and the map/interaction itself.
4. Test and verify per the acceptance criteria above, live-verified
   against production the same way every other phase in this doc has
   been.

## Phase 2c (also elevated — audited against the full landing-page
mockup, not just the map band) — Homepage composition gaps 📋
researched, not implemented

Asked directly whether the landing-page design was fully considered
after Phase 2b was scoped, the honest answer was **no** — Phase 2b
only captured the mockup's "EXPLORE THE MAP" band. Auditing the rest
of the same mockup section-by-section against `templates/home.html`
and `static/theme.css` surfaced three more real, previously-unlisted
gaps. Split out into their own phase deliberately: unlike Phase 2b,
none of these carry the MapLibre/LCP performance risk, so they don't
need that phase's spike-first gate and can ship independently and
sooner. **Research and scoping only, nothing below is implemented.**

**Verified current-state evidence**:
- **Hero has no call-to-action at all.** `templates/home.html`'s
  `site-intro` block (the `page_header` override) is `<h1>` + a
  tagline paragraph, nothing else — confirmed by direct read and by
  `grep -n "post-hero-link\|cta\|Explore the journey" templates/
  home.html static/theme.css` returning only the *latest-post* card's
  own link, not a hero-level CTA. The mockup's `[ Explore the
  journeys → ]` button doesn't exist anywhere on the page.
- **The "latest journey" hero card has no map/route visual.** The
  mockup shows a two-column layout (a `MAP / ROUTE` box beside the
  title/stats/summary text); the real `post-hero` is a single stacked
  column — cover photo, then title, then summary, then stats — with
  zero map or route-line imagery anywhere on it. This is a *different,
  smaller* feature from Phase 2b's aggregate all-trips map: a single
  route's own preview, not every trip on one map.
- **"More rides" grid cards have no photo at all.** Confirmed via
  `grep -n "post-preview" static/theme.css` — no `background-image`
  or `<img>` styling exists for `.post-preview`; the cards are
  title/subtitle/date + the stat chips added in Phase 1, text-only.
  The mockup's `[photo]` + short location/activity line
  (`Dolomites` / `4 days · hiking`) has no visual counterpart today.
- Nav ("Explore"/"Journal") is the fourth mockup element that doesn't
  match reality, but it's already tracked — Phase 2b's Leftover entry
  covers it; not repeated here.

**Goal**: close the three gaps above so the homepage actually matches
the agreed landing-page composition, independently of Phase 2b's
larger aggregate-map feature.

**Scope**
- [ ] Add a real CTA to the hero (`[ Explore the journeys → ]` or
  equivalent copy) — linking to Phase 2b's future map section once it
  exists is the obvious target, but this doesn't need to wait for
  Phase 2b: it can point at `/posts/` (today's de facto "see all
  trips" destination) now and be repointed later. Trivial, no schema
  or query changes.
- [ ] Give the "latest journey" hero card an actual route-preview
  visual. **Deliberately not a live MapLibre instance** — a static,
  server-rendered route-overview image (already the exact "poster"
  technique named as one of Phase 2b's technical candidates) is the
  right fit here specifically: it's one route, doesn't need
  interactivity, and avoids adding any MapLibre weight to the
  homepage ahead of Phase 2b's own performance spike. Needs its own
  small research spike: what actually generates the static image
  (server-side rendering via a headless MapLibre/maplibre-gl-native
  render at sync time and caching the result to R2 alongside the GPX,
  vs. a simpler polyline-on-static-basemap image library) — not
  decided here.
- [ ] Add a cover-photo thumbnail to "more rides" grid cards, reusing
  `Post.cover_image` (already exists, already used by the hero card—
  no new field). Straightforward CSS/template work, no backend change
  needed for this part alone.

**Explicit non-goals**: the aggregate "Explore the map" band (Phase
2b, separately gated), nav rename (Phase 2b's Leftover), country-
flag/activity-type tags on grid cards (would need new frontmatter
fields — `country`, `activity_type` or similar — not decided or
scoped here; flagged as a possible Phase 2c follow-up, not assumed).

**Done when**: a real browser screenshot of the homepage (same
Playwright-with-cached-Chromium technique used for Phase 1's mobile
verification) shows a CTA in the hero, a route-preview visual on the
latest-journey card, and photo thumbnails on every grid card that has
a cover image — verified visually, not just by template diff, since
this phase is specifically about visual composition.

## Phase 2d (the one fully-decided item left from Phase 2b's Leftover) —
Nav simplification: "Explore" anchor ✅ done

The nav-simplification decision was already resolved in the Open
questions table (row 7: "same-page 'Explore' anchor, placed in the
header nav before the dark-mode toggle") but never carved out as its
own phase or implemented. Confirmed with the operator before starting
— no other candidate fit the 2b/2c/3a pattern (decided, small,
independent of new endpoints/schema) as cleanly.

**A real dependency surfaced while scoping this**: the anchor's
natural long-term target — Phase 2b's homepage aggregate map — doesn't
exist yet. Rather than ship a dead link or defer the whole phase on
that account, the anchor points at the homepage's existing "more
rides" grid heading instead, via a new `id="explore"` placed on the
`<h2>` element itself (not its text). Phase 2b's own decided scope
already has the aggregate map rendering directly above that same
section, so when Phase 2b ships, the anchor id can simply move up one
element rather than being redesigned from scratch — a one-line
follow-up noted in Phase 2b's own text, not a new decision.

**Implementation notes**:
- `templates/base.html`: `<a href="/#explore" class="nav-explore-link">Explore</a>`
  added to `.nav-right`, immediately before the `#theme-toggle` button
  — matches the decided placement exactly, and works identically from
  any page (not just the homepage), since `/#explore` always navigates
  home first.
- `templates/home.html`: `id="explore"` added to the `<h2
  class="post-grid-heading">` element.
- `static/theme.css`: `.nav-explore-link` reuses the same color/hover
  treatment as the existing `.nav-links a` dropdown items — visually
  it's the same style of nav text, just always visible instead of
  tucked in the mobile menu. Also added `scroll-behavior: smooth` on
  `html`, gated inside `@media (prefers-reduced-motion:
  no-preference)` — deliberately not folded into the existing
  `*,*::before,*::after { transition-duration }` reduced-motion block
  below it, since `scroll-behavior` isn't a transition/animation and
  that block wouldn't have covered it.
- "Journal" as a second nav mode was explicitly not decided or scoped
  — only the "Explore" anchor was, per the Open questions table.

**A real bug caught by an existing test, not a false positive**: the
first version of the `base.html` comment explaining this decision
literally contained the substring "post-grid" in prose, which broke
`test_home_one_post_has_no_more_rides_section`'s `"post-grid" not in
resp.text` assertion — every page now always renders that HTML
comment in its `<head>`/nav markup, 1-post homepage included. Reworded
the comment to avoid the literal class-name substring rather than
weakening the test.

**Done when**: the "Explore" link renders in the header nav, before
the dark-mode toggle, on every page (not just the homepage); clicking
it on the homepage scrolls to the existing grid heading without a
dead/missing-anchor jump; both are confirmed live via `curl` against
production post-deploy, not just template diff.

Verified live: `curl`'d both `/` and `/posts/` against production
post-deploy — the "Explore" link renders before `#theme-toggle` on
both, and `id="explore"` lands on the grid heading. `make ci` green:
461 tests passed (3 new: link placement/order, anchor-target id
presence), 96.38% coverage, lint/pyright/djlint and
bandit/detect-secrets/pip-audit all clean.

## Phase 3a (audited against the full trip-page mockup) — Trip-page
metadata + Places chips ✅ done

Asked directly whether the trip-page design was fully met, the honest
answer was **no** — same pattern as Phase 2c's landing-page audit.
Checked the review's trip-page mockup section-by-section against the
real `templates/post.html`, `templates/partials/route_stats.html`,
`app/models/post.py`, and `app/models/route.py`. Most of it is genuinely
there (title, hero photo, prose, interactive route map, elevation
profile all confirmed present by direct read); four gaps were not
previously listed anywhere in this doc.

**Verified current-state evidence**:
- **No date range or country anywhere in the data model.** `Post` has
  a single `published_date` (the date it was posted, not a trip's
  start/end), and neither `Post` nor `Route` has a `country` (or any
  location-name) field — confirmed by reading both models in full.
  The mockup's "11–13 September 2026 · Germany" line needs new fields,
  not just new template markup.
- **Activity type exists but isn't surfaced where the mockup wants
  it.** `post.tags` (free-text, already populated on real posts —
  e.g. "Black Forest, Hiking") is already rendered, but only as tag
  badges at the very bottom of the article, not as a chip in the
  stat row up top the way the mockup shows "Gravel" beside the
  distance/elevation stats. This is a placement/reuse gap, not a
  missing-field gap — cheaper to close than the other three.
- **No "trip length in days" concept.** `route.duration_minutes` is
  GPX-derived moving time (hours/minutes, confirmed in `partials/
  route_stats.html`'s own duration rendering), not a calendar-day
  span. The mockup's "3 days" has no equivalent source field today.
- **"PLACES ALONG THE WAY" chip row doesn't exist.** POIs today are
  only ever markers on the map itself (`_pois_to_geojson` in `app/
  routes/posts.py`, rendered by `post-map.js`'s category-coloured
  marker elements) — there's no standalone summary list of POI
  categories below the map, confirmed by `grep` across `templates/`
  returning nothing for "places along"/similar.

**Explicitly not new findings — already tracked elsewhere, not
repeated as gaps here**:
- Numbered photo/POI markers along the route, linked to specific
  gallery photos — covered by Phase 4's map/story-sync item ("the
  most technically ambitious item in the whole review"), unchanged.
- "THE JOURNEY" day-by-day narrative sections with a per-day map
  highlight — needs day-grouping as a content-authoring concept,
  which is what Phase 3's typed-blocks work below actually enables;
  cross-referenced, not duplicated as its own item here.

**Goal**: close the two cheapest gaps (activity-type chip placement,
Places-along-the-way summary) without waiting on Phase 3's larger
block-model rework; treat the date-range/country and trip-day-count
fields as their own smaller schema decision.

**Scope**
- [ ] Move (or duplicate) an activity-type chip into the stat row
  itself, sourced from `post.tags` as-is — no new field. **Decided**:
  the first tag in `post.tags` (comma-separated, order as authored) is
  "the" activity-type chip shown up top; the full tag list stays
  rendered at the bottom as-is, unchanged.
- [ ] Add a "Places along the way" chip row below the map, grouping
  the same POIs already loaded into `pois_geojson` by category (reuse,
  not a new data source). **Decided**: informational-only for now, no
  click-to-scroll/highlight — the interactive version stays correctly
  deferred to Phase 4's map/story-sync scope, not built piecemeal here.
- **Decided — no**: adding a `country`/date-range frontmatter field is
  explicitly *not* happening for now ("keep it simple, no
  over-engineering" — operator). The stat row keeps `published_date`
  only, no location/date-range line. This also resolves Phase 2c's
  cross-referenced row 8 (country/`activity_type` fields for grid-card
  tags) the same way: not added, for the same reason.

**Done when**: ~~a real-browser screenshot of a trip page (same
technique used for Phase 1's mobile verification) shows an
activity-type chip in the stat row and a Places-along-the-way chip row
below the map, on both real posts that have POIs.~~ **Corrected while
verifying**: only one real post (`dream-of-north`) actually has any
POIs — `feldberg-summit-loop` and `sunday-gravel-loop` both have empty
`points_of_interest: []` lists (checked directly in `content/posts/`).
The original wording presupposed 2+ POI-bearing posts that don't exist
yet. Verified instead, live against production via `curl` post-deploy:
- `dream-of-north`: activity chip shows "71°10′ N" (first tag) in the
  stat row; "Places along the way" row shows a "Viewpoint" chip,
  correctly positioned after the map/toggles and before the elevation
  chart.
- `feldberg-summit-loop`: activity chip shows "Black Forest"; Places
  row correctly absent (0 POIs).
- `sunday-gravel-loop`: activity chip shows "Gravel"; Places row
  correctly absent (0 POIs).

**Implementation notes**:
- `app.routes.posts._poi_category_chips(pois)` (new, next to the
  existing `_route_to_geojson`/`_pois_to_geojson` helpers) builds a
  deduplicated, first-occurrence-ordered list of `{category, label}`
  dicts. The humanisation rule ("gas_station" -> "Gas station", only
  the first word capitalised) deliberately mirrors `categoryLabel()`
  in `static/js/post-map.js` exactly, rather than introducing a second,
  slightly different label format — the map's own POI popups and this
  chip row now read consistently.
- The activity chip itself needed no new backend logic —
  `post.tags.split(",")[0].strip()` directly in `route_stats.html`,
  guarded on `post is defined and post.tags` so the partial still
  works from any future caller that doesn't pass `post`.
- Both additions live in `templates/partials/route_stats.html`, which
  is *only* ever included from `post.html` (confirmed by `grep` before
  touching it) — `home.html`'s hero/grid stat chips are a separate,
  inline block and were not touched.
- Places chip row reuses `.tag-badge` (existing tag-list styling) for
  each chip; only the `.poi-categories`/`.poi-categories-label`
  container classes are new CSS, in `static/theme.css`.

**A real, newly-discovered gap found while implementing — not fixed
here, filed as a Leftover**: `route_stats.html` (and therefore this
phase's whole "Places along the way" row) is only ever included when
`route` is truthy — a post with POIs but *no* route currently renders
no map, no stat chips, and no Places row at all. No real post
exercises this today (all 3 have a route), but Phase 2b's own decided
scope explicitly treats POI-only posts as real for the homepage
aggregate map — so a POI-only trip page would currently be a dead end
with nothing to show. Out of scope for this pass (Phase 3a assumed a
route-bearing post, matching current real-world coverage); tracked
below.

**Tests added**: `tests/unit/test_poi_category_chips.py` (pure-function
tests: empty list, single/duplicate/multi-word categories, dedup
ordering, falsy-category skip) plus five new cases in
`tests/unit/test_templates.py` (activity chip present/absent, Places
row present/absent, and that it renders below the map, not above).
`make ci` green: 459 tests passed, 96.38% coverage, lint/pyright/djlint
and bandit/detect-secrets/pip-audit all clean. Deployed via `make
deploy` and verified live as above.

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
- ~~**Homepage large interactive map**~~ (Phase 1's original scope,
  briefly folded into Phase 4) — **superseded by Phase 2b above**. A
  follow-up review re-flagged this specifically, the operator
  confirmed it as the top priority, and it's been researched and
  scoped into its own phase (open product decisions, technical
  approach candidates, riskiest unknowns, acceptance criteria,
  recommended sequence) rather than left as a one-line Phase 4 bullet.
  Still not implemented — that section is explicitly research/scoping
  only, per the operator's own instruction for this round.
- **POI-only trip pages currently render nothing at all.** Found while
  implementing Phase 3a: `templates/partials/route_stats.html` (stat
  chips, map, and now the Places chip row) is only ever `{% include
  %}`-d from `post.html` inside a `{% if route %}` guard — confirmed
  by reading `post.html` directly. A post with POIs but no `Route` row
  would render no map, no stats, and no Places row at all, even though
  it has real location data. No real post exercises this today (all 3
  have a route), but Phase 2b's own decided scope explicitly treats
  POI-only posts as real for the homepage aggregate map — so the first
  POI-only post authored would land on a near-blank trip page. Fixing
  this means restructuring `post.html`'s guard from `{% if route %}` to
  `{% if route or pois %}` and making every block inside
  `route_stats.html` independently conditional on what's actually
  present (it isn't today — e.g. the map itself still hard-requires
  `route_geojson`, not `pois_geojson` alone). Real, scoped work, not a
  one-line fix — revisit when Phase 2b's POI-only-post support is
  actually implemented, since that's what would make this reachable
  from real content for the first time.
- **Nav simplification ("Explore" / "Journal" two-mode nav)** —
  real and reasonable per the follow-up review, deliberately kept as
  its own separable decision from Phase 2b's homepage map (see that
  section's Non-goals) rather than assumed to require a nav change.
  Revisit once Phase 2b's product decisions are made — whether
  "Explore" becomes a same-page anchor to the new map section or a
  future dedicated page changes what, if anything, the nav needs to
  do.
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

A later session closed Phase 1's remaining open item (real-browser
mobile verification, via a cached Chromium build) and completed Phase
2 (CMS field grouping, plus the slug-field product decision asked of
and answered by the operator) — both live-verified against production.
See those phases' own "done when"/scope sections above for the full
account; not repeated here.

A follow-up external review reaffirmed the same repositioning and
re-flagged the homepage's own large interactive map as the highest-
value item still missing — the operator confirmed this directly.
**Phase 2b is the result: research and scoping only, explicitly not
implemented this round**, per the operator's own instruction. Verified
against real code first (no aggregate GeoJSON endpoint, no `/explore`
route, zero map presence on the current homepage, and — the load-
bearing risk — MapLibre initializes eagerly today with an already-
documented, unresolved LCP/FCP regression on trip pages that a naive
second map instance on the homepage could reproduce on the site's most-
visited page). Scoped with the advisor's input into: verified
current-state evidence, a goal and explicit non-goals, three open
product decisions to ask the operator, technical-approach candidates
left deliberately open pending a real performance spike, three
specific riskiest unknowns, acceptance criteria, and a recommended
implementation sequence — see that section for the full scope. No
code, tests, or config changed for this round; `make ci`/`make deploy`
not re-run since nothing runtime changed.
---

## Open questions & decisions

Every open decision surfaced across the phases above, in one place. Rows already resolved keep their answer in the User input column instead of being deleted, so the decision trail stays intact. Blank rows are genuinely blocking the next implementation pass on that item — filling them in is the fastest way to unblock this doc's Leftover list.

  

| #   | Phase               | Question / Decision                                                                                                                                                                     | Recommendation                                                                                                                                                                                                                                                     | User input                                                                                                               |
| --- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| 1   | Phase 2             | Keep the explicit, pattern-validated `slug` field, or drop it for Sveltia's bare `{{title}}` auto-slug default?                                                                         | Keep it — auto-slug only fires at entry creation, not on later title edits, so it isn't an ongoing safety net either way; URL stability matters more than a few saved keystrokes.                                                                                  | **Decided 2026-09-20: keep the explicit `slug` field.**                                                                  |
| 2   | Phase 2b            | Which posts appear on the homepage's aggregate map — routes only, or also POI-only posts with no GPX track? What renders for a post with neither?                                       | Include both route posts and POI-only posts (a place-only pin beats invisibility); exclude a post entirely only if it has neither a route nor any POIs.                                                                                                            | **Decided**: route+POI posts, then POI-only posts, then everything else by `published_date` newest-first, in the grid only (never on the map if it has neither). No comments/likes tier — that feature doesn't exist; dropped after clarifying, per Phase 2b's updated text. |
| 3   | Phase 2b            | What happens on clicking a route/marker on the aggregate map — navigate straight to the trip page, or show an inline popup (title, stats, cover thumbnail) first?                       | Inline popup with a link, matching the existing trip-page POI-popup pattern in `post-map.js` — consistent interaction model, one less click-vs-navigate inconsistency across the site.                                                                             | go to the post the marker is from                                                                                        |
| 4   | Phase 2b            | Where does "Explore the map" sit on the homepage — above or below the "more rides" grid?                                                                                                | Below the grid — keeps the existing LCP element (hero cover image) undisturbed and lets the map load only once a visitor has already scrolled past the fold.                                                                                                       | **Decided**: above the grid (against the recommendation — noted as a load-timing spike consideration in Phase 2b). Grid itself renamed **"More stories"**, since content is broadening beyond rides (hiking, cooking, etc. — confirmed real, not hypothetical). |
| 5   | Phase 2b            | Data delivery for the aggregate map — a new `GET /trips.geojson` endpoint, or embed the aggregate directly in the homepage's own HTML?                                                  | New endpoint — mirrors the existing per-post GeoJSON pattern, is independently cacheable, and doesn't couple homepage response size to trip count as it grows.                                                                                                     | new endpoint                                                                                                             |
| 6   | Phase 2b            | Load-timing approach for the map — `IntersectionObserver`-gated script/stylesheet injection, or a static server-rendered route-overview poster swapped for the live map on interaction? | Spike both and measure against the current ~1.45s FCP baseline before choosing — this is the phase's actual go/no-go gate, not a preference call.                                                                                                                  | agree with recommendation                                                                                                |
| 7   | Phase 2b / Leftover | Nav simplification into "Explore" / "Journal" — a same-page anchor link to the new map section, a dedicated future page, or no nav change at all?                                       | Same-page anchor for now — cheapest, doesn't presuppose a dedicated `/explore` page that doesn't exist yet and isn't otherwise scoped.                                                                                                                             | **Decided**: same-page "Explore" anchor, placed in the header nav before the dark-mode toggle. "Journal" as a second nav mode not decided/scoped. |
| 8   | Phase 2c            | Add `country` / `activity_type` frontmatter fields to power grid-card tags (flag/activity chips), beyond what Phase 2c itself scopes?                                                   | Defer until Phase 3a's overlapping `country`/date-range decision (row 9) is made — don't add the same field twice from two different phases.                                                                                                                       | **Decided, per row 9: no.** Same "keep it simple" answer applies to both. |
| 9   | Phase 3a            | Add `country` and a start/end date range to `Post`/`Route` frontmatter, replacing/supplementing the single `published_date`?                                                            | Yes, if trip pages should show "11–13 Sep 2026 · Germany" — but it's a real schema change (Pydantic schema + all 3 existing posts' frontmatter must update together, per `AGENTS.md`); worth confirming the appetite for that migration before scoping it further. | **Decided: no.** "Keep it simple, no over-engineering for now." Stat row keeps `published_date` only; no location/date-range line. |
| 10  | Phase 3a            | "Places along the way" chip row — purely informational, or does clicking a chip scroll to / highlight the matching map marker?                                                          | Start informational-only; the interactive version edges into Phase 4's map/story-sync scope and shouldn't be built piecemeal ahead of that phase.                                                                                                                  | agree with recommendation                                                                                                |
| 11  | Phase 3a            | Which of a post's `tags` (if several) counts as "the" activity-type chip shown in the stat row, versus the full tag list staying at the bottom of the article?                          | First tag by convention (already the de facto primary category in how tags are authored today) — avoids a new field just for this.                                                                                                                                 | **Decided**: first tag (e.g. cycling, hiking, cooking, ...) — confirms tags already span non-travel categories today. |
