# Legal/GDPR refactor — personal/family classification, evaluated

> A proposal was submitted (full text preserved below as the reference
> spec) arguing BulliExplorer qualifies as an "exclusively private and
> non-commercial" personal diary under § 18 Abs. 1 MStV's
> personal/family exemption — and on that basis should **not** publish
> a residential address at all, rather than publishing one via a
> virtual-address service as `legal_gdpr.md` was previously extended to
> cover. This doc evaluates that proposal honestly before either gets
> built, and designs the code so the actual classification decision
> stays explicit and reversible, not baked in as an assumption.

---

## The central tension — worth stating plainly before anything else

**§ 18 Abs. 1 MStV's personal/family exemption is real and citable** —
the "private family holiday-photo page" example the proposal cites is a
genuine, commonly-referenced illustration of it. That part isn't in
question.

**What's genuinely uncertain is whether it's the safe classification
for *this specific site*.** Two things pull in opposite directions, and
neither can be waved away:

- **Toward "exempt"**: no ads, no affiliate links, no sponsorship, no
  donations, no paid features, no revenue — everything the proposal
  lists as evidence of non-commercial intent is factually true, checked
  against the actual code and content.
- **Toward "needs a real Impressum"**: this project's own roadmap
  (`buckets.md`, bucket #4) explicitly wants the site *not* invisible
  to search — sitemap, RSS, OpenGraph tags, structured data, all
  planned specifically to broaden public reach. A site actively pursuing
  search discoverability, built on production-grade infrastructure
  (CI/CD, monitoring, automated backups, a real deployment pipeline),
  sits further from "a private family holiday page shared with people
  who already know it exists" than the proposal's framing suggests. The
  German "geschäftsmäßig" test under the base § 5 DDG requirement has
  historically been read broadly by courts — closer to "operated on an
  ongoing, systematic basis" than "makes money" — which is a
  meaningfully different bar than the proposal's argument addresses.

**Neither position is obviously wrong. Both are genuinely arguable.**
That's exactly why this shouldn't be decided by defaulting to whichever
reading the code makes easiest to implement — it needs to be a
deliberate choice, made with the actual risk tolerance and ideally a
real legal check, not settled by which markdown file happened to get
written last.

## What this means for the design, not just the decision

The existing `legal_gdpr.md` safety net — refuse to publish (`503`) 
rather than serve an Impressum with a missing required field — was
built on exactly the right instinct: **an incomplete legal page is worse
than no page, so don't silently ship one.** The same instinct should
apply here: **defaulting to "personal/family, no address needed" is
itself an assumption, and an incorrect one carries real Abmahnung
risk** — no less real than the missing-address case the `503` already
guards against. The fix isn't picking one classification and building
only for it; it's making the classification an explicit, visible
configuration choice, with neither option as a silent default.

## Recommended design

**A single explicit setting, no default that assumes either
classification**:

```python
# app/core/config.py
legal_classification: Literal["personal", "commercial"] | None = None
```

`None` (unset) behaves like today's missing-value case — `503` on the
legal pages in production, forcing a deliberate choice before anything
publishes, exactly like the existing address-field guard.

- **`"personal"`**: renders the English/German personal-diary notice
  from the proposal's Section 3 — no address rendered, no
  `LEGAL_ADDRESS` required. `/privacy` still required and unaffected;
  the personal/family exemption is about provider *identification*
  (§ 5 DDG / § 18 MStV), not about GDPR, which the proposal itself
  correctly says remains fully in force either way (Section 4).
- **`"commercial"`**: today's existing behavior — full Impressum,
  `LEGAL_ADDRESS` required (the virtual-address guidance already in
  `legal_gdpr.md` applies here, unchanged).

Both code paths already mostly exist or are small additions — this
isn't a rewrite, it's making an implicit either/or into an explicit,
visible one.

## Everything else in the proposal — genuinely good, adopted as-is

Worth being clear this isn't a wholesale pushback — most of the
proposal is sound, evidence-based, and consistent with how this
project's legal work has been built so far:

- **Section 4's boundary** (no Impressum ≠ no privacy obligations) is
  exactly correct and already how `/privacy` is architected —
  unaffected by which classification wins.
- **Section 6's infrastructure audit instructions** (Caddy, Sentry,
  Cloudflare, Nominatim/Overpass, external resources) — this is the
  same rigor `privacy_data_flows.md` already applied; nothing to
  re-litigate, already done in that doc.
