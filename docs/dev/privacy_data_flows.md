# BulliExplorer data-flow matrix

Repository evidence on `legal-gdpr`, based on `develop` commit
`30b9108c4aced0b44093e2565dcf22fd4bf3ba52`. Runtime provider configuration
and provider contracts are not established by checked-in code.

| Flow / evidence | Data / recipient | Purpose / proposed basis | Retention / transfers / release action |
| --- | --- | --- | --- |
| Website delivery; `Caddyfile`, `Dockerfile` | IP and HTTP metadata to actual host | Content delivery and security; Art. 6(1)(f) | Verify host logs, AVV and actual provider identity; no Caddy access log configured, production Uvicorn access log now disabled |
| App operational logs; `app/routes/internal.py` | Error/operational text to host | Operations; Art. 6(1)(f) where personal | Resync client-address log removed; container rotation is a size limit, not a timed deletion guarantee; set actual retention |
| Optional server Sentry; `app/main.py` | Exceptions/stacktraces and minimized request context to Sentry | Error correction; Art. 6(1)(f), document balancing | No bodies, frame locals, default PII or traces; callback drops user/extra/breadcrumbs and sensitive request fields; verify DPA, region, event retention, transfer safeguards; error text/path may still identify people |
| Direct PMTiles; `app/core/config.py`, map template | Visitor IP/HTTP metadata to Cloudflare | Map delivery; Art. 6(1)(f), document necessity/balancing | Verify recipient, request-data retention, DPA, EU bucket jurisdiction and international transfer details; EU object storage alone does not settle all processing |
| Published R2 image URLs / CMS media config | Browser IP/HTTP metadata to Cloudflare | Media delivery; Art. 6(1)(f) | Same provider review; also audit authored media URLs for other hosts |
| Nominatim; `app/services/geo_sync.py` | Server IP, place queries to OSM service | Background editorial geocoding, no reader IP forwarded | Do not submit private/confidential addresses; maintain identification and rate limits |
| Overpass; `app/services/overpass.py` | Server IP and geometry queries to configured Overpass services | Background amenity discovery, no reader IP forwarded | Avoid private route disclosure; cache/rate-limit; no per-reader API connection |
| Theme; `templates/base.html` | Light/dark choice stored solely on device | Explicitly requested display setting; §25(2)(2) TDDDG assessment | Set only after selection, persists until change/browser deletion; disclose and revisit if storage expands |
| Public route GPX / geometry | Editorial location content to database and readers | Publishing authored routes | Redact identifiable homes, other people's tracks and timestamps; reassess on user-upload/import features |
| CMS; `static/editor/index.html` | Operator browser calls GitHub/R2 while managing content | Operator publishing | Initial jsDelivr bundle request replaced by local pinned Sveltia; CMS remains separate external-service tooling and not protected by this change |
| E-mail contact from legal page | Sender address/message to operator and actual mail provider | Responding; Art. 6(1)(f), or (b) for contract inquiries | Confirm mail provider/processors and handling; delete after completion unless retention justified |

No reader analytics, marketing pixels or browser Sentry were identified in the
assessed implementation. A marketing/analytics CMP is not added. This is not a
blanket exemption for future storage, embeds or processing. Verify actual browser
network requests, deployed settings and hosting logs before release.

The public notice uses configurable factual fields instead of asserting unverified
DPAs, DE Sentry region, EU R2 jurisdiction or fixed provider retention periods.
See [release checklist](legal_gdpr.md) for primary legal and vendor references.
