#!/usr/bin/env python3
"""Automated Website Seller — daily entrypoint.

Pipeline:
  gather leads (OSM + Apollo + manual CSV)
    -> dedup against everyone already contacted
    -> for each, until the per-run cap is hit:
         discover email -> compliance check -> verify deliverability
         -> build a personalized sample website
         -> render the outreach email
         -> deliver (send via SMTP in 'auto' mode, or draft to outbox/ in 'review')
         -> record in state
    -> refresh the public gallery + write a run summary

Examples:
  python run.py --dry-run            # build sites + drafts, never send
  python run.py --source osm         # only OpenStreetMap leads
  python run.py --limit 5            # cap this run at 5 prospects
  python run.py --unsubscribe a@b.com   # add an address to the suppression list
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from seller import compliance, enrich, website
from seller.config import load_config
from seller.sender import deliver
from seller.sources import apollo, manual, osm
from seller.state import (add_suppression, load_sent_keys, load_suppression,
                          mark_sent, sent_id)

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"
OUTBOX_DIR = ROOT / "outbox"
CONTACT_LIST_FIELDS = [
    "name", "email", "phone", "website", "weakness_score", "website_issues",
    "preview_url", "country", "city", "category", "source",
]


def mask_email(email: str) -> str:
    """Mask an address for console/log output (logs can be public)."""
    email = email or ""
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    head = local[0] if local else "*"
    return f"{head}***@{domain}"


def gather(cfg: dict, only: str) -> list[dict]:
    leads: list[dict] = []
    if only in ("all", "osm"):
        leads += osm.find_prospects(cfg)
    if only in ("all", "apollo"):
        leads += apollo.find_prospects(cfg)
    if only in ("all", "manual"):
        leads += manual.find_prospects(cfg)
    return leads


def _website_gate(prospect: dict, cfg: dict) -> tuple[bool, str]:
    targeting = cfg.get("targeting", {})
    if targeting.get("require_existing_website", True) and not prospect.get("website"):
        return False, "no_website"

    audit = prospect.get("website_audit") or {}
    if targeting.get("require_website_listed_email", True) and not audit.get("site_email_found"):
        return False, "no_site_email"

    if targeting.get("require_weak_website", True):
        threshold = int(targeting.get("min_website_weakness_score", 25))
        score = int(audit.get("weakness_score") or 0)
        if score < threshold:
            return False, f"website_good_enough({score})"

    return True, "ok"


def _write_contact_list(items: list[dict]) -> Path | None:
    if not items:
        return None
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTBOX_DIR / "contact_list.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CONTACT_LIST_FIELDS)
        writer.writeheader()
        for item in items:
            audit = item.get("website_audit") or {}
            writer.writerow({
                "name": item.get("name", ""),
                "email": item.get("email", ""),
                "phone": item.get("phone", ""),
                "website": item.get("website", ""),
                "weakness_score": audit.get("weakness_score", ""),
                "website_issues": ", ".join(audit.get("issues") or []),
                "preview_url": item.get("preview_url", ""),
                "country": item.get("country", ""),
                "city": item.get("city", ""),
                "category": item.get("category", ""),
                "source": item.get("source", ""),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated Website Seller")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--source", default="all",
                    choices=["all", "osm", "apollo", "manual"])
    ap.add_argument("--limit", type=int, default=None,
                    help="override max outreach for this run")
    ap.add_argument("--max-audit", type=int, default=None,
                    help="override max website-audit attempts for this run")
    ap.add_argument("--areas-per-run", type=int, default=None,
                    help="override OSM area rotation width for this run")
    ap.add_argument("--dry-run", action="store_true",
                    help="build sites + drafts but never send")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the email verification gate (testing only)")
    ap.add_argument("--unsubscribe", metavar="EMAIL",
                    help="add an address/domain to the suppression list and exit")
    args = ap.parse_args()

    cfg = load_config(args.config)

    if args.unsubscribe:
        add_suppression(args.unsubscribe, reason="cli")
        print(f"Added to suppression list: {args.unsubscribe}")
        return 0

    if args.dry_run:
        cfg.setdefault("sending", {})["mode"] = "review"
    if args.max_audit is not None:
        cfg.setdefault("targeting", {})["max_audit_attempts"] = args.max_audit
    if args.areas_per_run is not None:
        cfg.setdefault("osm", {})["areas_per_run"] = args.areas_per_run

    cap = args.limit if args.limit is not None else \
        int(cfg.get("targeting", {}).get("max_outreach_per_run", 15))
    mode = cfg.get("sending", {}).get("mode", "review")

    print(f"=== Automated Website Seller ===")
    print(f"mode={mode}  cap={cap}  source={args.source}"
          f"{'  [DRY-RUN]' if args.dry_run else ''}")

    # 1. gather + dedup
    leads = gather(cfg, args.source)
    sent_keys = load_sent_keys()
    suppression = load_suppression()
    fresh = [p for p in leads if sent_id(p) not in sent_keys]
    print(f"gathered={len(leads)}  new(after dedup)={len(fresh)}")

    # 2. qualify + act, until cap
    skips: Counter = Counter()
    actioned = []
    audit_attempts = 0
    max_audit_attempts = int(cfg.get("targeting", {}).get("max_audit_attempts", cap * 12))
    for p in fresh:
        if len(actioned) >= cap:
            break
        if audit_attempts >= max_audit_attempts:
            skips["audit_attempt_cap"] += len(fresh) - audit_attempts
            break
        p = enrich.discover_email(p, cfg)
        audit_attempts += 1
        print(f"  [audit] {audit_attempts}/{max_audit_attempts} "
              f"{p.get('name','?')} -> {p.get('website') or '-'}", flush=True)
        p = enrich.audit_existing_website(p, cfg)

        if sent_id(p) in sent_keys:
            skips["already_sent_after_site_audit"] += 1
            continue

        wok, wreason = _website_gate(p, cfg)
        if not wok:
            skips[wreason] += 1
            continue

        ok, reason = compliance.can_contact(p, cfg, suppression)
        if not ok:
            skips[reason] += 1
            continue

        if not args.no_verify:
            vok, vreason = enrich.verify_email(p["email"], cfg)
            if not vok:
                skips[f"unverified:{vreason}"] += 1
                continue

        preview_url, _ = website.build_preview(p, cfg)
        subject, html, text = website.render_email(p, cfg, preview_url)
        result = deliver(p, subject, html, text, preview_url, cfg)
        mark_sent(p, preview_url=preview_url, mode=result["mode"])
        audit = p.get("website_audit") or {}
        actioned.append({
            "name": p.get("name"), "email": p.get("email"),
            "phone": p.get("phone"), "website": p.get("website"),
            "country": p.get("country"), "city": p.get("city"),
            "category": p.get("category"), "source": p.get("source"),
            "website_audit": audit,
            "preview_url": preview_url, "result": result,
        })
        flag = "SENT" if result["sent"] else "DRAFT"
        score = audit.get("weakness_score", "?")
        print(f"  [{flag}] {p.get('name','?')} <{mask_email(p['email'])}> "
              f"score={score} phone={p.get('phone') or '-'} -> {preview_url}")

    # 3. refresh gallery + summary
    website.rebuild_gallery(cfg)
    contact_list = _write_contact_list(actioned)
    sent_count = sum(1 for a in actioned if a["result"]["sent"])
    summary = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode, "cap": cap, "source": args.source,
        "gathered": len(leads), "new_after_dedup": len(fresh),
        "actioned": len(actioned), "sent": sent_count,
        "drafted": len(actioned) - sent_count,
        "skips": dict(skips), "items": actioned,
    }
    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"{summary['ts'].replace(':', '').replace('-', '')}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n--- summary ---")
    print(f"actioned={len(actioned)} (sent={sent_count}, drafted={len(actioned)-sent_count})")
    if skips:
        print("skipped: " + ", ".join(f"{k}={v}" for k, v in skips.most_common()))
    print(f"run log: {out.relative_to(ROOT)}")
    if mode == "review" and actioned:
        print("review your drafts in outbox/ (open the .eml files, or outbox/review_queue.csv)")
    if contact_list:
        print(f"phone/contact list: {contact_list.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
