# Play Store Go-Live Runbook — CreditVoice / tiTi

CreditVoice is a **PWA** and is already wired to ship as a **TWA** (Trusted Web
Activity — a thin Android wrapper that opens the PWA full-screen). The app serves
a valid `manifest.webmanifest`, a service worker, 192/512 (+maskable) icons, and
`/.well-known/assetlinks.json` (reads `TWA_PACKAGE_NAME` + `TWA_SHA256_FINGERPRINT`).
So going live is **packaging + a store listing + compliance forms** — no new app code.

Start URL: `https://creditvoiceai.com/app` · Privacy: `https://creditvoiceai.com/app/privacy`
Data deletion: `https://creditvoiceai.com/app/data-deletion`

---

## PART 1 — Checklist

### A. Google Play Developer account
- [ ] Registered at play.google.com/console (**$25 one-time**).
- [ ] **Identity / business verification** completed (personal ID, or org **D-U-N-S** number). *Start early — can take days.*
- [ ] Decide **personal vs organization** account (affects the closed-testing rule — see Part 4).

### B. Package the app as a TWA
- [ ] Generated the Android package at **pwabuilder.com** (enter `https://creditvoiceai.com/app`).
- [ ] Saved the **signing key** (`.keystore`) somewhere safe + backed up. **Losing it = can't update the app.**
- [ ] Noted the **package name** (e.g. `com.creditvoiceai.app`) and the **SHA-256 fingerprint**.

### C. Verify Digital Asset Links (opens without an address bar)
- [ ] Set on Render → redeploy:
  - `TWA_PACKAGE_NAME` = your package name
  - `TWA_SHA256_FINGERPRINT` = the signing key's SHA-256
- [ ] Confirm it returns your values: open `https://creditvoiceai.com/.well-known/assetlinks.json` (should NOT be an empty `[]`).
- [ ] Validate at Google's statement-list tester if unsure.

### D. Store listing assets
- [ ] **App icon** 512×512 PNG.
- [ ] **Feature graphic** 1024×500 PNG.
- [ ] **Phone screenshots** (min 2, up to 8) — e.g. Chat/tiTi, record sale, dashboard, customers/debtors.
- [ ] **Short description** (≤80 chars) + **full description** (≤4000) — drafts in Part 5.
- [ ] Category: **Business** (or Finance), **contact email**, **Privacy Policy URL** (above).

### E. Content & data forms
- [ ] **Content rating** questionnaire completed.
- [ ] **Data safety** form filled (answers in Part 6) — must match the Privacy Policy.
- [ ] **Target audience & content** (adults / 18+; not directed at children).
- [ ] **Ads**: declare **No ads**.
- [ ] **App access**: login required → provide **test credentials** for reviewers (a demo phone + PIN).
- [ ] **Government/financial** declarations if prompted (it's a business record-keeping tool, not a lender).

### F. Release
- [ ] Uploaded the signed **`.aab`** to a release track.
- [ ] Ran **Internal testing** (fast) to confirm it installs + opens full-screen (no browser bar).
- [ ] (If required) completed **Closed testing** — see Part 4.
- [ ] Promoted to **Production** and submitted for review.

---

## PART 2 — What's already done (no action)
- ✅ Installable PWA: manifest, service worker, 192/512 + maskable icons, HTTPS.
- ✅ `/.well-known/assetlinks.json` endpoint (just needs the two env values).
- ✅ Public **Privacy Policy** and **Data Deletion** pages (required fields).

## PART 3 — Keep the signing key safe
The `.aab` is signed with a key PWABuilder generates. **Back it up** (and consider
enrolling in **Play App Signing**). If lost, you cannot publish updates to the
same app — you'd have to ship a brand-new listing.

## PART 4 — ⚠️ New-account closed-testing rule
For **new personal** developer accounts, Google requires a **closed test with
~12–20 testers running for 14 continuous days** before you can apply for a
production release. **Organization** accounts are generally exempt. Plan for this:
recruit testers (a WhatsApp group of early users works) and start the 14-day clock
as soon as the build is ready.

---

## PART 5 — Store listing copy (drafts)

**App name:** CreditVoice — Sales, Debt & Stock

**Short description (≤80):**
```
Record sales, track who owes you, and manage stock — on WhatsApp and the web.
```

**Full description (draft):**
```
CreditVoice turns bookkeeping into a chat. Meet tiTi — your business assistant on
WhatsApp and the web — built for small and medium businesses in Nigeria.

• Know who owes you. Record credit sales and never forget a debt again.
• Record sales in seconds — just type what happened.
• Track your stock and see your profit.
• Send receipts and invoices customers can trust.
• Simple dashboards: sales, debtors, and best-selling products.
• Thrift / Ajo savings groups, supplier tracking, staff and branches.

No accounting jargon. No new habits — you already use WhatsApp all day.
Free to start; upgrade as your business grows.

CreditVoice is a record-keeping and business-management tool. It is not a bank or
a lender.
```

---

## PART 6 — Data Safety form answers (map to Privacy Policy)

**Does the app collect or share user data?** Yes (collect). **Sell data?** No.
**Encrypted in transit?** Yes (HTTPS). **Can users request deletion?** Yes (in-app + the data-deletion page).

Declare these data types as **collected** (purpose: App functionality / Account management; **not** shared for ads; **not** sold):
- **Personal info:** Name, Phone number, Email (optional), Address (business), User IDs.
- **Financial info:** "Other financial info" — the user's own business records (sales, payments, customer balances, inventory). *(Not payment-card data.)*
- **Messages:** Text/voice messages the user sends to tiTi (for the AI to interpret transactions).
- **App activity:** In-app actions / usage.
- **App info & performance:** Diagnostics/crash logs (if applicable).
- **Device or other IDs / approximate location:** IP-derived, country-level (if applicable).

Security practices to tick:
- Data is **encrypted in transit**.
- Users can **request that data be deleted** (link the data-deletion URL).
- A way to review/manage data (DSAR/erasure endpoints exist).

*(Keep this exactly consistent with `/app/privacy`. If a field there changes, update here.)*

---

## Bottom line
Critical path: **verify Google account → generate TWA on PWABuilder → set the 2 env
vars + confirm assetlinks → build listing + Data Safety → (14-day closed test if
personal account) → submit to Production.**
