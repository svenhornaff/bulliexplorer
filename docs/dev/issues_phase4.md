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

## ✅ P1 — Landing page (`home.html`): `home-bg.jpg` is orphaned — FIXED (e1e2a14, deleted orphan)

**Criticality:** High — the old Clean Blog homepage had a full-bleed
masthead background image (`/static/img/home-bg.jpg`). Phase 3 deliberately
replaced it with a text-only `.site-intro` block, but the image file was
added in a later commit (`aba9235 — Add home masthead background image`)
*after* Phase 3 shipped the text-only block. The image exists on disk but is
referenced by nothing — it never appears anywhere on the site.

**Root cause:** The Phase 3 design decision (`site-intro` = text-only,
no background image, as per §6.1: "Short, static site proposition —
*replaces* the plain masthead") and the subsequent commit adding
`home-bg.jpg` are in direct tension. One of two things happened:

- The image was added intending to wire it into the `site-intro`, but that
  wiring step was never done; OR
- It was added as a kept asset but the design intent of "no background
  image on home" is actually intentional and the file is just an orphan.

**Impact:** Either the home header looks deliberately minimal (fine) or a
desired visual is silently absent. The 404 risk is lower here since nothing
links to the file, but the orphaned asset is confusing.

**Fix options (pick one — needs a decision):**

- A: Wire `home-bg.jpg` into `.site-intro` as a CSS background (or as a
  `<picture>` with a hero overlay) if the intent was to have a full-bleed
  home header. Update `.site-intro` CSS to handle dark overlay + white text.
- B: Confirm the text-only `.site-intro` is intentional, delete
  `static/img/home-bg.jpg` (or add it to `.gitignore`), and close the issue.

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

## P3 — Real posts have never used galleries, callouts, or `[[route-map]]` markers

**Criticality:** Low — Phase 4 shipped the block vocabulary and verified it
via a temporary smoke-test post (created, synced, verified, deleted) and unit/
integration fixtures. But neither real post (`sunday-gravel-loop`,
`kinzig-valley-loop`) uses any of the new features yet.

**Impact:** The first real editorial use will be the true end-to-end
validation. Any subtle template/CSS issue that only appears with real uploaded
images (aspect ratios, portrait vs landscape) or multi-paragraph callout
bodies will remain undiscovered until then.

**Fix:** Not a code fix — a content action. Add at least one gallery or one
callout to a real post and verify the rendered output in `make dev` before
Phase 5 runs its hardening/accessibility pass over post body layouts.

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
| 2 | `home-bg.jpg` orphaned | **P1** | `static/img/home-bg.jpg` | ✅ Fixed e1e2a14 |
| 3 | No CSS formatter | **P2** | `Makefile`, `pyproject.toml` | ✅ Fixed 905f99a |
| 4 | `.masthead` no `min-height` | **P2** | `static/theme.css` | ✅ Fixed e1e2a14 |
| 5 | WCAG route-line light-mode contrast | **P2** | `templates/post.html` | ✅ Fixed c1539b5 |
| 5b | WCAG POI marker colours | **P2** | `templates/post.html` | 🔲 Open |
| 6 | Cross-browser verification (WebKit/Gecko) | **P2** | — (manual) | 🔲 Open |
| 7 | `Post.body_html` redundant column | **P3** | `app/models/post.py`, Alembic | ✅ Fixed 74eb967 |
| 8 | No real post uses galleries/callouts | **P3** | `content/posts/*.md` | 🔲 Open (content action) |
| 9 | Phase 5 (hardening) not started | **P3** | — | 🔲 Open |
| 10 | `static/` not volume-mounted in prod | **P2** | `docker-compose.prod.yml` | ✅ Fixed ced0665 |
