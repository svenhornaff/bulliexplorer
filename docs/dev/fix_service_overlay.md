# Investigation: `Fetch failed loading` console messages on the map overlay

> **Resolution: not a bug.** This was a misread of ordinary browser
> console noise, not a real server-side problem. See below for the full
> (initially wrong) investigation and how it was corrected — kept for the
> record, since the false lead (R2 dev-URL throttling) is a plausible
> trap worth remembering not to repeat.

## Symptom

The MapLibre overlay on post pages showed repeated console messages:

```text
pmtiles.js:1205 Fetch failed loading: GET
  "https://pub-95f3f9a68cdd43998a000b1a75b2ce4c.r2.dev/tiles/europe.pmtiles".
```

Route line and stats always rendered correctly (pure client-side
GeoJSON/GPX math, no dependency on the basemap) — only console noise
about the tile fetch was in question.

## What this actually was

A direct Network-tab inspection (not just the Console tab's summarized
log lines) showed the real picture: **every completed request succeeded**
— real `200`/`206` responses, no `429`, no `5xx`, nothing resembling a
server-side rejection anywhere. The only entries that looked like
failures were a handful marked **`(canceled)`**, each `0.0 kB`, each
resolving in under 70 ms.

`(canceled)` means the *browser client* aborted the request — the server
never got a chance to respond either way. This is normal, correct
behavior for an interactive tile map: when you pan or zoom, `pmtiles.js`
uses an `AbortController` (confirmed directly in the vendored source,
`static/vendor/pmtiles.js` around the fetch call at line ~1195) to cancel
in-flight tile requests for locations you've scrolled away from, so it
doesn't waste bandwidth completing a fetch for a tile no longer needed.

The `Fetch failed loading: GET <url>` message itself is not something
`pmtiles.js` logs — it's **Chrome DevTools' own built-in console entry
for any rejected `fetch()` promise**, and Chrome's console does not
distinguish "the server rejected this" from "the app told me to abort
this." A deliberate, correct cancellation and a genuine network failure
produce the identical-looking console line. There is nothing
project-specific or fixable here; it's how Chrome's console always
behaves for aborted fetches.

**Confirmed by direct correlation**: the `(canceled)` rows only appear
during active panning/zooming, never while the map sits still — exactly
the signature of intentional cancel-on-pan behavior, not intermittent
server failure.

## The abandoned hypothesis (kept for the record)

Before checking the raw Network tab, the working theory was that this
was intermittent throttling on Cloudflare R2's free `pub-*.r2.dev`
development URL, with a proposed fix of migrating `TILES_URL` to a
Cloudflare custom domain via a Route 53 → Cloudflare subdomain
delegation (`media.bulliexplorer.com`). That diagnosis was built on a
real but incomplete signal — the *volume* of console messages looked
alarming — without first checking whether those console entries
corresponded to real HTTP failures at all. They didn't.

This is the same class of mistake as the earlier "Object Read & Write
permission gap" detour before the actual CORS-ordering bug was found in
Phase 5 of `gis_cycling_upgrade.md`: a plausible-sounding infrastructure
explanation, arrived at before checking the most direct evidence
available (the raw Network tab / a real preflight request). Worth
remembering: check the cheapest, most direct evidence first, before
reaching for a multi-phase infrastructure fix.

**No DNS delegation, custom domain, or `TILES_URL` change is needed.**
The `pub-*.r2.dev` URL is fine for this tileset at its current traffic
level. If real server-side throttling ever *is* observed (actual `429`s
or `5xx`s in the Network tab, not just console noise), the custom-domain
plan sketched in the abandoned draft of this doc remains a reasonable
fix to revisit at that point — just not needed now.

## Recommended next steps

None required. If this class of console noise causes confusion again in
the future, the fast diagnostic is: open the Network tab (not just
Console), filter to the fetch in question, and check the `Status` column
before assuming a server-side cause — `(canceled)` at `0.0 kB` is the
tell for a client-side abort, not a failure.
