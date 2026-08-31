# BulliExplorer — UI/UX Refresh for 2026

> Concept doc for bucket #2 from `buckets.md`. Not started yet — this is
> the plan, written before any code changes, the same way `maps_gis.md`
> was written before bucket #1's implementation. Nothing below is shipped.

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
Every phase below is scoped to work correctly at 0, 1, or 2 posts, not
just at some imagined future volume — no feature that only looks good
with 20 posts ships gated behind having 20 posts.

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

This is a **decision requiring sign-off before implementation begins**
(see §9) — flagged as a recommendation here, not treated as already
decided.

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

### Phase 1 — Foundation: retire Bootstrap, ship the token/type system

- Land the CSS custom-property token set (§5.2), replace `clean-blog.css`
  with the custom layer.
- Rebuild `base.html` nav/footer without Bootstrap JS; mobile nav via
  semantic HTML (+ minimal Alpine only if truly needed) — must work with
  JS disabled for core navigation.
- Self-host fonts / drop the Font Awesome CDN script (swap remaining
  icons to inline SVG or a tiny hand-picked subset).
- Parity check: every existing page (`home.html`, `post.html`, and the
  map) renders correctly, nothing regresses.
- Screenshot + lab-CWV baseline captured before/after for comparison in
  later phases.

### Phase 2 — Reading experience + dark mode

- Prose typography pass (measure, headings, links, blockquotes) on
  `post.html`.
- Dark/light/system theme + persisted toggle, no-flash pre-paint script.
- Dark-mode-aware MapLibre tile flavor + route/marker contrast re-check.
- `prefers-reduced-motion` support wired everywhere a transition exists.

### Phase 3 — Editorial homepage

- New `home.html` per §6.1 (site proposition + latest-post hero + list).
- Explicitly tested at 0/1/2 posts — no post-count-dependent breakage.

### Phase 4 — Post body block vocabulary

- `figure`, `gallery`, `callout` Jinja partials + content-schema fields
  to author them via Sveltia.
- `route-map` gains a body-placement marker with graceful "after body"
  fallback for existing posts that don't use it.
- Gallery images render as-uploaded until bucket #5 ships responsive
  variants — no fake `srcset` generated ahead of that bucket existing.
- Mandatory alt-text field enforced at the Pydantic frontmatter-schema
  level for any gallery image (frontmatter schema change — remember the
  AGENTS.md sync rule: update schema + every existing post in the same
  change).

### Phase 5 — Hardening

- Full keyboard/screen-reader pass, 200%-zoom check, print stylesheet.
- Lab CWV re-measurement against Phase 1 baseline.
- Remove now-dead Bootstrap/Clean Blog assets from `static/`.
- Update `buckets.md` row #2 to done, same pattern as bucket #1.

---

## 9. Decisions needing sign-off before implementation

- **Retiring Bootstrap/Clean Blog vs. keeping it and layering overrides**
  (this doc recommends retiring it — §5.1).
- Overall visual direction / design thesis (§3) — confirm or redirect.
- Whether a logo/wordmark accompanies this refresh, or text wordmark
  stays as-is.
- Homepage curation model confirmed as "latest-post hero + list," not a
  manual/featured-flag model.
- Willingness to produce/gather actual gallery-worthy photo sets for
  Phase 4 — if none exist yet for either current post, Phase 4 ships the
  reusable partials/schema and is used starting with the *next* post,
  not retrofitted with placeholder images onto existing content.

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
