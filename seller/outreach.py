"""Outreach email copy.

Several cohesive copy variants, picked deterministically per prospect (by a
hash of their address). That means:
  - wording varies across recipients, which reads more naturally and avoids the
    identical-blast fingerprint spam filters look for, while
  - any single address always gets the same wording (stable, reproducible).

Cold-email best practice baked in: short, plain, personal, a single clear ask,
and only two links (the sample site + the booking page) plus the unsubscribe.
"""
from __future__ import annotations

import hashlib

from .compliance import footer_html, footer_text

# Placeholders available to every string: {name} {city} {category} {where}
VARIANTS = [
    {
        "subject": "I built {name} a sample website",
        "greeting": "Hi {name} team,",
        "paras": [
            "I came across {name}{where} and noticed you don't seem to have a "
            "website yet — so I went ahead and built you a free sample one to "
            "show what it could look like.",
            "No strings attached, it's yours to look at. If you like the "
            "direction, I'd love to jump on a quick 30-minute call to tailor it "
            "to you — your photos, hours, booking, the lot — and get it live.",
            "Either way, hope it's a useful starting point.",
        ],
        "cta": "View your sample website",
    },
    {
        "subject": "{name} — made you a sample website",
        "greeting": "Hi there,",
        "paras": [
            "I help small businesses get a simple, good-looking website online. "
            "{name}{where} caught my eye because you don't have one yet, so I "
            "built a quick sample to show what's possible.",
            "Have a look — it's free and there's no catch. If it's close to what "
            "you'd want, a 30-minute call is all it takes to make it yours and "
            "get it live.",
        ],
        "cta": "See your free sample site",
    },
    {
        "subject": "A website for {name} (free sample inside)",
        "greeting": "Hello {name},",
        "paras": [
            "Quick one — I noticed {name}{where} is running without a website, "
            "which means people searching for you online can't easily find you. "
            "So I put together a free sample site for you to react to.",
            "It already uses your name, hours and details. If you like it, let's "
            "grab 30 minutes and I'll finish it off and get it live for you.",
        ],
        "cta": "Open your sample website",
    },
    {
        "subject": "Built {name} a quick website to look at",
        "greeting": "Hi {name} team,",
        "paras": [
            "I design simple websites for local businesses and made one for "
            "{name}{where} — completely free, just to show what it could look "
            "like online.",
            "Take a look whenever suits. If you'd like it tailored and published, "
            "a short 30-minute call is the easiest next step.",
            "Hope you like it!",
        ],
        "cta": "View your sample website",
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
    }
    html = env.get_template("email/outreach.html.j2").render(
        footer_html=footer_html(cfg, email), **common
    )
    text = env.get_template("email/outreach.txt").render(
        footer_text=footer_text(cfg, email), **common
    )
    return subject, html, text
