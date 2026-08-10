"""Transactional email via SendGrid's REST API.

Uses the stdlib (urllib) so there's no extra dependency — one small HTTPS POST to
SendGrid's v3 mail/send endpoint. No-op guard: callers should check
settings.email_enabled first; send_invite_email raises if it's called unconfigured.
"""

import json
import logging
import urllib.error
import urllib.request

from app.config import Settings, get_settings

logger = logging.getLogger("uvicorn.error")

_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"


def _send(to_email: str, to_name: str, subject: str, text: str, html: str,
          settings: Settings) -> None:
    body = {
        "personalizations": [{"to": [{"email": to_email, "name": to_name}]}],
        "from": {"email": settings.invite_from_email, "name": settings.invite_from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text},
            {"type": "text/html", "value": html},
        ],
    }
    req = urllib.request.Request(
        _ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status not in (200, 202):
                raise RuntimeError(f"SendGrid returned {resp.status}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        logger.error("SendGrid HTTP %s: %s", e.code, detail)
        # 401/403 = bad key; 403 often = unverified sender.
        raise RuntimeError(
            f"Email service rejected the request ({e.code}). "
            "Check the SendGrid API key and that the From address is a verified sender."
        ) from e
    except urllib.error.URLError as e:
        logger.error("SendGrid network error: %s", e)
        raise RuntimeError("Could not reach the email service.") from e


def send_invite_email(to_email: str, full_name: str, invite_url: str,
                      settings: Settings | None = None) -> None:
    """Email a new user a link to set their own password and get into the app."""
    s = settings or get_settings()
    if not s.email_enabled:
        raise RuntimeError("Email is not configured (set SENDGRID_API_KEY and INVITE_FROM_EMAIL).")
    first = (full_name or "there").split()[0]
    subject = "You've been added to Carter Kitchen & Bath"
    text = (
        f"Hi {first},\n\n"
        f"You've been given access to Carter Kitchen & Bath (the COAST suite).\n\n"
        f"Set your password to get started:\n{invite_url}\n\n"
        f"After that, sign in anytime at {s.app_base_url} with your email ({to_email}).\n\n"
        f"This link expires in 7 days. If it does, ask your admin to resend the invite.\n"
    )
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1c2b29">
  <h2 style="color:#125952;margin:0 0 8px">Welcome to Carter Kitchen &amp; Bath</h2>
  <p>Hi {first}, you've been given access to the COAST suite.</p>
  <p style="margin:24px 0">
    <a href="{invite_url}"
       style="background:#125952;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;display:inline-block;font-weight:bold">
      Set your password
    </a>
  </p>
  <p>After that, sign in anytime at
     <a href="{s.app_base_url}" style="color:#125952">{s.app_base_url}</a>
     with your email (<b>{to_email}</b>).</p>
  <p style="color:#6b7b78;font-size:13px">This link expires in 7 days. If it does, ask your admin to resend the invite.</p>
</div>"""
    _send(to_email, full_name, subject, text, html, s)