- **Section 9's regression guard** (ads, comments, analytics, hosting
  changes, etc. all require re-review) — genuinely good practice,
  worth adding to project docs regardless of which classification is
  chosen.
- **"Do not invent retention periods, mark unknowns as REQUIRES
  OPERATOR VERIFICATION"** — exactly the posture `legal_gdpr.md`
  already takes ("Do not claim contracts are signed until verified").

## Phased plan

**Status: code implemented and deployed (Phases 0–4); production
content still blocked on one operator-owned `.env` value, not a code
gap.** `LEGAL_CLASSIFICATION=personal` decided (Phase 0) and shipped;
see `docs/dev/legal_gdpr.md`'s "Legal classification" section for the
operative summary and the regression guard. Phase 3 closed the
code/deployment gap between "config value decided" and "actually live"
(missing compose passthrough + bare-JSON 503) — both confirmed fixed by
direct `curl` against production on 2026-09-18. Phase 4 (also
2026-09-18) made `LEGAL_ADDRESS` optional for `/datenschutz` specifically
— per operator decision, GDPR Art. 13 contact-details wording is
satisfied by name + email alone for this page; `/impressum`'s separate
§ 5 DDG address requirement is unaffected. `/impressum` and
`/datenschutz` both still return `503` in production, correctly, pending
only `LEGAL_EMAIL` — see Phase 3's "Still open" note.

### Phase 0 — The classification decision itself (not a code task)

This is the one step that has to happen first, and it's not something
a commit resolves. Worth writing down explicitly rather than letting it
stay implicit: weigh the SEO/discoverability ambition against the
personal/family exemption's narrower, safer scope, and decide — ideally
with a real legal check given actual Abmahnung exposure either way, not
inferred from web research alone (same caveat `legal_gdpr.md` already
states for the address-service question).

**Done when**: `LEGAL_CLASSIFICATION` has a real, deliberate value —
not left unset by default, not set reflexively to whichever is less
work.

**Decided: `personal`**, after legal advice (2026-09-17). Applied to
local `.env` and the production server's `.env` (both edited by the
operator directly — outside this repo, as `.env` is gitignored and
protected from automated edits by design).

### Phase 1 — Config + branching render logic — done

**Scope**
- [x] `legal_classification` setting as above, `None` triggers the same
  `503`-on-missing-required-value path already in `_render_legal`.
- [x] `"personal"` path: new Markdown source
  (`content/legal/impressum_personal.md`) using the proposal's Section 3
  text, English primary / German notice retained as specified, no
  address substitution required.
- [x] `"commercial"` path: existing `content/legal/impressum.md` +
  `LEGAL_ADDRESS` requirement, unchanged.
- [x] `/datenschutz` kept as-is (not renamed to `/privacy`) — already
  linked/indexed, and the proposal's own Section 4 boundary (provider ID
  vs. GDPR controller ID) doesn't require a URL change, only that the
  page's required fields stay independent of `legal_classification`,
  which they do (`page == "datenschutz"` branch is untouched by the new
  classification check).

**Done when** — verified:
- Setting `LEGAL_CLASSIFICATION=personal` renders the personal-diary
  notice with no address anywhere in the response —
  `test_classification_personal_renders_no_address_notice`.
- Setting `LEGAL_CLASSIFICATION=commercial` renders exactly today's
  existing behavior, unchanged —
  `test_classification_commercial_matches_existing_behaviour`.
- Leaving it unset still `503`s in production, same safety net as today
  (now covering **both** `/impressum` and `/datenschutz`, not just
  whichever field happened to be blank) —
  `test_classification_unset_refuses_in_production`.
- `/datenschutz` still requires its own fields (including address)
  under `personal` classification —
  `test_classification_personal_still_requires_datenschutz_fields`.

**Testing**
- `tests/unit/test_legal.py`: 6 new tests (personal render, personal
  missing-email 503, personal-doesn't-weaken-datenschutz, commercial
  unchanged, unset-503s-both-pages) plus the existing
  `test_production_legal_pages_with_verified_values` updated to set
  `LEGAL_CLASSIFICATION=commercial` explicitly (it previously relied on
  the pre-refactor implicit default). 12/12 pass;
  `make ci` green (333 tests, 96.17% coverage).

