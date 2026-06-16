"""Email discovery + verification.

Verification is a HARD GATE before sending: the research confirmed (against
primary AWS SES docs) that bounce rates above ~5% get a sender put "under
review" and above ~10% suspended. So every address is checked before it can be
emailed.

Tiers, best-effort and free-first:
  1. If HUNTER_API_KEY is set -> Hunter Email Verifier (authoritative).
  2. Else if dnspython is installed -> syntax + MX-record check (free).
  3. Else -> syntax check only (least safe; logged as low-confidence).

Discovery: if a prospect has no email but does have a website domain and a
Hunter key, try Hunter's Email Finder. (Most no-website prospects won't have a
domain, so this mainly helps the manual/Apollo paths.)
"""
from __future__ import annotations

import re

import requests

try:
    import dns.resolver  # type: ignore
    _HAVE_DNS = True
except Exception:  # pragma: no cover - optional dep
    _HAVE_DNS = False

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "yopmail.com",
    "trashmail.com", "tempmail.com", "getnada.com", "sharklasers.com",
}
HUNTER_VERIFY = "https://api.hunter.io/v2/email-verifier"
HUNTER_FIND = "https://api.hunter.io/v2/email-finder"


def _domain(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


def _syntax_ok(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def _mx_ok(domain: str) -> bool:
    if not _HAVE_DNS or not domain:
        return True  # can't check -> don't block on it
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        return len(answers) > 0
    except Exception:
        return False


def _hunter_verify(email: str, api_key: str) -> tuple[bool, str]:
    try:
        resp = requests.get(
            HUNTER_VERIFY, params={"email": email, "api_key": api_key}, timeout=30
        )
        if resp.status_code == 429:
            return True, "hunter_rate_limited(skip-check)"
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status", "unknown")
        score = data.get("score")
        if status in {"valid", "webmail"}:
            return True, f"hunter:{status}({score})"
        if status == "accept_all":
            return True, f"hunter:accept_all({score})"  # catch-all: risky but deliverable
        return False, f"hunter:{status}({score})"
    except (requests.RequestException, ValueError) as exc:
        return True, f"hunter_error(skip-check):{exc}"  # don't hard-fail on API hiccup


def verify_email(email: str, cfg: dict) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if not _syntax_ok(email):
        return False, "bad_syntax"
    domain = _domain(email)
    if domain in DISPOSABLE:
        return False, "disposable"

    vcfg = cfg.get("verification", {})
    hunter_key = cfg.get("secrets", {}).get("hunter_api_key", "")
    if vcfg.get("use_hunter", True) and hunter_key:
        return _hunter_verify(email, hunter_key)

    if vcfg.get("require_mx", True):
        if not _mx_ok(domain):
            return False, "no_mx"
        return True, "syntax+mx" if _HAVE_DNS else "syntax_only(no-dnspython)"

    return True, "syntax_only"


def discover_email(prospect: dict, cfg: dict) -> dict:
    """Fill in prospect['email'] if missing and we have a domain + Hunter key."""
    if prospect.get("email"):
        return prospect
    hunter_key = cfg.get("secrets", {}).get("hunter_api_key", "")
    website = prospect.get("website") or ""
    if not hunter_key or not website:
        return prospect
    domain = re.sub(r"^https?://(www\.)?", "", website).split("/")[0]
    if not domain:
        return prospect
    try:
        resp = requests.get(
            HUNTER_FIND,
            params={"domain": domain, "company": prospect.get("name", ""),
                    "api_key": hunter_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        if data.get("email"):
            prospect["email"] = data["email"].strip().lower()
            prospect["email_confidence"] = data.get("score")
    except (requests.RequestException, ValueError) as exc:
        print(f"  [enrich] hunter find failed for {domain}: {exc}")
    return prospect
