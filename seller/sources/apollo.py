"""Apollo.io B2B lead source (optional).

Free tier has API access but limited/throttled credits, so this is best for
low daily volume. Requires APOLLO_API_KEY. If the key is missing or apollo is
disabled in config, this returns [] silently — the pipeline carries on with
OSM + manual leads.

Note: Apollo masks emails ("email_not_unlocked@domain.com") until a credit is
spent. We keep only already-revealed, real-looking emails to avoid surprises.
"""
from __future__ import annotations

import requests

SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"


def _real_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if not email or "not_unlocked" in email or "@" not in email:
        return ""
    return email


def find_prospects(cfg: dict) -> list[dict]:
    ap = cfg.get("apollo", {})
    api_key = cfg.get("secrets", {}).get("apollo_api_key", "")
    if not ap.get("enabled", False) or not api_key:
        return []

    payload = {
        "person_titles": ap.get("titles", []),
        "person_locations": ap.get("locations", []),
        "q_organization_industries": ap.get("industries", []),
        "page": 1,
        "per_page": int(ap.get("per_page", 25)),
    }
    try:
        resp = requests.post(
            SEARCH_URL,
            json=payload,
            headers={"X-Api-Key": api_key, "Content-Type": "application/json",
                     "Cache-Control": "no-cache"},
            timeout=45,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
    except (requests.RequestException, ValueError) as exc:
        print(f"  [apollo] search failed: {exc}")
        return []

    out: list[dict] = []
    for person in people:
        email = _real_email(person.get("email"))
        if not email:
            continue
        org = person.get("organization") or {}
        out.append({
            "source": "apollo",
            "name": org.get("name") or person.get("name") or "",
            "contact_name": person.get("name", ""),
            "category": org.get("industry", "business"),
            "email": email,
            "phone": person.get("phone_numbers", [{}])[0].get("raw_number", "")
            if person.get("phone_numbers") else "",
            "website": org.get("website_url"),
            "address": org.get("street_address", ""),
            "city": person.get("city") or org.get("city", ""),
            "country": person.get("country") or org.get("country", ""),
        })
    print(f"  [apollo] {len(out)} prospects with revealed emails")
    return out
