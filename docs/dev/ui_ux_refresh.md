# BulliExplorer — UI/UX Refresh for 2026

> Concept doc for bucket #2 from `buckets.md`. All blocking decisions in
> §9 are signed off; implementation (Phase 1) has not started yet — this
> is the plan, written before any code changes, the same way
> `maps_gis.md` was written before bucket #1's implementation. Nothing
> below is shipped.

---

## 1. Status and relationship to other buckets

Bucket #1 (Maps & GIS) is done: `PointOfInterest`/`Route`, GPX parsing,
Nominatim geocoding, self-hosted PMTiles, and MapLibre rendering inside
the post body are all live, proven end-to-end on `kinzig-valley-loop`.
`maps_gis.md`'s own "explicitly out of scope" section already flagged
**dark mode** as belonging here, not there — this doc picks that up.

This doc does **not** own:

- **Bucket #3** (content discovery — tags, search, pagination)
- **Bucket #4** (SEO & syndication — sitemap, RSS, OpenGraph, JSON-LD)
- **Bucket #5** (media pipeline — image optimization, `srcset`/WebP, R2
  for uploads). Galleries below define the *markup and presentation
  contract*; actual responsive-image generation is bucket #5's job.
  Until #5 ships, galleries render with whatever image file is uploaded
  as-is.
- **Bucket #8** (performance & accessibility *audit* — Lighthouse/axe as
  independent verification). This doc sets budgets and *builds toward*
  them; #8 is the outside check that they were actually hit.

**Bucket #10's warning is taken seriously here**: 2 real posts exist.
That warning is actually two separate questions, and this doc answers
both rather than only the smaller one:

1. *If this bucket is built, how should it be scoped so it doesn't
   require content that doesn't exist?* — every phase below is scoped to
   work correctly at 0, 1, or 2 posts; no feature that only looks good
   with 20 posts ships gated behind having 20 posts.
2. *Should bucket #2 be built at all right now, versus writing more
   content on the existing Clean Blog and coming back to this later?* —
   this is the question the original text glossed over by jumping straight
   to (1). Answered directly: **yes, proceed now**, for a reason specific
   to this bucket and not a generic "UI matters" appeal — §5.1 recommends
   *retiring* Bootstrap/Clean Blog, and that swap is cheapest at the
   current 3-template, ~45-line-override size (stated in §5.1's
   rationale). Writing more content first under the current template
   only makes that later swap more expensive (more pages, more overrides,
   more visual regressions to re-check), for zero compounding benefit —
   unlike, say, bucket #5's media pipeline, where waiting for more real
   photos to exist before building it costs nothing. If the sign-off in
   §9 goes the other way — keep Bootstrap, skip the retirement — that
   cost-asymmetry argument for doing this *now* no longer holds, and
   deferring bucket #2 until there's more content to actually showcase
   becomes the more defensible call.

---

## 2. Research: what "modern blog design 2026" actually means

Split deliberately into two tiers — authoritative requirements vs. trend
inspiration — because these carry very different evidentiary weight and
conflating them was the failure mode to avoid.

### Authoritative (standards/engineering bodies — treated as requirements)

- **WCAG 2.2** (W3C) — target level AA. Concretely: focus visibility,
  target size, consistent help, no keyboard traps, semantic landmarks.
- **Core Web Vitals** (web.dev/Google) — LCP < 2.5s, CLS < 0.1,
  INP < 200ms, as lab-measured budgets (this site has too little traffic
  for reliable field CWV data — noted as a limitation, not a gap to fake).
- **MDN** — `prefers-color-scheme`, `prefers-reduced-motion`,
  `color-scheme`, CSS custom properties — the actual platform primitives
  dark mode and motion-safety are built from.

### Trend inspiration (design blogs/galleries — informative, not binding)

- Minimalism (whitespace, content-first) and editorial maximalism
  (bold typography, dense imagery) both show up in 2026 coverage —
  genuinely in tension, not a single consensus direction.
