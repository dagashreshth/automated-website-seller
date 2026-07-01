"""Lightweight website contact extraction and quality scoring.

The new campaign targets businesses that already have an official website, but
where the site appears weak enough that a rebuilt $150 sample is a relevant
offer. This module stays dependency-light: requests + stdlib HTML parsing only.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
BAD_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com",
    "yourdomain.com", "shiftora.ai", "company.site",
    "sentry.wixpress.com", "sentry-next.wixpress.com",
}
BAD_EMAILS = {"filler@godaddy.com"}
BAD_EMAIL_PREFIXES = ("abuse@", "postmaster@", "noreply@", "no-reply@", "donotreply@")
FREE_BUILDER_DOMAINS = (
    "wixsite.com", "weebly.com", "godaddysites.com", "business.site",
    "myshopify.com", "square.site",
)
SOCIAL_ONLY_DOMAINS = (
    "facebook.com", "instagram.com", "linktr.ee", "beacons.ai",
)
ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".css", ".js")
PHONE_RE = re.compile(
    r"(?x)(?:\+?\d[\d\s().-]{7,}\d)"
)
CONTACT_LINK_RE = re.compile(r"(contact|about|get-in-touch|reach-us|visit|location|book)", re.I)
UNDER_CONSTRUCTION_RE = re.compile(
    r"(under construction|coming soon|site is unavailable|domain for sale|"
    r"parked free|this site can't be reached|default web site page)",
    re.I,
)


@dataclass
class PageSummary:
    url: str
    final_url: str = ""
    status_code: int = 0
    elapsed_seconds: float = 0
    html: str = ""
    title: str = ""
    meta_description: str = ""
    viewport: str = ""
    h1_count: int = 0
    stylesheet_count: int = 0
    form_count: int = 0
    jsonld_count: int = 0
    og_count: int = 0
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    links: list[str] = field(default_factory=list)
    error: str = ""


class _SummaryParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_chunks: list[str] = []
        self.in_title = False
        self.summary = PageSummary(url=base_url)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            content = attr.get("content", "")
            if name == "description" and content:
                self.summary.meta_description = content.strip()
            elif name == "viewport" and content:
                self.summary.viewport = content.strip()
            elif name.startswith("og:"):
                self.summary.og_count += 1
        elif tag == "h1":
            self.summary.h1_count += 1
        elif tag == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "")
            if "stylesheet" in rel or href.lower().endswith(".css"):
                self.summary.stylesheet_count += 1
        elif tag == "script":
            if attr.get("type", "").lower() == "application/ld+json":
                self.summary.jsonld_count += 1
        elif tag == "form":
            self.summary.form_count += 1
        elif tag == "a":
            href = attr.get("href", "").strip()
            if not href:
                return
            if href.lower().startswith("mailto:"):
                self.summary.emails.update(extract_emails(href))
            elif href.lower().startswith("tel:"):
                phone = _clean_phone(href.split(":", 1)[1])
                if phone:
                    self.summary.phones.add(phone)
            else:
                self.summary.links.append(urljoin(self.base_url, href))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_chunks.append(data)

    def close(self) -> None:
        super().close()
        self.summary.title = " ".join(" ".join(self.title_chunks).split()).strip()


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def site_domain(url: str) -> str:
    host = urlparse(normalize_url(url)).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def extract_emails(text: str) -> set[str]:
    text = unescape(text or "").replace("%40", "@").replace("%20", " ")
    out = set()
    for match in EMAIL_RE.findall(text):
        email = match.strip(" .,:;<>[](){}'\"").lower()
        if email in BAD_EMAILS:
            continue
        domain = email.split("@")[-1]
        if domain in BAD_EMAIL_DOMAINS:
            continue
        if any(email.startswith(prefix) for prefix in BAD_EMAIL_PREFIXES):
            continue
        local = email.split("@", 1)[0]
        if len(local) >= 24 and re.fullmatch(r"[a-f0-9]+", local):
            continue
        if "sentry" in domain or "wixpress.com" in domain:
            continue
        if email.endswith(ASSET_EXTENSIONS):
            continue
        out.add(email)
    return out


def _clean_phone(raw: str) -> str:
    raw = unescape(raw or "").strip()
    raw = re.sub(r"(?i)^tel:", "", raw)
    raw = re.sub(r"\s+", " ", raw)
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8 or len(digits) > 16:
        return ""
    return raw


def extract_phones(text: str) -> set[str]:
    out = set()
    for match in PHONE_RE.findall(unescape(text or "")):
        phone = _clean_phone(match)
        if phone:
            out.add(phone)
    return out


def _visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return unescape(re.sub(r"\s+", " ", html))


def _fetch(url: str, user_agent: str, connect_timeout: int, read_timeout: int) -> PageSummary:
    url = normalize_url(url)
    summary = PageSummary(url=url)
    if not url:
        summary.error = "missing_url"
        return summary
    started = time.monotonic()
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=(connect_timeout, read_timeout),
            allow_redirects=True,
        )
        summary.elapsed_seconds = time.monotonic() - started
        summary.status_code = resp.status_code
        summary.final_url = resp.url
        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype and resp.text.strip().startswith("<"):
            ctype = "text/html"
        if "text/html" not in ctype:
            summary.error = f"non_html:{ctype or 'unknown'}"
            return summary
        summary.html = resp.text[:1_000_000]
    except requests.RequestException as exc:
        summary.elapsed_seconds = time.monotonic() - started
        summary.error = exc.__class__.__name__
        return summary

    parser = _SummaryParser(summary.final_url or url)
    try:
        parser.feed(summary.html)
        parser.close()
        parsed = parser.summary
        parsed.url = url
        parsed.final_url = summary.final_url
        parsed.status_code = summary.status_code
        parsed.elapsed_seconds = summary.elapsed_seconds
        parsed.html = summary.html
        parsed.error = summary.error
        parsed.emails.update(extract_emails(summary.html))
        parsed.phones.update(extract_phones(_visible_text(summary.html)))
        return parsed
    except Exception as exc:  # HTMLParser should not abort the whole pipeline.
        summary.error = f"parse_error:{exc.__class__.__name__}"
        summary.emails.update(extract_emails(summary.html))
        summary.phones.update(extract_phones(_visible_text(summary.html)))
        return summary


def _same_site(url: str, base_domain: str) -> bool:
    host = site_domain(url)
    return host == base_domain or host.endswith("." + base_domain)


def _contact_links(summary: PageSummary, limit: int) -> list[str]:
    base = site_domain(summary.final_url or summary.url)
    out = []
    seen = set()
    for href in summary.links:
        clean = href.split("#", 1)[0]
        if not clean or clean in seen:
            continue
        if not _same_site(clean, base):
            continue
        path = urlparse(clean).path.lower()
        if CONTACT_LINK_RE.search(path):
            seen.add(clean)
            out.append(clean)
        if len(out) >= limit:
            break
    return out


def choose_email(emails: set[str], website_url: str) -> str:
    if not emails:
        return ""
    domain = site_domain(website_url)
    role_order = ("info@", "contact@", "hello@", "enquiries@", "enquiry@",
                  "bookings@", "booking@", "sales@", "office@", "admin@")
    ordered = sorted(emails)
    role = [e for e in ordered if e.startswith(role_order)]
    if role:
        return role[0]
    same_domain = [e for e in ordered if e.split("@", 1)[1] == domain]
    if same_domain:
        return same_domain[0]
    return ordered[0]


def choose_phone(phones: set[str]) -> str:
    if not phones:
        return ""
    return sorted(phones, key=lambda p: (0 if p.strip().startswith("+") else 1, len(p)))[0]


def score_weakness(summary: PageSummary, extra_pages: list[PageSummary]) -> tuple[int, list[str]]:
    """Return (0-100 weakness score, issue labels). Higher means weaker."""
    issues: list[str] = []
    score = 0
    html = summary.html or ""
    low_html = html.lower()
    host = site_domain(summary.final_url or summary.url)

    if summary.error:
        score += 35
        issues.append(f"fetch:{summary.error}")
    if any(host == d or host.endswith("." + d) for d in FREE_BUILDER_DOMAINS):
        score += 30
        issues.append("free_builder_subdomain")
    if any(host == d or host.endswith("." + d) for d in SOCIAL_ONLY_DOMAINS):
        score += 25
        issues.append("social_page_as_website")
    if summary.status_code and summary.status_code >= 400:
        score += 35
        issues.append(f"http_{summary.status_code}")
    if normalize_url(summary.url).startswith("http://"):
        score += 10
        issues.append("no_https")
    if summary.elapsed_seconds >= 6:
        score += 18
        issues.append("very_slow")
    elif summary.elapsed_seconds >= 3:
        score += 10
        issues.append("slow")
    if not summary.viewport:
        score += 20
        issues.append("no_mobile_viewport")
    if not summary.title or len(summary.title) < 5:
        score += 8
        issues.append("weak_title")
    if not summary.meta_description:
        score += 6
        issues.append("missing_meta_description")
    if summary.h1_count == 0:
        score += 6
        issues.append("no_h1")
    if len(html) < 5_000:
        score += 10
        issues.append("thin_homepage")
    if summary.stylesheet_count == 0 and "<style" not in low_html:
        score += 6
        issues.append("little_visual_styling")
    if summary.form_count == 0 and "book" not in low_html and "contact" not in low_html:
        score += 6
        issues.append("weak_conversion_path")
    if summary.jsonld_count == 0 and summary.og_count == 0:
        score += 5
        issues.append("missing_modern_metadata")
    if UNDER_CONSTRUCTION_RE.search(html):
        score += 30
        issues.append("broken_or_placeholder_copy")
    if extra_pages:
        score = max(0, score - 5)
    return min(score, 100), issues


def audit_website(prospect: dict, cfg: dict) -> dict:
    """Fetch a prospect's site, extract official contacts, and score weakness.

    Mutates and returns a copy of the prospect-like dict for convenient pipeline
    use. The caller can then gate on `website_audit["weakness_score"]` and
    `website_audit["site_email_found"]`.
    """
    p = dict(prospect)
    url = normalize_url(p.get("website") or p.get("current_website") or "")
    if not url:
        p["website_audit"] = {
            "url": "", "weakness_score": 0, "issues": ["missing_website"],
            "site_email_found": False, "site_phone_found": False,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return p

    acfg = cfg.get("website_audit", {})
    connect_timeout = int(acfg.get("connect_timeout_seconds", 5))
    read_timeout = int(acfg.get("timeout_seconds", 8))
    max_contact_pages = int(acfg.get("contact_pages", 2))
    ua = cfg.get("brand", {}).get("from_email", "contact@example.com")
    user_agent = f"automated-website-seller/0.3 ({ua})"

    home = _fetch(url, user_agent, connect_timeout, read_timeout)
    extra = []
    for link in _contact_links(home, max_contact_pages):
        extra.append(_fetch(link, user_agent, connect_timeout, read_timeout))

    emails = set(home.emails)
    phones = set(home.phones)
    for page in extra:
        emails.update(page.emails)
        phones.update(page.phones)

    known_email = (p.get("email") or "").strip().lower()
    site_email = known_email if known_email in emails else choose_email(emails, home.final_url or url)
    site_phone = choose_phone(phones)
    if site_email:
        p["email"] = site_email
        p["email_source"] = "website"
    elif p.get("email"):
        p["email"] = str(p["email"]).strip().lower()
        p.setdefault("email_source", "source")
    if site_phone and not p.get("phone"):
        p["phone"] = site_phone

    weakness, issues = score_weakness(home, extra)
    p["website"] = home.final_url or url
    p["current_website"] = p["website"]
    p["website_audit"] = {
        "url": url,
        "final_url": home.final_url or url,
        "status_code": home.status_code,
        "elapsed_seconds": round(home.elapsed_seconds, 2),
        "weakness_score": weakness,
        "issues": issues,
        "site_email_found": bool(site_email),
        "site_phone_found": bool(site_phone),
        "emails_found": sorted(emails),
        "phones_found": sorted(phones),
        "contact_pages_checked": [page.final_url or page.url for page in extra],
        "title": home.title,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return p
