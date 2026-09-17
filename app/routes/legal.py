"""German legal pages rendered from the downloadable Markdown sources."""

from datetime import UTC, datetime
from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt

from app.core.config import get_settings

router = APIRouter()
_LEGAL_DIR = Path(__file__).resolve().parents[2] / "content" / "legal"


def _render_legal(request: Request, page: str, title: str) -> HTMLResponse:
    settings = get_settings()
    values = {
        "name": settings.legal_name or "Sven Hornaff",
        "address": settings.legal_address,
        "email": settings.legal_email,
        "hosting": settings.legal_hosting,
        "log_retention": settings.legal_log_retention,
        "cloudflare_details": settings.legal_cloudflare_details,
        "sentry_details": settings.legal_sentry_details,
    }
    required = ["address", "email"]
    if page == "datenschutz":
        required += ["hosting", "log_retention", "cloudflare_details"]
        if settings.sentry_dsn:
            required.append("sentry_details")
    # Do not publish invented provider commitments or unfinished legal notices.
    if settings.is_production and any(not values[key].strip() for key in required):
        raise HTTPException(status_code=503, detail="Rechtliche Angaben werden vervollständigt.")
    source = (_LEGAL_DIR / f"{page}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        # Render Markdown first, then escape configured text to prevent HTML
        # and Markdown link injection through environment-sourced fields.
        values[key] = value or f"[Noch einzutragen: {key}]"
    html = MarkdownIt("commonmark", {"html": False}).render(source)
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", escape(value).replace("\n", "<br>"))
    if page == "datenschutz" and not settings.sentry_dsn:
        start = html.index("<h2>Fehlerüberwachung mit Sentry</h2>")
        end = html.index("<h2>Cloudflare R2</h2>", start)
        html = html[:start] + html[end:]
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
    """Serve the privacy notice matching configured monitoring."""
    return _render_legal(request, "datenschutz", "Datenschutzerklärung")
