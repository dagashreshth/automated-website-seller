"""Manual CSV lead source.

Drop any leads here from anywhere — exported via the Apollo MCP, a directory
site, a referral, whatever. This is the practical high-quality path: paste in
verified business emails and the pipeline builds + sends for them.

Expected columns (header row, case-insensitive, extras ignored):
  name, email, category, address, city, country, phone, website
Only `name` and `email` are required per row.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def find_prospects(cfg: dict) -> list[dict]:
    mc = cfg.get("manual_csv", {})
    if not mc.get("enabled", False):
        return []
    path = ROOT / mc.get("path", "leads_manual.csv")
    if not path.exists():
        return []

    out: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() }
            name = row.get("name", "")
            email = row.get("email", "").lower()
            if not name or not email:
                continue
            out.append({
                "source": "manual",
                "name": name,
                "category": row.get("category", "local business"),
                "email": email,
                "phone": row.get("phone", ""),
                "website": row.get("website") or None,
                "address": row.get("address", ""),
                "city": row.get("city", ""),
                "country": row.get("country", ""),
            })
    print(f"  [manual] {len(out)} prospects from {path.name}")
    return out
