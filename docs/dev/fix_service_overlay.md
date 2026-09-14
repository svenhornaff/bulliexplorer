# Fix: intermittent tile-fetch failures on the live map overlay

> Root-cause investigation and fix plan for `Fetch failed loading` errors
> against `pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev/tiles/europe.pmtiles`,
> observed in production on `bulliexplorer.com`. See `maps_gis.md` for the
> Europe-extract migration this tileset came from, and
> `cloudflare_r2_setup.md` for the original R2 setup this corrects.

---

## Symptom

The MapLibre overlay on post pages intermittently fails to load tiles.
Browser console shows repeated:

```
pmtiles.js:1205 Fetch failed loading: GET
  "https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev/tiles/europe.pmtiles".
```

Route line and stats always render correctly (pure client-side GeoJSON/GPX
math, no dependency on the basemap) — only the tile imagery underneath is
affected.

## Investigation timeline

**Hypothesis 1 — stale extract file (ruled out).** Confirmed via `pmtiles
show` and a live upload verification that `tiles/europe.pmtiles` on R2 is
the correct, complete 23 GiB Europe extract (bounds `-25,34,45,72`, maxzoom
14) — not corrupted, not a partial upload.

**Hypothesis 2 — CORS/config regression (ruled out).** Direct verification
against the live object:

```
HEAD:            200, Content-Length: 24,487,117,444 bytes (matches the 23 GiB upload)
Range request:   206 Partial Content ✓
CORS preflight:  204, Access-Control-Allow-Origin: https://bulliexplorer.com ✓
GET w/ Range:    206, CORS headers present ✓
```

Every single-request check succeeds cleanly. This ruled out a config
regression in the object itself, its CORS policy, or R2's Range support —
all confirmed correct.

**Hypothesis 3 — burst load on huge-bbox routes only (ruled out).** Initial
suspicion was that "Dream of North" (~4,200 km, Germany → Nordkapp) triggers
an unusually large burst of concurrent tile requests at `fitBounds()` time,
overwhelming something route-size-specific. **Disproven**: the same
`Fetch failed loading` errors reproduce on `kinzig-valley-loop`, a tiny
local route with a trivial bounding box. This is not route-size-specific.

**Confirmed root cause — free `pub-*.r2.dev` URL throttling.** The failures
are **intermittent, not total** (a real session showed 12 tile fetches
succeed against 4 that fail) — a pattern inconsistent with a hard
misconfiguration (which would fail 100% of the time) and consistent with
rate-limiting/throttling on Cloudflare's free R2 developer URL. This
tracks even on small-bbox routes because `pmtiles.js` itself needs several
range reads just to walk the tileset's internal directory structure before
serving any tile at all — the request *count* against a 23 GiB single
object is nontrivial regardless of viewport size.

This exact risk was already flagged as **deferred future work** in
`maps_gis.md`'s Phase 1 ("Production custom domain... `r2.dev` URL is
already proven working... for tiles") — true for the much smaller 265 MB
Black Forest file this was originally verified against, not necessarily
under a 23 GiB object's real interactive request volume. What was "nice to
have, not urgent" is now confirmed necessary.

## The fix

Move `TILES_URL` off the free `pub-*.r2.dev` development URL onto a
Cloudflare-managed custom domain (e.g. `media.bulliexplorer.com`). Custom
domains are not subject to the same free-tier throttling as the dev URL.

### Why this isn't a same-session fix

`bulliexplorer.com`'s DNS is hosted on **Route 53** (AWS), confirmed via
`dig +short NS bulliexplorer.com`, not Cloudflare. Cloudflare R2 custom
domains require the hostname to live on a Cloudflare-managed zone, so this
needs a **subdomain delegation**, not just a dashboard toggle:

1. Create a new Cloudflare zone for `media.bulliexplorer.com`.
2. Delegate that subdomain to Cloudflare's assigned nameservers via an NS
   record in Route 53 (the root domain and everything else stays on
   Route 53 — only this one subdomain moves).
