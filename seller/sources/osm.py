"""OpenStreetMap lead source — FREE, no API key.

Strategy (validated by research):
  1. Geocode each target area name -> bounding box via Nominatim (free).
  2. Query the Overpass API for businesses in that box that have NO website
     tag, using the [!"website"] negation operator.
  3. Keep the ones that publish an email (auto-emailable); the rest are
     returned flagged no_email so the caller can log them for phone follow-up.

Respect the public-instance usage policies: a descriptive User-Agent and
modest request volume.
"""
from __future__ import annotations

import time

import requests

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"

# Pretty labels for the common OSM category values we target.
CATEGORY_LABELS = {
    "cafe": "café", "restaurant": "restaurant", "bar": "bar", "pub": "pub",
    "hairdresser": "hair salon", "beauty": "beauty salon", "clothes": "boutique",
    "florist": "florist", "jewelry": "jewellery shop", "bakery": "bakery",
    "butcher": "butcher", "massage": "massage studio", "car_repair": "auto shop",
}


def _user_agent(cfg: dict) -> str:
    email = cfg.get("brand", {}).get("from_email", "contact@example.com")
    return f"automated-website-seller/0.1 ({email})"


def geocode_area(area: str, cfg: dict) -> dict | None:
    """Return {bbox: (S,W,N,E), country: str} for a free-text place, or None."""
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
        print(f"  [osm] geocode failed for {area!r}: {exc}")
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
    no_site = '[!"website"][!"contact:website"][!"contact:url"]'
    parts = []
    for cat in categories:
        sel = _selector(cat) + no_site
        # nodes and ways (polygons) both hold POIs; relations are rare here.
        parts.append(f"  node{sel}{box};")
        parts.append(f"  way{sel}{box};")
    body = "\n".join(parts)
    return f"[out:json][timeout:60];\n(\n{body}\n);\nout tags center 200;"


def _label_for(tags: dict) -> str:
    for key in ("amenity", "shop", "craft", "office", "leisure"):
        if key in tags:
            return CATEGORY_LABELS.get(tags[key], tags[key].replace("_", " "))
    return "local business"


def _to_prospect(el: dict, default_country: str) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    email = tags.get("email") or tags.get("contact:email") or ""
    phone = tags.get("phone") or tags.get("contact:phone") or ""
    addr_parts = [
        tags.get("addr:housenumber", ""), tags.get("addr:street", ""),
        tags.get("addr:city", ""), tags.get("addr:postcode", ""),
    ]
    address = " ".join(p for p in addr_parts if p).strip()
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    return {
        "source": "osm",
        "osm_id": f"{el.get('type')}/{el.get('id')}",
        "name": name,
        "category": _label_for(tags),
        "email": email.strip().lower(),
        "phone": phone,
        "website": None,
        "address": address,
        "city": tags.get("addr:city", ""),
        "country": tags.get("addr:country") or default_country,
        "lat": lat,
        "lon": lon,
        "instagram": tags.get("contact:instagram") or tags.get("instagram") or "",
    }


def find_prospects(cfg: dict) -> list[dict]:
    osm_cfg = cfg.get("osm", {})
    if not osm_cfg.get("enabled", False):
        return []
    categories = osm_cfg.get("categories", [])
    max_per_area = int(osm_cfg.get("max_per_area", 60))
    require_email = bool(osm_cfg.get("require_email", True))
    ua = _user_agent(cfg)

    out: list[dict] = []
    for area in osm_cfg.get("areas", []):
        print(f"  [osm] searching: {area}")
        geo = geocode_area(area, cfg)
        time.sleep(1.1)  # Nominatim: <=1 req/sec
        if not geo:
            continue
        query = _build_query(geo["bbox"], categories)
        try:
            resp = requests.post(
                OVERPASS, data={"data": query},
                headers={"User-Agent": ua}, timeout=90,
            )
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"  [osm] overpass failed for {area!r}: {exc}")
            continue

        count = 0
        for el in elements:
            if count >= max_per_area:
                break
            p = _to_prospect(el, geo["country"])
            if not p:
                continue
            if require_email and not p["email"]:
                continue
            out.append(p)
            count += 1
        print(f"  [osm] {area}: {count} usable prospects "
              f"({'with email' if require_email else 'incl. no-email'})")
        time.sleep(1.0)
    return out
