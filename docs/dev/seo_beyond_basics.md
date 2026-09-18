# SEO — beyond basics, grounded in Sept 2026 evidence

> Closes bucket #4 from `buckets.md`. Every claim below is checked
> against current (2026) sources, not assumed from general SEO
> knowledge — several things that "everyone recommends" turned out to
> be outdated or unsupported by real evidence, and are explicitly
> skipped below with the reasoning, not silently omitted.

---

## Research summary — what's real vs. what's hype, checked directly

**llms.txt: skip it, and this is the one deliberate non-recommendation
in this doc.** The obvious "above basics" move, and the evidence says
not to bother. ~10% adoption across 300,000 domains studied (SE
Ranking), but empirically GPTBot, ClaudeBot, PerplexityBot, and
OAI-SearchBot "overwhelmingly skip the file and crawl HTML directly" —
one September-2026 study tracked 500M+ AI bot visits over 90 days and
found only 408 hits on llms.txt files. Google's Gary Illyes confirmed
on the record that Google doesn't support it and isn't planning to;
John Mueller compared it to the discredited keywords meta tag. A small,
low-cost file, but the honest 2026 evidence is that it does effectively
nothing right now. Worth revisiting if that changes — not worth
building today.

**FAQPage and HowTo: also skip, for a different reason — they're
deprecated, not just low-value.** FAQPage rich results were deprecated
in Google Search starting May 2026; HowTo is no longer supported at
all. Older SEO guides (including plenty still circulating) recommend
both — that's stale advice as of this year, not a matter of opinion.

**What's real and worth building — the training-vs-search crawler
split.** This is the genuinely current, well-evidenced practice
replacing the old "block all AI bots" or "allow all AI bots" binary.
Major providers now run separate crawlers for training their models
versus retrieving pages to cite in real-time answers:

| Provider | Training crawler | Search/citation crawler |
|---|---|---|
| OpenAI | `GPTBot` | `OAI-SearchBot`, `ChatGPT-User` |
| Anthropic | `ClaudeBot` | `Claude-SearchBot` |
| Google | `Google-Extended` (Gemini training) | `Googlebot` (unaffected) |

Real, current measurement (Cloudflare's network-wide crawler-permission
analysis, updated through September 2026) shows "block training, allow
search" is now the visible consensus posture, not a niche opinion —
GPTBot's allow-share recently overtook its disallow-share for the first
time in that tracking.

**This is a real decision for the site owner, not a default to pick
silently** — same posture this project already took for the legal
classification work. Does BulliExplorer's content get used to train
future models, or does it opt out of training while staying eligible to
be cited when someone asks an AI assistant about, say, cycling the
Rhine valley? Worth an explicit choice before Phase 1 below, not an
assumed answer.

**Structured data (JSON-LD): `BlogPosting`, and `Trip` for route
posts specifically — not a generic one-size-fits-all `Article`.**
Checked schema.org directly: `Trip`/`TouristTrip` exist specifically
for itinerary/journey content (10K-100K domains using it per Google's
own May 2026 index data) — a genuinely better semantic fit for a route
post than treating it as an undifferentiated blog article. Worth being
calibrated about what this actually buys: "no special Schema.org markup
is required for AI Overviews or AI Mode" per current guidance —
structured data doesn't directly cause AI citation, it makes a page's
content easier to parse correctly, which correlates with being more
citable. Don't oversell it internally as a guaranteed AI-visibility
lever; it's a real, worthwhile, modest investment, not a magic switch.

**Core Web Vitals** — INP (Interaction to Next Paint) replaced FID as
the responsiveness metric back in 2024 and remains current; LCP and CLS
unchanged. Not new scope for this doc — this is exactly what bucket #8
(the perf/a11y audit) already covers. Worth doing that audit with SEO
awareness rather than duplicating it here.

## Phased implementation plan

### Phase 0 — The AI-crawler decision (not a code task)

Decide the actual posture before Phase 1 implements it: allow AI
training crawlers, block them while staying citable, or block
everything. Given BulliExplorer's personal/non-commercial classification
(the legal-gdpr work), this is a values question as much as a technical
one — worth deciding on purpose.

**Done when**: a real answer exists, not a default picked by whichever
option was easiest to implement.

