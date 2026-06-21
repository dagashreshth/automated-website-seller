"""Unit tests for the pure (no-network) parts of the pipeline.

Run with:  pytest -q   (from the repo root, inside the venv)

These exercise the logic that decides who we contact, how we de-dupe and
suppress, how leads are parsed, how sites/emails render, and how area rotation
cycles — i.e. the bits where a silent bug would either leak PII, double-contact
someone, or email the wrong country. No network calls are made.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seller import compliance, enrich, outreach, website          # noqa: E402
from seller.sources import osm                                     # noqa: E402
from seller.state import _hash, is_suppressed, prospect_key, sent_id  # noqa: E402

CFG = {
    "brand": {
        "name": "Shiftora", "from_email": "info@shiftora.ai",
        "reply_to": "info@shiftora.ai",
        "postal_address": "12 Test St, Byron Bay NSW 2481, Australia",
        "booking_url": "https://cal.com/shiftora/30min",
        "unsubscribe_email": "info@shiftora.ai",
        "previews_base_url": "https://example.github.io/repo",
    },
    "targeting": {"allowed_countries": ["Australia", "United States"]},
}

SAMPLE = {
    "source": "osm", "osm_id": "node/1", "name": "The Blue Wren Café",
    "category": "café", "email": "hello@bluewren.com.au",
    "phone": "+61 8 1234 5678", "address": "1 High St, Fremantle",
    "city": "Fremantle", "country": "Australia", "lat": -32.05, "lon": 115.74,
    "instagram": "bluewren", "facebook": "bluewrencafe",
    "opening_hours": "Mo-Fr 07:00-15:00; Sa 08:00-14:00",
    "cuisine": "coffee, breakfast", "description": "",
}

EMPTY = {  # a minimal lead — everything optional is missing
    "source": "osm", "osm_id": "node/2", "name": "Nameless Co",
    "category": "local business", "email": "x@example.com", "country": "Australia",
}


# --------------------------------------------------------------- website/slug
def test_slugify_folds_accents_and_cleans():
    assert website.slugify("The Blue Wren Café!") == "the-blue-wren-cafe"
    assert website.slugify("") == "business"
    assert website.slugify("A/B  Test_Co") == "ab-testco"


def test_unique_slug_is_stable_and_distinct():
    a = website._unique_slug(SAMPLE)
    b = website._unique_slug(SAMPLE)
    c = website._unique_slug(EMPTY)
    assert a == b and a != c
    assert a.startswith("the-blue-wren-cafe-")


# ---------------------------------------------------------------- hours parse
def test_parse_hours_common_shapes():
    rows = website.parse_hours("Mo-Fr 07:00-15:00; Sa 08:00-14:00")
    assert rows == [
        {"day": "Mon–Fri", "time": "7:00 – 15:00"},
        {"day": "Sat", "time": "8:00 – 14:00"},
    ]
    assert website.parse_hours("24/7") == [{"day": "Every day", "time": "Open 24 hours"}]
    assert website.parse_hours("") == []
    # day list + multiple spans
    rows = website.parse_hours("Mo,We,Fr 09:00-12:00,13:00-17:00")
    assert rows[0]["day"] == "Mon, Wed, Fri"
    assert "&" in rows[0]["time"]


# ------------------------------------------------------------------- theming
def test_build_context_picks_category_theme():
    ctx = website.build_context(SAMPLE, CFG)
    assert ctx["theme"]["accent"] == website.PALETTES["coffee"]["accent"]
    assert ctx["services"]  # non-empty
    assert ctx["hours"]     # parsed
    assert ctx["theme"]["ink"] and ctx["theme"]["hero_from"]


def test_unknown_category_falls_back_to_default_theme():
    ctx = website.build_context(EMPTY, CFG)
    assert ctx["theme"]["accent"] == website.PALETTES["default"]["accent"]


# ----------------------------------------------------- template renders (no I/O)
def test_site_template_renders_full_and_empty():
    tmpl = website._env.get_template("site/index.html.j2")
    full = tmpl.render(**website.build_context(SAMPLE, CFG))
    assert "The Blue Wren Café" in full
    assert "make it yours" in full
    assert CFG["brand"]["booking_url"] in full
    # an almost-empty lead must still render without raising
    empty = tmpl.render(**website.build_context(EMPTY, CFG))
    assert "Nameless Co" in empty


# ----------------------------------------------------------- email/outreach copy
def test_every_outreach_variant_formats_cleanly():
    sub = {"name": "X", "city": "Y", "category": "café", "where": " in Y"}
    for v in outreach.VARIANTS:
        v["subject"].format(**sub)
        v["greeting"].format(**sub)
        v["cta"].format(**sub)
        for p in v["paras"]:
            p.format(**sub)


def test_variant_pick_is_deterministic():
    assert outreach._pick("a@b.com", 4) == outreach._pick("a@b.com", 4)


def test_render_email_substitutes_and_includes_links():
    subject, html, text = website.render_email(SAMPLE, CFG, "https://prev/url/")
    assert "Blue Wren" in subject
    assert "https://prev/url/" in text and "https://prev/url/" in html
    assert CFG["brand"]["booking_url"] in text
    # compliance footer present in both parts
    assert CFG["brand"]["postal_address"] in text
    assert CFG["brand"]["postal_address"] in html


# ------------------------------------------------------------- state / privacy
def test_hash_is_stable_and_pii_free():
    h = _hash("Hello@Example.com")
    assert h == _hash("hello@example.com")        # case-insensitive
    assert "@" not in h and "example" not in h     # no raw PII leaks
    assert len(h) == 32


def test_sent_id_keys_on_email_then_osm_then_name():
    assert prospect_key(SAMPLE).startswith("email:")
    no_email = dict(SAMPLE); no_email["email"] = ""
    assert prospect_key(no_email).startswith("osm:")
    assert sent_id(SAMPLE) == sent_id(dict(SAMPLE))


def test_suppression_matches_email_and_domain():
    supp = {_hash("blocked@foo.com"), _hash("bar.com")}
    assert is_suppressed("blocked@foo.com", supp)         # exact email
    assert is_suppressed("anyone@bar.com", supp)          # whole domain blocked
    assert not is_suppressed("ok@safe.com", supp)


# --------------------------------------------------------------- compliance gate
def test_can_contact_country_and_suppression_and_no_email():
    ok, _ = compliance.can_contact(SAMPLE, CFG, set())
    assert ok
    blocked = dict(SAMPLE); blocked["country"] = "India"
    ok, reason = compliance.can_contact(blocked, CFG, set())
    assert not ok and "country_not_allowed" in reason
    supp = {_hash(SAMPLE["email"])}
    ok, reason = compliance.can_contact(SAMPLE, CFG, supp)
    assert not ok and reason == "suppressed"
    noemail = dict(SAMPLE); noemail["email"] = ""
    ok, reason = compliance.can_contact(noemail, CFG, set())
    assert not ok and reason == "no_email"


def test_unsubscribe_link_and_footer():
    link = compliance.unsubscribe_link("a@b.com", CFG)
    assert link.startswith("mailto:info@shiftora.ai")
    assert "UNSUBSCRIBE" in link
    assert CFG["brand"]["postal_address"] in compliance.footer_text(CFG, "a@b.com")
    assert "Unsubscribe" in compliance.footer_html(CFG, "a@b.com")


# ------------------------------------------------------------- OSM helpers/rotation
def test_osm_selector_and_handle_and_label():
    assert osm._selector("amenity=cafe") == '["amenity"="cafe"]'
    assert osm._selector("craft=*") == '["craft"]'
    assert osm._clean_handle("https://instagram.com/bluewren/") == "bluewren"
    assert osm._clean_handle("@handle") == "handle"
    assert osm._label_for({"amenity": "cafe"}) == "café"
    assert osm._label_for({"shop": "hairdresser"}) == "hair salon"


def test_osm_to_prospect_requires_name_and_extracts_fields():
    el = {"type": "node", "id": 7, "lat": 1.0, "lon": 2.0, "tags": {
        "name": "Joe's", "amenity": "cafe", "contact:email": "Joe@Joes.com",
        "opening_hours": "Mo-Fr 09:00-17:00", "cuisine": "coffee",
        "contact:instagram": "https://instagram.com/joes"}}
    p = osm._to_prospect(el, "Australia")
    assert p["name"] == "Joe's" and p["email"] == "joe@joes.com"
    assert p["category"] == "café" and p["instagram"] == "joes"
    assert osm._to_prospect({"type": "node", "id": 8, "tags": {}}, "Australia") is None


def test_area_rotation_cycles_through_everything():
    areas = [f"town-{i}" for i in range(28)]
    cfg = {"areas": areas, "rotate": True, "areas_per_run": 4}
    # each run returns exactly per_run areas, all valid
    for day in range(40):
        sel = osm.select_areas(cfg, day=day)
        assert len(sel) == 4
        assert all(a in areas for a in sel)
    # over a full cycle (len/per_run = 7 days) every area is covered
    covered = set()
    for day in range(7):
        covered.update(osm.select_areas(cfg, day=day))
    assert covered == set(areas)
    # deterministic for a given day
    assert osm.select_areas(cfg, day=5) == osm.select_areas(cfg, day=5)


def test_rotation_disabled_returns_all():
    cfg = {"areas": ["a", "b", "c"], "rotate": False, "areas_per_run": 2}
    assert osm.select_areas(cfg) == ["a", "b", "c"]


# ---------------------------------------------------------------- verification
def test_verify_email_syntax_and_disposable():
    cfg = {"verification": {"use_hunter": False, "require_mx": False}, "secrets": {}}
    ok, _ = enrich.verify_email("good@example.com", cfg)
    assert ok
    ok, reason = enrich.verify_email("not-an-email", cfg)
    assert not ok and reason == "bad_syntax"
    ok, reason = enrich.verify_email("a@mailinator.com", cfg)
    assert not ok and reason == "disposable"
