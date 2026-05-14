"""
Picky Assist outbound sender.
Docs: https://www.pickyassist.com/docs/
The exact payload depends on the account's outbound configuration; this is a reasonable default
that sends a text message and (optionally) an attached audio file URL.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings

log = logging.getLogger("irri")


def send_via_picky_assist(hook, to_number: str, text: str, audio_url: Optional[str] = None) -> dict:
    if not settings.PICKY_ASSIST_TOKEN:
        raise RuntimeError("PICKY_ASSIST_TOKEN not configured.")

    payload = {
        "token": settings.PICKY_ASSIST_TOKEN,
        "platform": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": text[:4000],
        "sender_id": hook.whatsapp_number,
    }
    if audio_url:
        payload["type"] = "audio"
        payload["media_url"] = audio_url

    r = requests.post(settings.PICKY_ASSIST_SEND_URL, json=payload, timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {"status_code": r.status_code, "text": r.text[:500]}
    if r.status_code >= 400:
        log.warning("PickyAssist error %s: %s", r.status_code, data)
    return data