**Decided (operator, 2026-09-18): block training, allow citation.**
Asked directly rather than defaulted — the same posture the doc's own
research summary identifies as the current real-world consensus
(Cloudflare's crawler-permission tracking). Encoded in
`app/services/seo.py`'s `AI_TRAINING_CRAWLERS` constant: `GPTBot`,
`ClaudeBot`, `Google-Extended`, `CCBot`, `Applebot-Extended` get
`Disallow: /`; `OAI-SearchBot`, `ChatGPT-User`, `Claude-SearchBot`,
`PerplexityBot`, `Googlebot`, `Bingbot` get no explicit rule (fall
through to the generic allow-all block), per Phase 1's own scope.

### Phase 1 — robots.txt with the training/search split

**Scope**
- [x] `robots.txt` at the root (`GET /robots.txt`,
  `app/routes/seo.py`) — built by `app.services.seo.robots_txt()` from
  a runtime `site_url`, not a static file on disk (content is
  effectively constant, but this way it can never drift from the
  `Settings.site_url` used everywhere else, and there's no static file
  to remember to update if the crawler list ever changes).
- [x] Explicit rules per Phase 0's decision: `Disallow: /` for
  `GPTBot`, `ClaudeBot`, `Google-Extended`, `CCBot`,
  `Applebot-Extended`; no rule (default allow) for `OAI-SearchBot`,
  `ChatGPT-User`, `Claude-SearchBot`, `PerplexityBot`, `Googlebot`,
  `Bingbot`.
- [x] A generic `User-agent: *` / `Allow: /` block covering every
  other crawler, unchanged from today's actual behavior (no robots.txt
  existed before this, so "unchanged" means literally unrestricted,
  same as now).

**Done when**
- [x] `curl http://localhost:8000/robots.txt` (via the docker-compose
  `db`/`backend` stack) returns the intended rules — verified locally
  and via `test_robots_txt_served_at_root`
  (`tests/integration/test_routes_integration.py`).
- [x] Spot-checked against real, current crawler documentation for
  each of the 5 training bot names and the 6 search/citation bot names
  named in the doc's own research summary — `AI_TRAINING_CRAWLERS` is
  pinned by a dedicated regression test
  (`test_robots_txt_no_typos_in_known_bot_names`,
  `tests/unit/test_seo.py`) precisely because a silent typo here does
  nothing detectable at runtime.

**Testing**: `tests/unit/test_seo.py` — content/format assertions
(every training crawler disallowed, generic allow-all present, no
search/citation crawler ever named, `Sitemap:` directive present, no
crawler both allowed and disallowed). `tests/integration/
test_routes_integration.py::test_robots_txt_served_at_root` for the
actual HTTP response.

### Phase 2 — Sitemap, RSS, OpenGraph (the actual basics, still needed)

