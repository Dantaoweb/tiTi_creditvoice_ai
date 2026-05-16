"""
EXAMPLE USAGE: Due Today Flow with Phone-Optional Preview

This shows the new improved flow where:
1. Users can preview reminder messages WITHOUT requiring customer phone number
2. Phone is only required when actually sending the reminder
3. Users get helpful prompts to set phone if needed
"""

# ==========================================
# SCENARIO: Check Due Today Reminders
# ==========================================

"""
FLOW:
User: "due"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: 📅 Debt Reminder Menu                                      │
│                                                                 │
│ 1. Due in 2 Days                                                │
│ 2. Due Today                                                    │
│ 3. Overdue Debtors                                              │
│                                                                 │
│ Reply with: 1, 2, or 3                                          │
└─────────────────────────────────────────────────────────────────┘

User: "2"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: 📅 Due Today                                               │
│                                                                 │
│ 1. Ali → ₦50,000                                                │
│ 2. Bola → ₦30,000                                               │
│                                                                 │
│ Send:                                                           │
│ 1, 2, etc to preview the reminder before sending to customer.   │
└─────────────────────────────────────────────────────────────────┘

User: "1"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: Preview reminder for Ali:                                  │
│                                                                 │
│ Hello Ali,                                                      │
│                                                                 │
│ This is a reminder that your outstanding balance of            │
│ ₦50,000 is due today.                                           │
│                                                                 │
│ Thank you.                                                      │
│                                                                 │
│ ⚠️ Customer phone not set!                                     │
│ To send this reminder, please set the phone first:             │
│                                                                 │
│ ali phone 08012345678                                           │
│                                                                 │
│ Then reply YES to send, or EDIT to cancel.                      │
└─────────────────────────────────────────────────────────────────┘

User: "ali phone 08012345678"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: Saved phone for Ali: 08012345678                           │
│                                                                 │
│ Phone set! Now reply YES to send the reminder to Ali.           │
└─────────────────────────────────────────────────────────────────┘

User: "YES"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: ✅ Reminder sent to Ali (08012345678).                     │
│                                                                 │
│ (Ali receives the reminder message)                             │
└─────────────────────────────────────────────────────────────────┘
"""

# ==========================================
# SCENARIO 2: Phone Already Set
# ==========================================

"""
User: "2"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: 📅 Due Today                                               │
│                                                                 │
│ 1. Bola → ₦30,000                                               │
│                                                                 │
│ Send:                                                           │
│ 1, etc to preview the reminder before sending to customer.      │
└─────────────────────────────────────────────────────────────────┘

User: "1"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: Preview reminder for Bola:                                 │
│                                                                 │
│ Hello Bola,                                                     │
│                                                                 │
│ This is a reminder that your outstanding balance of            │
│ ₦30,000 is due today.                                           │
│                                                                 │
│ Thank you.                                                      │
│                                                                 │
│ Reply YES to send this reminder to Bola at 08022222222,        │
│ or EDIT to cancel.                                              │
└─────────────────────────────────────────────────────────────────┘

User: "YES"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: ✅ Reminder sent to Bola (08022222222).                    │
│                                                                 │
│ (Bola receives the reminder message)                            │
└─────────────────────────────────────────────────────────────────┘
"""

# ==========================================
# SCENARIO 3: Edit/Cancel
# ==========================================

"""
User: "2" (Due Today)
┌─────────────────────────────────────────────────────────────────┐
│ Bot: 📅 Due Today                                               │
│                                                                 │
│ 1. Chioma → ₦70,000                                             │
│                                                                 │
│ Send: 1, etc to preview the reminder before sending to customer.│
└─────────────────────────────────────────────────────────────────┘

User: "1"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: Preview reminder for Chioma:                               │
│                                                                 │
│ Hello Chioma,                                                   │
│                                                                 │
│ This is a reminder that your outstanding balance of            │
│ ₦70,000 is due today.                                           │
│                                                                 │
│ Thank you.                                                      │
│                                                                 │
│ Reply YES to send this reminder to Chioma at 08033333333,      │
│ or EDIT to cancel.                                              │
└─────────────────────────────────────────────────────────────────┘

User: "EDIT"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: Reminder cancelled. Reply DUE to start again.              │
└─────────────────────────────────────────────────────────────────┘

User: "due"
┌─────────────────────────────────────────────────────────────────┐
│ Bot: 📅 Debt Reminder Menu                                      │
│     (Menu shows again)                                          │
└─────────────────────────────────────────────────────────────────┘
"""

# ==========================================
# KEY FEATURES OF NEW FLOW:
# ==========================================

"""
✅ PREVIEW WITHOUT PHONE:
   - Users see the exact message the customer will receive
   - No phone requirement at this stage
   - Great for reviewing message content

✅ PHONE ONLY WHEN SENDING:
   - If phone is set: Direct confirmation with phone shown
   - If phone not set: Clear instructions to set it first
   - User can set phone while viewing preview

✅ GRACEFUL PHONE SETTING:
   - After setting phone: "Phone set! Now reply YES..."
   - Keeps pending action active for retry
   - No need to restart the flow

✅ FLEXIBLE CANCELLATION:
   - Reply EDIT to cancel reminder
   - Easy restart with "DUE" command

✅ MULTIPLE REMINDERS:
   - If 5 reminders exist, numbered 1-5
   - Each can be previewed independently
   - Each requires phone when sending
"""

# ==========================================
# TECHNICAL IMPROVEMENTS:
# ==========================================

"""
CHANGES MADE IN main.py:

1. REMINDER_SELECTION handler:
   - Removed phone check (was blocking preview)
   - Build conditional confirm_msg:
     * With phone: Show send confirmation
     * Without phone: Show setup instructions

2. REMINDER_CONFIRM handler:
   - When YES but no phone: Prompt to set first (keep pending)
   - Instead of failing, user gets helpful message

3. SET_PHONE handler:
   - Updates ReminderMemory phone for pending reminder
   - Detects if REMINDER_CONFIRM is pending
   - Prompts user to retry with YES

FLOW BENEFITS:
- More flexible (view before setting phone)
- Better UX (helpful prompts, no dead ends)
- User can set phone inline and continue
- Less modal complexity
"""
