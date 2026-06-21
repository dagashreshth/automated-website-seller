"""OpenStreetMap lead source — FREE, no API key.

Strategy (validated by research):
  1. Geocode each target area name -> bounding box via Nominatim (free).
  2. Query the Overpass API for businesses in that box that have NO website
     tag, using the [!"website"] negation operator.
  3. Keep the ones that publish an email (auto-emailable); the rest are
     returned flagged no_email so the caller can log them for phone follow-up.

This is the coherent free engine for the whole product: it finds businesses
that genuinely have no website AND publish a contact email, which is exactly
who we can email a sample site to.

Robustness:
  - Overpass public instances are flaky, so we retry across several mirrors.
  - The `areas` list can be large; daily ROTATION picks a fresh slice each run
    (keyed by the calendar day) so we cycle through every town over time
    instead of rescanning the same place every morning.

We respect public-instance usage policies: a descriptive User-Agent and modest
request volume.
"""
from __future__ import annotations

import re
import time
from datetime import date

import requests

NOMINATIM = "https://nominatim.openstreetmap.org/search"

# Overpass public mirrors, tried in order until one answers.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Pretty labels for the common OSM category values we target.
CATEGORY_LABELS = {
    "cafe": "café", "restaurant": "restaurant", "bar": "bar", "pub": "pub",
    "fast_food": "eatery", "ice_cream": "ice cream shop",
    "hairdresser": "hair salon", "beauty": "beauty salon", "clothes": "boutique",
    "florist": "florist", "jewelry": "jewellery shop", "bakery": "bakery",
    "butcher": "butcher", "deli": "deli", "greengrocer": "grocer",
    "massage": "massage studio", "car_repair": "auto shop", "tyres": "tyre shop",
    "shoes": "shoe shop", "gift": "gift shop", "books": "bookshop",
    "optician": "optician", "pharmacy": "pharmacy", "pet": "pet shop",
    "dry_cleaning": "dry cleaner", "tattoo": "tattoo studio",
    "fitness_centre": "gym", "dentist": "dental practice", "doctors": "clinic",
    "veterinary": "veterinary clinic", "estate_agent": "estate agency",
    "travel_agency": "travel agency", "photographer": "photography studio",
    "electrician": "electrician", "plumber": "plumber", "carpenter": "carpenter",
    "painter": "painter & decorator", "gardener": "landscaper",
    "caterer": "caterer", "winery": "winery",
}


def _user_agent(cfg: dict) -> str:
    email = cfg.get("brand", {}).get("from_email", "contact@example.com")
    return f"automated-website-seller/0.2 ({email})"


def select_areas(osm_cfg: dict, day: int | None = None) -> list[str]:
    """Pick this run's areas. With rotation on, cycle through the full list a
    slice at a time, keyed by the calendar day, so every town is eventually
    scanned without rescanning the same one every morning. `day` defaults to
    today's ordinal; pass it explicitly for deterministic tests."""
    areas = [a for a in osm_cfg.get("areas", []) if a]
    if not areas:
        return []
    per_run = int(osm_cfg.get("areas_per_run", 0) or 0)
    if not osm_cfg.get("rotate", True) or per_run <= 0 or per_run >= len(areas):
        return areas
    if day is None:
        day = date.today().toordinal()
    start = (day * per_run) % len(areas)
    return [areas[(start + i) % len(areas)] for i in range(per_run)]


