# BulliExplorer — UI/UX Refresh Issues (Post Phase 4)

Collected after Phase 4 completion. Each issue has a criticality rating,
root-cause, and a concrete fix. Ordered by criticality (P1 → P3).

---

## ✅ P1 — Post masthead: background image never displays — FIXED (e1e2a14)

**Criticality:** High — visible regression on every post page that has a
`cover_image` set (e.g. `sunday-gravel-loop`). The header renders as a
plain dark-grey bar; the cover photo is completely absent.

**Root cause (two sub-problems):**

1. **Missing fallback file.** `post.html` line 10 falls back to
   `/static/img/post-bg.jpg` when a post has no `cover_image`. That
   file does not exist — flagged as a known gap in Phase 1's "Left over"
   and never fixed. For `kinzig-valley-loop` (empty `cover_image: ''`)
   the masthead always requests a 404.

2. **`background-image` on a CSS-background `<div>` is not prioritised by
   the browser's preload scanner.** §6.2 of `ui_ux_refresh.md` explicitly
   states this should be converted to a real `<img fetchpriority="high">`
   element — "CSS background images can't be prioritized by the browser's
   preload scanner." Phase 4 did not address this; the `post.html` header
   still uses an inline `style="background-image: url(...)"` approach.
   This means:
   - The image is discovered late (after CSS is parsed, not during HTML
     scan), hurting LCP.
   - The Lighthouse post-LCP of 6.2 s (already short of the 2.5 s §7
     budget) is partly explained by this.

**Files affected:**

- `templates/post.html` — masthead `<header>` markup
- `static/theme.css` — `.masthead` styles
- `static/img/post-bg.jpg` — does not exist

**Fix:**

1. Convert the `.masthead` to contain a real `<img>` element (with
   `fetchpriority="high"`, explicit `width`/`height`, `object-fit:cover`
   via CSS) instead of a CSS `background-image`, per §6.2.
2. Either add a real `static/img/post-bg.jpg` fallback image, or remove
   the fallback entirely and let the masthead render as a solid-colour bar
   (matching the `.masthead { background-color: #343a40 }` already set)
   when no `cover_image` is provided — the solid-colour bar is actually
   a cleaner fallback and avoids the 404.

---

## ✅ P1 — Landing page (`home.html`): homepage header cover photo — REOPENED, FIXED (Option A)

**Criticality:** High. Original history: the old Clean Blog homepage had a
full-bleed masthead background image. Phase 3 deliberately replaced it
with a text-only `.site-intro` block; a later commit (`aba9235`) added
`home-bg.jpg` back but never wired it in, leaving an orphaned file. That
state was initially closed as **Option B** (`e1e2a14` — confirmed
text-only was intentional, deleted the orphan).

**Reopened:** decision revisited — Option A preferred after all: a
full-bleed cover photo reads better against the "field journal meets
modern editorial" design thesis than a bare text header.

**Resolution (Option A) — `b3d260f`:**

- `home-bg.jpg` regenerated (same visual language as `post.html`'s
  masthead composites) and placed at `static/img/home-bg.jpg`.
- `templates/home.html`: `.site-intro` header now includes a real
  `<img class="site-intro-cover" fetchpriority="high">`, mirroring
  `.masthead`'s img/overlay/z-index pattern in `static/theme.css` exactly
  — one consistent header treatment across `post.html` and `home.html`,
  not two divergent ones.
- `static/theme.css`: added `.site-intro--has-cover`, `.site-intro-cover`,
  and the dark-overlay `::after` rule; text color flips to white-on-dark
  only when the cover class is present, so the plain text-only path still
  works if the class is ever omitted.
- `tests/unit/test_templates.py`: docstring corrected to reflect the
  reopen; the assertion itself only checks the text-stack markup stays
  present, so it needed no logic change.
- Verified: 161/161 unit tests pass, tested on both mobile and desktop,
  confirmed live and committed (`b3d260f`).

---

## ✅ P2 — No CSS formatter in the project toolchain — FIXED (905f99a, djlint added)

**Criticality:** Medium — `make lint` / `make ci` only runs `ruff` and
`pyright`, both Python-only. `static/theme.css` is ~600 lines of hand-
authored CSS with no automated formatting or linting. The recent "theme
added" commit (`ffc840b`) is entirely a whitespace-only reformat (2-space
→ 1-space indent) applied by hand — that kind of manual re-indentation
adds noise to diffs and will recur.

**Root cause:** No CSS formatter is configured. The project's "no npm,
ever" constraint rules out Prettier / stylelint via npm, but there are
two viable options that require zero npm:

- **`stylelint` via `uv` + `node_modules`-free usage** — not available
  without npm.
