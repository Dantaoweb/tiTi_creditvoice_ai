"""
Email delivery via SMTP (Brevo or any SMTP provider).

Required env vars:
  SMTP_HOST     smtp-relay.brevo.com
  SMTP_PORT     587
  SMTP_USER     your-brevo-login-email
  SMTP_PASS     your-brevo-smtp-key
  SMTP_FROM     CreditVoice <noreply@yourdomain.com>
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "CreditVoice <noreply@creditvoice.app>")

_CONFIGURED = bool(SMTP_USER and SMTP_PASS)


def send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    if not _CONFIGURED:
        print(f"Email send skipped (SMTP not configured): to={to} subject={subject}", flush=True)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to
        if text:
            msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASS)
            srv.sendmail(SMTP_FROM, to, msg.as_string())
        print(f"Email sent: to={to} subject={subject}", flush=True)
        return True
    except Exception as exc:
        print(f"Email send failed: {exc}", flush=True)
        return False


def send_otp_email(to: str, otp: str) -> bool:
    subject = f"{otp} — Your CreditVoice verification code"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
      <div style="background:#1f7a4d;color:#fff;border-radius:8px 8px 0 0;padding:20px 24px">
        <strong style="font-size:20px">CreditVoice</strong>
        <p style="margin:4px 0 0;font-size:13px;opacity:.8">Business Desk</p>
      </div>
      <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;padding:28px 24px">
        <p style="color:#111827;font-size:15px;margin:0 0 16px">Your one-time verification code:</p>
        <div style="background:#f3f4f6;border-radius:8px;padding:20px;text-align:center;letter-spacing:8px;font-size:32px;font-weight:800;color:#111827">
          {otp}
        </div>
        <p style="color:#6b7280;font-size:13px;margin:16px 0 0">
          Valid for <strong>10 minutes</strong>. Do not share this code with anyone.
        </p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
        <p style="color:#9ca3af;font-size:12px;margin:0">
          If you didn't request this, ignore this email.
        </p>
      </div>
    </div>
    """
    text = f"Your CreditVoice verification code: {otp}\n\nValid for 10 minutes. Do not share."
    return send_email(to, subject, html, text)


def send_welcome_email(to: str, name: str) -> bool:
    subject = "Welcome to CreditVoice — your business desk is ready"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
      <div style="background:#1f7a4d;color:#fff;border-radius:8px 8px 0 0;padding:20px 24px">
        <strong style="font-size:20px">CreditVoice</strong>
      </div>
      <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;padding:28px 24px">
        <p style="color:#111827;font-size:16px;font-weight:700;margin:0 0 12px">Hi {name}, welcome aboard!</p>
        <p style="color:#374151;font-size:14px;margin:0 0 16px">
          Your CreditVoice account is ready. You can now record sales, manage customers,
          track inventory, and view your business reports from any device.
        </p>
        <p style="color:#374151;font-size:14px;margin:0 0 8px">
          <strong>Tip:</strong> Link WhatsApp to unlock reminders, voice capture, and more —
          simply send <em>Hello</em> to tiTi on WhatsApp.
        </p>
      </div>
    </div>
    """
    return send_email(to, subject, html)


def is_email_configured() -> bool:
    return _CONFIGURED


def mask_email(email: str) -> str:
    """Return a***@gmail.com style hint without revealing the full address."""
    try:
        local, domain = email.rsplit("@", 1)
        visible = local[:2] if len(local) > 2 else local[:1]
        return f"{visible}***@{domain}"
    except Exception:
        return "***"
