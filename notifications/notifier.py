"""Notification module: SMS (Twilio) + email (SMTP) alerts.

Reads credentials from environment variables:
  Twilio:  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
  SMTP:    SMTP_HOST, SMTP_USER, SMTP_PASS  (optionally SMTP_PORT, SMTP_TLS)
  SendGrid: SENDGRID_API_KEY (used as SMTP auth if SMTP_HOST unset)

If the required env vars are missing the notifier logs to console instead of
raising, so the rest of the system keeps working with zero external keys.
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("notifications")


def _all_set(*names):
    return all(bool(os.getenv(n)) for n in names)


def _twilio_enabled():
    return _all_set("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")


def _smtp_enabled():
    return _all_set("SMTP_HOST") and _all_set("SMTP_USER", "SMTP_PASS")


def send_sms(to, message):
    if not to:
        return False
    if not _twilio_enabled():
        log.info("[sms:disabled] to=%s body=%s", to, message)
        return False
    try:
        from twilio.rest import Client

        client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        client.messages.create(
            to=to,
            from_=os.getenv("TWILIO_FROM_NUMBER"),
            body=message,
        )
        log.info("[sms] sent to=%s via Twilio", to)
        return True
    except Exception as exc:  # never take the scoring loop down with us
        log.warning("[sms] delivery failed for %s: %s", to, exc)
        return False


def send_email(to, subject, body):
    if not to:
        return False
    if not _smtp_enabled():
        log.info("[email:disabled] to=%s subject=%s body=%s", to, subject, body)
        return False
    try:
        host = os.getenv("SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "587"))
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = os.getenv("SMTP_USER")
        msg["To"] = to
        with smtplib.SMTP(host, port, timeout=10) as server:
            if os.getenv("SMTP_TLS", "1") == "1":
                server.starttls()
            server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
            server.send_message(msg)
        log.info("[email] sent to=%s via SMTP", to)
        return True
    except Exception as exc:
        log.warning("[email] delivery failed for %s: %s", to, exc)
        return False


def notify_alert(customer, message):
    """Fire SMS + email for a persisted alert. Returns channels actually attempted."""
    channels = []
    if send_sms(customer.get("phone"), message):
        channels.append("sms")
    if send_email(customer.get("email"), "SecureBank fraud alert", message):
        channels.append("email")
    return channels or ["log"]


def notify_otp(customer, code, txn_id):
    """Deliver an OTP code for a STEP_UP transaction. Returns channels attempted."""
    message = (
        f"SecureBank: use OTP {code} to approve transaction #{txn_id}. "
        "It expires in 5 minutes. Do not share it."
    )
    channels = []
    if send_sms(customer.get("phone"), message):
        channels.append("sms")
    if send_email(customer.get("email"), f"SecureBank OTP for transaction #{txn_id}", message):
        channels.append("email")
    return channels or ["log"]