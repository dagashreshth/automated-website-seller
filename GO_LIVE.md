# GO_LIVE.md — From "Review Mode" to "Live Auto-Send"

This is your one-time setup checklist. The system already exists and works in **review mode** (it writes drafts but never sends). This guide covers **only the parts you must do yourself**: getting a booking link, setting up a sending domain, plugging in free email credentials, meeting the Gmail/Yahoo rules, and warming up safely before you flip the switch to `auto`.

Everything here uses **free or near-free** tools:
- **Cal.com Free** — $0 forever, public 30-min booking link.
- **Brevo Free** — $0, **300 emails/day**, real SMTP relay.
- A **domain** you already own (the only real cost, ~$10–15/yr if you don't have one).

Work top to bottom. Each step has a checklist. Don't flip `SEND_MODE=auto` until the **pre-flight checklist in Step 9** is all green.

> Throughout this guide, anything in `<ANGLE_BRACKETS>` is a **placeholder** — replace it with your own value. Don't paste it literally.

---

## Step 1 — Get your free Cal.com booking link

This becomes the call-to-action button in every email ("Book a 30-min call").

1. Go to **https://cal.com** and sign up (free "Individuals" plan — $0 forever, public booking page included).
2. Pick a username. This becomes your handle: `cal.com/<YOUR_HANDLE>`.
3. New accounts come with a default **"30 Min Meeting"** event whose slug is `30min`. Your link is:
   ```
   https://cal.com/<YOUR_HANDLE>/30min
   ```
   (If you'd rather build your own: **Event Types → + New**, set **Duration = 30 minutes**, set the **slug** to `30min`, save.)
4. Open the link in a private browser window to confirm it loads and shows open times.
5. Paste it into `config.yaml`:
   ```yaml
   brand:
     booking_url: "https://cal.com/<YOUR_HANDLE>/30min"
   ```

**Checklist**
- [ ] Cal.com account created (Free plan)
- [ ] 30-min event exists and the public link loads in a private window
- [ ] `brand.booking_url` in `config.yaml` updated with the real link

> Note: the Free plan keeps "Cal.com" branding on the page and is limited to 1 user. That's fine for outreach.

---

## Step 2 — Decide on a sending domain (use a SUBDOMAIN)

**Send cold email from a subdomain, not your main domain.** Example: `mail.shiftora.ai` instead of `shiftora.ai`.

**Why this matters:** mailbox providers track reputation per-domain. Cold outreach inevitably collects some spam complaints and bounces. If you send from your root domain, that damage spills onto your **business-critical mail** — your invoices, support replies, password resets, and your team's day-to-day inbox. A dedicated sending subdomain **walls off** outreach reputation so a bad week never poisons the mail you can't afford to lose. The subdomain also builds its own reputation over time.

You have two options:
- **Subdomain of a domain you already own** (recommended, $0): e.g. `mail.shiftora.ai`. You'll add DNS records to it in Step 4.
- **A separate cheap domain** just for outreach (e.g. `shiftora-mail.com`, ~$10/yr): maximum isolation, slightly more setup.

Your `FROM_EMAIL` (Step 6) will live on this subdomain, e.g. `hello@mail.shiftora.ai`.

> Keep the **friendly From name** and **reply-to** pointed at your real brand so humans recognise you (the system already sets `reply_to: info@shiftora.ai` in `config.yaml`). Only the technical sending domain is the subdomain.

**Checklist**
- [ ] Chosen a sending subdomain, e.g. `mail.<YOUR_DOMAIN>`
- [ ] You have access to that domain's **DNS settings** (where you bought the domain, or Cloudflare)
- [ ] Decided the `FROM_EMAIL` address you'll use, e.g. `hello@mail.<YOUR_DOMAIN>`

---

## Step 3 — Create a free Brevo account and find your SMTP credentials

Brevo (formerly Sendinblue) is the free SMTP relay that actually delivers the mail.

1. Sign up at **https://www.brevo.com** (Free plan: **300 emails/day**, reset daily, no rollover).
2. In the dashboard, open the **account dropdown (top-right) → Settings → SMTP & API → SMTP tab**.
3. Note the connection details (these are fixed for everyone):

   | Field | Value |
   |---|---|
   | **SMTP host** | `smtp-relay.brevo.com` |
   | **Port** | `587` (recommended — TLS/STARTTLS) |
   | **Alt port** | `2525` (use if 587 is blocked) · `465` (deprecated SSL) |
   | **Encryption** | Leave empty for 587/2525. Only pick SSL/TLS if you use 465. |
   | **SMTP login (username)** | a unique email shown on this page — your `<YOUR_BREVO_SMTP_LOGIN>` |

4. **Generate an SMTP key (this is your password — NOT an API key):**
   - On the **SMTP** tab, click **Generate a new SMTP key**.
   - Choose **Standard (64 characters)**.
   - **Copy it immediately and store it somewhere safe** — Brevo shows the full key **only once**.

> Important: you must use an **SMTP key** as the password, not an API key. The old "master SMTP password" is deprecated. And never delete an in-use SMTP key — doing so instantly stops sending.

**Checklist**
- [ ] Brevo Free account created
- [ ] Found host `smtp-relay.brevo.com`, port `587`
- [ ] Copied your **SMTP login** (`<YOUR_BREVO_SMTP_LOGIN>`)
- [ ] Generated and **saved** a Standard SMTP **key** (`<YOUR_BREVO_SMTP_KEY>`)

---

## Step 4 — Authenticate your domain in Brevo (DNS records)

This proves you own the domain and lets Brevo sign your mail so Gmail/Yahoo trust it.

In Brevo: **Senders, Domains & Dedicated IPs → Domains → Add a domain**, enter your sending subdomain (e.g. `mail.shiftora.ai`). Brevo then shows you **the exact records to add** — a **Brevo code** (ownership) and a **DKIM** record. **Always copy the values from your own Brevo console** — the ones below show the *shape* so you know what you're looking at. Then add a **DMARC** record yourself.

Go to your DNS provider and add these. Replace every placeholder with the values Brevo shows you:

| Purpose | Type | Host / Name | Value (copy from Brevo unless noted) |
|---|---|---|---|
| **Brevo code** (ownership) | TXT | `mail` *(your subdomain)* | `brevo-code:<CODE_FROM_BREVO>` |
| **DKIM** (signs your mail) | TXT *or* CNAME | `mail._domainkey.<SUBDOMAIN>` *(TXT)* **or** `brevo1._domainkey` + `brevo2._domainkey` *(CNAME pair)* | TXT: `k=rsa;p=<PUBLIC_KEY_FROM_BREVO>` · CNAME: `b1.<id>.dkim.brevo.com` / `b2.<id>.dkim.brevo.com` |
| **DMARC** (you create this) | TXT | `_dmarc.<SUBDOMAIN>` | `v=DMARC1; p=none; rua=mailto:dmarc-reports@<YOUR_DOMAIN>` |
| **SPF** (optional, see note) | TXT | `<SUBDOMAIN>` | `v=spf1 include:spf.brevo.com ~all` |

**Notes that save you hours:**
- **Use whichever DKIM format Brevo displays for your account** (older accounts get a TXT record; newer ones get the two CNAMEs). Don't mix — copy exactly what the console shows.
- **SPF is optional for Brevo.** Brevo achieves DMARC compliance through **DKIM alignment** on shared sending, so you don't strictly need an SPF record for Brevo to work. Add the one above only if you want SPF published anyway. (Gmail/Yahoo bulk rules in Step 5 are still satisfied via DKIM + DMARC.)
- DNS changes can take **a few minutes to a few hours** to propagate. Then click **Verify / Authenticate** in Brevo. Wait until Brevo shows **green checks** before sending.
- Start DMARC at `p=none` (monitor only — zero delivery impact). You'll tighten it later (Step 8).

**Checklist**
- [ ] Brevo **code** TXT record added
- [ ] **DKIM** record(s) added exactly as Brevo shows (TXT *or* the CNAME pair)
- [ ] **DMARC** TXT record added at `_dmarc.<SUBDOMAIN>` with `p=none` and a real `rua=` address
- [ ] (Optional) SPF TXT record added
- [ ] Returned to Brevo and clicked **Verify** — domain shows **green / authenticated**

---

## Step 5 — Meet the Gmail / Yahoo 2024+ bulk-sender rules

Since **February 1, 2024**, Gmail and Yahoo require all senders (and strictly enforce on **bulk senders** = more than **5,000 messages/day** to Gmail) to meet these four pillars. The good news: completing Steps 3–4 already covers most of them.

| Rule | What it means | How this system meets it |
|---|---|---|
| **SPF + DKIM** | Mail must be authenticated | DKIM via Brevo (Step 4). SPF optional but allowed. |
| **DMARC** | Published policy on your From domain, `p=none` minimum, aligned via SPF **or** DKIM | DMARC record at `_dmarc.<SUBDOMAIN>` (Step 4); DKIM aligns because Brevo signs with your domain |
| **One-click unsubscribe** | `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers **and** a visible unsubscribe link in the body; honor requests within **2 days** | The system includes an unsubscribe mechanism and auto-suppresses anyone who asks. Keep `brand.unsubscribe_email` set. |
| **Spam complaint rate < 0.30%** | Stay under the hard ceiling; aim **< 0.10%** | Tight targeting + low volume + the warm-up ramp in Step 8 |

Also required of all senders and already handled by Brevo's infrastructure: **TLS** for transmission, valid **forward + reverse DNS (PTR)**, and RFC-compliant message format.

> You'll likely send **well under** 5,000/day. You still must authenticate, publish DMARC, keep complaints low, and offer unsubscribe — these apply at any volume and protect your deliverability.

**Checklist**
- [ ] DKIM passing (Step 4 green checks)
- [ ] DMARC published (`p=none` or stricter)
- [ ] Unsubscribe handling on; `brand.unsubscribe_email` set in `config.yaml`
- [ ] Plan to watch spam rate (Step 8) and keep it **< 0.30%**, target **< 0.10%**

---

## Step 6 — Add the GitHub repository Secrets

These let the automated run authenticate to Brevo **without putting secrets in the code**. In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add each of these with the **EXACT name** shown:

| Secret name | Value | What it is |
|---|---|---|
| `SMTP_HOST` | `smtp-relay.brevo.com` | Brevo's SMTP server (fixed) |
| `SMTP_PORT` | `587` | TLS/STARTTLS port (recommended default) |
| `SMTP_USER` | `<YOUR_BREVO_SMTP_LOGIN>` | Your Brevo SMTP **login** from Step 3 |
| `SMTP_PASSWORD` | `<YOUR_BREVO_SMTP_KEY>` | Your Brevo SMTP **key** (NOT an API key) from Step 3 |
| `FROM_EMAIL` | `hello@mail.<YOUR_DOMAIN>` | The address mail is sent from (on your subdomain) |
| `FROM_NAME` | `Shiftora` | The friendly sender name recipients see |
| `SEND_MODE` | `review` | Master switch. Keep `review` until pre-flight passes — **then** set to `auto` |

**Explanation of each:**
- **`SMTP_HOST` / `SMTP_PORT`** — where to connect. Always `smtp-relay.brevo.com` and `587`.
- **`SMTP_USER`** — your Brevo SMTP login (a unique email-style username from the SMTP tab).
- **`SMTP_PASSWORD`** — your generated **SMTP key**. If sending breaks, this is the first thing to recheck.
- **`FROM_EMAIL`** — must be on the **authenticated subdomain** so DKIM aligns. Don't use a free Gmail/Yahoo address here.
- **`FROM_NAME`** — the human-readable name in the inbox (e.g. "Shiftora").
- **`SEND_MODE`** — `review` = drafts only (safe). `auto` = actually sends. This is your go-live switch and your kill switch.

> Secret **names are case-sensitive and must match exactly**. A typo here is the most common reason "nothing sends."

**Checklist**
- [ ] All 7 secrets added with **exact** names
- [ ] `SMTP_PASSWORD` is the **SMTP key**, not an API key
- [ ] `FROM_EMAIL` is on your **authenticated subdomain**
- [ ] `SEND_MODE` is still `review` for now

---

## Step 7 — Fill your postal address & keep volume low (config.yaml)

Two edits in `config.yaml`:

1. **Postal address (legally required).** CAN-SPAM (US), the Spam Act (AU), CASL (CA) and others **mandate a real physical postal address** in every marketing email. Put a real one (a registered business address or a mailbox you control):
   ```yaml
   brand:
     postal_address: "<YOUR REAL POSTAL ADDRESS, e.g. 12 Main St, Byron Bay NSW 2481, Australia>"
   ```
2. **Keep outreach volume low.** Start small and let reputation build (Step 8). The system caps sends per run here:
   ```yaml
   targeting:
     max_outreach_per_run: 15   # keep this low during warm-up
   ```

**Checklist**
- [ ] `brand.postal_address` is a **real** address (not the placeholder text)
- [ ] `targeting.max_outreach_per_run` is **low** (≈ 15 or less during warm-up)

---

## Step 8 — 3-week warm-up ramp + thresholds to watch

A brand-new sending domain has **no reputation**. Sending a lot on day one looks like spam. Ramp slowly. Below is a safe schedule for cold outreach from one mailbox. Set `targeting.max_outreach_per_run` to match the **daily** target (the system can run once/day).

| Week | Days | Emails/day (`max_outreach_per_run`) | Who to send to |
|---|---|---|---|
| **Week 1** | 1–7 | **10–20** | Your most relevant, highest-quality prospects |
| **Week 2** | 8–14 | **20–40** | Expand to real prospect list |
| **Week 3** | 15–21 | **40–60** | Continue steady growth |
| Week 4+ | 22+ | **60–80**, then hold | Steady state (cap ~100–150/day per mailbox) |

**Rules during ramp:**
- **Never spike.** Increase gradually; don't jump from 20 to 200.
- **Quality over quantity.** Tight targeting → replies and "not spam" signals → trust. Bad lists → complaints.
- **Brevo Free caps you at 300/day** anyway — a natural ceiling that keeps you safe.

**Thresholds to watch (pull volume back immediately if you cross these):**

| Metric | Target | Hard ceiling | Where to check |
|---|---|---|---|
| **Spam complaint rate** | **< 0.10%** | **< 0.30%** | Google Postmaster Tools (`postmaster.google.com`), Yahoo CFL |
| **Bounce rate** | **< 2%** | **> 3–5% = list-quality emergency** | Brevo dashboard stats |

If spam rate trends toward 0.10%+, or bounces exceed ~2–3%, **stop, lower volume, and clean/verify your list** before resuming. Set up **Google Postmaster Tools** (free) for your domain to watch the spam-rate dashboard.

**Checklist**
- [ ] Week 1 volume set low (10–20/day)
- [ ] Google Postmaster Tools set up for your domain
- [ ] You know your two numbers to watch: spam **< 0.30%**, bounce **< 2%**

---

## Step 9 — Final pre-flight checklist + how to roll back

Run **one last test in review mode**: trigger a run and read the generated drafts. Confirm the booking link, From name, unsubscribe line, and postal address all look right in an actual draft.

**Pre-flight — every box must be checked before you flip to `auto`:**
- [ ] **Booking link** works (`brand.booking_url`) — opened it live
- [ ] **Brevo domain authenticated** — green checks on DKIM (and DMARC published)
- [ ] **DMARC** record live at `_dmarc.<SUBDOMAIN>` (`p=none` minimum)
- [ ] **All 7 GitHub Secrets** present with exact names; `SMTP_PASSWORD` is the SMTP **key**
- [ ] **`FROM_EMAIL`** is on the authenticated subdomain
- [ ] **`postal_address`** is real (not placeholder)
- [ ] **`max_outreach_per_run`** set to Week-1 level (10–20)
- [ ] A **review-mode draft** looks correct: booking CTA, unsubscribe link, postal address present
- [ ] **Google Postmaster Tools** set up to monitor spam rate

**Flip the switch:** change the GitHub secret **`SEND_MODE`** from `review` to `auto`. The next scheduled run will send for real.

```
SEND_MODE = review   →   SEND_MODE = auto
```

**How to roll back (kill switch):** if deliverability dips, complaints rise toward 0.10%+, bounces exceed ~2–3%, or anything looks wrong — set **`SEND_MODE` back to `review`** in GitHub Secrets. The next run goes back to drafts-only and **sends nothing**. No code changes needed. Then lower `max_outreach_per_run`, clean your list, and ramp again from a lower volume.

---

## Sources

- Brevo SMTP (host/ports/keys): https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP
- Brevo ports 587/465/2525: https://help.brevo.com/hc/en-us/articles/10905415650322-Which-SMTP-port-should-I-use-Port-587-465-or-2525
- Brevo SMTP keys: https://help.brevo.com/hc/en-us/articles/7959631848850-Create-and-manage-your-SMTP-keys
- Brevo Free plan limits (300/day): https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan
- Brevo domain authentication (Brevo code / DKIM / DMARC): https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC
- Gmail/Yahoo bulk-sender rules (SPF+DKIM+DMARC, one-click unsubscribe, spam rate): https://support.google.com/a/answer/81126
- Google sender FAQ (spam rate, RFC 8058, 48-hr unsubscribe): https://support.google.com/a/answer/14229414
- Yahoo sender best practices: https://senders.yahooinc.com/best-practices/
- Cal.com pricing (Free plan): https://cal.com/pricing
- Warm-up & subdomain isolation guidance: https://www.topo.io/blog/safe-sending-limits-cold-email · https://www.mailgun.com/blog/deliverability/domain-warmup-reputation-stretch-before-you-send/
