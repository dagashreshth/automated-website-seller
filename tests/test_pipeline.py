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

from seller import compliance, enrich, outreach, site_audit, website  # noqa: E402
from seller.sources import osm                                     # noqa: E402
from seller.state import _hash, is_suppressed, prospect_key, sent_id  # noqa: E402

CFG = {
    "brand": {
        "name": "Shiftora", "from_email": "info@shiftora.ai",
        "reply_to": "info@shiftora.ai",
        "price": "$150",
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
    "email_source": "website", "website": "https://bluewren.com.au",
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
def _cafe_accents():
    return {website.PALETTES[n]["accent"] for n in ("coffee", "coffee2")}


def test_build_context_picks_category_theme():
    ctx = website.build_context(SAMPLE, CFG)
    # café maps to one of its palette options (chosen per-business by a hash)
    assert ctx["theme"]["accent"] in _cafe_accents()
    assert ctx["service_cards"]  # non-empty
    assert all(c.get("title") and c.get("blurb") for c in ctx["service_cards"])
    assert ctx["hours"]     # parsed
    assert ctx["theme"]["ink"] and ctx["theme"]["hero_from"]


def test_unknown_category_falls_back_to_default_theme():
    ctx = website.build_context(EMPTY, CFG)
    default_accents = {website.PALETTES[n]["accent"]
                       for n in ("default", "default2", "calm2", "steel")}
    assert ctx["theme"]["accent"] in default_accents


def test_brand_colors_drive_a_legible_derived_palette():
    p = dict(SAMPLE)
    p["brand_colors"] = {"primary": "#1e88e5"}  # a brand blue
    theme = website.build_context(p, CFG)["theme"]
    for key in ("accent", "accent_dark", "ink", "soft", "hero_from", "hero_to"):
        assert theme[key].startswith("#") and len(theme[key]) == 7
    # hero background must stay dark enough for white text
    assert sum(website._hex_to_rgb(theme["hero_from"])) / 3 < 0.4


def test_grayscale_brand_colors_stay_neutral():
    p = dict(SAMPLE)
    p["brand_colors"] = {"primary": "#696969", "secondary": "#111111"}
    theme = website.build_context(p, CFG)["theme"]
    assert theme["accent"] == "#4a4a4a"
    assert theme["hero_from"] == "#101010"
    assert theme["vibe"] == "neutral"


def test_palette_name_override_is_respected():
    p = dict(SAMPLE); p["palette_name"] = "vino"
    assert website.build_context(p, CFG)["theme"]["accent"] == website.PALETTES["vino"]["accent"]


# ----------------------------------------------------- template renders (no I/O)
def test_site_template_renders_full_and_empty():
    tmpl = website._env.get_template("site/index.html.j2")
    full = tmpl.render(**website.build_context(SAMPLE, CFG))
    assert "The Blue Wren Café" in full
    # the studio's note now lives quietly in the footer, not a top ribbon
    assert "Free sample site by Shiftora" in full
    # NO fabricated trust signals anywhere
    assert "Loved by locals" not in full
    assert "★★★★★" not in full
    # no booking/calendar link on the prospect's own site
    assert "cal.com" not in full
    # an almost-empty lead must still render without raising
    empty = tmpl.render(**website.build_context(EMPTY, CFG))
    assert "Nameless Co" in empty


def test_real_reviews_render_only_when_present():
    tmpl = website._env.get_template("site/index.html.j2")
    no_rev = tmpl.render(**website.build_context(SAMPLE, CFG))
    assert "What customers say" not in no_rev
    assert "what people say about" not in no_rev
    p = dict(SAMPLE)
    p["reviews"] = [{"text": "Best flat white in town.", "author": "Jo M.",
                     "source": "Google"}]
    with_rev = tmpl.render(**website.build_context(p, CFG))
    assert "What customers say" in with_rev
    assert "Best flat white in town." in with_rev


def test_injected_copy_is_used():
    p = dict(SAMPLE)
    p["copy"] = {
        "hero_headline": "The friendliest corner cafe in Fremantle",
        "hero_sub": "Single-origin coffee and house-baked pastries since 2014.",
        "services": [{"title": "Single-Origin Coffee", "blurb": "Roasted locally."}],
        "about": ["We opened our doors in 2014."],
    }
    out = website._env.get_template("site/index.html.j2").render(**website.build_context(p, CFG))
    assert "The friendliest corner cafe in Fremantle" in out
    assert "Single-origin coffee and house-baked pastries since 2014." in out
    assert "We opened our doors in 2014." in out


def test_slug_override_keeps_published_urls_stable():
    p = dict(SAMPLE); p["slug"] = "the-blue-wren-cafe-dda331"
    assert website._unique_slug(p) == "the-blue-wren-cafe-dda331"


def test_cta_is_category_aware_and_uses_phone():
    # a salon with a phone -> "book" CTA that dials the shop
    p = {"name": "Snip", "category": "hair salon", "phone": "+61 8 1234"}
    cta = website.build_context(p, CFG)["cta"]
    assert cta["kind"] == "book" and cta["href"] == "tel:+61 8 1234"
    # a bookshop with no phone -> "visit" CTA that scrolls to contact
    p2 = {"name": "Pages", "category": "bookshop"}
    cta2 = website.build_context(p2, CFG)["cta"]
    assert cta2["kind"] == "visit" and cta2["href"] == "#contact"


def test_menu_steps_gtk_render_only_when_present():
    tmpl = website._env.get_template("site/index.html.j2")
    plain = tmpl.render(**website.build_context(SAMPLE, CFG))
    # the section markup (not the always-present CSS) is absent without data
    assert '<section class="menu">' not in plain
    assert '<div class="steps-grid">' not in plain
    assert '<section class="gtk">' not in plain
    # cta band always present
    assert '<section class="cta-band">' in plain
    p = dict(SAMPLE)
    p["menu"] = {"title": "Our coffee", "groups": [
        {"name": "Coffee", "items": [{"name": "Flat white", "price": "$5"}]}]}
    p["steps"] = {"title": "How to order", "items": [{"title": "Walk in", "desc": "Grab a seat."}]}
    p["good_to_know"] = ["Dog-friendly", "EFTPOS & cash"]
    full = tmpl.render(**website.build_context(p, CFG))
    assert '<section class="menu">' in full
    # menu items use bracket access (not the dict.items method) -> real item shows
    assert "Our coffee" in full and "Flat white" in full and "$5" in full
    assert '<div class="steps-grid">' in full and "How to order" in full and "Walk in" in full
    assert '<section class="gtk">' in full and "Dog-friendly" in full


# ----------------------------------------------------------- email/outreach copy
def test_subject_is_short_nameless_and_clean():
    assert len(outreach.SUBJECT.split()) < 6
    assert "—" not in outreach.SUBJECT and "–" not in outreach.SUBJECT
    assert SAMPLE["name"] not in outreach.SUBJECT


def test_render_email_substitutes_and_excludes_booking_link():
    subject, html, text = website.render_email(SAMPLE, CFG, "https://prev/url/")
    assert subject == outreach.SUBJECT
    assert "The Blue Wren Café" in text and "The Blue Wren Café" in html
    assert "https://prev/url/" in text and "https://prev/url/" in html
    assert "$150" in text
    assert "current website" in text
    assert "doesn't have one yet" not in text
    # no calendar/booking link anywhere in the email
    assert CFG["brand"]["booking_url"] not in text
    assert "cal.com" not in text and "cal.com" not in html
    # personal sign-off
    assert "Shreshth / Shiftora" in text and "Shreshth / Shiftora" in html
    # NO postal address line anywhere (removed by request)
    assert CFG["brand"]["postal_address"] not in text
    assert CFG["brand"]["postal_address"] not in html
    assert "POSTAL ADDRESS" not in text.upper() and "POSTAL ADDRESS" not in html.upper()
    # sender id + unsubscribe still present (deliverability + opt-out)
    assert "info@shiftora.ai" in text and "Unsubscribe" in html


def test_render_email_possessive_for_names_ending_in_s():
    p = dict(SAMPLE)
    p["name"] = "Adore Charter Services"
    _, _, text = website.render_email(p, CFG, "https://prev/url/")
    assert "Adore Charter Services' current website" in text
    assert "Services's" not in text


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
    alias = dict(SAMPLE); alias["country"] = "United States of America"
    ok, _ = compliance.can_contact(alias, CFG, set())
    assert ok
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
    # postal address line removed; sender id + unsubscribe remain
    assert CFG["brand"]["postal_address"] not in compliance.footer_text(CFG, "a@b.com")
    assert "info@shiftora.ai" in compliance.footer_text(CFG, "a@b.com")
    assert "business website/contact address" in compliance.footer_text(CFG, "a@b.com")
    assert "Unsubscribe" in compliance.footer_html(CFG, "a@b.com")


# ------------------------------------------------------------- OSM helpers/rotation
def test_osm_selector_and_handle_and_label():
    assert osm._selector("amenity=cafe") == '["amenity"="cafe"]'
    assert osm._selector("craft=*") == '["craft"]'
    assert osm._clean_handle("https://instagram.com/bluewren/") == "bluewren"
    assert osm._clean_handle("@handle") == "handle"
    assert osm._label_for({"amenity": "cafe"}) == "café"
    assert osm._label_for({"shop": "hairdresser"}) == "hair salon"
    query = osm._build_query((1, 2, 3, 4), ["amenity=cafe"])
    assert '["website"]' in query
    assert '[!"website"]' not in query


def test_osm_to_prospect_requires_name_and_extracts_fields():
    el = {"type": "node", "id": 7, "lat": 1.0, "lon": 2.0, "tags": {
        "name": "Joe's", "amenity": "cafe", "contact:email": "Joe@Joes.com",
        "website": "https://joes.example",
        "opening_hours": "Mo-Fr 09:00-17:00", "cuisine": "coffee",
        "contact:instagram": "https://instagram.com/joes"}}
    p = osm._to_prospect(el, "Australia")
    assert p["name"] == "Joe's" and p["email"] == "joe@joes.com"
    assert p["website"] == "https://joes.example"
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


# ------------------------------------------------------------- website audit
def test_site_audit_extracts_contacts_and_scores_weak_page():
    html = """
    <html><head><title>Joe's Cafe</title></head>
    <body>
      <h1>Joe's Cafe</h1>
      <a href="mailto:hello@joes.example">Email us</a>
      <a href="tel:+61 8 1234 5678">Call</a>
      <p>Call +61 8 1234 5678 for bookings.</p>
    </body></html>
    """
    emails = site_audit.extract_emails(html)
    phones = site_audit.extract_phones(html)
    assert site_audit.choose_email(emails, "https://joes.example") == "hello@joes.example"
    assert site_audit.choose_phone(phones).startswith("+61")

    summary = site_audit.PageSummary(
        url="https://joes.example", final_url="https://joes.example",
        status_code=200, elapsed_seconds=0.2, html=html, title="Joe's Cafe",
        h1_count=1, emails=emails, phones=phones,
    )
    score, issues = site_audit.score_weakness(summary, [])
    assert score >= 25
    assert "no_mobile_viewport" in issues
    assert "missing_meta_description" in issues


def test_site_audit_filters_technical_emails_and_scores_builder_domains():
    html = """
    hello@realbusiness.com
    605a7baede844d278b89dc95ae0a9123@sentry-next.wixpress.com
    abuse@company.site
    impallari@gmail.com
    hello@rfuenzalida.com
    """
    assert site_audit.extract_emails(html) == {"hello@realbusiness.com"}
    summary = site_audit.PageSummary(
        url="https://shop.wixsite.com/home",
        final_url="https://shop.wixsite.com/home",
        status_code=200,
        html="<html><head><meta name='viewport' content='width=device-width'></head><body><h1>Hi</h1></body></html>",
        title="Shop",
        meta_description="A shop",
        viewport="width=device-width",
        h1_count=1,
        stylesheet_count=1,
    )
    score, issues = site_audit.score_weakness(summary, [])
    assert score >= 30
    assert "free_builder_subdomain" in issues


def test_visible_text_strips_script_numbers_before_phone_extraction():
    html = """
    <script>var noise = '+0490-0491';</script>
    <p>Call 0435 353 838</p>
    """
    phones = site_audit.extract_phones(site_audit._visible_text(html))
    assert "0435 353 838" in phones
    assert "+0490-0491" not in phones


def test_site_audit_prefers_known_business_email(monkeypatch):
    html = """
    <html><head><meta name="viewport" content="width=device-width"></head>
    <body>info@latinotype.com saltybasketco@gmail.com</body></html>
    """

    class Resp:
        status_code = 200
        url = "https://saltybasketco.godaddysites.com/contact-us"
        headers = {"content-type": "text/html"}
        text = html
        def raise_for_status(self):
            return None

    monkeypatch.setattr(site_audit.requests, "get", lambda *a, **k: Resp())
    p = site_audit.audit_website({
        "name": "Salty Basket Co.",
        "website": "https://saltybasketco.godaddysites.com/contact-us",
        "email": "saltybasketco@gmail.com",
    }, {"brand": {"from_email": "info@shiftora.ai"}, "website_audit": {"contact_pages": 0}})
    assert p["email"] == "saltybasketco@gmail.com"
