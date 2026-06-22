"""Outreach email copy.

A short, personal introduction from the founder. ONE consistent version for
every prospect (no anti-fingerprint variant rotation any more — the founder
wants consistent, predictable output). The only thing that changes per
recipient is the business name in the greeting/intro and their sample link.

Cold-email best practice baked in: short, plain, personal, one clear ask, the
sample link, and the unsubscribe. No booking-link / calendar URL. Subject is
kept under six words, carries no recipient name, and uses no em dashes.

Placeholders available: {founder} {location} {brand} {price} {name}
"""
from __future__ import annotations

from .compliance import footer_html, footer_text

# Subject: under six words, no recipient name, no em dashes.
SUBJECT = "A free sample website"


def render(prospect: dict, cfg: dict, preview_url: str, env) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""
    brand = cfg.get("brand", {})
    email = prospect.get("email", "")

    founder = brand.get("founder", "Shreshth")
    location = brand.get("founder_location", "Dubai")
    brand_name = brand.get("name", "Shiftora")
    price = brand.get("price", "$299")
    name = prospect.get("name", "your business")

    greeting = f"Hi {name} team,"
    intro = (
        f"I'm {founder}, a {location}-based founder. The {brand_name} team makes "
        f"websites for local businesses, and I noticed {name} doesn't have one "
        f"yet. So here's a free sample I built for you."
    )
    link_lead = "Here is the link to open and check out this very rough sample website:"
    price_line = (
        f"If you want it live, it's a flat {price} all in, designed, set up and "
        f"hosted, with me handling the technical side end to end."
    )
    cta_line = "Happy to get on a call this upcoming week to discuss further."

    common = {
        "greeting": greeting,
        "intro": intro,
        "link_lead": link_lead,
        "preview_url": preview_url,
        "price_line": price_line,
        "cta_line": cta_line,
        "founder": founder,
        "brand": brand,
    }
    html = env.get_template("email/outreach.html.j2").render(
        footer_html=footer_html(cfg, email), **common
    )
    text = env.get_template("email/outreach.txt.j2").render(
        footer_text=footer_text(cfg, email), **common
    )
    return SUBJECT, html, text
