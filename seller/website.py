"""Generate a personalized one-page sample website per prospect.

Each site is fully self-contained (inline CSS, no external assets, no build
step) and written to previews/<slug>/index.html. With GitHub Pages serving the
repo, the public URL becomes:
    <previews_base_url>/previews/<slug>/

The page is filled with the REAL data we scraped (opening hours, address,
socials) and — when the caller has researched the business — REAL brand colours,
REAL reviews, real photos and copy written specifically for that business.

Enrichment contract (all optional; every field degrades gracefully so the
unattended cron still produces a beautiful page with none of them):

    prospect["slug"]          -> force a stable preview slug (keeps live URLs)
    prospect["brand_colors"]  -> {"primary": "#hex", "secondary": "#hex"?}
                                 a full, legible palette is DERIVED from these
    prospect["palette_name"]  -> name of a built-in palette to use instead
    prospect["copy"] = {
        "hero_headline", "hero_kicker", "hero_sub",
        "secondary_cta", "service_eyebrow", "service_heading", "service_lead",
        "story_heading", "about": [..paras..],
        "services": [{"title","blurb"}, ..],
        "highlights": [..short honest chips..],
    }
    prospect["reviews"]       -> [{"text","author","source"?}, ..]  (REAL only)
    prospect["photos"]        -> {"logo_url"?, "hero_url"?}
    prospect["visual_seed"]   -> int, varies the CSS-only artwork between sites
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
# SELLER_PREVIEWS_DIR lets tests/dry-runs write sites somewhere disposable.
PREVIEWS_DIR = Path(os.environ.get("SELLER_PREVIEWS_DIR", str(ROOT / "previews")))
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    # Escape HTML/XML templates (incl. the *.html.j2 ones) but NOT the plain
    # text email (*.txt.j2) — escaping there turns apostrophes into entities.
    autoescape=select_autoescape(
        enabled_extensions=("html", "xml", "html.j2"),
        disabled_extensions=("txt.j2",),
        default=False, default_for_string=False,
    ),
)

# --------------------------------------------------------------------------
# Colour helpers — derive a whole coherent, legible palette from one brand hex.
# --------------------------------------------------------------------------
def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = (h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"bad hex: {h!r}")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _hls(h: str) -> tuple[float, float, float]:
    r, g, b = _hex_to_rgb(h)
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    return hue, light, sat


def _from_hls(hue: float, light: float, sat: float) -> str:
    light = max(0.0, min(1.0, light))
    sat = max(0.0, min(1.0, sat))
    return _rgb_to_hex(colorsys.hls_to_rgb(hue % 1.0, light, sat))


def _rel_lum(h: str) -> float:
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _rel_lum(a), _rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _ensure_white_contrast(hexv: str, target: float = 3.5) -> str:
    """Darken a colour (keeping its hue/saturation) until white text on it
    clears the target contrast ratio. Bright greens/teals/yellows otherwise
    look washed out under #fff button labels."""
    hue, light, sat = _hls(hexv)
    out = hexv
    for _ in range(50):
        if _contrast(out, "#ffffff") >= target:
            return out
        light -= 0.02
        if light <= 0.02:
            return _from_hls(hue, 0.02, sat)
        out = _from_hls(hue, light, sat)
    return out


def _palette_from_brand(primary: str, secondary: str | None = None) -> dict:
    """Build accent/accent_dark/ink/soft/hero_from/hero_to from a brand colour.

    The accent is kept close to the real brand colour but nudged to a mid
    lightness so white text and the light page both read well. The hero is a
    deep, hue-matched gradient (always dark enough for white text), and ink/soft
    are hue-tinted near-black / near-white so the whole page feels of-a-piece.
    """
    hue, light, sat = _hls(primary)
    if sat < 0.08:
        return {"accent": "#4a4a4a", "accent_dark": "#242424", "ink": "#202020",
                "soft": "#f5f5f5", "hero_from": "#101010", "hero_to": "#2b2b2b",
                "vibe": "neutral", "secondary": secondary or "#707070"}
    # Accent: keep brand hue/saturation, clamp lightness into a usable band so
    # buttons on white and white text on buttons both have contrast.
    acc_l = min(0.56, max(0.40, light))
    acc_s = min(0.85, max(0.42, sat))
    # buttons put white text on the accent, so guarantee legible contrast.
    accent = _ensure_white_contrast(_from_hls(hue, acc_l, acc_s), 3.5)
    accent_dark = _ensure_white_contrast(_from_hls(hue, max(0.30, acc_l - 0.12), acc_s), 4.8)
    # Secondary (for the hero's second glow) — fall back to a hue shift.
    if secondary:
        s_hue, _, s_sat = _hls(secondary)
    else:
        s_hue, s_sat = (hue + 0.06) % 1.0, acc_s
    hero_from = _from_hls(hue, 0.11, min(0.55, max(0.22, sat)))
    hero_to = _from_hls(s_hue, 0.17, min(0.50, max(0.20, s_sat)))
    ink = _from_hls(hue, 0.16, min(0.30, sat * 0.5 + 0.06))
    soft = _from_hls(hue, 0.965, min(0.55, sat))
    return {"accent": accent, "accent_dark": accent_dark, "ink": ink,
            "soft": soft, "hero_from": hero_from, "hero_to": hero_to,
            "vibe": "brand", "secondary": secondary or accent}


