"""Persistent state across runs: who we've already contacted (dedup) and who
must never be contacted (suppression / unsubscribes).

PRIVACY: this repo is meant to be public (so GitHub Pages can host the preview
sites for free). So we NEVER write raw email addresses to disk here — dedup and
suppression are keyed by a salted-ish SHA-256 hash. Raw emails exist only in
memory during a run and in the local-only, git-ignored outbox/ and runs/.

Both files are plain CSVs under state/ so the GitHub Action can commit them back
to the repo after each run — zero database, zero cost.
"""
from __future__ import annotations

import csv
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# SELLER_STATE_DIR lets tests/dry-runs use an isolated state dir so they never
# pollute the committed state/ files. Defaults to the repo's state/.
STATE_DIR = Path(os.environ.get("SELLER_STATE_DIR", str(ROOT / "state")))
SENT_CSV = STATE_DIR / "sent.csv"
SUPPRESSION_CSV = STATE_DIR / "suppression.csv"

# Note: no raw "email" column — only a hash, business name, and non-PII metadata.
SENT_FIELDS = ["key", "name", "source", "country", "preview_url", "sent_at", "mode"]
SUPPRESSION_FIELDS = ["value", "reason", "added_at"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(value: str) -> str:
    return hashlib.sha256((value or "").strip().lower().encode("utf-8")).hexdigest()[:32]


def prospect_key(prospect: dict) -> str:
    """Stable identity for dedup (in-memory, may contain raw email)."""
    email = (prospect.get("email") or "").strip().lower()
    if email:
        return f"email:{email}"
    if prospect.get("osm_id"):
        return f"osm:{prospect['osm_id']}"
    name = (prospect.get("name") or "").strip().lower()
    city = (prospect.get("city") or "").strip().lower()
    return f"name:{name}|{city}"


def sent_id(prospect: dict) -> str:
    """Hashed, PII-free identity persisted in sent.csv."""
    return _hash(prospect_key(prospect))


def _ensure_files() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SENT_CSV.exists():
        with open(SENT_CSV, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(
                fh, fieldnames=SENT_FIELDS, lineterminator="\n"
            ).writeheader()
    if not SUPPRESSION_CSV.exists():
        with open(SUPPRESSION_CSV, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(
                fh, fieldnames=SUPPRESSION_FIELDS, lineterminator="\n"
            ).writeheader()


def load_sent_keys() -> set[str]:
    """Set of hashed ids already contacted."""
    _ensure_files()
    with open(SENT_CSV, newline="", encoding="utf-8") as fh:
        return {row["key"] for row in csv.DictReader(fh) if row.get("key")}


def load_suppression() -> set[str]:
    """Set of hashed emails AND hashed domains to block."""
    _ensure_files()
    with open(SUPPRESSION_CSV, newline="", encoding="utf-8") as fh:
        return {row["value"].strip() for row in csv.DictReader(fh) if row.get("value")}


def is_suppressed(email: str, suppression: set[str]) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    if _hash(email) in suppression:
        return True
    domain = email.split("@")[-1] if "@" in email else ""
    return bool(domain and _hash(domain) in suppression)


def mark_sent(prospect: dict, *, preview_url: str, mode: str) -> None:
    _ensure_files()
    with open(SENT_CSV, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(
            fh, fieldnames=SENT_FIELDS, lineterminator="\n"
        ).writerow({
            "key": sent_id(prospect),
            "name": prospect.get("name", ""),
            "source": prospect.get("source", ""),
            "country": prospect.get("country", ""),
            "preview_url": preview_url,
            "sent_at": _now(),
            "mode": mode,
        })


def add_suppression(value: str, reason: str = "manual") -> None:
    """Store the HASH of an email or domain so the list never leaks addresses."""
    _ensure_files()
    hashed = _hash(value)
    if not value.strip() or hashed in load_suppression():
        return
    with open(SUPPRESSION_CSV, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(
            fh, fieldnames=SUPPRESSION_FIELDS, lineterminator="\n"
        ).writerow(
            {"value": hashed, "reason": reason, "added_at": _now()}
        )
