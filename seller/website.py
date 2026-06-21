"""Generate a personalized one-page sample website per prospect.

Each site is fully self-contained (inline CSS, no external assets, no build
step) and written to previews/<slug>/index.html. With GitHub Pages serving the
repo, the public URL becomes:
    <previews_base_url>/previews/<slug>/

The look adapts to the business category (a café feels warm, a law firm feels
sharp) via a per-category theme + copy map, and the page is filled with the
REAL data we scraped (opening hours, cuisine, socials, address) so the owner
sees their own business, not a generic stock template.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .compliance import footer_html, footer_text

ROOT = Path(__file__).resolve().parent.parent
# SELLER_PREVIEWS_DIR lets tests/dry-runs write sites somewhere disposable.
PREVIEWS_DIR = Path(os.environ.get("SELLER_PREVIEWS_DIR", str(ROOT / "previews")))
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml", "j2"]),
)

# --------------------------------------------------------------------------
# Theming: a palette per "mood", and a per-category map -> palette + copy.
# Templates use exactly these theme keys: accent, accent_dark, ink, soft,
# hero_from, hero_to, vibe.
# --------------------------------------------------------------------------
_INK, _SOFT = "#1d2433", "#f6f7fb"


def _palette(accent, accent_dark, hero_from, hero_to, vibe):
    return {"accent": accent, "accent_dark": accent_dark, "ink": _INK,
            "soft": _SOFT, "hero_from": hero_from, "hero_to": hero_to, "vibe": vibe}


PALETTES = {
    "coffee":   _palette("#c9893f", "#a96f2c", "#2b2118", "#3a2b1c", "warm"),
    "fresh":    _palette("#d2693f", "#a84f2c", "#1f2a24", "#2c3a30", "fresh"),
    "night":    _palette("#c9a227", "#9c7d18", "#161320", "#25203a", "moody"),
    "vino":     _palette("#9c2f4a", "#7d2138", "#1c1014", "#2a1820", "rich"),
    "rose":     _palette("#d6708f", "#b8536f", "#2a1c24", "#3a2630", "soft"),
    "luxe":     _palette("#b89150", "#97743a", "#16161a", "#24242c", "refined"),
    "bloom":    _palette("#e07a5f", "#c25f44", "#1e2a22", "#2c3a2e", "lively"),
    "bread":    _palette("#d99a3a", "#b87d22", "#2a2014", "#3a2c1a", "homely"),
    "greens":   _palette("#4f9d69", "#3a7d4f", "#16241b", "#213a29", "natural"),
    "calm":     _palette("#3aa6a0", "#2a807b", "#14252a", "#1e3a3e", "calm"),
    "steel":    _palette("#3a7bd5", "#2a5da8", "#161b24", "#20293a", "solid"),
    "ink":      _palette("#5b6cff", "#3f4fd8", "#14161f", "#20243a", "sharp"),
    "energy":   _palette("#7ed957", "#5fb53a", "#161a14", "#20281c", "bold"),
    "default":  _palette("#4f7cff", "#3a5fd8", "#161a24", "#232a3a", "modern"),
}

# category label (as produced by osm._label_for) -> palette + copy
CATEGORY_DESIGN = {
    "café":             ("coffee",  ["Specialty Coffee", "Fresh Pastries", "All-Day Brunch", "Takeaway"]),
    "restaurant":       ("fresh",   ["Seasonal Menu", "Private Dining", "Online Reservations", "Local Produce"]),
    "eatery":           ("fresh",   ["Fresh & Fast", "Daily Specials", "Takeaway", "Catering"]),
    "bar":              ("night",   ["Craft Cocktails", "Local Beers", "Live Events", "Happy Hour"]),
    "pub":              ("night",   ["Tap List", "Pub Classics", "Sunday Roast", "Live Sport"]),
    "winery":           ("vino",    ["Cellar Door Tastings", "Estate Wines", "Vineyard Tours", "Events"]),
    "bakery":           ("bread",   ["Fresh Bread Daily", "Custom Cakes", "Pastries", "Catering"]),
    "ice cream shop":   ("rose",    ["Small-Batch Gelato", "Sundaes", "Vegan Options", "Party Tubs"]),
    "deli":             ("greens",  ["Artisan Cheeses", "Cured Meats", "Fresh Sandwiches", "Hampers"]),
    "butcher":          ("greens",  ["Premium Cuts", "Free-Range & Local", "Sausages Made In-House", "BBQ Packs"]),
    "grocer":           ("greens",  ["Fresh Produce", "Local Suppliers", "Pantry Staples", "Home Delivery"]),
    "caterer":          ("fresh",   ["Event Catering", "Corporate Lunches", "Grazing Tables", "Custom Menus"]),
    "hair salon":       ("rose",    ["Cuts & Styling", "Colour & Balayage", "Treatments", "Bridal"]),
    "beauty salon":     ("rose",    ["Facials", "Nails", "Brows & Lashes", "Waxing"]),
    "massage studio":   ("calm",    ["Remedial Massage", "Relaxation", "Deep Tissue", "Couples"]),
    "tattoo studio":    ("ink",     ["Custom Design", "Fine Line", "Cover-Ups", "Walk-Ins"]),
    "boutique":         ("luxe",    ["New Arrivals", "Personal Styling", "Gift Cards", "Local Designers"]),
    "jewellery shop":   ("luxe",    ["Fine Jewellery", "Custom Pieces", "Repairs", "Valuations"]),
    "shoe shop":        ("luxe",    ["New Season", "Fitting Service", "Repairs", "Accessories"]),
    "florist":          ("bloom",   ["Bouquets", "Event Flowers", "Same-Day Delivery", "Subscriptions"]),
    "gift shop":        ("bloom",   ["Curated Gifts", "Cards & Wrap", "Local Makers", "Gift Wrapping"]),
    "bookshop":         ("ink",     ["New Releases", "Staff Picks", "Special Orders", "Events"]),
    "optician":         ("steel",   ["Eye Tests", "Designer Frames", "Contact Lenses", "Repairs"]),
    "pharmacy":         ("calm",    ["Prescriptions", "Health Advice", "Vaccinations", "Home Delivery"]),
    "pet shop":         ("greens",  ["Food & Treats", "Grooming", "Accessories", "Expert Advice"]),
    "dry cleaner":      ("steel",   ["Dry Cleaning", "Alterations", "Laundry", "Pickup & Delivery"]),
    "gym":              ("energy",  ["Memberships", "Personal Training", "Classes", "Free Trial"]),
    "dental practice":  ("calm",    ["Check-Ups", "Cosmetic Dentistry", "Emergency Care", "New Patients Welcome"]),
    "clinic":           ("calm",    ["Appointments", "Family Care", "Telehealth", "New Patients"]),
    "veterinary clinic":("calm",    ["Consultations", "Vaccinations", "Surgery", "Emergency Care"]),
    "auto shop":        ("steel",   ["Servicing", "Repairs", "Roadworthy/MOT", "Tyres"]),
    "tyre shop":        ("steel",   ["New Tyres", "Fitting & Balancing", "Wheel Alignment", "Puncture Repair"]),
    "electrician":      ("steel",   ["Wiring & Repairs", "Switchboards", "Lighting", "Emergency Call-Outs"]),
    "plumber":          ("steel",   ["Blocked Drains", "Hot Water", "Leaks & Repairs", "24/7 Emergency"]),
    "carpenter":        ("bread",   ["Custom Joinery", "Decks & Pergolas", "Renovations", "Repairs"]),
    "painter & decorator": ("steel", ["Interior", "Exterior", "Feature Walls", "Free Quotes"]),
    "landscaper":       ("greens",  ["Garden Design", "Maintenance", "Paving & Decks", "Irrigation"]),
    "estate agency":    ("ink",     ["Buy", "Sell", "Rent", "Free Appraisals"]),
    "travel agency":    ("steel",   ["Tailored Itineraries", "Flights & Hotels", "Group Tours", "Expert Advice"]),
    "photography studio": ("luxe",  ["Portraits", "Weddings", "Events", "Commercial"]),
    # professional services (mostly arrive via Apollo / manual CSV)
    "law firm":         ("ink",     ["Property & Conveyancing", "Family Law", "Wills & Estates", "Free First Consult"]),
    "lawyer":           ("ink",     ["Property & Conveyancing", "Family Law", "Wills & Estates", "Free First Consult"]),
    "solicitor":        ("ink",     ["Property & Conveyancing", "Family Law", "Wills & Estates", "Free First Consult"]),
    "accountant":       ("ink",     ["Tax Returns", "Bookkeeping", "Business Advisory", "BAS & Payroll"]),
    "accounting firm":  ("ink",     ["Tax Returns", "Bookkeeping", "Business Advisory", "BAS & Payroll"]),
    "financial adviser": ("ink",    ["Financial Planning", "Superannuation", "Insurance", "Retirement"]),
    "insurance agency": ("steel",   ["Home & Contents", "Business Cover", "Life & Income", "Free Quotes"]),
    "consultant":       ("ink",     ["Strategy", "Advisory", "Implementation", "Free Discovery Call"]),
    "marketing agency": ("ink",     ["Branding", "Social Media", "Web & SEO", "Free Audit"]),
    "architect":        ("luxe",    ["Residential", "Commercial", "Extensions", "Council Approvals"]),
    "real estate agency": ("ink",   ["Buy", "Sell", "Rent", "Free Appraisals"]),
}

DEFAULT_DESIGN = ("default", ["What We Offer", "Why Choose Us", "Our Promise", "Get In Touch"])


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


# --------------------------------------------------------------------------
# Opening-hours parsing (OSM opening_hours -> tidy display rows).
# --------------------------------------------------------------------------
_DAY = {"Mo": "Mon", "Tu": "Tue", "We": "Wed", "Th": "Thu", "Fr": "Fri",
        "Sa": "Sat", "Su": "Sun", "PH": "Public hols"}


def _fmt_t(hhmm: str) -> str:
    hhmm = hhmm.strip()
    if re.match(r"^0\d:", hhmm):  # 09:00 -> 9:00
        hhmm = hhmm[1:]
    return hhmm


def _fmt_span(span: str) -> str:
    span = span.strip()
    if span.lower() in ("off", "closed"):
        return "Closed"
    parts = span.split("-")
    if len(parts) == 2:
        return f"{_fmt_t(parts[0])} – {_fmt_t(parts[1])}"
    return span


def _fmt_days(token: str) -> str:
    token = token.strip()
    if "-" in token and "," not in token:
        a, b = token.split("-", 1)
        return f"{_DAY.get(a, a)}–{_DAY.get(b, b)}"
    if "," in token:
        return ", ".join(_DAY.get(d.strip(), d.strip()) for d in token.split(","))
    return _DAY.get(token, token)


def parse_hours(raw: str) -> list[dict]:
    """Turn an OSM opening_hours string into [{day, time}, ...] for display."""
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw == "24/7":
        return [{"day": "Every day", "time": "Open 24 hours"}]
    rows: list[dict] = []
    for rule in raw.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        m = re.match(r"^((?:[A-Za-z]{2}(?:[-,][A-Za-z]{2})*)+)\s+(.+)$", rule)
        if m:
            days = _fmt_days(m.group(1))
            times = " & ".join(_fmt_span(s) for s in m.group(2).split(","))
            rows.append({"day": days, "time": times})
        elif re.match(r"^\d", rule):  # times only -> assume daily
            times = " & ".join(_fmt_span(s) for s in rule.split(","))
            rows.append({"day": "Every day", "time": times})
        else:
            rows.append({"day": "Hours", "time": rule})
    return rows[:7]


# --------------------------------------------------------------------------
# Copy generation
# --------------------------------------------------------------------------
def _design_for(category: str) -> tuple[dict, list[str]]:
    palette_name, services = CATEGORY_DESIGN.get(category, DEFAULT_DESIGN)
    return PALETTES.get(palette_name, PALETTES["default"]), list(services)


def _tagline(prospect: dict) -> str:
    name = prospect.get("name", "Welcome")
    return name


def _hero_sub(prospect: dict) -> str:
    cat = prospect.get("category", "local business")
    city = prospect.get("city", "")
    cuisine = prospect.get("cuisine", "")
    where = f" in {city}" if city else ""
    if prospect.get("description"):
        return prospect["description"]
    if cuisine and cat in ("restaurant", "eatery", "café", "bar"):
        return f"{cuisine.title()} done right{where}. Now with a home online — come see what's on."
    article = "an" if cat[:1].lower() in "aeiou" else "a"
    return (f"Proudly {article} {cat}{where}. Discover what we offer, find our hours, "
            f"and get in touch — all in one place.")


def build_context(prospect: dict, cfg: dict) -> dict:
    category = (prospect.get("category") or "local business").lower()
    theme, services = _design_for(category)
    brand = cfg.get("brand", {})
    return {
        "biz": prospect,
        "brand": brand,
        "theme": theme,
        "services": services,
        "hours": parse_hours(prospect.get("opening_hours", "")),
        "tagline": _tagline(prospect),
        "hero_sub": _hero_sub(prospect),
        "map_url": _map_url(prospect),
        "booking_url": brand.get("booking_url", "#"),
        "year": datetime.now(timezone.utc).year,
    }


def build_preview(prospect: dict, cfg: dict) -> tuple[str, Path]:
    """Render the site, return (public_url, local_path)."""
    slug = _unique_slug(prospect)
    out_dir = PREVIEWS_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    html = _env.get_template("site/index.html.j2").render(**build_context(prospect, cfg))
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps({"name": prospect.get("name", ""), "slug": slug,
                    "category": (prospect.get("category") or "local business").lower(),
                    "city": prospect.get("city", "")}),
        encoding="utf-8",
    )

    base = cfg.get("brand", {}).get("previews_base_url", "").rstrip("/")
    public_url = f"{base}/previews/{slug}/" if base else f"previews/{slug}/index.html"
    return public_url, out_dir / "index.html"


def render_email(prospect: dict, cfg: dict, preview_url: str) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body) for the outreach email."""
    from . import outreach  # local import to avoid a cycle at module load
    return outreach.render(prospect, cfg, preview_url, _env)


def rebuild_gallery(cfg: dict) -> None:
    """Refresh previews/index.html so the Pages root lists all sample sites."""
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for meta_file in sorted(PREVIEWS_DIR.glob("*/meta.json")):
        try:
            items.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    # newest first by directory mtime
    items_sorted = sorted(
        items,
        key=lambda it: (PREVIEWS_DIR / it.get("slug", "")).stat().st_mtime
        if (PREVIEWS_DIR / it.get("slug", "")).exists() else 0,
        reverse=True,
    )
    by_cat: dict = {}
    for it in items_sorted:
        by_cat[it.get("category", "other")] = by_cat.get(it.get("category", "other"), 0) + 1
    html = _env.get_template("site/gallery.html.j2").render(
        items=items_sorted, brand=cfg.get("brand", {}), count=len(items_sorted),
        categories=len(by_cat),
    )
    (PREVIEWS_DIR / "index.html").write_text(html, encoding="utf-8")