# --------------------------------------------------------------------------
# Built-in palettes (fallbacks when we can't pull a real brand colour).
# More than one option per "mood" so sites in the same category still differ.
# --------------------------------------------------------------------------
def _palette(accent, accent_dark, hero_from, hero_to, vibe):
    accent = _ensure_white_contrast(accent, 3.5)
    accent_dark = _ensure_white_contrast(accent_dark, 4.8)
    hue, light, sat = _hls(accent)
    ink = _from_hls(hue, 0.16, min(0.28, sat * 0.5 + 0.05))
    soft = _from_hls(hue, 0.965, min(0.5, sat))
    return {"accent": accent, "accent_dark": accent_dark, "ink": ink,
            "soft": soft, "hero_from": hero_from, "hero_to": hero_to,
            "vibe": vibe, "secondary": accent}


PALETTES = {
    "coffee":   _palette("#c9893f", "#a96f2c", "#2b2118", "#3a2b1c", "warm"),
    "coffee2":  _palette("#a9744e", "#875733", "#241a13", "#33241a", "warm"),
    "fresh":    _palette("#d2693f", "#a84f2c", "#1f2a24", "#2c3a30", "fresh"),
    "fresh2":   _palette("#c75d52", "#a3463d", "#241c1a", "#352724", "fresh"),
    "night":    _palette("#c9a227", "#9c7d18", "#161320", "#25203a", "moody"),
    "vino":     _palette("#9c2f4a", "#7d2138", "#1c1014", "#2a1820", "rich"),
    "rose":     _palette("#d6708f", "#b8536f", "#2a1c24", "#3a2630", "soft"),
    "rose2":    _palette("#c76a86", "#a64f69", "#27191f", "#38242d", "soft"),
    "luxe":     _palette("#b89150", "#97743a", "#16161a", "#24242c", "refined"),
    "luxe2":    _palette("#9a8466", "#7c694e", "#17150f", "#262217", "refined"),
    "bloom":    _palette("#e07a5f", "#c25f44", "#1e2a22", "#2c3a2e", "lively"),
    "bloom2":   _palette("#d98a72", "#bb6c54", "#231d1a", "#342822", "lively"),
    "bread":    _palette("#d99a3a", "#b87d22", "#2a2014", "#3a2c1a", "homely"),
    "greens":   _palette("#4f9d69", "#3a7d4f", "#16241b", "#213a29", "natural"),
    "greens2":  _palette("#5a8f5b", "#447045", "#161f16", "#22321f", "natural"),
    "calm":     _palette("#3aa6a0", "#2a807b", "#14252a", "#1e3a3e", "calm"),
    "calm2":    _palette("#4f93b0", "#3a7290", "#13212a", "#1d3340", "calm"),
    "steel":    _palette("#3a7bd5", "#2a5da8", "#161b24", "#20293a", "solid"),
    "ink":      _palette("#5b6cff", "#3f4fd8", "#14161f", "#20243a", "sharp"),
    "indigo":   _palette("#6457c9", "#4c40a3", "#15131f", "#211d35", "sharp"),
    "energy":   _palette("#5fb53a", "#4a9a2c", "#161a14", "#20281c", "bold"),
    "default":  _palette("#4f7cff", "#3a5fd8", "#161a24", "#232a3a", "modern"),
    "default2": _palette("#5a8a8f", "#436a6e", "#161e20", "#22302f", "modern"),
}

