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


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated Website Seller")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--source", default="all",
                    choices=["all", "osm", "apollo", "manual"])
    ap.add_argument("--limit", type=int, default=None,
                    help="override max outreach for this run")
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
    for p in fresh:
        if len(actioned) >= cap:
            break
        p = enrich.discover_email(p, cfg)

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
        actioned.append({
            "name": p.get("name"), "email": p.get("email"),
            "country": p.get("country"), "source": p.get("source"),
            "preview_url": preview_url, "result": result,
        })
        flag = "SENT" if result["sent"] else "DRAFT"
        print(f"  [{flag}] {p.get('name','?')} <{mask_email(p['email'])}> -> {preview_url}")

    # 3. refresh gallery + summary
    website.rebuild_gallery(cfg)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
