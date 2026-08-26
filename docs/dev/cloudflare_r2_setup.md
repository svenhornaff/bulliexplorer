# Cloudflare R2 Setup — Basemap Tiles (Maps & GIS Phase 4)

> Runbook for hosting the self-extracted PMTiles basemap on Cloudflare R2.
> See `maps_gis.md` for why R2 + PMTiles was chosen over a tile-server
> approach, and the overall Maps & GIS phased plan this closes out.

---

## Checklist

- [x] R2 enabled on the Cloudflare account (free tier)
- [x] Bucket `bulliexplorer` created
- [x] Account API token created (Object Read & Write, scoped to this bucket)
- [x] Credentials filled into `.env`
- [x] PMTiles file uploaded to the bucket
- [x] Public Development URL enabled (r2.dev subdomain)
- [x] CORS policy applied (Dashboard → flat-array JSON from `docs/dev/r2-cors.json`)
- [x] Upload + CORS verified via `curl` (HTTP 206 + `Access-Control-Allow-Origin: *`)
- [x] `static/basemap-test.html` updated to the R2 URL and visually confirmed
- [x] `docs/dev/r2-cors.json` + updated test page committed and pushed

---

## 1. Enable R2 on the account

1. Go to **https://dash.cloudflare.com/** and sign in.
2. Left sidebar → **R2 Object Storage**.
3. If this is the account's first use of R2, click **"Add R2 subscription to
   my account."** This is not a paid plan by itself — it's how Cloudflare
   turns the feature on. A payment method on file is required even though
   usage stays free under the limits below, standard for Cloudflare's
   usage-based billing model.

