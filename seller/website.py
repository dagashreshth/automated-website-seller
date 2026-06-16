"""Generate a personalized one-page sample website per prospect.

Each site is fully self-contained (inline CSS, no external assets, no build
step) and written to previews/<slug>/index.html. With GitHub Pages serving the
repo, the public URL becomes:
    <previews_base_url>/previews/<slug>/
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .compliance import footer_html, footer_text

ROOT = Path(__file__).resolve().parent.parent
PREVIEWS_DIR = ROOT / "previews"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml", "j2"]),
)

# Category -> a few plausible "services" to make the sample feel tailored.
SERVICES = {
    "café": ["Specialty Coffee", "Fresh Pastries", "All-Day Brunch"],
    "restaurant": ["Seasonal Menu", "Private Dining", "Online Reservations"],
    "bar": ["Craft Cocktails", "Local Beers", "Live Events"],
    "pub": ["Tap List", "Pub Classics", "Sunday Roast"],
    "hair salon": ["Cuts & Styling", "Colour", "Treatments"],
    "beauty salon": ["Facials", "Nails", "Brows & Lashes"],
    "boutique": ["New Arrivals", "Personal Styling", "Gift Cards"],
    "florist": ["Bouquets", "Event Flowers", "Same-Day Delivery"],
    "jewellery shop": ["Fine Jewellery", "Custom Pieces", "Repairs"],
    "bakery": ["Fresh Bread", "Custom Cakes", "Catering"],
}
DEFAULT_SERVICES = ["What We Offer", "Why Choose Us", "Get In Touch"]


def slugify(text: str) -> str:
    # Fold accents to ASCII so preview URLs stay clean (café -> cafe).
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_-]+", "-", text) or "business"


def _unique_slug(prospect: dict) -> str:
    base = slugify(prospect.get("name", "business"))
    seed = (prospect.get("email") or prospect.get("osm_id") or prospect.get("name") or "")
    short = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6]
    return f"{base}-{short}"


def _map_url(prospect: dict) -> str:
    lat, lon = prospect.get("lat"), prospect.get("lon")
    if lat and lon:
        return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}"
    query = " ".join(x for x in [prospect.get("name", ""), prospect.get("city", "")] if x)
    return f"https://www.openstreetmap.org/search?query={query.replace(' ', '+')}"


def build_preview(prospect: dict, cfg: dict) -> tuple[str, Path]:
    """Render the site, return (public_url, local_path)."""
    slug = _unique_slug(prospect)
    out_dir = PREVIEWS_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    category = (prospect.get("category") or "local business").lower()
    services = SERVICES.get(category, DEFAULT_SERVICES)

    html = _env.get_template("site/index.html.j2").render(
        biz=prospect,
        brand=cfg.get("brand", {}),
        services=services,
        map_url=_map_url(prospect),
        booking_url=cfg.get("brand", {}).get("booking_url", "#"),
        year=datetime.now(timezone.utc).year,
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps({"name": prospect.get("name", ""), "slug": slug,
                    "category": category, "city": prospect.get("city", "")}),
        encoding="utf-8",
    )

    base = cfg.get("brand", {}).get("previews_base_url", "").rstrip("/")
    public_url = f"{base}/previews/{slug}/" if base else f"previews/{slug}/index.html"
    return public_url, out_dir / "index.html"


def render_email(prospect: dict, cfg: dict, preview_url: str) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body) for the outreach email."""
    brand = cfg.get("brand", {})
    subject = f"I built {prospect.get('name','your business')} a sample website"
    email = prospect.get("email", "")
    common = {
        "biz": prospect, "brand": brand, "preview_url": preview_url,
        "booking_url": brand.get("booking_url", "#"),
    }
    html = _env.get_template("email/outreach.html.j2").render(
        footer_html=footer_html(cfg, email), **common
    )
    text = _env.get_template("email/outreach.txt").render(
        footer_text=footer_text(cfg, email), **common
    )
    return subject, html, text


def rebuild_gallery(cfg: dict) -> None:
    """Refresh previews/index.html so the Pages root lists all sample sites."""
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for meta_file in sorted(PREVIEWS_DIR.glob("*/meta.json")):
        try:
            items.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    html = _env.get_template("site/gallery.html.j2").render(
        items=items, brand=cfg.get("brand", {}), count=len(items),
    )
    (PREVIEWS_DIR / "index.html").write_text(html, encoding="utf-8")
