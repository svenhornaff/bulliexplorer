---
title: E2E Fixture — With Route
slug: e2e-fixture-with-route
date: 2026-01-01
summary: Stable Playwright smoke-test fixture — has a route (map + elevation chart).
draft: false
route:
  name: E2E Fixture Loop
  gpx_file: e2e_fixture.gpx
  description: 'Synthetic loop, not a real ride — see docs/dev/playwright_e2e_smoke_tests.md.'
points_of_interest:
  - name: E2E Fixture Hut
    category: shelter
    lat: 47.8790
    lng: 8.0040
    notes: ''
galleries: []
callouts: []
---

Stable fixture post for the Playwright e2e smoke-test tier
(`docs/dev/playwright_e2e_smoke_tests.md`). Has a route, so this post
exercises the map canvas + elevation chart checks. Not real content —
checked into `tests/e2e/fixtures/`, never synced into the production
database.
