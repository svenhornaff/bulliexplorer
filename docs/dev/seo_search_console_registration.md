# Search engine registration — Google Search Console + Bing Webmaster Tools

> Distinct from `seo_beyond_basics.md`, which covers what the *site
> itself* serves (sitemap, robots.txt, JSON-LD, OG tags). This doc
> covers the external, manual, one-time registration step: telling
> Google and Bing the site exists and asking them to actually crawl it
> — the missing piece confirmed by direct search: `sitemap.xml` going
> live doesn't mean anything's been crawled yet, and a search for
> "Dream of North gravel" currently surfaces nothing from the live
> site at all, only the unrelated GitHub repo.

---

## Why this is its own document, not a line item in the other one

`seo_beyond_basics.md` is about artifacts the server generates —
code, tested, deployed like everything else in this project. This is
about a **manual registration action** in an external platform's
console — nothing to unit test, nothing that lives in a Python module,
and the one piece of code it does need (a single meta tag) is small
enough that conflating it with the larger SEO doc would bury the actual
manual steps under unrelated implementation detail.

## The verification method — meta tag, not DNS

Google Search Console's **"Domain" property** requires DNS
verification — a TXT record at whichever provider hosts DNS (Route 53
for `bulliexplorer.com`), which is what pointed back to AWS.

**Recommended instead: a "URL prefix" property**
(`https://bulliexplorer.com`), which supports **HTML meta tag**
verification — one line in `<head>`, deployed the same way as
everything else in this codebase, no DNS console, no propagation wait.

**Trade-off, stated plainly so the choice is informed**: a Domain
property auto-covers every subdomain and both `http`/`https` variants
under one verification. URL-prefix only covers that exact prefix. For
this site — one domain, no subdomains, no `www.` variant in play — that
difference doesn't matter here. URL-prefix is fully sufficient.

## Phased plan

### Phase 1 — Google Search Console — code done, manual console steps pending

**Scope**
- [ ] Register a URL-prefix property for `https://bulliexplorer.com`.
  **Manual, external, not something this agent can perform** — no
  Google account access. See Leftover.
- [x] Add the verification meta tag to `templates/base.html`'s
  `<head>`, alongside the existing OG/Twitter tags:
  ```html
  <meta name="google-site-verification" content="<token>" />
  ```
  Implemented as `Settings.google_site_verification` (empty by
  default — a public verification value designed to be published in
  HTML, not a secret requiring the "no default" treatment `secret_key`/
  `resync_token` get), exposed as a Jinja global
  (`app/main.py`, same pattern as `site_url`) so every page's `<head>`
  gets it without threading it through each route's context dict. The
  tag renders only when the setting is non-empty — an empty/placeholder
  verification tag is worse than no tag at all. **The real token
  already exists in both the local and server `.env` files** (per this
  task's own instruction) — wired through `docker-compose.prod.yml`'s
  `GOOGLE_SITE_VERIFICATION` env passthrough, confirmed rendering live
  in production after deploy (see Summary).
- [ ] Submit `sitemap.xml` directly in Search Console (Sitemaps →
  Add a new sitemap) — this is the actual "please crawl this" signal,
  distinct from the sitemap file simply existing at a URL. **Manual,
  external** — see Leftover.
- [ ] Use "Request Indexing" (URL Inspection tool) on each of the
  three live posts individually. **Manual, external** — see Leftover.

**Done when**
- [ ] Search Console shows the property as verified. **Not done by
  this agent** — requires the operator's own Google account; the code
  side (the meta tag itself, live and correct in production) is the
  part this agent could actually complete.
- [ ] The sitemap shows as "Success" in Search Console's Sitemaps
  report. **Not done** — same reason.
- [ ] A repeat of the exact search that motivated this doc — "Dream of
  North gravel" — surfaces the actual post. **Not yet re-checked** —
  depends on the manual steps above happening first; re-check once
  they're done, not before (a search re-check today would just confirm
  what's already known: nothing's been submitted for crawling yet).

**Testing**: `tests/unit/test_search_console.py` — the one code change
(the meta tag) is unit-tested for both the configured and unconfigured
cases (real `Settings` + `monkeypatch` + `get_settings.cache_clear()`,
same pattern as `test_editor.py`'s R2-config tests —
`GOOGLE_SITE_VERIFICATION` is environment-dependent, and a real value
already exists in this developer's own `.env`, so the "unset" case
needs an explicit override to be testable at all). Everything else is
a manual console action with its own built-in verification step, not
something to unit test.

### Phase 2 — Bing Webmaster Tools — not started, manual/external

**Scope**
- [ ] Register at Bing Webmaster Tools. Worth checking at setup time
  whether it offers importing verification/site data directly from an
  already-verified Google Search Console account — if so, this is
  close to zero additional work once Phase 1 is done, not a second
  full registration process.
- [ ] Submit `sitemap.xml` there too — Bing doesn't share crawl data
  with Google, so this is a genuinely separate step, not redundant.