**Free tier limits** (relevant for sanity-checking, not something to
actively manage at this project's scale):

| Resource | Free / month | This project's actual usage |
|---|---|---|
| Storage | 10 GB | ~0.26 GB (one 265 MB PMTiles file) |
| Class A operations (writes) | 1,000,000 | A handful |
| Class B operations (reads) | 10,000,000 | Won't get close at personal-blog traffic |

"Total Due Now: $0.00" on the confirmation screen is expected and correct.

## 2. Create the bucket

R2 dashboard → **Create bucket** → name: `bulliexplorer` (matches
`S3_BUCKET`'s default in `app/core/config.py`) → default region
(Western Europe / WEUR is fine, closest to Hetzner's Nuremberg location).

## 3. Create an API token

R2 → **Manage API Tokens** → **Create Account API token** (not "User API
token" — the account-scoped one is correct here since this credential is
used by an automated process/service, not tied to one person's individual
access, even though it's a solo project).

Settings:
- **Permissions**: **Object Read & Write** (not Admin — this token only
  ever needs to read/write objects, never create/delete buckets or change
  bucket config)
- **Specify bucket(s)**: **"Apply to specific buckets only"** → select
  `bulliexplorer`. Least-privilege, matches every other credential in this
  project.
- **TTL**: `Forever` is fine — rotate later if ever suspected compromised,
  same policy as the GitHub PAT used for Sveltia.
- **Client IP Address Filtering**: leave blank. This credential is used
  from a personal Mac with a dynamic residential IP, not a fixed server —
  an IP filter here would just break silently on the next DHCP lease
  renewal. (If this were used *from* the Hetzner server with a static IP,
  filtering would make sense — it isn't, so it doesn't yet.)

Click **Create Account API Token**. Copy the **Access Key ID** and
**Secret Access Key** immediately — the secret is shown once only.

## 4. Fill in `.env`

```bash
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_ACCESS_KEY=<access key id from step 3>
S3_SECRET_KEY=<secret access key from step 3>
S3_BUCKET=bulliexplorer
```

The account ID is visible in the R2 dashboard's overview / bucket "General"
tab (also embedded in the S3 API URL shown there).

## 5. Upload the PMTiles file

Requires the AWS CLI (`brew install awscli` — R2 is S3-compatible, the
official AWS CLI works against it directly with no plugin):

```bash
source .env  # or export the three S3_* vars manually

AWS_ACCESS_KEY_ID=$S3_ACCESS_KEY \
AWS_SECRET_ACCESS_KEY=$S3_SECRET_KEY \
aws s3 cp static/pmtiles/black-forest-20260826.pmtiles \
  s3://bulliexplorer/tiles/black-forest.pmtiles \
  --endpoint-url $S3_ENDPOINT_URL \
  --content-type application/x-protomaps-tiles
```

265 MB — takes a minute or two depending on connection speed.

## 6. Enable public access

R2 → bucket `bulliexplorer` → **Settings** → **Public Development URL** →
**Enable**.

This is Cloudflare's own label for what's commonly called the `r2.dev`
public URL — genuinely fine for this use case (public, non-sensitive tile
data on a personal blog), though Cloudflare's docs position **Custom
Domains** (e.g. `tiles.bulliexplorer.com`, mapped via Route 53 since the
domain's already there) as the production-recommended path. Worth
revisiting later; not needed to get Phase 4 working.

Copy the resulting public URL — format: `https://pub-<hash>.r2.dev`.

## 7. Apply the CORS policy

**Important gotcha, worth reading before pasting anything:** R2 accepts
**two different CORS JSON schemas** depending on which interface applies
it — using the wrong one for the wrong interface fails or silently does
nothing.

**Dashboard UI** (and the S3-compatible `aws s3api put-bucket-cors` path)
— flat array, classic S3 shape:

```json
[
  {
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["Range", "Accept-Encoding", "Content-Type"],
    "ExposeHeaders": ["Content-Range", "Content-Length", "ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

`Range` in `AllowedHeaders` and `Content-Range`/`ETag` in `ExposeHeaders`
matter specifically because PMTiles works entirely via HTTP range
requests — without these, the browser blocks MapLibre from reading the
partial-content responses even though the request itself succeeds.
`AllowedOrigins: ["*"]` is a reasonable choice for this specific file —
it's public, read-only, non-sensitive tile data; scoping it to
`bulliexplorer.com` specifically buys no real security benefit here.

**`wrangler r2 bucket cors set --file <path>`** (the CLI path, if used
instead) — nested `rules`/`allowed` shape, Cloudflare's native API format:

```json
{
  "rules": [
    {
      "id": "pmtiles-browser-access",
      "allowed": {
        "origins": ["*"],
        "methods": ["GET", "HEAD"],
        "headers": ["Range", "Accept-Encoding", "Content-Type"]
      },
      "exposeHeaders": ["Content-Range", "Content-Length", "ETag"],
      "maxAgeSeconds": 3600
    }
  ]
}
```

Save whichever one's actually used as `docs/dev/r2-cors.json`.

**Dashboard path**: bucket → **Settings** → **CORS Policy** → **Add** →
paste the flat-array JSON.

**CLI path** (needs `wrangler login` first — opens a browser, one-time):
```bash
wrangler login
wrangler r2 bucket cors set bulliexplorer --file docs/dev/r2-cors.json
```

## 8. Verify

Check both criteria — range-request support *and* CORS headers — in one
request:

```bash
curl -sI -H "Origin: https://bulliexplorer.com" -H "Range: bytes=0-1023" \
  https://pub-<your-hash>.r2.dev/tiles/black-forest.pmtiles
```

Expected response includes:
```
HTTP/1.1 206 Partial Content
Content-Range: bytes 0-1023/264607949
Access-Control-Allow-Origin: *
Access-Control-Expose-Headers: Content-Range,Content-Length,ETag
```

`206` confirms range requests work; the two `Access-Control-*` headers
confirm CORS is actually applied — both are required, neither alone is
sufficient proof.

## 9. Point the test page at the real URL

```javascript
// static/basemap-test.html
const PRODUCTION_TILES_URL =
  "pmtiles://https://pub-<your-hash>.r2.dev/tiles/black-forest.pmtiles";

const TILES_URL = PRODUCTION_TILES_URL;  // switch from LOCAL_TILES_URL
```

Open the page (`make dev`, or on the deployed server) and **visually
confirm the map actually renders** — the curl check above proves the
plumbing works, but the literal Phase 4 `Done when` criterion is seeing
the basemap on screen, not just a successful HTTP response.

## 10. Commit

```bash
git add static/basemap-test.html docs/dev/r2-cors.json
git commit -m "Phase 4: R2-hosted PMTiles with CORS, close out basemap setup"
git push origin develop
```

Then update `maps_gis.md`'s Phase 4 checkboxes (upload done, `Done when`
verified) and add the usual Summary — same pattern as every prior phase.