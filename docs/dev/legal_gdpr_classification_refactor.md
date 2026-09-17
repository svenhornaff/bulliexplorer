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

**Status: implemented.** `LEGAL_CLASSIFICATION=personal` decided (Phase 0)
and shipped; see `docs/dev/legal_gdpr.md`'s "Legal classification" section
for the operative summary and the regression guard.

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

## Explicitly out of scope

- **Building only the "personal" path and removing the existing
  commercial/address machinery** — the proposal's Step 2 suggests
  this, and it's the one instruction from it this doc deliberately
  doesn't adopt as written. Removing a working, tested safety path to
  replace it with an unverified assumption is a net increase in risk,
  not a simplification — keep both, gated by an explicit choice.
- **Actually deciding the classification** — that's Phase 0, and it's
  not a code decision this doc or any implementation can make.