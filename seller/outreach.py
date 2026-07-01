"""Outreach email copy for the weak-existing-website campaign.

The note is intentionally diplomatic: it never insults the current site. It
acknowledges that the business already has a website, links to a rough sample,
and quotes one flat price.
"""
from __future__ import annotations

from .compliance import footer_html, footer_text

# Subject: under six words, no recipient name, no em dashes.
SUBJECT = "A cleaner website sample"

ISSUE_LABELS = {
    "no_mobile_viewport": "the mobile experience",
    "missing_meta_description": "how it appears in search",
    "weak_conversion_path": "the contact flow",
    "thin_homepage": "the amount of useful detail",
    "little_visual_styling": "the visual polish",
    "missing_modern_metadata": "the search and sharing setup",
    "slow": "load speed",
    "very_slow": "load speed",
    "weak_title": "the page title",
    "no_h1": "the page structure",
    "broken_or_placeholder_copy": "some placeholder/broken-page signals",
}


def _site_note(prospect: dict) -> str:
    audit = prospect.get("website_audit") or {}
    issues = [ISSUE_LABELS[i] for i in (audit.get("issues") or []) if i in ISSUE_LABELS]
    if issues:
        named = ", ".join(dict.fromkeys(issues[:2]))
        return f"I noticed a few places where the current site could be stronger, especially {named}."
    return "I thought the current site could make a stronger first impression with a cleaner, more modern version."


def render(prospect: dict, cfg: dict, preview_url: str, env) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""
    brand = cfg.get("brand", {})
    email = prospect.get("email", "")

    founder = brand.get("founder", "Shreshth")
    location = brand.get("founder_location", "Dubai")
    brand_name = brand.get("name", "Shiftora")
    price = brand.get("price", "$150")
    name = prospect.get("name", "your business")

    greeting = f"Hi {name} team,"
    intro = (
        f"I'm {founder}, a {location}-based founder. The {brand_name} team makes "
        f"websites for local businesses. I was looking at {name}'s current website. "
        f"{_site_note(prospect)} So I put together a very rough sample in the "
        f"direction I think would work better."
    )
    link_lead = "Here is the link to open and check out the rough sample:"
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
