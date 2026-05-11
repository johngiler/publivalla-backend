from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


def _mailgun_base_url(region: str) -> str:
    r = (region or "").strip().lower()
    if r == "eu":
        return "https://api.eu.mailgun.net"
    return "https://api.mailgun.net"


def send_mailgun_text_email(
    *,
    api_key: str,
    domain: str,
    region: str,
    from_email: str,
    to_emails: list[str],
    subject: str,
    text: str,
) -> bool:
    key = (api_key or "").strip()
    dom = (domain or "").strip()
    if not key or not dom:
        return False
    recipients = [e.strip() for e in (to_emails or []) if (e or "").strip()]
    if not recipients:
        return False

    base = _mailgun_base_url(region)
    url = f"{base}/v3/{dom}/messages"
    data = {
        "from": from_email,
        "to": recipients,
        "subject": subject,
        "text": text,
    }
    try:
        res = requests.post(url, auth=("api", key), data=data, timeout=25)
        if 200 <= res.status_code < 300:
            return True
        logger.warning("Mailgun send fallo HTTP %s: %s", res.status_code, res.text[:800])
        return False
    except Exception:
        logger.exception("Mailgun send fallo (domain=%s).", dom)
        return False

