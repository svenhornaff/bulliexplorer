# Legal / GDPR release notes

This is an implementation and a reviewable German disclosure draft, not certification
of legal compliance. Sources are in `content/legal/*.md` and render at `/impressum`
and `/datenschutz`. Keep footer links accessible on every reader page.

## Required before publishing

Set public disclosure values in the server `.env` (forwarded by production Compose):

| Variable | Verified value to supply |
| --- | --- |
| `LEGAL_NAME` | Operator's full name (fallback: Sven Hornaff) |
| `LEGAL_ADDRESS` | Serviceable postal address including country; no guessed home address |
| `LEGAL_EMAIL` | Operator contact email, not automatically the package author's work email |
| `LEGAL_HOSTING` | Actual hosting provider/legal entity, location, data recipients and transfer details |
| `LEGAL_LOG_RETENTION` | Actual log deletion criteria/retention, including hosting-level logs |
| `LEGAL_CLOUDFLARE_DETAILS` | Actual entity, DPA, object jurisdiction, request-data retention and transfer safeguards/access to copies |
| `LEGAL_SENTRY_DETAILS` | Actual entity, DPA, region, event retention and transfer safeguards/access to copies; needed when DSN set |

Production legal endpoints return 503 when their required values are missing;
other application endpoints keep working. Development displays explicit placeholders.
Sentry disclosure is omitted when `SENTRY_DSN` is empty. Cloudflare remains disclosed
because authored content can contain direct R2 image links independent of settings.
Do not deploy this draft until the missing values have been reviewed and supplied.

## Account-side work (not accomplished by a repository change)

- Verify hosting AVV/DPA and actual request/error logs, including any Cloudflare proxy configuration.
- Accept/verify applicable Cloudflare and Sentry DPAs. Do not claim contracts are signed until verified.
- Verify Sentry organization DE region and project scrubbing. Choose minimum practical retention;
  URLs/exception text may still contain personal data despite SDK filtering. Test synthetic events.
- Check R2 bucket jurisdiction; EU jurisdiction is distinct from a best-effort location hint.
  Existing buckets may need a separately planned migration. EU object residency does not
  settle all international transfer questions. Do not migrate/delete buckets blindly.
- Record actual recipient legal entities, retention and applicable GDPR chapter V safeguards.
- Confirm operator duties under § 18 MStV as well as § 5 DDG; name/address may be required
  for noncommercial offers outside exclusively personal/family purposes. Review whether
  the blog is journalistically edited and the designated responsible person qualifies.
- Redact home endpoints, timestamps and other identifiable people's location data in published GPX.
- Reassess before introducing accounts, imports, uploads, embeds, analytics or marketing.

## Technical changes

Sentry defaults are explicit: no default PII, no local variables/request bodies/traces.
`before_send` retains only request method and a URL stripped of userinfo/query/fragment,
and removes user, extra and breadcrumbs while preserving diagnostic stacktraces.
Application error text still needs data-minimizing logging and project-side scrubbing.
Manual resync no longer logs the client address. Production Uvicorn access logging
is disabled; checked-in Caddy already has no `log` directive. Docker rotation limits
bytes/files, not a time-based retention policy.

Sveltia 0.208.0 is vendored locally with its license. This removes the initial
jsDelivr script request; authenticated CMS features still contact external services.
The editor is not made anonymous-safe or access-restricted by local vendoring;
GitHub/R2 authentication flow and all `/static/editor/*` paths need a separate review.
No resync token is reused as a browser login password.

## Primary references

- [GDPR, especially Articles 5, 6, 13, 21, 28, 32 and 44 onward](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng)
- [§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html)
- [§ 18 MStV](https://www.gesetze-bayern.de/Content/Document/MStV-18)
- [§ 25 TDDDG](https://www.gesetze-im-internet.de/ttdsg/__25.html)
- [Caddy logging](https://caddyserver.com/docs/caddyfile/directives/log)
- [R2 data location](https://developers.cloudflare.com/r2/reference/data-location/)
- [Sentry Python SDK options](https://docs.sentry.io/platforms/python/configuration/options/)