# category label (as produced by osm._label_for) -> (palette name(s), default
# service titles). Where several palettes are listed, one is chosen per-business
# by a stable hash so two cafés in the same town don't look identical.
CATEGORY_DESIGN = {
    "café":             (["coffee", "coffee2"], ["Specialty Coffee", "Fresh Pastries", "All-Day Brunch", "Takeaway"]),
    "restaurant":       (["fresh", "fresh2"],   ["Seasonal Menu", "Private Dining", "Bookings", "Local Produce"]),
    "eatery":           (["fresh", "fresh2"],   ["Fresh & Fast", "Daily Specials", "Takeaway", "Catering"]),
    "bar":              (["night"],             ["Craft Cocktails", "Local Beers", "Live Events", "Happy Hour"]),
    "pub":              (["night"],             ["Tap List", "Pub Classics", "Sunday Roast", "Live Sport"]),
    "winery":           (["vino"],              ["Cellar Door Tastings", "Estate Wines", "Vineyard Tours", "Events"]),
    "bakery":           (["bread"],             ["Fresh Bread Daily", "Custom Cakes", "Pastries", "Catering"]),
    "ice cream shop":   (["rose", "rose2"],     ["Small-Batch Gelato", "Sundaes", "Vegan Options", "Party Tubs"]),
    "deli":             (["greens", "greens2"], ["Artisan Cheeses", "Cured Meats", "Fresh Sandwiches", "Hampers"]),
    "butcher":          (["greens", "greens2"], ["Premium Cuts", "Free-Range & Local", "House-Made Sausages", "BBQ Packs"]),
    "grocer":           (["greens", "greens2"], ["Fresh Produce", "Local Suppliers", "Pantry Staples", "Home Delivery"]),
    "caterer":          (["fresh", "fresh2"],   ["Event Catering", "Corporate Lunches", "Grazing Tables", "Custom Menus"]),
    "hair salon":       (["rose", "rose2"],     ["Cuts & Styling", "Colour & Balayage", "Treatments", "Bridal"]),
    "beauty salon":     (["rose", "rose2"],     ["Facials", "Nails", "Brows & Lashes", "Waxing"]),
    "massage studio":   (["calm", "calm2"],     ["Remedial Massage", "Relaxation", "Deep Tissue", "Couples"]),
    "tattoo studio":    (["ink", "indigo"],     ["Custom Design", "Fine Line", "Cover-Ups", "Walk-Ins"]),
    "boutique":         (["luxe", "luxe2"],     ["New Arrivals", "Personal Styling", "Gift Cards", "Local Designers"]),
    "jewellery shop":   (["luxe", "luxe2"],     ["Fine Jewellery", "Custom Pieces", "Repairs", "Valuations"]),
    "shoe shop":        (["luxe", "luxe2"],     ["New Season", "Fitting Service", "Repairs", "Accessories"]),
    "florist":          (["bloom", "bloom2"],   ["Bouquets", "Event Flowers", "Same-Day Delivery", "Subscriptions"]),
    "gift shop":        (["bloom", "bloom2"],   ["Curated Gifts", "Cards & Wrap", "Local Makers", "Gift Wrapping"]),
    "bookshop":         (["indigo", "ink"],     ["New Releases", "Staff Picks", "Special Orders", "Events"]),
    "optician":         (["steel"],             ["Eye Tests", "Designer Frames", "Contact Lenses", "Repairs"]),
    "pharmacy":         (["calm", "calm2"],     ["Prescriptions", "Health Advice", "Vaccinations", "Home Delivery"]),
    "pet shop":         (["greens", "greens2"], ["Food & Treats", "Grooming", "Accessories", "Expert Advice"]),
    "dry cleaner":      (["steel"],             ["Dry Cleaning", "Alterations", "Laundry", "Pickup & Delivery"]),
    "gym":              (["energy"],            ["Memberships", "Personal Training", "Classes", "Free Trial"]),
    "dental practice":  (["calm", "calm2"],     ["Check-Ups", "Cosmetic Dentistry", "Emergency Care", "New Patients Welcome"]),
    "clinic":           (["calm", "calm2"],     ["Appointments", "Family Care", "Telehealth", "New Patients"]),
    "veterinary clinic":(["calm", "calm2"],     ["Consultations", "Vaccinations", "Surgery", "Emergency Care"]),
    "auto shop":        (["steel"],             ["Servicing", "Repairs", "Roadworthy/MOT", "Tyres"]),
    "tyre shop":        (["steel"],             ["New Tyres", "Fitting & Balancing", "Wheel Alignment", "Puncture Repair"]),
    "electrician":      (["steel"],             ["Wiring & Repairs", "Switchboards", "Lighting", "Emergency Call-Outs"]),
    "plumber":          (["steel"],             ["Blocked Drains", "Hot Water", "Leaks & Repairs", "24/7 Emergency"]),
    "carpenter":        (["bread"],             ["Custom Joinery", "Decks & Pergolas", "Renovations", "Repairs"]),
    "painter & decorator": (["steel"],          ["Interior", "Exterior", "Feature Walls", "Free Quotes"]),
    "landscaper":       (["greens", "greens2"], ["Garden Design", "Maintenance", "Paving & Decks", "Irrigation"]),
    "estate agency":    (["indigo", "ink"],     ["Buy", "Sell", "Rent", "Free Appraisals"]),
    "travel agency":    (["steel"],             ["Tailored Itineraries", "Flights & Hotels", "Group Tours", "Expert Advice"]),
    "photography studio": (["luxe", "luxe2"],   ["Portraits", "Weddings", "Events", "Commercial"]),
    "law firm":         (["indigo", "ink"],     ["Property & Conveyancing", "Family Law", "Wills & Estates", "Free First Consult"]),
    "lawyer":           (["indigo", "ink"],     ["Property & Conveyancing", "Family Law", "Wills & Estates", "Free First Consult"]),
    "solicitor":        (["indigo", "ink"],     ["Property & Conveyancing", "Family Law", "Wills & Estates", "Free First Consult"]),
    "accountant":       (["indigo", "ink"],     ["Tax Returns", "Bookkeeping", "Business Advisory", "BAS & Payroll"]),
    "accounting firm":  (["indigo", "ink"],     ["Tax Returns", "Bookkeeping", "Business Advisory", "BAS & Payroll"]),
    "financial adviser": (["indigo", "ink"],    ["Financial Planning", "Superannuation", "Insurance", "Retirement"]),
    "insurance agency": (["steel"],             ["Home & Contents", "Business Cover", "Life & Income", "Free Quotes"]),
    "consultant":       (["indigo", "ink"],     ["Strategy", "Advisory", "Implementation", "Free Discovery Call"]),
    "marketing agency": (["indigo", "ink"],     ["Branding", "Social Media", "Web & SEO", "Free Audit"]),
    "architect":        (["luxe", "luxe2"],     ["Residential", "Commercial", "Extensions", "Council Approvals"]),
    "real estate agency": (["indigo", "ink"],   ["Buy", "Sell", "Rent", "Free Appraisals"]),
}