**Files touched**: `app/core/config.py`, `app/routes/legal.py`,
`content/legal/impressum_personal.md` (new), `tests/unit/test_legal.py`,
`.env.example` / `docs/dev/deployment.md` (`.env` template),
`docs/dev/legal_gdpr.md` (operative summary + regression guard).

### Phase 2 — Regression guard as an actual project artifact — done

**Scope**
- [x] Section 9's list added to `docs/dev/legal_gdpr.md` as a standing
  "Regression guard" checklist under the new "Legal classification"
  section — the point isn't the list itself, it's that a future "add
  comments" or "add analytics" change has something concrete to check
  against before shipping, not just good intentions.

**Done when**: the checklist exists somewhere a future change would
actually be checked against, not just in this doc's history. ✅
`docs/dev/legal_gdpr.md` → "Legal classification (personal vs.
commercial)" → "Regression guard".

### Phase 3 — Closing the deployment gap (code shipped, production wasn't actually live) — done

Phase 1 shipped `LEGAL_CLASSIFICATION` in `app/core/config.py` and the
server's `.env` was updated to `personal` (2026-09-17), but the site was
still 503ing live — the same "code ready, deployment isn't" gap this
project has hit before (`docs/dev/monitoring_ops.md` Phase 4's restore-test
gap is the same shape). Two independent causes, both found by SSHing into
the production host and checking what the running container actually saw,
not just what the repo/docs claimed:

1. **`docker-compose.prod.yml` never passed `LEGAL_CLASSIFICATION`
   through to the container.** Commit 9980066 added the setting to
   `app/core/config.py` and updated `.env`/`.env.example`/docs, but never
   added the matching `LEGAL_CLASSIFICATION=${LEGAL_CLASSIFICATION:-}`
   line to the compose file's `app.environment` block — the same block
   every other `LEGAL_*` var already passes through. `docker compose exec
   app env | grep LEGAL` on the server confirmed the var simply wasn't
   present inside the container, so `settings.legal_classification`
   silently evaluated to `None` regardless of what `.env` said. Fixed by
   adding the passthrough line. **Regression guard**: a new
   `tests/unit/test_config.py::test_docker_compose_prod_passes_through_every_legal_setting`
   parses `docker-compose.prod.yml` and asserts every `legal_*`
   `Settings` field has a matching `LEGAL_*` passthrough line — the next
   `legal_*` field added to `config.py` without a compose-file update now
   fails CI instead of silently 503ing in production.
2. **The 503 rendered as bare JSON** (`{"detail": "Rechtliche Angaben
   werden vervolländigt."}`), FastAPI's default `HTTPException` body —
   reported by the operator as "an API endpoint is showing when touching
   the url", correctly: to a site visitor a naked JSON error looks like a
   broken API, not unpublished HTML content. `/impressum` and
   `/datenschutz` are the only HTML-rendered routes with a
   raise-on-missing-config path; every other route's `HTTPException`
   (health checks, the webhook, future API routes) is correctly JSON and
   must stay that way. Fixed with a dedicated `LegalContentUnavailable`
   exception (raised only by `app/routes/legal.py`) and an
   `app.exception_handler(LegalContentUnavailable)` registered in
   `app/main.py`'s `create_app()` that renders the site's own
   `templates/legal_unavailable.html` shell at `503` — scoped to exactly
   these two routes, zero change to how any other endpoint's errors render.

**Done when** — verified against the live host, not just tests:
- `curl -s https://bulliexplorer.com/impressum` and `/datenschutz` both
  return `200` with the site's HTML chrome (nav/footer), not a bare JSON
  body.
- `make ci` stays green with the new compose-passthrough guard and the
  new `test_production_unavailable_renders_branded_html_not_json` test
  (branded-HTML-503 regression coverage) — 336 tests, 96.19% coverage.

**Files touched**: `docker-compose.prod.yml`, `app/routes/legal.py`
(`LegalContentUnavailable`), `app/main.py` (handler registration),
`templates/legal_unavailable.html` (new), `tests/unit/test_config.py`,
`tests/unit/test_legal.py`.

**Still open — not resolved by this phase, both confirmed live on
2026-09-18**: fixing the passthrough and the error page did not by
itself make either page publishable, because the *content* values are
still missing on the server — verified with `curl https://bulliexplorer.com/impressum`
and `/datenschutz`, both still `503` (branded HTML now, not bare JSON).

