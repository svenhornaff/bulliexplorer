"""German legal pages rendered from the downloadable Markdown sources."""

from datetime import UTC, datetime
from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt

from app.core.config import get_settings

router = APIRouter()
_LEGAL_DIR = Path(__file__).resolve().parents[2] / "content" / "legal"

_UNAVAILABLE_DETAIL = "Rechtliche Angaben werden vervollständigt."


class LegalContentUnavailable(Exception):
    """Raised instead of ``HTTPException`` for the legal-page 503 case.

    A plain ``HTTPException`` renders FastAPI's default JSON error body
    (``{"detail": ...}``), which is correct for API endpoints but wrong
    here — /impressum and /datenschutz are HTML pages, and a bare JSON
    503 looks like a broken API endpoint to a site visitor rather than
    site content that isn't published yet. A dedicated exception type
    scopes the HTML-error-page handler to exactly these two routes,
    without touching how every other endpoint's ``HTTPException`` (health
    checks, the webhook, future API routes) is rendered — see
    app/main.py's registered handler for
    ``LegalContentUnavailable``.
    """

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__(_UNAVAILABLE_DETAIL)


def _render_legal(request: Request, page: str, title: str) -> HTMLResponse:
    settings = get_settings()
    classification = settings.legal_classification
    # Unset classification is a deliberate non-default (not "personal" or
    # "commercial" by fallback) — see docs/dev/legal_gdpr_classification_refactor.md.
    # Refuse to publish rather than guess in production; dev keeps today's
    # behaviour (full/commercial Impressum) so local work isn't blocked.
    if settings.is_production and classification is None:
        raise LegalContentUnavailable(title)
    source_page = page
    if page == "impressum" and classification == "personal":
        source_page = "impressum_personal"
        values = {"email": settings.legal_email}
        required = ["email"]
    else:
        values = {
            "name": settings.legal_name or "Sven Hornaff",
            "address": settings.legal_address,
            "email": settings.legal_email,
        }
        if page == "datenschutz":
            # GDPR Art. 13(1)(a) requires "the identity and the contact
            # details of the controller" — the statutory text itself does
            # not name a postal address specifically, and BulliExplorer
            # deliberately does not publish the operator's residential
            # address (see docs/dev/legal_gdpr.md's "LEGAL_ADDRESS
            # specifically" section on Abmahnung risk from an
            # unverified/home address). Name + a dedicated contact email is
            # treated as sufficient controller identification for this
            # personal blog; LEGAL_ADDRESS is optional and never blocks
            # /datenschutz. This does NOT apply to a commercial /impressum
            # below (§ 5 DDG Impressumspflicht requires the address for a
            # commercial offering) — only /datenschutz's separate GDPR duty
            # is relaxed here.
            #
            # No LEGAL_HOSTING/LOG_RETENTION/CLOUDFLARE_DETAILS/SENTRY_DETAILS
            # here (removed 2026-09-18, see
            # docs/dev/legal_gdpr_classification_refactor.md Phase 5) —
            # datenschutz.md now uses static, abstracted recipient
            # categories ("European hosting provider", "error-monitoring
            # service provider", "CDN/object-storage provider") per GDPR
            # Art. 13(1)(e)'s "recipients or categories of recipients"
            # wording, not env-templated vendor-specific text. Concrete
            # facts moved to docs/dev/DATA_PROCESSING.md (internal
            # RoPA-style record, never published). A category change
            # (e.g. a genuinely new non-EU recipient) is a content edit,
            # not an env var flip.
            required = ["email"]
        else:
            # Commercial /impressum: address stays required (§ 5 DDG).
            required = ["address", "email"]
    # Do not publish invented provider commitments or unfinished legal notices.
    if settings.is_production and any(not values[key].strip() for key in required):
        raise LegalContentUnavailable(title)
    source = (_LEGAL_DIR / f"{source_page}.md").read_text(encoding="utf-8")
    if page == "datenschutz" and not values["address"].strip():
        # Omit the address line entirely rather than a placeholder — see
        # the required-fields comment above on why LEGAL_ADDRESS is
        # optional here. "{{address}}  " is the exact source line (two
        # trailing spaces are CommonMark's hard-line-break marker).
        source = source.replace("{{address}}  \n", "")
    for key, value in values.items():
        # Render Markdown first, then escape configured text to prevent HTML
        # and Markdown link injection through environment-sourced fields.
        values[key] = value or f"[Noch einzutragen: {key}]"
    html = MarkdownIt("commonmark", {"html": False}).render(source)
    for key, value in values.items():
        if key == "address" and page == "datenschutz" and not value:
            continue
        html = html.replace("{{" + key + "}}", escape(value).replace("\n", "<br>"))
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="legal.html",
        context={"title": title, "legal_html": html, "year": datetime.now(UTC).year},
    )


@router.get("/impressum", response_class=HTMLResponse)
async def impressum(request: Request) -> HTMLResponse:
    """Serve the operator identification page."""
    return _render_legal(request, "impressum", "Impressum")


@router.get("/datenschutz", response_class=HTMLResponse)
async def datenschutz(request: Request) -> HTMLResponse:
    """Serve the privacy notice."""
    return _render_legal(request, "datenschutz", "Datenschutzerklärung")