3. Only then can the R2 bucket's custom-domain toggle (dashboard-only, not
   available via the S3-compatible API) be attached to that hostname.

None of this is reachable with the credentials in this project: the R2
credentials in `.env` are deliberately scoped to Object Read & Write only
(no Zone/DNS permissions), `wrangler` isn't installed/authenticated, and
there's no Cloudflare account-level API token anywhere in this repo. Steps
1 and 2 need a human at the Cloudflare and Route 53 dashboards directly —
this is an access gap, not a scope restriction that can be worked around.

## Phased implementation plan

### Phase 1 — DNS delegation (manual, needs dashboard access)

**Scope**

- [ ] In Cloudflare: **Add a site** → `media.bulliexplorer.com` → free
  plan is fine. Cloudflare will assign two nameservers (e.g.
  `xxx.ns.cloudflare.com`, `yyy.ns.cloudflare.com`).
- [ ] In Route 53 (existing `bulliexplorer.com` hosted zone): add an **NS
  record** for `media.bulliexplorer.com` pointing at those two Cloudflare
  nameservers. This delegates only that subdomain — the root domain and
  every other record stay on Route 53, untouched.
- [ ] Wait for the Cloudflare zone to show **Active** (DNS propagation,
  usually a few minutes to a few hours).

**Done when**

- `dig +short NS media.bulliexplorer.com` returns the two Cloudflare
  nameservers.
- The Cloudflare dashboard shows the `media.bulliexplorer.com` zone as
  Active, not Pending.

### Phase 2 — Attach the R2 custom domain (manual, needs dashboard access)

**Scope**

- [ ] Cloudflare dashboard → R2 → the `bulliexplorer` bucket → Settings →
  **Custom Domains** → Connect Domain → `media.bulliexplorer.com`.
  Cloudflare handles the CNAME automatically since the zone above is now
  Cloudflare-managed.
- [ ] Confirm the domain shows **Active** in the bucket's custom domain
  list (not just added).

**Done when**

- `https://media.bulliexplorer.com/tiles/europe.pmtiles` returns `200`
  with the correct `Content-Length` (same object, new hostname).
- A Range request against that URL returns `206`.

### Phase 3 — Cut over `TILES_URL` and verify (I can do this once Phases 1-2 land)

**Scope**

- [ ] Update `TILES_URL` in both local `.env` and the production server's
  `.env` from
  `pmtiles://https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev/tiles/europe.pmtiles`
  to
  `pmtiles://https://media.bulliexplorer.com/tiles/europe.pmtiles`.
- [ ] `make deploy`.
- [ ] Verify on the real site: load `dream-of-north` (previously the
  clearest repro) and `kinzig-valley-loop` (previously also repro'd),
  confirm no `Fetch failed loading` errors across a normal pan/zoom
  session, not just initial load.
- [ ] Confirm the old `pub-*.r2.dev` URL is no longer referenced anywhere
  in `.env`, `.env.example`, or docs — replace remaining mentions with
  the new custom domain, noting the dev URL still works as a fallback if
  the custom domain ever needs to be temporarily rolled back.

**Done when**

- A real, sustained interactive session (multiple pans/zooms, not a
  single page load) on both previously-affected posts shows zero tile
  fetch failures.
- `TILES_URL` in both environments points at `media.bulliexplorer.com`.

## Left over

Phases 1-2 are entirely blocked on dashboard/DNS-account access this
session doesn't have. Phase 3 is ready to execute the moment Phase 2's
"Done when" is met — no code changes needed beyond the two `.env` edits
and a redeploy.

## Recommended next steps

Once this lands, the same custom-domain pattern should be considered for
the media library's `R2_PUBLIC_URL` (currently also a `pub-*.r2.dev` URL,
per `media_storage_r2.md`) if upload/asset-browsing volume ever grows
large enough to risk the same throttling — not urgent today (that bucket's
traffic pattern is nothing like a 23 GiB tileset under sustained range
reads), but worth remembering as the same class of fix if it ever
resurfaces there too.
