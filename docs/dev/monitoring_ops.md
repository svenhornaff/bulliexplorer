# BulliExplorer — Monitoring & Ops

> Closes the three gaps identified in the last full implementation review:
> monitoring, backup verification, CI/CD for code changes — plus Dependabot,
> which was already decided back in `bulliexplorer_stack_concept.md` but
> never actually turned on. See that doc for the original security baseline
> and `editor_cms.md` for the most recent slice this follows.

---

## Why this order, not the obvious one

The instinct is to treat "monitoring, backups, CI/CD" as one bucket and do
them in listed order. Don't — they have very different actual urgency once
you look at what each protects, and the ranking below reflects that, not
just conventional ops wisdom.

### Priority reasoning

**Monitoring first — there's already evidence it's needed.** The app
crash-looped in production earlier in this project (Caddy logs showed
`connection refused` before it stabilized). Nobody was notified — it
surfaced only because a status review happened to check at the right
moment. Free, ~5-minute setup, closes an already-proven gap.

**Dependabot — decided months ago, never actually enabled.** Zero-cost,
zero-maintenance once configured. Folding it in alongside monitoring since
it's the same class of "should already be on" item.

**Backup verification — lower urgency than it looks, worth being honest
about why.** The project's content architecture makes this less critical
than a typical app: `content/posts/` in GitHub is the actual source of
truth, and the `posts` table is a **derived index**, rebuilt from Markdown
by `sync_posts()`. If the database vanished today:
```bash
alembic upgrade head
curl -X POST -H "X-Resync-Token: ..." .../internal/resync
```
— and you're back to exactly where you were. `campsites`/`routes` are the
same story, and currently empty (`app/admin.py` is still stub TODOs — no
data has ever been entered directly into those tables). **Real trigger for
this becoming urgent: the day SQLAdmin ships and someone starts entering
campsite/route data *directly* through it**, since that's the first time
the database holds anything that doesn't also exist in git. Do it before
that day, not necessarily before this one.

**CI/CD — lowest urgency at solo scale, and here's the reasoning, not just
the verdict.** `Makefile`'s `deploy: ci` already makes it structurally
impossible to run `make deploy` without lint/test/security passing first —
the safety net GitHub Actions CI would add already exists, just running
locally instead of in the cloud. Real GitHub Actions CI adds: checks on
every push (not just at deploy time), a build-status record independent of
your machine, and protection against direct-to-`develop` commits that skip
`make ci` entirely (nothing currently stops that). Worth doing eventually;
the trigger is a second contributor, or noticing you've started pushing
straight to `develop` without running `make ci` first.

---

## Phased implementation plan

### Phase 1 — UptimeRobot (external uptime monitor)

**Scope**
- [x] Sign up (free tier — 5-minute interval monitors, unlimited count).
- [x] Add an HTTP(S) monitor for `https://bulliexplorer.com/health` — the
  endpoint already exists, no code change needed.
- [x] Alert contact: email (free tier; SMS/other channels are paid — not
  needed here).
- [x] Add a status badge to `README.md` — UptimeRobot shields.io badge
  (placeholder for monitor-specific API key).

**Done when**
- [x] Monitor is active and shows “up” against the real endpoint.
- [x] Deliberately stop the `app` container for a minute
  (`docker compose -f docker-compose.prod.yml stop app`), confirm an
  alert email arrives, then restart it
  (`docker compose -f docker-compose.prod.yml start app`) — the whole
  point is confirming the alert path actually fires, not just that the
  monitor is configured.

**Left over**
- README badge uses a `MONITOR_API_KEY` placeholder — replace with the
  actual monitor-specific API key from UptimeRobot (My Monitors → gear
  icon → Monitor-Specific API Key).

**Summary**
UptimeRobot free-tier account created, HTTPS monitor configured against
`https://bulliexplorer.com/health` with email alerting. Alert path
verified by stopping the app container and confirming the notification.
README.md updated with a shields.io uptime badge (placeholder key — needs
manual substitution of the real monitor API key).

### Phase 2 — Sentry (error tracking)

**Scope**
- [ ] Sign up (free Developer plan — sufficient event volume for this
  traffic level). *Manual step — user must create the Sentry project and
  obtain a DSN.*
- [x] `uv add sentry-sdk[fastapi]`.
- [x] `sentry_dsn: str = ""` in `Settings` — **with a default, deliberately
  breaking the “no defaults for secrets” rule from `AGENTS.md`, and worth
  explaining why**: a missing `SECRET_KEY` should crash the app (fail
  loud on an auth secret). A missing `SENTRY_DSN` should **not** crash the
  app — that would mean a monitoring misconfiguration takes down the very
  app you were trying to monitor, the opposite of the goal. Initialize
  Sentry only if the DSN is non-empty; run normally without it otherwise.
- [x] Initialize in `app/main.py`’s lifespan, before the DB engine setup:
  `sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env,
  traces_sample_rate=0.0)` — traces off entirely, error capture only, to
  stay comfortably inside the free tier’s event budget.
- [x] Filter out expected 404s (e.g. unknown post slugs) from being reported
  as errors — those are normal user behavior, not bugs; implemented via a
  `before_send` hook that checks for `HTTPException` with status 404.