- **`djlint`** — already a Python tool (`uv add djlint`) that formats
  Jinja2/HTML templates *and* can format inline `<style>` blocks; also
  lints HTML for accessibility issues. Nearest zero-npm option.
- **`prettier` via `npx --yes`** — one-off execution, no install, but
  violates the spirit of "no npm."
- **Manual / no formatter** — accept the inconsistency, document a
  convention (e.g. "2-space CSS indent") in `AGENTS.md` and enforce via
  code review only.

**Files affected:**

- `static/theme.css`
- `pyproject.toml` / `Makefile` (if a formatter is added)

**Fix:** Decide on an approach and document the choice. If `djlint` is
added: `uv add --dev djlint`, add a `make format-html` target (or fold
into `make format`), and add a `make lint` check. If no formatter:
add a CSS style convention to `AGENTS.md`.

---

## ✅ P2 — Post masthead has no `min-height` — FIXED (e1e2a14, 18rem set)

**Criticality:** Medium — the `.masthead` class sets only
`padding: var(--space-4) 0` (no `min-height`). When a post has no
`cover_image` (e.g. `kinzig-valley-loop`) or the fallback 404s, the
header is extremely short — just the padding around the title text,
with no visual weight. On the old Clean Blog the masthead had a fixed
`350px` / `450px` height.

**Root cause:** The Phase 1 CSS rebuild didn't set a `min-height` on
`.masthead`, likely because the focus was on removing Bootstrap and the
LCP concern (make it shorter = faster paint). But there's no visual design
decision documented for "how tall should the masthead be when there's no
image."

**Fix:** Add a `min-height` (e.g. `18rem` or `280px`) to `.masthead` in
`theme.css`. This is independent of fixing the `<img>` vs `background-image`
issue above — it matters even after that fix for the no-image fallback case.

---

## ✅ P2 — WCAG contrast: route-line light-mode — PARTIAL FIX (c1539b5)

**Route-line fixed:** `#e87722` → `#b85c00` (~4.6:1 on light basemap). POI marker palette still open.

---

## P2 — WCAG contrast gaps: POI marker colours — open

**Criticality:** Medium — flagged as pre-existing in Phase 2's "Left over"
and again in Phase 4's, but still unresolved after two full phases. Both
are WCAG 1.4.11 (graphical object, 3:1 minimum) failures:

- Route line `#e87722` on light basemap: ~2.2:1 (fails 3:1 by a margin).
- Several POI marker fill colours (`gas_station` #9C27B0 ~2.6:1 dark;
  `campsite`, `hotel`, `viewpoint`, `water_point` all under 3:1 on light).

**Fix:** Before Phase 5 (hardening / accessibility pass), agree whether to:
a) Lighten/darken the route-line light-mode colour to hit 3:1 while staying
   "orange enough" to read as the BulliExplorer brand accent.
b) Redesign `CATEGORY_COLOURS` in `post.html` for all 8 categories on both
   tile styles — small palette change but requires checking all 8 against
   both basemap earth-fill colours.
Both are scoped as "map code" but narrower than the Phase 2 carve-out that was
granted; either could follow the same one-item carve-out path.

---

## P2 — Cross-browser verification (second rendering engine) still open

**Criticality:** Medium — Phase 2 and Phase 3 both note that only Blink
(Chromium / Puppeteer headless) has been used for verification. The dark-
mode CSS (`prefers-color-scheme`, `color-scheme`, `[data-theme]`),
`<details>`/`<summary>` mobile nav, and `prefers-reduced-motion` all have
historically had WebKit/Gecko quirks.

**Fix:** Manual spot-check in the user's own Safari (WebKit) and/or Firefox
(Gecko) — this is the correct path, as noted in Phase 2. Cannot be done
with agent-driven live-browser automation (that was correctly aborted once
before). Takes 5 minutes and closes the outstanding "Done when" item for
Phase 2.

---

## ✅ P3 — `Post.body_html` column dropped — FIXED (74eb967)

**Criticality:** Low — `body_html` is still written on every sync by
`post_sync.py` and stored in the DB, but `post.html` now renders
exclusively from `post.body_blocks`. The column is dead weight: extra
DB storage, extra sync work, and a possible source of confusion for anyone
reading the schema.

**Root cause:** Phase 4 explicitly deferred this: "planned for removal once
`body_html` is fully superseded — tracked as Phase 5 follow-up, not this
phase's job."

**Fix (Phase 5 candidate):**

1. Remove the `body_html` column from `Post` model.
2. Remove the `body_html` assignment in `post_sync.py`.
3. Add an Alembic migration dropping the column.
4. Update `AGENTS.md` content-schema-sync checklist entry if needed.
No template or service logic changes — `post.html` already doesn't use it.

---