def geocode_area(area: str, cfg: dict) -> dict | None:
    """Return {bbox: (S,W,N,E), country: str} for a free-text place, or None."""
    for attempt in range(3):
        try:
            resp = requests.get(
                NOMINATIM,
                params={"q": area, "format": "json", "limit": 1, "addressdetails": 1},
                headers={"User-Agent": _user_agent(cfg)},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            hit = data[0]
            # Nominatim boundingbox = [south, north, west, east] as strings.
            s, n, w, e = (float(x) for x in hit["boundingbox"])
            country = hit.get("address", {}).get("country", "")
            if not country and "," in area:
                country = area.rsplit(",", 1)[-1].strip()
            return {"bbox": (s, w, n, e), "country": country}
        except (requests.RequestException, KeyError, ValueError) as exc:
            if attempt == 2:
                print(f"  [osm] geocode failed for {area!r}: {exc}")
                return None
            time.sleep(2 * (attempt + 1))
    return None


def _selector(category: str) -> str:
    """Turn 'amenity=cafe' or 'craft=*' into an Overpass key/value selector."""
    if "=" not in category:
        return f'["{category}"]'
    key, value = category.split("=", 1)
    if value == "*":
        return f'["{key}"]'
    return f'["{key}"="{value}"]'


def _build_query(bbox: tuple[float, float, float, float], categories: list[str]) -> str:
    s, w, n, e = bbox
    box = f"({s},{w},{n},{e})"
    # No website tag in any of its common forms.
    no_site = '[!"website"][!"contact:website"][!"contact:url"][!"url"]'
    # Must publish a contact email in one of its common forms — this is what
    # makes the prospect auto-emailable. (Done in Overpass to cut payload size.)
    parts = []
    for cat in categories:
        sel = _selector(cat) + no_site
        for kind in ("node", "way"):
            parts.append(f'  {kind}{sel}["email"]{box};')
            parts.append(f'  {kind}{sel}["contact:email"]{box};')
    body = "\n".join(parts)
    return f"[out:json][timeout:90];\n(\n{body}\n);\nout tags center 400;"


def _query_overpass(query: str, ua: str) -> list[dict]:
    """POST the query to each mirror in turn; return elements or []."""
    last = ""
    for url in OVERPASS_MIRRORS:
        try:
            resp = requests.post(
                url, data={"data": query},
                headers={"User-Agent": ua}, timeout=120,
            )
            if resp.status_code in (429, 504):  # busy/timeout -> next mirror
                last = f"{url} -> HTTP {resp.status_code}"
                time.sleep(2)
                continue
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except (requests.RequestException, ValueError) as exc:
            last = f"{url} -> {exc}"
            continue
    print(f"  [osm] all overpass mirrors failed ({last})")
    return []


def _label_for(tags: dict) -> str:
    for key in ("amenity", "shop", "craft", "office", "leisure", "healthcare"):
        if key in tags:
            return CATEGORY_LABELS.get(tags[key], tags[key].replace("_", " "))
    return "local business"


def _clean_handle(value: str) -> str:
    """Normalise an instagram/facebook value to a bare handle or short url."""
    value = (value or "").strip()
    if not value:
        return ""
    value = re.sub(r"^https?://(www\.)?(instagram\.com|facebook\.com)/", "", value, flags=re.I)
    return value.strip("/@ ").split("?")[0]


def _to_prospect(el: dict, default_country: str) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    email = (tags.get("email") or tags.get("contact:email") or "").strip().lower()
    phone = tags.get("phone") or tags.get("contact:phone") or ""
    addr_parts = [
        tags.get("addr:housenumber", ""), tags.get("addr:street", ""),
        tags.get("addr:suburb", ""), tags.get("addr:city", ""),
        tags.get("addr:postcode", ""),
    ]
    address = " ".join(p for p in addr_parts if p).strip()
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    cuisine = (tags.get("cuisine") or "").replace("_", " ").replace(";", ", ")
    return {
        "source": "osm",
        "osm_id": f"{el.get('type')}/{el.get('id')}",
        "name": name,
        "category": _label_for(tags),
        "email": email,
        "phone": phone,
        "website": None,
        "address": address,
        "city": tags.get("addr:city") or tags.get("addr:suburb", ""),
        "country": tags.get("addr:country") or default_country,
        "lat": lat,
        "lon": lon,
        "instagram": _clean_handle(tags.get("contact:instagram") or tags.get("instagram") or ""),
        "facebook": _clean_handle(tags.get("contact:facebook") or tags.get("facebook") or ""),
        "opening_hours": tags.get("opening_hours", ""),
        "cuisine": cuisine,
        "description": (tags.get("description") or "").strip(),
    }


def find_prospects(cfg: dict) -> list[dict]:
    osm_cfg = cfg.get("osm", {})
    if not osm_cfg.get("enabled", False):
        return []
    categories = osm_cfg.get("categories", [])
    max_per_area = int(osm_cfg.get("max_per_area", 60))
    ua = _user_agent(cfg)

    out: list[dict] = []
    seen: set[str] = set()
    areas = select_areas(osm_cfg)
    print(f"  [osm] scanning {len(areas)} area(s) this run: {', '.join(areas)}")
    for area in areas:
        print(f"  [osm] searching: {area}")
        geo = geocode_area(area, cfg)
        time.sleep(1.1)  # Nominatim: <=1 req/sec
        if not geo:
            continue
        query = _build_query(geo["bbox"], categories)
        elements = _query_overpass(query, ua)

        count = 0
        for el in elements:
            if count >= max_per_area:
                break
            p = _to_prospect(el, geo["country"])
            if not p or not p["email"]:
                continue
            if p["osm_id"] in seen:
                continue
            seen.add(p["osm_id"])
            out.append(p)
            count += 1
        print(f"  [osm] {area}: {count} emailable prospects (no website + published email)")
        time.sleep(1.0)
    return out