DEFAULT_DESIGN = (["default", "default2", "calm2", "steel"],
                  ["What We Offer", "Why Choose Us", "Our Promise", "Get In Touch"])


def slugify(text: str) -> str:
    # Fold accents to ASCII so preview URLs stay clean (café -> cafe).
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_-]+", "-", text) or "business"


def _stable_int(prospect: dict) -> int:
    seed = (prospect.get("email") or prospect.get("osm_id")
            or prospect.get("name") or "")
    return int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)


def _unique_slug(prospect: dict) -> str:
    # An explicit slug always wins (keeps already-published URLs stable).
    if prospect.get("slug"):
        return str(prospect["slug"])
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
# Theme + copy resolution
# --------------------------------------------------------------------------
def _resolve_theme(prospect: dict, category: str) -> dict:
    """Pick the site palette. Priority: researched brand colour -> explicit
    palette name -> a per-business choice from the category's palette set."""
    bc = prospect.get("brand_colors")
    if isinstance(bc, dict) and bc.get("primary"):
        try:
            return _palette_from_brand(bc["primary"], bc.get("secondary"))
        except (ValueError, TypeError):
            pass
    name = prospect.get("palette_name")
    if name and name in PALETTES:
        return PALETTES[name]
    options, _ = CATEGORY_DESIGN.get(category, DEFAULT_DESIGN)
    choice = options[_stable_int(prospect) % len(options)]
    return PALETTES.get(choice, PALETTES["default"])


