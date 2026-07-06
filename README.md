# Automated Website Seller

Finds local businesses that already have an **official but weak website**,
extracts the public email/phone from that site, auto-builds a **personalized
sample replacement site**, and prepares (or sends) a **cold-outreach email**
with a flat **$150** offer — running itself every morning on **GitHub Actions'
free tier**.

Built to run at **~$0** using OpenStreetMap, GitHub Pages, and GitHub Actions.
The only stage that may cost money is *sending* email (and even that has a free
tier) — by design you can run everything else for free and send by hand.

---

## How it works

```
  ┌──────────────┐   ┌───────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────┐
  │  Find leads  │ → │  Verify   │ → │ Build sample │ → │ Write outreach│ → │ Send or  │
  │ OSM/Apollo/  │   │ site +    │   │   website    │   │    email      │   │  draft   │
  │   manual CSV │   │ email     │   │ (GitHub Pages)│  │ ($150 CTA)    │   │ + phone  │
  └──────────────┘   └───────────┘   └──────────────┘   └───────────────┘   └──────────┘
        website weakness + official site email + dedup + suppression + country filter applied throughout
```

Each generated site lands at `previews/<slug>/index.html` and is served at
`<previews_base_url>/previews/<slug>/`. The email links to it.

---

## ⚠️ Read this first — the honest limits

1. **The old "no website" model bounced too much.** The default path now starts
   from businesses that publish an official website, crawls that site for a
   public email/phone, and only drafts outreach when the site itself exposes the
   address.