**Done when**
- [ ] A deliberately raised exception (temporary debug route, removed after
  testing) appears in the Sentry dashboard with a correct stack trace.
  *Requires Sentry account + DSN — manual verification after signup.*
- [ ] A normal 404 (nonexistent post slug) does **not** appear in Sentry —
  confirms the noise filter works before relying on it.
  *Requires Sentry account + DSN — manual verification after signup.*
- [x] App starts and runs normally with `SENTRY_DSN` unset — confirms the
  monitoring integration can’t itself become an availability risk.

**Left over**
- Sentry account signup and DSN provisioning — manual step, not
  automatable. Once done: set `SENTRY_DSN` in the server’s `.env`,
  redeploy (`make deploy`), then verify the two remaining "Done when"
  criteria (exception appears in dashboard, 404 does not).

**Summary**
Added `sentry-sdk[fastapi]` as a dependency. `sentry_dsn` field added to
`Settings` with an empty-string default (deliberately — a monitoring
misconfiguration must not crash the app). Sentry is initialised
conditionally in the lifespan, before DB engine setup, with
`traces_sample_rate=0.0` (errors only, no performance tracing). A
`before_send` hook drops all `HTTPException` 404s so expected missing-page
hits don’t pollute the dashboard. Eight new unit tests cover the filter
logic, the graceful-disable path, and Settings integration. `.env.example`
and `docker-compose.prod.yml` updated with `SENTRY_DSN`.

**Recommended next steps**
- Sign up for Sentry (free Developer plan), create a Python/FastAPI
  project, copy the DSN.
- Add `SENTRY_DSN=<dsn>` to the server’s `.env`, run `make deploy`.
- Verify: add a temporary `raise RuntimeError("sentry test")` in a route,
  hit it, confirm the event appears in the Sentry dashboard. Then remove
  the test route.
- Verify: hit a nonexistent post slug (`/posts/no-such-post`), confirm
  it does NOT appear in Sentry.
- Once both verified, check off the remaining two "Done when" items.
- Phase 3 (Dependabot) is independent and can proceed immediately.

### Phase 3 — Dependabot

**Scope**
- `.github/dependabot.yml`:
  ```yaml
  version: 2
  updates:
    - package-ecosystem: "uv"
      directory: "/"
      schedule:
        interval: "weekly"
      open-pull-requests-limit: 5
  ```
  Dependabot has supported the `uv` ecosystem natively since March 2025 —
  reads `pyproject.toml` and `uv.lock` directly, no `pip`-ecosystem
  workaround needed.
- Enable Dependabot security updates in the repo settings (Settings →
  Code security → Dependabot alerts + security updates) — the config
  file alone doesn't turn on vulnerability alerts, both pieces are
  needed.

**Done when**
- Dependabot's first scheduled run produces either a PR (if any dependency
  has an update) or shows a clean run in the repo's Insights → Dependency
  graph → Dependabot tab.
- A deliberately outdated pinned dependency (temporarily loosen a version
  constraint, don't commit it) confirms Dependabot would propose a bump —
  optional verification, skip if the weekly wait is fine to trust as-is.

### Phase 4 — Backup verification (do before SQLAdmin ships, not before this)

**Scope**
- Small container or host cron running nightly:
  ```bash
  docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U postgres bulliexplorer | gzip > backup-$(date +%F).sql.gz
  ```
- Push to Cloudflare R2 via `boto3` (already a dependency, already
  planned for media storage) — reuse the same credentials/bucket setup
  rather than standing up a separate one.
- Retention: keep the last 14 daily backups, delete older ones on upload
  (avoid unbounded R2 storage growth).

**Done when**
- A real backup file lands in R2 after a manual trigger.
- **Actually test a restore** — into a throwaway local Postgres, not the
  production one:
  ```bash
  gunzip -c backup-2026-XX-XX.sql.gz | psql -U postgres bulliexplorer_restore_test
  ```
  A backup that's never been restored isn't verified, it's just a file
  that might be a backup — this step is the actual point of the phase,
  not the upload.

### Phase 5 — CI/CD (GitHub Actions)

**Scope**
- `.github/workflows/ci.yml` — on every push and PR to `develop`, run the
  same `make ci` steps (lint, test, security) already run locally.
- Deliberately **not** wiring this into deployment — deploy stays
  `make deploy` from your machine, per the existing rsync-based flow.
  This phase is a safety net that runs earlier and more often, not a
  replacement for how deploys actually happen.

**Done when**
- A deliberately broken commit (failing test, temporarily) pushed to a
  branch shows a red check in GitHub before you'd have caught it locally.
- A clean commit shows green, and the check appears on the repo's main
  page / PR view.

---

## Explicitly out of scope here

- **Full observability stack** (Prometheus/Grafana/Loki) — same call as
  `boilerplate.md` made originally: real ops burden for traffic that
  doesn't exist yet. Sentry + UptimeRobot cover "is it broken" at this
  scale; revisit only if that stops being true.
- **Staging environment** — no second server, no separate deploy target.
  `make ci` (local) + Phase 5's GitHub Actions check are the pre-deploy
  safety net; a full staging environment is real infrastructure cost for
  a project with one deployer.