# Honest, varied per-card blurbs used only when the caller hasn't supplied
# researched, business-specific service copy.
_FALLBACK_BLURBS = [
    "Done properly, with the care you'd expect from a local favourite.",
    "One of the little things that keeps people coming back.",
    "Thoughtful, reliable, and done the way the regulars love it.",
    "Simple things, done exceptionally well — every time.",
    "Looked after by people who genuinely take pride in it.",
    "Friendly, dependable, and made to feel just right for you.",
]


def _service_cards(prospect: dict, category: str) -> list[dict]:
    """Return [{title, blurb}, ..]. Use researched copy if present, else build
    sensible cards from the category defaults with varied honest blurbs."""
    copy = prospect.get("copy") or {}
    services = copy.get("services")
    if services:
        cards = []
        for i, s in enumerate(services):
            if isinstance(s, dict):
                cards.append({"title": s.get("title", ""),
                              "blurb": s.get("blurb", _FALLBACK_BLURBS[i % len(_FALLBACK_BLURBS)])})
            else:
                cards.append({"title": str(s),
                              "blurb": _FALLBACK_BLURBS[i % len(_FALLBACK_BLURBS)]})
        return [c for c in cards if c["title"]][:6]
    _, titles = CATEGORY_DESIGN.get(category, DEFAULT_DESIGN)
    base = _stable_int(prospect)
    return [{"title": t, "blurb": _FALLBACK_BLURBS[(base + i) % len(_FALLBACK_BLURBS)]}
            for i, t in enumerate(titles)]


def _hero_sub(prospect: dict) -> str:
    copy = prospect.get("copy") or {}
    if copy.get("hero_sub"):
        return copy["hero_sub"]
    cat = (prospect.get("category") or "local business")
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


def _highlights(prospect: dict, hours: list) -> list[str]:
    """Honest hero chips (NO fabricated star ratings). Researched chips win."""
    copy = prospect.get("copy") or {}
    if copy.get("highlights"):
        return [str(h) for h in copy["highlights"]][:4]
    out = []
    if prospect.get("city"):
        out.append(f"Right here in {prospect['city']}")
    out.append("Independent & local")
    if hours:
        out.append("Open this week")
    if prospect.get("phone"):
        out.append("Call us any time")
    return out[:3]


# Category-aware primary call-to-action. (label, kind) — kind drives the link:
# book/enquire/order -> call the shop if we have a number, else scroll to
# contact; visit -> scroll to contact/map; call -> tel; email -> mailto.
_CTA_DEFAULTS = {
    "hair salon": ("Book an appointment", "book"),
    "beauty salon": ("Book an appointment", "book"),
    "massage studio": ("Book a session", "book"),
    "tattoo studio": ("Enquire about a tattoo", "enquire"),
    "gym": ("Start with a free session", "enquire"),
    "dental practice": ("Book a check-up", "book"),
    "clinic": ("Book an appointment", "book"),
    "veterinary clinic": ("Book an appointment", "book"),
    "café": ("Plan your visit", "visit"),
    "bakery": ("Plan your visit", "visit"),
    "restaurant": ("Book a table", "book"),
    "eatery": ("Plan your visit", "visit"),
    "bar": ("Book a table", "book"),
    "pub": ("Book a table", "book"),
    "winery": ("Plan a tasting", "book"),
    "deli": ("Visit the shop", "visit"),
    "butcher": ("Place an order", "order"),
    "grocer": ("Visit the shop", "visit"),
    "caterer": ("Request a quote", "enquire"),
    "florist": ("Order flowers", "order"),
    "bookshop": ("Visit the shop", "visit"),
    "boutique": ("Visit the shop", "visit"),
    "gift shop": ("Visit the shop", "visit"),
    "jewellery shop": ("Visit the shop", "visit"),
    "shoe shop": ("Visit the shop", "visit"),
    "pet shop": ("Visit the shop", "visit"),
    "dressmaker": ("Get a quote", "enquire"),
    "dry cleaner": ("Get a quote", "enquire"),
    "electronics repair": ("Get a repair quote", "enquire"),
    "auto shop": ("Book a service", "book"),
    "optician": ("Book an eye test", "book"),
    "photography studio": ("Enquire about a shoot", "enquire"),
}

_CTA_HEADINGS = {
    "book": "Ready to book?",
    "enquire": "Get in touch",
    "order": "Place an order",
    "visit": "Come and see us",
    "call": "Give us a call",
    "email": "Drop us a line",
}


