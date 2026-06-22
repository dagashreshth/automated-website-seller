"""Compliance guardrails.

The research could NOT confirm that fully-automated unsolicited email is lawful
in the EU/EEA (Sweden, Finland), Canada (CASL), or Australia (Spam Act). The
defensible posture this code enforces:
  - contact published BUSINESS role addresses with a relevant offer (the
    "inferred/implied consent" path under the Spam Act / CASL B2B exemption),
  - identify the sender truthfully,
  - provide a working one-click unsubscribe, and honor it forever,
  - only ever contact allowed (high-income) countries,
  - never contact anyone twice or anyone on the suppression list.
None of this is legal advice — see README "Legal".
"""
from __future__ import annotations

from urllib.parse import quote


def allowed_country(prospect: dict, allowed: list[str]) -> bool:
    country = (prospect.get("country") or "").strip()
    if not country:
        # Unknown country: be conservative and allow only if list is empty.
        return not allowed
    allowed_lower = {c.strip().lower() for c in allowed}
    return country.strip().lower() in allowed_lower


def unsubscribe_link(email: str, cfg: dict) -> str:
    """Zero-cost unsubscribe: a mailto that pre-fills an opt-out request.
    Anyone who sends it gets added to suppression on the next run."""
    unsub = cfg.get("brand", {}).get("unsubscribe_email", cfg["brand"].get("from_email", ""))
    subject = quote(f"UNSUBSCRIBE {email}")
    body = quote("Please remove me from your list.")
    return f"mailto:{unsub}?subject={subject}&body={body}"


def footer_text(cfg: dict, recipient_email: str) -> str:
    b = cfg.get("brand", {})
    return (
        f"\n\n--\n{b.get('name','')} | {b.get('from_email','')}\n"
        f"You received this one-time message because your business is publicly "
        f"listed without a website. To never hear from us again, reply with "
        f"'UNSUBSCRIBE' or email {b.get('unsubscribe_email','')}.\n"
    )


def footer_html(cfg: dict, recipient_email: str) -> str:
    b = cfg.get("brand", {})
    unsub = unsubscribe_link(recipient_email, cfg)
    return (
        '<hr style="border:none;border-top:1px solid #e5e5e5;margin:24px 0 12px">'
        '<p style="font-size:12px;color:#888;line-height:1.5">'
        f"{b.get('name','')} &middot; {b.get('from_email','')}<br>"
        "You received this one-time message because your business is publicly "
        "listed without a website. "
        f'<a href="{unsub}" style="color:#888">Unsubscribe</a>.'
        "</p>"
    )


def can_contact(prospect: dict, cfg: dict, suppression: set[str]) -> tuple[bool, str]:
    """Returns (ok, reason_if_not)."""
    from .state import is_suppressed  # local import to avoid cycle

    email = (prospect.get("email") or "").strip().lower()
    if not email:
        return False, "no_email"
    if "@" not in email:
        return False, "bad_email"
    if is_suppressed(email, suppression):
        return False, "suppressed"
    allowed = cfg.get("targeting", {}).get("allowed_countries", [])
    if not allowed_country(prospect, allowed):
        return False, f"country_not_allowed({prospect.get('country','?')})"
    return True, "ok"
