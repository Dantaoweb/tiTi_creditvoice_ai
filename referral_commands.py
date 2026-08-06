"""
WhatsApp referral commands: set your own referral code and view/share it — so
the whole refer-a-friend loop works from chat (create -> view -> share), mirror
of the web dashboard's Invite a Friend section.
"""
import os
import re

REF_CODE_RE = re.compile(r"^[A-Z0-9]{3,20}$")


def _share_lines(code):
    """How-to-share block (WhatsApp join + optional web link)."""
    base = os.getenv("APP_BASE_URL", "").rstrip("/")
    lines = [
        f"Share it: ask a friend to send  join {code}  to me,",
    ]
    if base:
        lines.append(f"or share your link: {base}/app/login?mode=register&ref={code}")
    lines.append("")
    lines.append(
        "Your friend gets 14 days free on GO when they join. On a paid plan you "
        "earn plan credit each month for every friend on an active paid plan."
    )
    return "\n".join(lines)


def handle_set_referral_code(db, user, code, send_message, phone):
    from models import User
    if not user:
        send_message(phone, "You need an account first. Send  hi  to get started.")
        return {"status": "referral_code_no_user"}

    code = (code or "").strip().upper()
    if not REF_CODE_RE.match(code):
        send_message(phone, "A referral code must be 3–20 letters and numbers, no spaces.\n\n"
                            "Example:  set my referral code DANSHOP")
        return {"status": "referral_code_invalid"}

    taken = db.query(User).filter(User.referral_code == code, User.id != user.id).first()
    if taken:
        send_message(phone, f"The code {code} is already taken. Please try another, e.g. "
                            f"set my referral code {code}1")
        return {"status": "referral_code_taken"}

    user.referral_code = code
    db.commit()
    send_message(phone, f"Done! Your referral code is *{code}*.\n\n{_share_lines(code)}")
    return {"status": "referral_code_set", "code": code}


def handle_show_referral_code(db, user, send_message, phone):
    if not user:
        send_message(phone, "You need an account first. Send  hi  to get started.")
        return {"status": "referral_code_no_user"}

    code = (getattr(user, "referral_code", None) or "").strip()
    if not code:
        send_message(phone, "You haven't set a referral code yet.\n\n"
                            "Pick one by sending:  set my referral code YOURCODE\n"
                            "(e.g.  set my referral code DANSHOP)")
        return {"status": "referral_code_unset"}

    send_message(phone, f"Your referral code is *{code}*.\n\n{_share_lines(code)}")
    return {"status": "referral_code_shown", "code": code}
