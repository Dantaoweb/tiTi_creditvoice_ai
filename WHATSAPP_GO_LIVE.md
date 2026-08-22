# WhatsApp Go-Live Runbook — CreditVoice / tiTi

The app already integrates the **Meta WhatsApp Cloud API** (sends via
`graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages`, receives at `POST /webhook`
with `X-Hub-Signature-256` verification). Going live is **configuration + Meta
setup**, plus **message templates** for anything tiTi sends outside the 24-hour
window. Callback URL: `https://creditvoiceai.com/webhook`.

---

## PART 1 — Go-live checklist

### A. Meta accounts & app
- [ ] Meta **Business account** created (business.facebook.com) and **Business Verification** started.
- [ ] **Meta App** created (developers.facebook.com) with the **WhatsApp** product added.
- [ ] **WhatsApp Business Account (WABA)** available under the app.

### B. Phone number
- [ ] tiTi business number added in App → WhatsApp → API Setup (number **not** already active on consumer WhatsApp / WhatsApp Business app).
- [ ] Number verified (SMS/voice).
- [ ] **Display name** submitted for approval.
- [ ] Copied **Phone Number ID** and **WABA ID**.

### C. Credentials
- [ ] **System User** created in Business Settings, assigned the App + WABA.
- [ ] **Permanent token** generated with `whatsapp_business_messaging` + `whatsapp_business_management` (set to **never expire**) → this is `WHATSAPP_TOKEN`.
- [ ] **App Secret** copied (App → Settings → Basic) → this is `META_APP_SECRET`.
- [ ] Chose a `VERIFY_TOKEN` string (any secret string).

### D. Webhook
- [ ] App → WhatsApp → Configuration → Webhook:
  - Callback URL: `https://creditvoiceai.com/webhook`
  - Verify token: the `VERIFY_TOKEN` value.
  - **Verify and Save** succeeded.
- [ ] Subscribed the WABA to the **messages** field.

### E. Environment (Render) — then redeploy
- [ ] `WHATSAPP_TOKEN`
- [ ] `PHONE_NUMBER_ID`
- [ ] `VERIFY_TOKEN`
- [ ] `META_APP_SECRET`
- [ ] `TITI_WHATSAPP` (display number for wa.me links, optional)
- [ ] Redeployed.

### F. Test
- [ ] Message the tiTi number from a phone → tiTi receives + replies.
- [ ] Render logs show **no** "WhatsApp send skipped: WHATSAPP_TOKEN or PHONE_NUMBER_ID is missing".
- [ ] Signature check passing (no "META_APP_SECRET not set — rejecting" in logs).

### G. Go live
- [ ] App switched from Development → **Live** mode.
- [ ] Messaging tier confirmed (new numbers start ~250–1,000 conversations/day; scales with volume + verification).
- [ ] Templates below submitted and **APPROVED** (needed for proactive sends).

---

## PART 2 — Message template drafts

Submit in **WhatsApp Manager → Message templates**. Rules followed: no variable at
the very start/end of the body, no two variables adjacent, samples provided.
Most are **UTILITY** (transactional → cheaper, better delivery). Language: `en`.

> Variables are positional (`{{1}}`, `{{2}}`, …). Keep the order when wiring the code.

### 1. `debt_reminder` — UTILITY (→ customer)
**Body:**
```
Hello {{1}}, a friendly reminder from {{2}}: your balance is ₦{{3}}. Kindly settle when you can. Thank you.
```
**Sample:** 1=Ada, 2=Ayo Stores, 3=3,000

### 2. `debt_reminder_due` — UTILITY (→ customer, with due date)
**Body:**
```
Hello {{1}}, reminder from {{2}}: your balance of ₦{{3}} is due on {{4}}. Kindly settle. Thank you.
```
**Sample:** 1=Ada, 2=Ayo Stores, 3=3,000, 4=15/09/2026

### 3. `payment_received` — UTILITY (→ customer)
**Body:**
```
Payment received ✅ {{1}}, we recorded ₦{{2}} from you at {{3}}. Remaining balance: ₦{{4}}. Thank you.
```
**Sample:** 1=Ada, 2=2,000, 3=Ayo Stores, 4=1,000

### 4. `supplier_due_reminder` — UTILITY (→ owner)
**Body:**
```
Reminder: you owe {{1}} a balance of ₦{{2}}, due {{3}}. Open CreditVoice to record a payment.
```
**Sample:** 1=Dangote Depot, 2=45,000, 3=20/09/2026

### 5. `thrift_savings_nudge` — UTILITY (→ group member)
**Body:**
```
Savings update for {{1}}: ₦{{2}} of ₦{{3}} saved so far ({{4}}%). Keep it up — add your bit today. 🎯
```
**Sample:** 1=Eid Fund, 2=40,000, 3=100,000, 4=40

### 6. `thrift_goal_reached` — UTILITY (→ group member)
**Body:**
```
Goal reached 🎉 {{1}} has hit its ₦{{2}} target. Well done to everyone who contributed!
```
**Sample:** 1=Eid Fund, 2=100,000

### 7. `ajo_payout_turn` — UTILITY (→ group member)
**Body:**
```
It's your turn, {{1}} 🎉 You are collecting the ₦{{2}} pot from {{3}} this round.
```
**Sample:** 1=Amina, 2=15,000, 3=Market Women Ajo

### 8. `staff_void_alert` — UTILITY (→ owner)
**Body:**
```
Void alert: {{1}} voided a ₦{{2}} transaction (#{{3}}). Reason: {{4}}. Check your dashboard if this looks off.
```
**Sample:** 1=Staff Ada, 2=5,000, 3=142, 4=wrong amount

### 9. `titi_reengage` — MARKETING (→ dormant user, optional)
**Footer:** `Reply STOP to opt out`
**Body:**
```
Hi {{1}} 👋 It's tiTi. Ready to record today's sales and see who owes you? Just send me a message to start.
```
**Sample:** 1=Ayo

---

## PART 3 — The 24-hour window (why templates matter)
- **Replies to a user's message** (the core tiTi flow): free-form, no template — works out of the box once connected.
- **Proactive sends** (reminders, thrift nudges, ajo turn, supplier-due, void alerts, re-engagement): sent outside the 24h window → **must** use an **approved template**, or Meta rejects them.

### Code-wiring plan (the only dev work for a clean launch)
- Add a `send_whatsapp_template(to, name, lang, variables)` helper in `whatsapp_client.py` (posts the `template` message type to the same Graph endpoint).
- Route the proactive senders to templates when outside the window:
  - `reminder_automation.py` / reminders → `debt_reminder` / `debt_reminder_due`
  - `transaction_save.py` payment receipt (when proactive) → `payment_received`
  - `proactive_scheduler.py` supplier-due → `supplier_due_reminder`
  - `proactive_scheduler.py` `_check_target_savings` → `thrift_savings_nudge` / `thrift_goal_reached`
  - thrift payout turn → `ajo_payout_turn`
  - void alerts → `staff_void_alert`
- Keep free-form for in-window replies (cheaper, no template needed).

**Status:** templates above are drafts ready to submit. Ask to build the
`send_whatsapp_template` helper + wire the senders once the first templates are approved.