2. **Deliverability is a hard gate, not a nicety.** Per AWS SES's own docs, a
   sender goes "under review" above a **5%** bounce rate and is paused above
   **10%**. That's why every address is verified before sending and the per-run
   cap starts tiny. Sending blasts of unverified mail will get your domain
   blocked. ([AWS SES enforcement](https://docs.aws.amazon.com/ses/latest/dg/faqs-enforcement.html))
3. **Fully-automated unsolicited email is legally risky in your target
   countries.** See [Legal](#legal--compliance) — this is the biggest risk in
   the whole design and the research could not confirm it's lawful in the
   EU/EEA (Sweden, Finland), Canada, or Australia.

---

## Cost: what's free, what isn't

| Stage | Tool | Cost |
|---|---|---|
| Local lead sourcing | **OpenStreetMap / Overpass + Nominatim** | **Free**, no key |
| B2B lead sourcing | Apollo.io API (optional) | Free tier (throttled credits); paid for volume |
| Email find/verify | Hunter.io (optional) → else **MX + syntax** | Free tier / free fallback |
| Sample-site hosting | **GitHub Pages** (many sites, one repo) | **Free** |
| Orchestration / cron | **GitHub Actions** (2,000 min/mo private) | **Free** |
| State (dedup/suppression) | **CSV committed to the repo** | **Free** |
| **Email sending** | **Brevo SMTP free tier (300/day)**, or SES (~$0.10/1k) | **Free → cheap** |

The **minimum unavoidable cost is $0** if you send manually from the drafts.
For automated sending, Brevo's free 300/day tier keeps it at $0 up to that
volume; a dedicated sending domain (recommended, ~$10/yr) improves inbox rates.

---

## Quick start (local, 100% free)

```bash
# 1. install (uses a virtualenv so it won't touch system Python)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configure — edit config.yaml (areas, brand, price, website-audit threshold)
#    copy .env.example -> .env if you have any API keys (all optional)
cp .env.example .env

# 3. dry run: builds real sample sites + email drafts, sends nothing
python run.py --dry-run

# 4. look at the output
open previews/index.html        # gallery of generated sample sites
open outbox/                    # ready-to-send .eml drafts (open in Mail to send)
cat  outbox/review_queue.csv    # who/what/where + site score
cat  outbox/contact_list.csv    # end-of-day email/phone/site list
```

Useful flags: `--source osm|apollo|manual|all`, `--limit N`,
`--max-audit N`, `--areas-per-run N`, `--unsubscribe email@x.com`
(adds to the suppression list).

Run the test suite (no network, ~0.1s):

```bash
pip install -r requirements-dev.txt
pytest -q          # 19 unit tests: dedup, suppression, country gate, rotation, rendering
```

> Tip: set `SELLER_STATE_DIR` / `SELLER_PREVIEWS_DIR` to throwaway paths when
> experimenting, so your dry runs never touch the committed `state/` or
> `previews/`.

---

## Going live on GitHub Actions (runs while your laptop is shut)

```bash
# from this folder, with the GitHub CLI already logged in:
git init && git add -A && git commit -m "initial"
gh repo create automated-website-seller --public --source . --push
```

> **Why public?** GitHub Pages only hosts sites from public repos on the free
> plan, and the preview sites must be publicly reachable for prospects to open
> them. **No prospect PII is ever committed:** dedup/suppression are stored as
> SHA-256 hashes (`state/`), email drafts and run logs stay local/git-ignored
> (`outbox/`, `runs/`), and console output masks addresses — so the public repo
> and its Action logs contain no email addresses. The repo holds only the code
> and the generated sample sites (which are public by design).

Then, in the new repo:

1. **Enable Pages**: Settings → Pages → Source = *Deploy from a branch* →
   `main` / root. Your previews go live at
   `https://<you>.github.io/automated-website-seller/previews/<slug>/`.
   Put that base (without `/previews/...`) into `config.yaml → previews_base_url`.
2. **Add secrets** (Settings → Secrets and variables → Actions) for any of:
   `HUNTER_API_KEY`, `APOLLO_API_KEY`, `SMTP_HOST/PORT/USER/PASSWORD`,
   `FROM_EMAIL`, `FROM_NAME`, `SEND_MODE`.
3. **Schedule**: the included workflow runs in GitHub Actions, not on your
   laptop, so it still runs while your Mac is asleep or shut. The default
   schedule is `22:37 UTC`, which is **02:37 Asia/Dubai**. Edit the cron in
   `.github/workflows/daily.yml` if you want a different local time.
4. **Test it**: Actions tab → *Daily outreach* → *Run workflow*.
5. **Go auto** only when ready: set the `SEND_MODE` secret to `auto` and add
   the `SMTP_*` secrets (see **[GO_LIVE.md](GO_LIVE.md)**).

> **Review mode is a LOCAL workflow.** Scheduled cloud runs only do real work
> once `SEND_MODE=auto`. Why: in review mode the pipeline writes `.eml` drafts
> to the runner's `outbox/` — which **must stay private** (they contain prospect
> emails) and are destroyed with the runner. A scheduled review-mode run would
> build throwaway drafts yet still mark those prospects contacted, **burning
> leads you never emailed**. So while in review mode, **run it locally** to get
> drafts you can send by hand:
>
> ```bash
> python run.py            # finds leads, builds sites, writes outbox/*.eml
> open outbox/             # open each .eml in Mail and send the good ones
> ```
>
> (You can still trigger a manual cloud run from the Actions tab any time to
> test the cloud path — that always runs.) When you flip to `auto`, the daily
> cron sends for real and commits `state/` + `previews/` back to the repo.

The scheduled run always runs the **tests** as a health check, even in review
mode.

### Laptop-closed automation

Your laptop cannot run local Python/Codex tasks while it is shut. For overnight
unattended outreach, use the GitHub Actions workflow:

1. Add the GitHub Secrets from [GO_LIVE.md](GO_LIVE.md), including SMTP
   credentials and `SEND_MODE`.
2. Keep `SEND_MODE=review` while testing. Scheduled review-mode cloud runs only
   run tests, because private `.eml` drafts would be destroyed with the runner.
3. When domain authentication and warm-up checks are ready, set
   `SEND_MODE=auto`. From that point, the nightly GitHub Actions run does the
   full workflow and commits `state/` + `previews/` back to the repo.

---

## Sending email (the cheap-but-not-always-free part)

> **➡️ Full step-by-step setup is in [GO_LIVE.md](GO_LIVE.md)** — a 9-step,
> copy-pasteable guide that takes you from review mode to live auto-send using
> free/near-free tools (Brevo Free + your sending domain), with the exact DNS
> records, the Gmail/Yahoo 2024+ rules, a 3-week warm-up ramp, and a one-switch
> rollback.

You said you'll handle paid sending manually — so the default is **review mode**
(drafts you send yourself). To automate it cheaply:

- **Brevo** free tier: 300 emails/day over SMTP, $0. Put its SMTP creds in the
  `SMTP_*` secrets and set `SEND_MODE=auto`.
- **Authenticate your domain** (SPF, DKIM, DMARC) before any volume — cold mail
  from an unauthenticated domain goes straight to spam.
- **Warm up + ramp slowly.** Keep `max_outreach_per_run` low (10–20) for the
  first couple of weeks. Keep bounces under ~2% (verification gate handles this).
- Use a **separate domain/subdomain** for outreach so a reputation hit never
  touches your main inbox.

---

## Legal & compliance

**This is not legal advice. Get a lawyer before sending automated cold email
into the EU, Canada, or Australia.**

The research deliberately flagged that it **could not verify** fully-automated
unsolicited B2B cold email is lawful in:

- **EU/EEA (incl. Sweden & Finland)** — GDPR + ePrivacy generally require prior
  consent (opt-in) for marketing email; B2B has narrow leeway that varies by
  country. **Highest risk** of your targets.
- **Canada (CASL)** — strict opt-in; a limited B2B exemption exists.
- **Australia (Spam Act 2003)** — consent-based, but "inferred consent" can
  apply to a business whose address is *conspicuously published* and the message
  is *relevant to its function* — the most defensible of your targets.
- **US (CAN-SPAM)** — opt-out model; the most permissive.

**Guardrails this tool enforces automatically:**
- contacts only **published business addresses** with a **relevant** offer,
- includes a **truthful sender identity** + **real postal address** (set it in
  `config.yaml`!) + a working **unsubscribe** in every email,
- honors a permanent **suppression list** (`state/suppression.csv`),
- only contacts **allowed (high-income) countries**,
- never contacts anyone twice.

**Recommendation:** keep `require_email: true`, target role addresses
(`info@`, `contact@`) of businesses, and consider starting with **Australia/US**
(more defensible) before EU/Canada. Scraping Google Maps directly is a Terms-of-
Service breach — this tool uses OSM/official APIs instead and you should too.

---

## Lead sources

- **OpenStreetMap** (`config.yaml → osm`): set `areas` (free-text place names)
  and `categories` (`amenity=cafe`, `shop=hairdresser`, …). Pulls businesses
  with an official `website`/`contact:website` tag, then the audit stage fetches
  that site, extracts the public email/phone, and skips websites that already
  look good enough.
  **Daily rotation** is automatic: with `rotate: true` and `areas_per_run: N`,
  each run scans a fresh slice of the `areas` list and cycles through all of
  them over successive days — no rescanning, no manual rotation. Queries retry
  across several Overpass mirrors for reliability.
- **Apollo** (`config.yaml → apollo`): set `enabled: true` + `APOLLO_API_KEY`.
  Best for B2B (dentists, law firms). Free tier credits are limited.
- **Manual CSV** (`leads_manual.csv`): the practical high-quality path. Columns
  `name,email,category,address,city,country,phone,website` (only name+email
  required). **Tip:** use the Apollo MCP inside Claude to pull a batch of
  verified B2B leads, then paste them here.

---

## Configuration reference

All behaviour is in **`config.yaml`** (safe to edit, no secrets). Secrets go in
**`.env`** locally or **GitHub Secrets** in the cloud. Key knobs:

- `brand.*` — your name, from-email, flat **price**, unsubscribe inbox,
  **previews_base_url** (your Pages URL).
- `targeting.allowed_countries`, `targeting.max_outreach_per_run` (start low).
- `targeting.require_existing_website`, `targeting.require_website_listed_email`,
  `targeting.min_website_weakness_score` — the new quality gate.
- `targeting.max_audit_attempts` — hard cap on network-heavy website checks per
  run.
- `website_audit.connect_timeout_seconds`, `website_audit.timeout_seconds`,
  `website_audit.contact_pages` — how much of each official site to inspect for
  contact details and weakness signals.
- `osm.areas`, `osm.categories`, `osm.rotate`, `osm.areas_per_run`,
  `osm.overpass_timeout_seconds`.
- `verification.use_hunter`, `verification.require_mx`.
- `sending.mode` (`review`/`auto`), `sending.delay_seconds`.

## What each prospect gets

A **personalized, category-themed one-page site** (a café looks warm, a law firm
sharp), filled with their **real** scraped data — name, opening hours, cuisine,
address, phone, Instagram/Facebook — plus researched copy when available.
All inline CSS, no external assets, fully responsive, served free on GitHub Pages.
The **outreach email** uses one consistent personal note and carries the sample
link, the flat $150 offer, and a working unsubscribe.

---

## Why these choices (from the research)

- Google Maps is **no longer free** at useful volume: the old $200 credit was
  replaced March 2025 by small per-SKU caps, and the website field forces the
  **$20/1k Enterprise SKU**. OSM website tags are free, then this repo audits
  the official site directly.
  ([Google](https://developers.google.com/maps/billing-and-pricing/march-2025),
  [OSM](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL))
- **GitHub Actions**: 2,000 free private-repo minutes/mo, hard $0 cap with no
  card on file, Libsodium-encrypted secrets — but cron is **delayed/dropped at
  the top of the hour**, so we schedule off-peak.
  ([GitHub](https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions))
- **Hunter.io** is one API for both finding and verifying email.
  ([Hunter](https://hunter.io/api-documentation))

---

## Project layout

```
run.py                      # daily entrypoint / orchestrator
config.yaml                 # all settings (edit me)
GO_LIVE.md                  # step-by-step guide to switch on auto-send
.env.example                # secrets template (copy to .env)
requirements.txt            # runtime deps  ·  requirements-dev.txt = pytest
leads_manual.csv            # drop your own/Apollo-MCP leads here
seller/
  config.py  state.py  compliance.py  enrich.py
  website.py  outreach.py  sender.py
  sources/   osm.py  apollo.py  manual.py
  templates/ site/index.html.j2  site/gallery.html.j2
             email/outreach.html.j2  email/outreach.txt
tests/      test_pipeline.py   # 19 no-network unit tests
previews/                   # generated sample sites (served by Pages)
state/                      # sent.csv + suppression.csv (committed each run)
outbox/                     # local .eml drafts in review mode (gitignored)
.github/workflows/daily.yml # the free cron
```