## ✅ P3 — Real posts have never used galleries, callouts, or `[[route-map]]` markers — FIXED (content, `dream-of-north`)

**Criticality:** Low — Phase 4 shipped the block vocabulary and verified it
via a temporary smoke-test post (created, synced, verified, deleted) and unit/
integration fixtures. But neither real post (`sunday-gravel-loop`,
`kinzig-valley-loop`) uses any of the new features yet.

**Impact:** The first real editorial use will be the true end-to-end
validation. Any subtle template/CSS issue that only appears with real uploaded
images (aspect ratios, portrait vs landscape) or multi-paragraph callout
bodies will remain undiscovered until then.

**Resolution:** `dream-of-north.md` now defines one real gallery
(`coffee-stop`, two images) and one real callout (`tip-001`, `warning`
variant), placed via `[[gallery:coffee-stop]]` and `[[callout:tip-001]]`
markers in the body and verified end-to-end in `make dev`.

- **Orientation coverage:** the two gallery images are roughly square
  (1952×1954) and landscape (4032×2268) — the portrait case is still
  *not* exercised by any real post; leaving this open as a follow-up
  rather than rotating an image just to tick the box.
- **Alt text:** rewritten from placeholder (`coffee`, `bike`) to real
  descriptive text, since Phase 5's VoiceOver/NVDA pass needs something
  real to test against.
- **Variant/title rendering confirmed:** `post-callout--warning` renders
  with its own CSS (not falling back to `tip`), and the optional `title`
  renders correctly.
- **Finding for Phase 5 — callout body is not Markdown-rendered.**
  `templates/partials/blocks.html`'s `render_callout` outputs
  `{{ block.body }}` as plain text inside a single `<p>`, not through
  the Markdown renderer used for gallery captions/prose. A multi-paragraph
  callout body will *not* get separate `<p>` tags — newlines are dropped
  by HTML whitespace collapsing. Not fixed here (template change, out of
  scope for a content-only fix) — tracked for Phase 5.
- **Finding for Phase 5 — gallery image weight.** The two uploaded images
  are 1.5 MB and 4.6 MB straight from a phone/camera, unresized. Gallery
  `<img>`s already have `loading="lazy"` so this doesn't hit LCP on this
  post (the gallery is below the fold, after the Norway section), but an
  editorial workflow that doesn't resize uploads will eventually put a
  multi-MB image above the fold on some other post. Worth a Phase 5 note
  on an upload-time resize step, not a blocker here.

---

## P3 — Phase 5 (hardening) not yet started

**Criticality:** Low (it's the plan, not a bug) — but it has explicit
open items gating "UI/UX Refresh done":

- Full keyboard-only + screen reader (VoiceOver/NVDA) pass.
- 200% browser-zoom check.
- Final lab CWV re-measurement (LCP/CLS/INP vs §7 budgets).
- `grep -ri bootstrap static/ templates/` clean check.
- Update `buckets.md` row #2 to done.

**Fix:** Start Phase 5. The two P2 contrast issues and cross-browser
verification above should ideally be resolved first, so Phase 5's
accessibility pass starts from a cleaner baseline.

---

## Summary table

| # | Issue | Criticality | Files |
| --- | ------- | ------------- | ------- |
| # | Issue | Criticality | Files | Status |
| --- | ------- | ------------- | ------- | ------ |
| 1 | Post masthead cover image not displayed | **P1** | `templates/post.html`, `static/theme.css` | ✅ Fixed e1e2a14 |
| 2 | Homepage header cover photo | **P1** | `templates/home.html`, `static/theme.css`, `static/img/home-bg.jpg` | ✅ Fixed b3d260f (reopened → Option A) |
| 3 | No CSS formatter | **P2** | `Makefile`, `pyproject.toml` | ✅ Fixed 905f99a |
| 4 | `.masthead` no `min-height` | **P2** | `static/theme.css` | ✅ Fixed e1e2a14 |
| 5 | WCAG route-line light-mode contrast | **P2** | `templates/post.html` | ✅ Fixed c1539b5 |
| 5b | WCAG POI marker colours | **P2** | `templates/post.html` | 🔲 Open |
| 6 | Cross-browser verification (WebKit/Gecko) | **P2** | — (manual) | 🔲 Open |
| 7 | `Post.body_html` redundant column | **P3** | `app/models/post.py`, Alembic | ✅ Fixed 74eb967 |
| 8 | No real post uses galleries/callouts | **P3** | `content/posts/*.md` | ✅ Fixed (content, `dream-of-north`) |
| 9 | Phase 5 (hardening) not started | **P3** | — | 🔲 Open |
| 10 | `static/` not volume-mounted in prod | **P2** | `docker-compose.prod.yml` | ✅ Fixed ced0665 |
