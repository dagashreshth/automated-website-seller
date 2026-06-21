"""Outreach email copy.

A short, personal introduction from the founder. Several cohesive variants,
picked deterministically per prospect (by a hash of their address) so wording
varies across recipients — reads naturally and avoids the identical-blast
fingerprint spam filters look for — while any single address always gets the
same wording.

Cold-email best practice baked in: short, plain, personal, one clear ask, and
only two links (the sample site + the booking page) plus the unsubscribe.

Placeholders available to every string:
  {founder}  {location}  {brand}  {price}  {name}  {city}  {category}  {where}
"""
from __future__ import annotations

import hashlib

from .compliance import footer_html, footer_text

VARIANTS = [
    {
        "subject": "I built {name} a free sample website",
        "greeting": "Hi {name} team,",
        "paras": [
            "My name's {founder} — I'm a {location}-based founder, and the "
            "{brand} team makes websites for companies exactly like yours. I "
            "noticed {name}{where} doesn't have a website yet, so I built you a "
            "free sample to show what we'd do:",
            "I'd love to set the full thing up for you at a flat {price} — that's "
            "everything, start to finish. Hosting and setup are handled (I can "
            "even run it all on my end, so there's nothing technical for you to "
            "worry about).",
            "It's yours to look at either way. If you like it, let's have a quick "
            "30-minute call.",
        ],
        "cta": "View your free sample website",
    },
    {
        "subject": "{name} — a free sample website (flat {price})",
        "greeting": "Hey there,",
        "paras": [
            "Quick hello — I'm {founder}, a {location}-based founder. My team at "
            "{brand} builds simple, great-looking websites for businesses like "
            "yours, and {name}{where} caught my eye because you don't have one "
            "yet. So I put together a free sample for you:",
            "If you'd like it live, it's a flat {price} — the full build, set up "
            "and hosted for you. I can run the whole thing on my end, so there's "
            "nothing technical for you to manage.",
            "Have a look whenever suits, and if it's close to what you'd want, "
            "let's grab 30 minutes.",
        ],
        "cta": "See your sample site",
    },
    {
        "subject": "Made {name} a sample website — {price} to go live",
        "greeting": "Hello {name},",
        "paras": [
            "I'm {founder}, a {location}-based founder — the {brand} team makes "
            "websites for local businesses, and I noticed {name}{where} doesn't "
            "have one yet. So here's a free sample I built for you:",
            "If you want it live, it's a flat {price} all in — designed, set up "
            "and hosted, with me handling the technical side end to end.",
            "Happy to tailor it to you on a quick 30-minute call whenever works.",
        ],
        "cta": "Open your sample website",
    },
]


def _pick(email: str, n: int) -> int:
    h = hashlib.sha256((email or "").encode("utf-8")).hexdigest()
    return int(h, 16) % max(n, 1)


def render(prospect: dict, cfg: dict, preview_url: str, env) -> tuple[str, str, str]:
    """Return (subject, html_body, text_body)."""
    brand = cfg.get("brand", {})
    email = prospect.get("email", "")
    v = VARIANTS[_pick(email, len(VARIANTS))]

    city = prospect.get("city", "")
    sub = {
        "founder": brand.get("founder", "Shreshth"),
        "location": brand.get("founder_location", "Dubai"),
        "brand": brand.get("name", "Shiftora"),
        "price": brand.get("price", "$299"),
        "name": prospect.get("name", "your business"),
        "city": city,
        "category": prospect.get("category", "business"),
        "where": f" in {city}" if city else "",
    }
    fmt = lambda s: s.format(**sub)
    subject = fmt(v["subject"])
    common = {
        "greeting": fmt(v["greeting"]),
        "paras": [fmt(p) for p in v["paras"]],
        "cta": fmt(v["cta"]),
        "preview_url": preview_url,
        "booking_url": brand.get("booking_url", "#"),
        "brand": brand,
        "founder": sub["founder"],
    }
    html = env.get_template("email/outreach.html.j2").render(
        footer_html=footer_html(cfg, email), **common
    )
    text = env.get_template("email/outreach.txt").render(
        footer_text=footer_text(cfg, email), **common
    )
    return subject, html, text
