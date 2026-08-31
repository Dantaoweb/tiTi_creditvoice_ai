# CreditVoice / tiTi — Product Requirements Document (PRD)

> The **what** and **why** of the product. (For the **how to run the code**, see a
> README.) Living document — update as the product evolves.

---

## 1. Overview
**CreditVoice** is a business-management platform for small and medium scale
enterprises (SMEs) in Nigeria, delivered through a WhatsApp assistant called
**tiTi** and a companion **web dashboard** (also installable as an Android app via
PWA/TWA).

**One-liner:** *Run your business from WhatsApp — record sales, track who owes you,
manage stock, and save — with a web dashboard when you want the bigger picture.*

## 2. Problem
Nigerian SMEs track sales, customer credit, and stock in exercise books or in
their heads. The result: forgotten debts, money leakage, stock-outs, and no proof
of who paid what. Existing accounting apps are too heavy/jargon-heavy, and POS
hardware is costly. But every trader already lives on **WhatsApp**.

## 3. Target users
Everyday Nigerian businesses, prioritised as beachheads:
1. **Patent-medicine / pharmacy** — many SKUs, credit customers, receipts matter.
2. **Poultry & agriculture** — egg/feed tracking is a differentiator.
3. **Market traders / provisions / wholesalers** — high volume, credit-heavy.
4. **Thrift / ajo collectors (alajo)** — the savings engine is a standout.
5. **Artisans / services** (tailors, mechanics, salons) — deposits, "ready by" dates.

## 4. Goals & success metrics
- **Activation:** % of new users who record a first sale within their first session/week.
- **Retention:** week-4 retention of activated users.
- **Depth:** businesses tracking credit + stock (not just sales).
- **Growth:** referral-driven signups; cost per activated user from ads.

## 5. Non-goals (explicitly out of scope, for now)
- Not a **bank, lender, or licensed financial service**.
- Not full double-entry **accounting** / tax filing.
- Not a marketplace or e-commerce storefront.
- No outbound **disbursements** yet (payouts are recorded, paid by hand).

## 6. Product surfaces
- **tiTi on WhatsApp** — the primary channel. Record by typing (or voice on GO+).
  Replies, guided flows, reminders. Meta WhatsApp Cloud API.
- **Web dashboard** (`/app`) — richer management: inventory, POS, reports,
  customers, staff/branches, thrift groups, poultry, partners. React SPA.
- **Android app** — same web app wrapped as a **TWA** (PWA is Play-ready).

## 7. Core features
**Transactions & credit**
- Record sales, payments, and direct/cash income by chat or guided forms.
- Customer **credit/debt** tracking (who owes, balances, reminders).
- **Void** a transaction (returns stock; keeps an audit trail).

**Inventory**
- Products/services with cost, selling, **retail sub-unit** (e.g. sell eggs per
  crate or loose) and **wholesale** (quantity-break) pricing.
- Stock received (supplier purchases), stock movements history, price-change log.
- Low-stock alerts; catalog/bulk setup by business type.

**Point of Sale (web)** — product picker, cart, customer attach, part-payment,
settle prior debt at checkout, deliver/ready-by date.

**Receipts & invoices** — every sale and payment has a receipt; credit sales can
become formal invoices (INV-####) sent to the customer.

**Reports** — dashboard (sales, debtors, top products, period filters), and the
**Insights** report (margin snapshot, price changes, stock received/cost trend).

**Suppliers** — track purchases, balances owed, due reminders; a verified supplier
directory with an admin-brokered handshake.

**Staff & branches** — invite staff (own phone + PIN), scope them to a branch,
optional branch-admin; owner sees across branches.

**Thrift / Ajo / savings** — three group types:
- **Rotating (ajo):** fixed contribution, pot rotates by turn/choice.
- **Daily collection (alajo):** collect a daily amount from many customers; cash
  each out any time, keeping a commission.
- **Target (shared goal):** everyone saves toward one goal (e.g. Eid) — Pro+.
  Plus personal savings; invite links; caps; approver role; progress nudges.

**Poultry vertical** — an **Egg & Feed** screen: daily egg collection by grade
(production IN) + daily feed usage (consumption OUT), with an egg-production report
(collected vs sold, feed cost vs egg income).

**Partners & investors** (Pro/Premium) — link co-owners/investors with role, equity
%, and capital; copyable **phone-locked** invite link; role-scoped read-only view.

**Wallet (coming)** — virtual accounts (Monnify) to collect customer payments and
thrift contributions with auto-reconciliation. Inbound is built; outbound
disbursements are not yet.

**Growth** — referral program (invite → 14 days GO free; earn plan credit),
single-use token/plan codes for orgs/cooperatives.

## 8. Plans & monetization (4 tiers)
- **BASIC (free):** core recording, credit, personal savings, capped thrift groups
  (rotating/collector), up to 5 priced items.
- **GO:** unlimited inventory, invoices, exports, **voice**, reminder automation.
- **PRO:** branches, staff, partners/investors (1 each), **target** savings groups.
- **PREMIUM:** unlimited branches, partners, investors.
Freemium; upgrade by payment (Monnify) or token code. Expiry → auto-return to BASIC.

## 9. Platform & AI
- FastAPI + SQLAlchemy backend; React 19 SPA; SQLite dev / Postgres prod (Render).
- tiTi uses AI to interpret messages (Claude; OpenAI Whisper for voice). Users are
  told to verify important figures; anonymised review to improve accuracy.

## 10. Compliance, privacy & security
- **NDPA**-aligned Privacy Policy, Terms, and a public **Data Deletion** page.
- PBKDF2-hashed PINs, HMAC-signed sessions, per-tenant isolation, admin gating,
  signed webhooks. (See a security review for details.)

## 11. Roadmap / open items
- WhatsApp **message templates** + sender wiring (for proactive sends in production).
- **Fast-path onboarding** for cold ad traffic (skip to first debt).
- Supplier-purchase **void/reverse**.
- Wallet **disbursements** (auto-payouts) once Monnify disbursement is approved.
- Poultry **custom fields** (batch/vaccine expiry); adaptive mobile tab bar.
- Play Store + WhatsApp go-live (see the runbooks).

## 12. Open questions
- Primary beachhead segment + first market?
- Free-first vs paid-first positioning?
- Voice as a free acquisition hook (with a quota) vs a GO upsell?
