"""Delivery layer.

Two modes (chosen by config 'sending.mode' or the SEND_MODE env var):
  - "review" (default): write a ready-to-send .eml draft to outbox/ and a row
    to outbox/review_queue.csv. You open/send them yourself. Zero cost, zero
    deliverability/legal risk until a human clicks send.
  - "auto": actually send over SMTP (needs SMTP_* secrets). Brevo's free tier
    (300/day) works well here.

Either way the message is a proper multipart/alternative (text + HTML) with a
List-Unsubscribe header, which both compliance and inbox placement want.
"""
from __future__ import annotations

import csv
import re
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from .compliance import unsubscribe_link
from .config import has_smtp

ROOT = Path(__file__).resolve().parent.parent
OUTBOX = ROOT / "outbox"
REVIEW_CSV = OUTBOX / "review_queue.csv"
REVIEW_FIELDS = [
    "name", "email", "phone", "website", "weakness_score", "website_issues",
    "subject", "preview_url", "eml_path", "country", "source",
]


def _safe_name(prospect: dict) -> str:
    base = re.sub(r"[^\w.-]+", "_", (prospect.get("email") or prospect.get("name") or "lead"))
    return base[:80]


def _build_message(prospect: dict, subject: str, html_body: str, text_body: str,
                   cfg: dict) -> EmailMessage:
    brand = cfg.get("brand", {})
    from_email = brand.get("from_email", "")
    from_name = brand.get("name", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = prospect["email"]
    if brand.get("reply_to"):
        msg["Reply-To"] = brand["reply_to"]
    # Deliverability + compliance: one-click unsubscribe.
    msg["List-Unsubscribe"] = f"<{unsubscribe_link(prospect['email'], cfg)}>"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _write_draft(prospect: dict, msg: EmailMessage, subject: str,
                 preview_url: str) -> Path:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    eml_path = OUTBOX / f"{_safe_name(prospect)}.eml"
    eml_path.write_bytes(bytes(msg))
    if REVIEW_CSV.exists():
        lines = REVIEW_CSV.read_text(encoding="utf-8").splitlines()
        first = lines[0].strip() if lines else ""
        if first.split(",") != REVIEW_FIELDS:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            REVIEW_CSV.rename(OUTBOX / f"review_queue_legacy_{ts}.csv")
    new_file = not REVIEW_CSV.exists()
    audit = prospect.get("website_audit") or {}
    with open(REVIEW_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({
            "name": prospect.get("name", ""),
            "email": prospect.get("email", ""),
            "phone": prospect.get("phone", ""),
            "website": prospect.get("website", ""),
            "weakness_score": audit.get("weakness_score", ""),
            "website_issues": ", ".join(audit.get("issues") or []),
            "subject": subject,
            "preview_url": preview_url,
            "eml_path": str(eml_path.relative_to(ROOT)),
            "country": prospect.get("country", ""),
            "source": prospect.get("source", ""),
        })
    return eml_path


def _send_smtp(msg: EmailMessage, cfg: dict) -> None:
    s = cfg["secrets"]
    with smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.login(s["smtp_user"], s["smtp_password"])
        server.send_message(msg)


def deliver(prospect: dict, subject: str, html_body: str, text_body: str,
            preview_url: str, cfg: dict) -> dict:
    mode = cfg.get("sending", {}).get("mode", "review").lower()
    msg = _build_message(prospect, subject, html_body, text_body, cfg)

    if mode == "auto" and has_smtp(cfg):
        try:
            _send_smtp(msg, cfg)
            time.sleep(int(cfg.get("sending", {}).get("delay_seconds", 30)))
            return {"sent": True, "mode": "auto", "detail": "smtp_ok"}
        except Exception as exc:  # fall back to a draft so the lead isn't lost
            path = _write_draft(prospect, msg, subject, preview_url)
            return {"sent": False, "mode": "review", "detail": f"smtp_failed:{exc}",
                    "draft": str(path)}

    path = _write_draft(prospect, msg, subject, preview_url)
    detail = "review_mode" if mode != "auto" else "auto_requested_but_no_smtp"
    return {"sent": False, "mode": "review", "detail": detail, "draft": str(path)}