- Typography as a primary design element, not just body text styling.
- Dark mode implemented via CSS custom properties / multiple luminance
  levels, explicitly **not** pure-black inversion.
- Curated homepages (a handful of strong entries) over full-archive
  listings.
- Motion/micro-interactions trending, but every source pairs this with a
  caution against overuse (parallax, scroll-jacking) — taken as a
  warning, not encouragement.

**Resolution**: rather than chase every trend, pick one coherent design
thesis (below) and let *that* decide what to adopt, not a checklist.

---

## 3. Design thesis

**"Field journal meets modern editorial adventure storytelling."**

Concretely: the writing and the ride data (map, stats, photos) are the
content — the chrome around them should get out of the way and let
typography, photography, and the route itself carry the page. Not a
SaaS-marketing-site look, not a maximalist visual playground. Restraint,
not minimalism-as-absence — there should be real personality in
typography and color, just not noise competing with the content.

This thesis is what arbitrates every open trend tension above: dense
imagery only where a gallery genuinely has images to show; bold
typography on headings and pull-quotes, not decoration everywhere; no
motion that isn't legible feedback (hover states, theme-toggle
transition) — no parallax, no scroll-jacking, no autoplay.

---

## 4. Current-state audit

| Area | Current state |
| --- | --- |
| CSS framework | Bootstrap 5 via the "Clean Blog" template (`clean-blog.css`, 2016-era), + 45 lines of project overrides in `style.css` |
| Fonts/icons | Google Fonts (Lora, Open Sans) + Font Awesome, both loaded from CDN `<script>`/`<link>` tags |
| Navigation | Bootstrap navbar-collapse, JS-dependent hamburger on mobile |
| Homepage | Single static masthead image + flat reverse-chronological post list — same treatment whether there are 2 posts or 200 |
| Post page | Masthead → body HTML → route stats row → MapLibre map (**already renders inside the post body**, immediately after the prose — not a separate page. The gap isn't "no map in post," it's no *author control* over where in the body it lands, and no other body-level content types besides prose) |
| Dark mode | None. No `prefers-color-scheme`, no toggle |
| Image galleries | None. Only a single `cover_image` field per post |
| Theming | Hard-coded colors in `style.css` (`#e87722` orange accent, `#f8f9fa`/`#343a40` greys) — no custom-property token layer |
| Accessibility | Ad hoc — `aria-label`s exist on the map and stat icons (good precedent), but no systematic focus-state or landmark review has been done |
| Performance | Untested — no Lighthouke/CWV run exists yet (that's bucket #8's job to verify, this doc's job to not regress) |

**Correction to bucket #2's original one-line framing**: "no richer post
layout (embedded route map inside a post body)" is stale — the map is
already embedded inline. What's actually missing is (a) a vocabulary of
body-level content blocks beyond prose + the one fixed map slot, and
(b) author control over block placement/order.

---

## 5. Design system

### 5.1 Architecture decision: retire Bootstrap/Clean Blog

**This is a reversal of a stated project decision, named explicitly as
such — not a natural next increment.** `post_and_backend.md` chose
Bootstrap + Start Bootstrap's "Clean Blog" template *specifically because*
the goal at the time was "porting a design, not building one from
scratch" — the free-template-ecosystem argument was the deciding factor
over Pico/Bulma, not a technical merit call. This doc now recommends
doing the from-scratch design work that decision was explicitly trying to
avoid. That original trade-off isn't wrong in retrospect — it correctly
got a real site shipped fast with zero design effort while the backend
was the actual risk (bucket #1's territory). But the context that made
"port, don't build" the right call has changed: the backend is now
proven, and the thing genuinely missing per bucket #2's own framing is a
distinctive, dark-mode-capable identity — which "porting a 2016 template"
can no longer supply. Reversing it is a real cost (real design/CSS effort
that was avoided once already), not a free upgrade, and is called out
here as a decision to confirm, not something this doc is unilaterally
treating as settled (see §9).

**Recommendation: replace Clean Blog/Bootstrap with a small custom CSS
layer, not another round of overrides on top of it.**

Rationale:

- Only 3 templates and ~45 lines of override CSS exist today — this is
  the cheapest point in the project's life to make this switch; it only
  gets more expensive as more pages/overrides accumulate.
- A distinctive editorial identity and a *correct* dark mode (not an
  inverted-Bootstrap hack) are both meaningfully harder layered on top
  of a framework's own opinions than built from tokens up.
- No new dependency, no build step — plain CSS custom properties +
  flexbox/grid + Jinja partials satisfies "no npm, ever" exactly as well
  as Bootstrap-via-CDN does.
- Bootstrap's navbar JS also currently gates mobile nav behind JS being
  available; a semantic `<details>`/`<nav>`-based mobile menu (or a tiny
  Alpine toggle) doesn't have that dependency.

This was a **decision requiring sign-off before implementation begins**
— confirmed per §9: retire Bootstrap now.

### 5.2 Tokens (CSS custom properties)

```css
:root {
  /* Color — light, default */
  --color-bg:        #fdfcfb;
  --color-surface:    #ffffff;
  --color-surface-2:  #f4f1ec;   /* route-stats-style panels */
  --color-text:       #1f1c18;
  --color-text-muted: #5c564d;
  --color-accent:     #e87722;   /* kept — proven, matches the route line color */
  --color-border:      #e4ddd2;

  /* Typography */
  --font-serif: "Lora", Georgia, serif;      /* headings, pull-quotes */
  --font-sans:  "Source Sans 3", system-ui, sans-serif; /* body, UI chrome */
  --measure:    68ch;                         /* prose max line length */

  /* Motion */
  --transition-fast: 120ms ease;
}

[data-theme="dark"] {
  /* Multiple luminance levels, not pure black — per research above */
  --color-bg:         #16140f;
  --color-surface:    #201d17;
  --color-surface-2:  #29251d;
  --color-text:       #ece7de;
  --color-text-muted: #b4ac9d;
  --color-accent:     #f0954a;   /* lightened for AA contrast on dark bg */
  --color-border:     #3a352a;
}
```

Font choice: keep Lora (already proven for headings) but move body text
off Open Sans (via Google Fonts CDN) to a self-hostable system-ui-first
stack, revisited fully in Phase 1 — self-hosting fonts and dropping the
Font Awesome CDN script both reduce external requests, which helps LCP.

### 5.3 Component/block vocabulary (post body)

A small, fixed set of server-rendered Jinja partials — not a generic
page builder, not raw HTML from the CMS:

- `prose` — the existing rendered Markdown (default, always present)
- `figure` — single image + optional caption, used for in-body images
- `gallery` — a grid of `figure`s (2-N images), semantic `<figure>`
  elements with mandatory `alt` text (enforced at the content-schema
  level, not just convention)
- `route-map` — the existing stats-row + MapLibre block, but placeable
  via an explicit marker in the post body rather than always appended
  after all prose (falls back to "after body" if no marker is present —
  no post breaks on this change)
- `callout` — a styled aside for a tip/warning (e.g. "this pass is closed
  in winter") — small addition, cheap, real editorial value

### 5.4 Dark mode

- `prefers-color-scheme` respected by default; explicit toggle in nav
  persisted to `localStorage`, overriding the system preference.
- Applied via a tiny inline pre-paint `<script>` in `<head>` (reads
  `localStorage`, sets `data-theme` before first render) — the standard
  no-flash pattern, doesn't need a framework.
- MapLibre: the map's own tile style (`namedFlavor("light")` currently)
  needs a dark counterpart — `basemaps.js`/Protomaps ships a dark flavor;
  swap based on `data-theme`. Route line color and POI marker colors
  re-checked for contrast against both tile styles.
- `prefers-reduced-motion` respected — the theme-switch cross-fade (and
  any other transition) becomes an instant swap for users who set it.

---

## 6. Page concepts

### 6.1 Homepage

Deterministic curation, no manual homepage-CMS — not worth building at 2
posts (bucket #10). Structure:

1. Short, static site proposition (replaces the plain masthead — a
   sentence of *why this exists*, not just a hero image)
2. Latest post — larger treatment (cover image, summary, route stat
   chips pulled from its `Route` if it has one)
3. Remaining posts — a simple grid/list below, same as today's list but
   restyled

Explicitly **not** built now: manual "featured" flag/ordering, distinct
homepage sections requiring content that doesn't exist yet. Revisit the
"1 hero + N grid" split becoming awkward once there are enough posts to
need real pagination (bucket #3's job) — not a #2 concern.

### 6.2 Post page

- Same three sections as today (header, body, route block) but body
  gains the block vocabulary from §5.3.
- Cover image becomes a real `<img>`/`<picture>` element with explicit
  `width`/`height` and `fetchpriority="high"` (LCP candidate), not a CSS
  `background-image` on the masthead div as today — CSS background
  images can't be prioritized by the browser's preload scanner.

### 6.3 Navigation/footer

Kept intentionally simple: brand name, home link, dark-mode toggle. No
new nav items invented for content that doesn't exist (no fake "Blog /
About / Contact" menu).

---

## 7. Accessibility and performance budgets (gates every phase)

- WCAG 2.2 AA as the target level for every new/changed component.
- Lab budgets: LCP < 2.5s, CLS < 0.1, INP < 200ms — checked manually
  each phase; **independent verification is bucket #8**, not this doc.
- `prefers-reduced-motion` respected everywhere motion is added.
- Keyboard-only and screen-reader pass on every new template before a
  phase is called done.
- No new render-blocking third-party requests beyond what already
  exists today (net reduction expected once Google Fonts CDN / Font
  Awesome CDN script are self-hosted/replaced).

---

## 8. Phases

Each phase below follows the same **Scope / Done when / Testing**
structure used in `maps_gis.md` and `post_and_backend.md` — "Done when"
is a checkable pass/fail bar an agent (or reviewer) can verify without
judgment calls, not a process description like "parity check, nothing
regresses."

### Phase 1 — Foundation: retire Bootstrap, ship the token/type system

**Scope**

- [x] Land the CSS custom-property token set (§5.2) in a new stylesheet;
  remove `clean-blog.css` and the vendored Bootstrap CSS/JS from
  `static/` and `base.html`'s `<link>`/`<script>` tags.
- [x] Rebuild `base.html` nav/footer without Bootstrap's navbar JS —
  semantic HTML (`<details>`/`<nav>`, or a minimal Alpine toggle if
  needed) for the mobile menu.
- [x] Self-host the two font families (§5.2) instead of the Google Fonts
  CDN `<link>`; drop the Font Awesome CDN `<script>`, replacing every
  icon currently in use with inline SVG.
- [x] Capture a lab-CWV baseline (LCP/CLS/INP, e.g. via Lighthouse CLI or
  Chrome DevTools) on `home.html` and `post.html` *before* this phase's
  changes land, for comparison in Phase 5.

**Done when**

- [x] `home.html`, `post.html` (with and without a route/map), and the
  MapLibre map render with no visual breakage and no console errors, on
  both a desktop and a small-phone viewport — checked directly, not
  assumed from "the CSS compiles."
- [x] Zero requests to `fonts.googleapis.com` or any Font Awesome CDN
  host in the network panel on either page.
- [x] Core site navigation (home → post → back) works with JavaScript
  disabled in the browser — verifies the mobile menu isn't JS-load-order
  dependent.
- [x] Post-change lab CWV numbers on both pages are captured and are not
  worse than the pre-change baseline on any of LCP/CLS/INP.

**Testing**

- Existing route/template tests (`GET /`, `GET /posts/{slug}`) were
  updated, not left unmodified as originally scoped — see "Left over"
  below for why (the Scope/Testing conflict this revealed). All other
  behavioral assertions (title, body, tags, route stats, map rendering,
  404s) are unchanged and still pass; only the CSS/navbar/masthead-
  specific markup assertions were updated to match the new HTML, plus
  new assertions added confirming zero Bootstrap/Clean Blog/CDN
  references remain.
- Manual: keyboard-only tab through the nav on both pages, verified with
  a scripted Puppeteer check — all tab stops reachable, visible 3px
  focus outline at each stop (full keyboard/screen-reader pass across
  all templates remains Phase 5's job, not repeated per phase).

**Left over**

None blocking. One scope note: the original Testing subsection said
existing tests should pass "unmodified," which directly contradicted the
Scope bullet removing Bootstrap/Clean Blog (several existing tests
asserted on `clean-blog.css`/`clean-blog.js`/`navbar-brand` literally
being present). Resolved per sign-off: the CSS/markup-specific
assertions in `test_templates.py` were updated to match the new output;
no route/service-layer behavior changed, and no test was weakened, only
retargeted at new class names. Flagging this here since it's a
self-contradiction in the original phase spec worth being aware of for
future phase-writing, not a shortcut taken during implementation.

**Summary**

Replaced Bootstrap 5 / Start Bootstrap "Clean Blog" with a small custom
CSS token system in `static/theme.css` (colors, typography, spacing as
CSS custom properties, per §5.2). Removed `static/clean-blog.css`,
`static/clean-blog.js`, and the now-unused `static/style.css` (its
content was folded into `theme.css`). Rebuilt `base.html`'s nav as a
semantic `<details>`/`<summary>` mobile menu with zero JS dependency,
and removed the Google Fonts and Font Awesome CDN `<script>`/`<link>`
tags. Lora is now self-hosted (`static/fonts/lora-{normal,italic}.woff2`,
latin-only subset); body text moved to a system-ui-first stack with no
webfont download. The five Font Awesome icons in use (menu, road,
arrow-up, arrow-down, clock) were replaced with hand-authored inline SVG
macros in `templates/partials/icons.html`. `home.html` and `post.html`
had their Bootstrap grid classes stripped in favor of the new plain-CSS
layout. Verified with real headless-Chrome renders (desktop + mobile
viewports, both templates, with and without a route/map), a no-JS
navigation pass, a keyboard-tab-order pass, and before/after Lighthouse
runs: home LCP 7.5s → 2.0s, post LCP 14.0s → 6.2s, both pages' TBT and
CLS also improved, confirming no regression against the §7 budgets.

**Recommended next steps**

- Phase 2 (dark mode) can build directly on the `theme.css` token set
  landed here — the `:root` custom properties are already structured for
  a `[data-theme="dark"]` override block per §5.4, nothing further to
  restructure first.
- `static/img/post-bg.jpg` (the post masthead fallback image referenced
  in `post.html`) does not exist and returns a 404 — confirmed
  pre-existing (present before this phase's changes too, verified via
  `git show HEAD:static/img/`), not a Phase 1 regression, but worth a
  one-line fix (add the file, or fall back to the same solid-color
  masthead `home.html` already has) whenever convenient — not blocking
  Phase 2.
- The Phase 1 Lighthouse run surfaced the map-heavy post page's LCP
  (6.2s after, still short of the <2.5s §7 budget) as the main remaining
  performance gap on `post.html` — worth keeping in view for Phase 5's
  final budget check, though not this phase's job to fix (MapLibre/tile
  loading is explicitly out of scope here, per the "never touch ...
  map code" hard stop).
- No schema or route/service-code changes occurred in this phase, so
  Phase 2 starts from the same backend surface Phase 1 did.

### Phase 2 — Reading experience + dark mode

**Scope**

- [ ] Prose typography pass on `post.html` (measure, headings, links,
  blockquotes) using the Phase 1 token set.
- [ ] Dark/light/system theme: `data-theme` attribute driven by a
  no-flash inline pre-paint `<script>` in `<head>` (§5.4), toggle in the
  nav, choice persisted to `localStorage`.
- [ ] Dark-mode-aware MapLibre basemap flavor swap + route-line/POI-marker
  contrast re-check against the dark tile style.
- [ ] Every CSS transition introduced (theme cross-fade, hover states)
  wrapped so `prefers-reduced-motion: reduce` makes it instant.

**Done when**

- [ ] Loading any page with the OS set to dark mode (no prior toggle use)
  renders dark on first paint — no light-mode flash, checked by a slow
  network throttle, not just a fast local reload where a flash wouldn't
  be visible anyway.
- [ ] Toggling the theme persists across a full page reload and across
  navigating from `home.html` to `post.html`.
- [ ] The MapLibre map on a route-bearing post switches basemap flavor to
  match the active theme, and the route line + POI markers both meet
  WCAG AA contrast (checked with a contrast-checker tool, both against
  the light tile style and the dark one) — not just re-used unchanged
  from the light-mode values.
- [ ] With the OS "reduce motion" setting on, the theme toggle changes
  instantly with no visible fade.

**Testing**

- Manual: verified in at least two real browsers (not just one engine),
  since `prefers-color-scheme`/`localStorage` persistence and pre-paint
  script timing are exactly the kind of thing that can silently differ.
- No new backend/service code in this phase — no new automated test
  expected; existing route tests must still pass.

### Phase 3 — Editorial homepage

**Scope**

- [ ] New `home.html` per §6.1: static site-proposition line, a larger
  "latest post" treatment (cover image, summary, route stat chips if the
  latest post has a `Route`), remaining posts below in a simple
  grid/list.

**Done when**

- [ ] Rendered correctly with 0 posts (empty-state copy, no crash), 1
  post (hero only, empty list section handled gracefully — no dangling
  "more posts" heading over nothing), and 2 posts (today's real content)
  — each checked as its own case, not inferred from the 2-post case
  working.
- [ ] The latest post's route stat chips appear when it has a `Route` and
  are simply absent (not a broken/empty chip) when it doesn't.

**Testing**

- Extend the existing homepage integration test (or add one) asserting
  the 0/1/2-post render cases from "Done when" don't 500 and contain the
  expected post title(s) — this is exactly the kind of case `AGENTS.md`
  requires a test for since it's new template behavior.

### Phase 4 — Post body block vocabulary

**Scope**

- [ ] `figure`, `gallery`, `callout` Jinja partials (§5.3).
- [ ] `PostFrontmatter`/content-schema additions to author gallery images
  (with a mandatory `alt` field per image) and callouts via Sveltia.
- [ ] `route-map` block gains an explicit in-body placement marker;
  falls back to "render after body" when the marker is absent.

**Done when**

- [ ] A fixture post using a marker to place the route map mid-body
  renders the map at that position, not appended after all prose.
- [ ] Both existing real posts (`sunday-gravel-loop`,
  `kinzig-valley-loop`), which predate this schema change and contain no
  marker, render exactly as before — map still appears after the body,
  zero regression. **Explicit regression test**, per the same principle
  `maps_gis.md` Phase 2 applied to routeless posts.
- [ ] A gallery image frontmatter entry with a missing `alt` field fails
  `PostFrontmatter` validation (schema-level enforcement, not a template
  convention that can be silently skipped).
- [ ] A fixture gallery of 3 images renders as a semantic `<figure>` grid
  with each `alt` present in the rendered HTML.

**Testing**

- Unit test on the frontmatter schema: gallery image without `alt`
  raises a validation error.
- Unit test on the sync/render path for the route-map marker: with
  marker present → map renders at marker position; without → map renders
  after body (both cases as separate tests, not one combined assertion).
- Integration test: the two real existing posts still sync and render
  unchanged — the `AGENTS.md` content-schema-sync rule applies here
  (schema change → every existing post updated in the same change, plus
  a CHANGELOG entry).

### Phase 5 — Hardening

**Scope**

- [ ] Full keyboard-only and screen-reader pass across `home.html`,
  `post.html` (with/without route, with/without gallery), and the
  dark-mode toggle.
- [ ] 200%-browser-zoom check (WCAG 2.2 requirement, distinct from mobile
  responsiveness) and a print stylesheet for `post.html`.
- [ ] Lab-CWV re-measurement against the Phase 1 baseline.
- [ ] Remove any now-dead Bootstrap/Clean Blog assets still present in
  `static/` (should be none after Phase 1, but confirm).
- [ ] Update `buckets.md` row #2 to done, matching bucket #1's pattern.

**Done when**

- [ ] Every interactive element (nav links, theme toggle, gallery images
  if they're focusable/expandable) is reachable and operable by keyboard
  alone, with a visible focus indicator at every stop.
- [ ] A screen reader (VoiceOver or NVDA) announces the page's landmark
  structure, image alt text, and the theme-toggle's current state
  sensibly — checked directly by running one, not inferred from having
  used semantic HTML.
- [ ] At 200% browser zoom, no text is clipped/overlapping and no
  horizontal scroll appears on either template.
- [ ] Final lab CWV numbers on `home.html` and `post.html` meet the §7
  budgets (LCP < 2.5s, CLS < 0.1, INP < 200ms) and are not worse than the
  Phase 1 baseline.
- [ ] `grep -ri bootstrap static/ templates/` (or equivalent) returns
  nothing.

**Testing**

- No new automated tests expected beyond what Phases 1–4 already added —
  this phase is manual verification + budget measurement, recorded in
  this doc's phase summary once complete (per this repo's convention of
  a Summary section closing out each phase).

---

## 9. Decisions needing sign-off before implementation

- ~~Retiring Bootstrap/Clean Blog vs. keeping it and layering overrides~~
  — **confirmed: retire it now** (§5.1). Rejected the "wait for more
  content first" alternative on the record: the cost driver is template/
  override count, not post count, so deferring wouldn't have made this
  cheaper — proceeding with Phase 1 as planned.
- ~~Overall visual direction / design thesis (§3)~~ — **confirmed**:
  "field journal meets modern editorial adventure storytelling."
- Logo/wordmark — **confirmed: text wordmark stays**, no logo designed
  for this refresh.
- Homepage curation model — **confirmed: "latest-post hero + list,"** not
  a manual/featured-flag model.
- Willingness to produce/gather actual gallery-worthy photo sets for
  Phase 4 — **not yet resolved, and correctly not blocking**: ships as
  reusable schema/partials in Phase 4 regardless, used starting with the
  *next* post rather than retrofitted onto `sunday-gravel-loop` or
  `kinzig-valley-loop` with placeholder images.

## 10. Explicitly out of scope / deferred

- Search, tags-as-filter, pagination — bucket #3.
- Sitemap/RSS/OpenGraph/JSON-LD — bucket #4.
- Actual responsive image generation (`srcset`, WebP/AVIF, R2-hosted
  variants) — bucket #5; this doc only defines the gallery markup
  contract it will eventually fill.
- Independent Lighthouse/axe verification — bucket #8; this doc sets
  budgets, doesn't certify them.
- Comments, social share buttons, newsletter — bucket #9, not decided by
  this refresh either way.
- No SPA, no npm/bundler, no frontend framework, no generic page
  builder, no animation library, no autoplay/parallax/scroll-jacking.
- No manual homepage CMS, no fabricated homepage sections requiring
  content the blog doesn't have yet.