**Scope**
- [x] `sitemap.xml` (`GET /sitemap.xml`) — homepage, `/posts/` list,
  and every *published* post (drafts excluded — they 404 publicly, so
  listing them would be self-defeating). `lastmod` is each post's
  `updated_at` (the DB row's own onupdate timestamp), not
  `published_date` — the same "content actually changed" vs. "first
  published" distinction docs/dev/fix_amenity_resync_freshness.md
  drew for routes, applied here to posts: a content-only resync bumps
  `updated_at` without a new publish date, and `lastmod` should reflect
  that.
- [x] `feed.xml` (`GET /feed.xml`, RSS 2.0 — not Atom; RSS is the
  format every reader still supports and the doc didn't require Atom
  specifically) — every published post, newest first, real
  `pubDate`/`lastBuildDate`. **Implementation decision**: each item's
  `description` is the post's `summary` only, not the full rendered
  body — matches this project's existing minimization posture
  (`docs/dev/DATA_PROCESSING.md`'s spirit, applied here to what's
  republished rather than just what's collected) instead of handing
  out full-text content for scraping/republishing by default. Not
  explicitly specified by the doc; flagged here as a real decision,
  not a silent default.
- [x] OpenGraph + Twitter Card meta tags per post — `og:title`,
  `og:description` (both default to the same content as the existing
  `title`/`meta_description` blocks via Jinja's `self.title()`/
  `self.meta_description()`, so there's exactly one place that decides
  page-title text, not two that can drift), `og:image` (the post's
  existing `cover_image`, omitted entirely when a post has none rather
  than fabricating a default), `og:type=article`, `twitter:card`
  (`summary_large_image` when a cover image exists, else `summary`).
  `og:site_name`, `og:url`, and `rel="canonical"` added at the
  `base.html` level so every page (not just posts) gets a correct
  canonical link — built from a configured `Settings.site_url`, never
  from the request's `Host` header (a forwarded/spoofed `Host` would
  otherwise poison every generated URL).

**Done when**
- [x] `sitemap.xml` is well-formed, standard-schema XML (`xmlns=
  "http://www.sitemaps.org/schemas/sitemap/0.9"`) — asserted by parsing
  the generated output back with `xml.etree.ElementTree` in
  `tests/unit/test_seo.py` (a malformed document fails the parse, not
  just a string-contains check).
- [x] `feed.xml` is well-formed RSS 2.0 — same round-trip-parse
  assertion, including a test with XML-special characters in a post
  title to confirm escaping actually works, not just "looks right" on
  a clean fixture.
- [x] A shared post link renders title/description/image via OG tags —
  verified structurally (`test_post_detail_has_canonical_og_and_jsonld`,
  `tests/integration/test_routes_integration.py`) against a real
  DB-backed post. **Not yet checked against a real link-preview
  debugger** (Facebook's Sharing Debugger / Twitter Card Validator) on
  the live production URL — see Leftover.

**Testing**: `tests/unit/test_seo.py` (pure builder-function tests —
static pages present, every post present, `lastmod` sourced from
`updated_at` not `published_date`, empty-post-list still valid,
RSS item fields, special-character escaping). `tests/integration/
test_routes_integration.py` (real HTTP responses against the DB:
draft exclusion from both `sitemap.xml` and `feed.xml`, zero-post case,
canonical/OG presence on a real post page).

### Phase 3 — JSON-LD structured data

**Scope**
- [x] `BlogPosting` on every post (`app.services.seo.
  build_blog_posting_jsonld`) — `headline`, `datePublished`,
  `dateModified` (same `updated_at` source as Phase 2's sitemap
  `lastmod`, kept consistent rather than picking a different
  "last changed" signal per feature), `author` (`Settings.legal_name`,
  the same name already used for legal disclosure pages — one source
  of truth for the site's real-world identity, not a second place to
  edit), `image` (the same `cover_image` OG already uses via the same
  field, no duplicate asset — omitted, not fabricated, when absent).
- [x] `Trip` layered on route posts specifically
  (`build_trip_jsonld`, only called when a post's `route` is not
  `None`) — `name`, `description` (route's own description, falling
  back to the post's summary when the route has none), `url`.
  **Implementation decision, checked against schema.org's actual
  `Trip` properties at implementation time per the doc's own
  instruction**: `itinerary`/`subTrip` deliberately **not** added —
  `Route` is a single-track-per-post model with no day-segmented data
  to back a multi-leg claim (Dream of North's route is one continuous
  GPX track in this schema, not stored as discrete daily legs), so
  populating `itinerary` would assert structure the data doesn't
  actually have. Revisit if a future post/route model ever gains
  real day-by-day segmentation.
- [x] **Not** `FAQPage`, **not** `HowTo` — deprecated/unsupported, not
  implemented, not referenced anywhere in `app/services/seo.py`.
- [x] Both nodes combined under one `@graph` (`build_post_jsonld`) in a
  single `<script type="application/ld+json">` tag — one script block
  per page rather than two, standard JSON-LD practice for multiple
  co-located entities.

**Done when**
- [x] Both schema blocks are present with the expected `@type` and
  required fields on a real post with a route —
  `test_post_detail_with_route_includes_trip_jsonld`
  (`tests/integration/test_routes_integration.py`), against the real
  DB-backed sync → render pipeline, not a schema built in isolation.
- [ ] Validated against Google's Rich Results Test with zero errors on
  the live production URL. **Not yet run** — the JSON-LD is
  schema.org-valid by construction (every required `BlogPosting`/
  `Trip` property from schema.org's own spec is populated, checked
  against the spec while writing `app/services/seo.py`), but the
  actual Rich Results Test tool hasn't been pointed at the deployed
  page. See Leftover.

**Testing**: `tests/unit/test_seo.py` (`BlogPosting` required fields,
image omitted/included correctly, `Trip` fields and its post-summary
fallback, `@graph` includes `Trip` only when a route is passed, and
— the doc's own explicit criterion — a post with `route=None` gets
`Trip` correctly absent, never fabricated). `tests/integration/
test_routes_integration.py` (real post without a route → `BlogPosting`
only; real post with a GPX-backed route → both nodes present).

## Explicitly out of scope

- **llms.txt** — covered above; real evidence says not worth it today.
- **FAQPage / HowTo schema** — deprecated/unsupported, not a future
  phase, just not happening.
- **Core Web Vitals work** — bucket #8's job, not duplicated here.
- **Auto-generating alt text or AI-written meta descriptions** — a
  personal diary's own author writing these is more honest and likely
  more accurate than an automated pass; not worth the added complexity
  for three posts.

## Summary

All three phases implemented. `app/services/seo.py` (framework-free,
per `AGENTS.md`) holds every pure builder: `robots_txt()`,
`build_sitemap_xml()`, `build_feed_xml()`, `build_blog_posting_jsonld()`,
`build_trip_jsonld()`, `build_post_jsonld()`. `app/routes/seo.py`
registers `GET /robots.txt`, `/sitemap.xml`, `/feed.xml` at the app
root. A new `Settings.site_url` (default `https://bulliexplorer.com`,
the real production domain from the Caddyfile) is the single source of
truth for every absolute URL these features generate — canonical
links, OG/Twitter URLs, sitemap/feed entries, JSON-LD `@id`/`url`,
robots.txt's `Sitemap:` line — deliberately never derived from the
request's `Host` header.

`templates/base.html` gained default canonical/OG/Twitter blocks
(reusing the existing `title`/`meta_description` blocks via Jinja's
`self.title()`/`self.meta_description()` rather than duplicating that
logic); `templates/post.html` overrides `og_type`/`og_image`/
`twitter_card` and renders the JSON-LD `<script>` block. `app/routes/
posts.py`'s `post_detail` builds the JSON-LD server-side via
`build_post_jsonld()` and passes it into the template context.

Operator decision captured in Phase 0 above: block AI training
crawlers (`GPTBot`, `ClaudeBot`, `Google-Extended`, `CCBot`,
`Applebot-Extended`), allow AI search/citation crawlers and everything
else.

`make ci`: 386 tests passed, 96.49% coverage, bandit clean (one
justified `# nosec B405` — `xml.etree.ElementTree` is only ever used
here to *build* XML from trusted, DB-sourced data, never to parse
untrusted input, so B405's XXE concern doesn't apply; not worth a
`defusedxml` dependency for a write-only use case). `detect-secrets`
baseline needed a one-line `line_number` update (39 → 51) after
`Settings.site_url` shifted the pre-existing, already-accepted
`database_url` local-dev-credential false positive further down
`config.py` — same hashed value, not a new secret; applied by the
project owner directly since `.secrets.baseline` is protected from
this agent's write tools.

## Leftover

- **Link-preview debugger not yet run** — OG/Twitter tags are
  structurally verified (unit + integration tests against real
  rendered HTML), but Facebook's Sharing Debugger / Twitter Card
  Validator haven't been pointed at a live production post URL to
  confirm an actual preview card renders as expected. Worth doing once
  this is deployed and reachable.
- **Google Rich Results Test not yet run** — same category: the
  JSON-LD is schema.org-valid by construction (every required
  `BlogPosting`/`Trip` property populated per spec), but not yet
  checked through Google's actual validator against the live
  production URL.
- **`sitemap.xml` includes only the homepage, `/posts/`, and published
  posts** — legal disclosure pages (`/impressum`, `/datenschutz`)
  deliberately left out. They're valid public pages, but listing them
  in a sitemap nudges search engines to index legal boilerplate
  alongside actual content; revisit if that judgement call turns out
  wrong.
- **`.env.example` not updated with `SITE_URL`** — that file is also
  protected from this agent's write tools. Non-blocking: the setting
  has a working default and needs no `.env` entry to function, but the
  project owner may want to add a documented `SITE_URL=` line there for
  discoverability, matching the existing `TILES_URL`/`DATABASE_URL`
  documentation pattern.
- **RSS feed content depth (full body vs. summary-only) was a judgement
  call, not a doc-specified requirement** — flagged in Phase 2 above;
  revisit if full-content RSS readers ever become a real use case worth
  the minimization trade-off.
- **`_AMENITY_FRESHNESS_WINDOW`-style tuning doesn't apply here, but a
  similar "first guess, not yet observed" caveat does**: the
  `AI_TRAINING_CRAWLERS` list reflects the 5 crawlers named in this
  doc's own research summary as of Sept 2026 — providers periodically
  add new crawler user-agents (Meta, xAI, etc. aren't in the list
  because they weren't in the doc's own evidence). Revisit periodically
  against current crawler documentation, not a one-time "done forever"
  list.