# DATA_PROCESSING.md — internal record of processing (RoPA)

**Internal document — never linked from the public site.** This is
where the concrete infrastructure facts that used to live in
`content/legal/datenschutz.md` moved to on 2026-09-18 (see
`legal_gdpr_classification_refactor.md` Phase 5). The public
`/datenschutz` page states purposes, legal bases, recipient
*categories*, retention *criteria*, and transfer safeguards — GDPR
Art. 13's actual requirement (see EDPB WP260 rev.01: "recipients or
categories of recipients" is the standard, not a named-vendor
inventory). It deliberately does not name products, versions,
endpoints, regions, or operational thresholds, because none of that is
required for visitor-facing transparency and publishing it turns a
privacy notice into unpaid infrastructure reconnaissance for anyone
probing the site.

This file is where those facts live instead — Art. 30 GDPR requires a
controller to *maintain* a record of processing activities, just not to
*publish* it. Keep this file accurate as the stack changes; it's the
source of truth `datenschutz.md`'s abstracted categories trace back to,
and what an actual supervisory-authority request would draw on.

## 1. Hosting

- **Provider**: Hetzner Online GmbH, Industriestr. 25, 91710
  Gunzenhausen, Deutschland.
- **Server location**: Helsinki, Finland (confirmed via `ipinfo.io`
  against the production IP).
- **Web server**: Caddy (TLS termination, reverse proxy to the app
  container). No `log` directive configured — no HTTP access logs are
  written.
- **Application server**: Uvicorn, run with `--no-access-log`.
- **Category disclosed publicly**: "European hosting provider."

## 2. Operational / error logs

- **Mechanism**: Docker's `json-file` log driver, `max-size: "10m"`,
  `max-file: "5"` (`docker-compose.prod.yml`) — a rolling ~50MB cap per
  container; oldest entries are overwritten, not retained for a fixed
  number of days.
- **No dedicated app-level access log** — see §1, both the web server and
  app server have access logging disabled.
- **Category disclosed publicly**: "limited operational/error logs,
  automatically overwritten" (retention *criterion*, not the exact
  byte/file count).

## 3. Error monitoring — Sentry

- **Vendor**: Functional Software, Inc. ("Sentry"), San Francisco, USA.
- **Ingest endpoint**: `ingest.de.sentry.io` — confirmed via the
  production `SENTRY_DSN` hostname.
- **Data region**: EU (Frankfurt, Germany) — confirmed directly in the
  Sentry dashboard (Settings → General → Data Storage Location shows
  "EU"), not inferred from the hostname alone.
- **Plan**: free Developer tier.
- **Event retention**: 30 days (Developer tier default), then automatic
  deletion.
- **SDK configuration** (`app/main.py`): performance tracing disabled;
  automatic PII capture, stack-frame local variables, and request bodies
  disabled; user context, extra context, breadcrumbs, and request
  headers stripped before send; request URLs scrubbed of credentials,
  query parameters, and fragments before send.
- **Third-country transfer**: Sentry is a US company; EU-US Data Privacy
  Framework certification is the applicable safeguard for any data that
  reaches the US side of the business (e.g. account/support data), even
  though event ingestion itself is EU-region. DPA:
  <https://sentry.io/legal/dpa/>.
- **Category disclosed publicly**: "error-monitoring service provider,"
  with the third-country/DPF safeguard covered in `datenschutz.md`'s
  transfers section (not tied to naming Sentry specifically).

## 4. Object storage / CDN — Cloudflare R2

- **Vendor**: Cloudflare, Inc., San Francisco, USA.
- **Product**: R2 Object Storage, used for PMTiles map archives and
  Sveltia CMS media uploads.
- **Location hint**: `WEUR` (Western Europe) — confirmed via the bucket
  endpoint pattern (`<account>.r2.cloudflarestorage.com`, i.e. the
  default/hint-only endpoint, not `<account>.eu.r2.cloudflarestorage.com`
  which would indicate a binding EU jurisdictional restriction).
  Cloudflare's own documentation is explicit that a location hint is
  best-effort placement, not a contractual data-residency guarantee.
- **DNS/proxy note**: Cloudflare is used only for R2 storage here — the
  site's own DNS is on AWS Route 53 and Caddy terminates TLS directly
  (confirmed: response `Server: uvicorn`, no `cf-*` headers on
  `bulliexplorer.com` itself). Cloudflare never sees visitor traffic to
  the main site, only requests that hit R2-hosted assets (map tiles,
  uploaded media) directly.
- **Third-country transfer**: Cloudflare is a US company; treated the
  same as Sentry above — EU-US DPF certification is the applicable
  safeguard, disclosed at the category level in `datenschutz.md`.
- **Category disclosed publicly**: "CDN/object-storage provider," with
  the same transfers-section safeguard language as Sentry.

## 5. Maps and geodata

- **Client-side libraries**: MapLibre GL JS, PMTiles reader — both
  vendored, served from `static/`, never fetched from a third-party CDN
  at request time.
- **Server-side lookups**: Nominatim (geocoding) and Overpass
  (amenity discovery) are called by the *sync* pipeline
  (`app/services/geo_sync.py`, `app/services/overpass.py`) when content
  is published — not by a visitor's page load. A normal page view never
  sends a visitor's IP to either service.
- **Category disclosed publicly**: not disclosed as a visitor-facing
  recipient at all — see the reasoning above; this is deliberately
  omitted from `datenschutz.md`, not abstracted, because visitors are
  not a data source for these calls.

## 6. Editor / CMS (operator tool, not visitor-facing)

- **GitHub**: Sveltia CMS commits content directly to
  `svenhornaff/bulliexplorer` via the GitHub API; the webhook then pulls
  those commits via a fine-grained PAT (`GITHUB_TOKEN`,
  Contents: Read).
- **Cloudflare R2**: also used as the CMS's media-upload target (see §4).
- **Scope**: `/editor/` is an operator-only tool. Visitors reading the
  public site never interact with GitHub or trigger this path. This is
  why it's excluded from `datenschutz.md` — that page describes what
  happens to *visitor* data, and no visitor data reaches GitHub through
  normal site use.

## 7. Keeping this file current

Update this file in the same change that changes any of the above —
switching hosting providers, changing Sentry/Cloudflare plans or
regions, altering log rotation, adding a new third-party service that
processes any visitor data. If a change here also changes what
`datenschutz.md`'s abstracted categories actually cover (e.g. a new
non-EU recipient, a materially different retention period), update
`datenschutz.md` too — abstraction is not a reason to let the public
notice drift out of sync with what's actually true.