- **`/impressum`** needs only `LEGAL_EMAIL` under `personal`
  classification (no address required) — confirmed empty on the server
  (`docker compose exec app env | grep LEGAL_EMAIL` → empty). **Operator
  decision (2026-09-18): will set it directly on the server** — no code
  change, `.env` is gitignored/protected from automated edits by design.
- **`/datenschutz` originally still required `LEGAL_ADDRESS`** regardless
  of classification at the time this note was first written — superseded
  the same day by Phase 4 below, which made `LEGAL_ADDRESS` optional for
  `/datenschutz` specifically. Kept here for the historical record of
  what Phase 3's live-verification pass actually found before that
  decision.

Set `LEGAL_EMAIL` remains a deliberate, operator-owned `.env` edit
outside this repo, not a follow-up code task. Re-run the same live-`curl`
check after it's set to confirm `/impressum` actually renders `200`, not
just that `.env` was edited — the passthrough bug this phase fixed is
exactly why "`.env` says X" and "the container sees X" aren't the same
claim.

### Phase 4 — `/datenschutz` must render without `LEGAL_ADDRESS` — done

Operator instruction (2026-09-18), overriding Phase 1's original
design: **`/datenschutz` must render without `LEGAL_ADDRESS`, full
stop** — no residential address, and no waiting on a virtual-address
service either. Rationale given: GDPR Art. 13(1)(a) requires "the
identity and the contact details of the controller," but the statutory
text does not name a postal address specifically (unlike § 5 DDG's
explicit "ladungsfähige Anschrift" language, which is a different duty
for a different page). Name + a dedicated BulliExplorer contact email is
treated as sufficient contact details for `/datenschutz`'s
Verantwortlicher section. This is a genuinely unsettled question in
general (German legal commentary tends to expect a postal address; the
regulation's own text does not require one explicitly) — recorded here
as the operator's considered call for this specific personal blog, not
as a claim that the question is settled generally.

**Scope, `app/routes/legal.py`**:
- `/datenschutz`'s `required` list drops `address` (kept: `email`,
  `hosting`, `log_retention`, `cloudflare_details`, `sentry_details`
  when a DSN is set) — empty `LEGAL_ADDRESS` no longer 503s
  `/datenschutz`.
- The commercial `/impressum` path is unchanged — `address` stays
  required there (§ 5 DDG Impressumspflicht is a different duty for a
  different page, untouched by this decision). This split is now an
  explicit `if page == "datenschutz": ... else: ...` in the code, not an
  implicit shared list, specifically so the two duties can't
  accidentally re-merge in a future edit.
- When `LEGAL_ADDRESS` is empty, the `{{address}}` line is stripped from
  the rendered Markdown source entirely (not replaced with a
  `[Noch einzutragen: address]` placeholder like every other missing
  field) — the address is absent by design here, not a to-do item.

**Testing**: `test_datenschutz_renders_without_address_in_production`
(200 with empty `LEGAL_ADDRESS`, no placeholder text either);
`test_classification_personal_still_requires_datenschutz_hosting_fields`
renamed/re-scoped from the old address-focused test to assert the
*other* required fields still 503 correctly;
`test_production_refuses_missing_disclosures` re-scoped off
`LEGAL_ADDRESS` onto `LEGAL_EMAIL` as the missing-field case common to
both pages. `make ci` green: 336 tests, 96.13% coverage.

**Files touched**: `app/routes/legal.py`, `tests/unit/test_legal.py`,
`docs/dev/legal_gdpr.md` ("`LEGAL_ADDRESS` specifically" section and the
"Legal classification" section both updated to reflect the split), this
file.

**Still open**: `LEGAL_EMAIL` is still empty on the server — both pages
remain `503` in production until the operator sets it (see Phase 3's
note above). Setting it is the only remaining step to actually publish
both pages.

## Explicitly out of scope

- **Building only the "personal" path and removing the existing
  commercial/address machinery** — the proposal's Step 2 suggests
  this, and it's the one instruction from it this doc deliberately
  doesn't adopt as written. Removing a working, tested safety path to
  replace it with an unverified assumption is a net increase in risk,
  not a simplification — keep both, gated by an explicit choice.
- **Actually deciding the classification** — that's Phase 0, and it's
  not a code decision this doc or any implementation can make.