**Done when**: Bing Webmaster Tools shows the site verified and the
sitemap accepted, same bar as Phase 1. **Not done** — depends on a
Bing account this agent doesn't have access to; see Leftover. Bing's
verification also commonly supports a meta tag (same mechanism as
Google's), so if/when that's registered, the same
`Settings.google_site_verification`-style pattern (a new
`bing_site_verification` setting rendering its own meta tag) would be
the natural code-side counterpart — not built yet since there's no
token to wire in.

**Testing**: none, same reasoning as Phase 1.

### Phase 3 — Periodic check, not a one-time action

**Scope**
- [ ] A recurring (monthly is plenty at this scale) glance at Search
  Console's Coverage/Indexing report — confirms new posts are actually
  getting indexed as they're published, not just that the first three
  eventually were.

**Done when**: this becomes a habit, not a task with a checkbox — same
spirit as the token-rotation habit noted in `security_review_owasp.md`
Phase 4. A line in `docs/dev/` saying so is enough; this isn't code.
**Recorded here** as that written standard — the habit itself can't
start until Phase 1's registration exists to check.

## Explicitly out of scope

- **Paid search / Google Ads verification** — irrelevant, this site
  has no advertising per the legal classification work; nothing here
  should be confused with ad-account setup.
- **Other search engines beyond Google and Bing** (Yandex, Baidu,
  etc.) — not worth the registration overhead for a German/EU-focused
  personal blog; revisit only if there's a real reason to think readers
  are coming from elsewhere.

## Summary

The code-side half of this doc is done; the manual, external-console
half is not — and can't be, by this agent, since it requires the
operator's own Google/Bing account access.

**What's implemented**: `Settings.google_site_verification` (empty
default, same non-required pattern as `sentry_dsn`/`tiles_url` — a
missing verification token degrades gracefully to "no tag rendered",
not a startup crash, because it's a public value, not a secret).
Exposed as a Jinja global in `app/main.py` alongside the existing
`site_url` global, rendered conditionally in `templates/base.html`'s
`<head>`. Wired through `docker-compose.prod.yml`'s env passthrough.
The real token (already present in both local and server `.env`, per
this task's own starting instruction) required no `.env` changes on
either side — only the code path to actually read and render it was
missing.

**Verified live in production after `make deploy`**:
`curl -s https://bulliexplorer.com/ -L | grep google-site-verification`
returned the exact configured token, confirmed present in the actual
response HTML, not just asserted from settings/config.

**What's not done, and why**: registering the Search Console
URL-prefix property, submitting `sitemap.xml` there, using "Request
Indexing" on the three live posts, and the entire Bing Webmaster Tools
phase are all manual actions inside external SaaS consoles tied to the
operator's own Google/Bing accounts — the same category of blocker as
`security_review_owasp.md`'s SonarCloud account and this session's
repeated `.secrets.baseline`/`.env.example` file-protection pattern:
something only the operator can actually do. Unlike those, there's no
single command to hand off here (it's a multi-step console workflow,
not a one-line fix) — see Leftover for the concrete steps.

**Testing**: 2 new unit tests (`test_search_console.py`) — tag present
with the exact configured value when set, absent entirely when unset.
`make ci`: 398 tests passing (up from 396), 96.33% coverage, security
checks clean. `make deploy` completed; the live token check above was
run against the real deployed app, not asserted from configuration
alone.

## Leftover

- **Phase 1's manual Search Console steps** — all four remaining, in
  order: (1) sign in to Google Search Console with the operator's own
  Google account, add a URL-prefix property for
  `https://bulliexplorer.com`, verify via the "HTML tag" method (the
  meta tag is already live, so this should confirm instantly); (2)
  Sitemaps → Add a new sitemap → `sitemap.xml`; (3) URL Inspection
  tool → "Request Indexing" on each of the three live post URLs; (4)
  re-run the "Dream of North gravel" search from this doc's own
  motivating example after a few days to confirm the real completion
  signal, not just the console's own status indicators.
- **Phase 2, Bing Webmaster Tools, not started** — register, check
  whether it can import verification from the now-registered Google
  property, submit `sitemap.xml` there too. If Bing's own verification
  ends up being a meta tag (common), the natural code-side follow-up
  is a `bing_site_verification` setting mirroring
  `google_site_verification` exactly — not built yet since there's no
  token to wire in, and building a setting for a token that doesn't
  exist yet isn't useful.
- **Phase 3, the periodic-check habit** — can't meaningfully start
  until Phase 1's registration exists; noted here as the standard to
  follow once it does, same as the token-rotation habit in
  `security_review_owasp.md`.
- **`.env.example` not updated with `GOOGLE_SITE_VERIFICATION`** — that
  file is protected from this agent's write tools (same limitation
  encountered in `seo_beyond_basics.md`'s Leftover for `SITE_URL`, and
  neither has been added there since). Non-blocking: the setting has a
  working empty default and needs no `.env` entry to function, but the
  operator may want to add documented `SITE_URL=`/
  `GOOGLE_SITE_VERIFICATION=` lines there for discoverability at some
  point, matching the existing `TILES_URL`/`DATABASE_URL` pattern.