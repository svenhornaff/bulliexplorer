# docs/dev/ — index

Housekeeping item from `docs/dev/review_17SEP2026.md`'s tech-debt
register ("`docs/dev/` sprawl") — 22+ files accumulated across the
project's phases; this index exists to keep that culture's actual value
(a durable, evidence-first record — see `review_17SEP2026.md`'s "What's
genuinely strong" section) without imposing a full-directory read just
to find one thing. Grouped by whether a file is still something you'd
consult to make a decision today, or is a record of one already made.

Add new docs to the relevant section below in the same change that adds
them — this file goes stale exactly as fast as anything else if nobody
updates it, so treat it as part of the "done when" for any doc-adding
change, not a separate chore.

## Active reference — consult these to make a decision today

| Doc | What it's for |
| --- | --- |
| `bulliexplorer_stack_concept.md` | Architecture and hosting decisions — the doc `AGENTS.md` points to first. |
| `boilerplate.md` | Dev-environment conventions — the doc `AGENTS.md` points to second. |
| `deployment.md` | How to actually deploy/operate the production host — commands, crontab entries, rollback. |
| `monitoring_ops.md` | Monitoring/backup/CI-CD setup and status — phased, with **Done when**/**Summary** per phase. |
| `buckets.md` | The backlog — numbered "buckets" of open/in-progress/superseded work, kept current as items ship. |
| `cloudflare_r2_setup.md` | R2 bucket/CORS/credentials setup reference. |
| `review_17SEP2026.md` | The most recent full-codebase review — findings, tech-debt register, and the implementation log working through them. |
| `prompts.md` | Prompt template for implementing one phase of a multi-phase doc — reusable process, not tied to one feature. |
| `legal_gdpr.md` | Legal/GDPR release notes — required `LEGAL_*` env vars, the `LEGAL_ADDRESS`/virtual-address reasoning, classification semantics. Consult before touching `/impressum` or `/datenschutz`. |
| `DATA_PROCESSING.md` | Internal RoPA-style record of concrete infrastructure facts (hosting entity/location, monitoring vendor/region/plan, storage vendor/region hint, log rotation) — never published. The source of truth `datenschutz.md`'s abstracted categories trace back to; keep current as the stack changes. |

## Historical — implemented; kept as the record of what was decided and why

Each of these already shipped (see `buckets.md` for current status of
the bucket it belongs to). Consult when you need the *reasoning* behind
something that already exists, not to decide what to do next.

| Doc | Bucket / feature |
| --- | --- |
| `maps_gis.md` | Maps & GIS, Phases 1–5 (schema, GPX parsing, geocoding, PMTiles, rendering) — bucket #1. |
| `gis_refactor.md` | Europe-wide basemap swap + coverage-check safeguard, following `maps_gis.md`. |
| `gis_cycling_upgrade.md` | Cycling-specific tile layers + nearby-amenity discovery (Overpass) — bucket #1 follow-on. |
| `elevation_profile_chart.md` | Elevation profile chart — Tier 1 (static chart, storage + rendering) not started, Tier 2 (Komoot-style hover sync) optional/additive on top. |
| `fix_overpass_urban_density_timeout.md` | Overpass resilience: timeout → mirror → split → 429 backoff. |
| `fix_incremental_amenity_writes.md` | Per-chunk amenity writes so partial Overpass failures don't lose completed work. |
| `fix_startup_blocking_amenity_sync.md` | Moved amenity discovery off the startup-blocking path into a background task. |
| `fix_amenity_overlay_performance.md` | Clustered rendering fix for 15k+-amenity routes (DOM markers → GL layers). |
| `fix_amenity_overlay_ux.md` | Amenity popup content/category UX following the performance fix. |
| `media_storage_r2.md` | R2 media library (browser→R2 uploads via Sveltia) — bucket #5. |
| `post_and_backend.md` | Original post/backend architecture — FastAPI + Jinja2 + Markdown sync design. |
| `editor_cms.md` | Sveltia CMS integration (`/editor/`) + GitHub webhook auto-publish design. |
| `ui_ux_refresh.md` | 2026 UI/UX refresh concept — bucket #2 (signed off; Phase 1 not started, still current for *when* it starts). |
| `issues_phase4.md` | Bugs found and fixed after `ui_ux_refresh.md` Phase 4 — all resolved. |
| `legal_gdpr_classification_refactor.md` | Legal classification decision (`LEGAL_CLASSIFICATION=personal`), the deploy/passthrough bugs that followed, `LEGAL_ADDRESS` becoming optional for `/datenschutz`, and the later de-detailing of the public notice to recipient categories only. |

## Documented false leads — kept deliberately, not deleted

Per `review_17SEP2026.md`'s "What's genuinely strong" note: false leads
caught before building a fix for a non-problem are worth keeping as a
record, not erasing once corrected.

| Doc | What looked wrong, and wasn't |
| --- | --- |
| `fix_service_overlay.md` | Console `Fetch failed loading` noise misread as R2 dev-URL rate-limiting — was ordinary browser console behavior. |

## Config / non-prose files

| File | What it's for |
| --- | --- |
| `r2-cors.json` | The actual CORS policy applied to the R2 bucket (paired with `cloudflare_r2_setup.md`). |