def _cta(prospect: dict, category: str) -> dict:
    """Return {label, href, kind, heading} for the primary call to action."""
    c = prospect.get("cta") or {}
    label = c.get("label")
    kind = c.get("kind") or c.get("type")
    if not label or not kind:
        d_label, d_kind = _CTA_DEFAULTS.get(category, ("Get in touch", "enquire"))
        label = label or d_label
        kind = kind or d_kind
    phone = prospect.get("phone")
    email = prospect.get("email")
    if kind in ("call", "book", "enquire", "order") and phone:
        href = f"tel:{phone}"
    elif kind == "email" and email:
        href = f"mailto:{email}"
    else:
        href = "#contact"
    return {"label": label, "href": href, "kind": kind,
            "heading": _CTA_HEADINGS.get(kind, "Get in touch")}


def _menu(prospect: dict) -> dict | None:
    """Normalise an optional menu / price list into {eyebrow, title, note,
    groups:[{name, items:[{name, desc, price}]}]}. Accepts a flat item list too.

    ``eyebrow`` lets researched samples describe an unpriced product or service
    list accurately instead of implying that prices are shown.
    """
    m = prospect.get("menu")
    if not isinstance(m, dict):
        return None
    raw_groups = m.get("groups")
    if not raw_groups and isinstance(m.get("items"), list):
        raw_groups = [{"name": "", "items": m["items"]}]
    if not isinstance(raw_groups, list):
        return None
    groups = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        items = []
        for it in (g.get("items") or []):
            if isinstance(it, dict) and it.get("name"):
                items.append({"name": str(it["name"]),
                              "desc": str(it.get("desc", "") or ""),
                              "price": str(it.get("price", "") or "")})
            elif isinstance(it, str) and it.strip():
                items.append({"name": it.strip(), "desc": "", "price": ""})
        if items:
            groups.append({"name": str(g.get("name", "") or ""), "items": items})
    if not groups:
        return None
    return {"eyebrow": str(m.get("eyebrow", "") or ""),
            "title": str(m.get("title") or "What we offer"),
            "note": str(m.get("note", "") or ""), "groups": groups}


def _steps(prospect: dict) -> dict | None:
    """Optional 'how it works' steps -> {title, items:[{title, desc}]}."""
    s = prospect.get("steps")
    if not isinstance(s, dict):
        return None
    items = []
    for it in (s.get("items") or []):
        if isinstance(it, dict) and it.get("title"):
            items.append({"title": str(it["title"]), "desc": str(it.get("desc", "") or "")})
    if not items:
        return None
    return {"title": str(s.get("title") or "How it works"), "items": items[:5]}


def _good_to_know(prospect: dict) -> list[str]:
    gtk = prospect.get("good_to_know")
    if not isinstance(gtk, list):
        return []
    return [str(x).strip() for x in gtk if str(x).strip()][:6]


def build_context(prospect: dict, cfg: dict) -> dict:
    category = (prospect.get("category") or "local business").lower()
    theme = _resolve_theme(prospect, category)
    brand = cfg.get("brand", {})
    hours = parse_hours(prospect.get("opening_hours", ""))
    copy = prospect.get("copy") or {}
    reviews = [r for r in (prospect.get("reviews") or [])
               if isinstance(r, dict) and r.get("text")][:3]
    photos = prospect.get("photos") or {}
    return {
        "biz": prospect,
        "brand": brand,
        "theme": theme,
        "service_cards": _service_cards(prospect, category),
        "menu": _menu(prospect),
        "steps": _steps(prospect),
        "good_to_know": _good_to_know(prospect),
        "cta": _cta(prospect, category),
        "hours": hours,
        "headline": copy.get("hero_headline") or prospect.get("name", ""),
        "hero_kicker": copy.get("hero_kicker", ""),
        "hero_sub": _hero_sub(prospect),
        "secondary_cta": copy.get("secondary_cta", "See what we offer"),
        "service_eyebrow": copy.get("service_eyebrow", "What we offer"),
        "service_heading": copy.get("service_heading", ""),
        "service_lead": copy.get("service_lead", ""),
        "story_heading": copy.get("story_heading", ""),
        "about_paras": [p for p in (copy.get("about") or []) if p],
        "highlights": _highlights(prospect, hours),
        "reviews": reviews,
        "logo_url": photos.get("logo_url", ""),
        "hero_url": photos.get("hero_url", ""),
        "visual_seed": int(prospect.get("visual_seed", _stable_int(prospect))) % 4,
        "map_url": _map_url(prospect),
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
