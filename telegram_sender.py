"""Telegram message delivery."""

from __future__ import annotations

import os
from pathlib import Path

import requests


_ENV_PATH = Path(__file__).resolve().parent / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def split_telegram(text: str, limit: int = 3900) -> list[str]:
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        add_len = len(line) + 1
        if current and current_len + add_len > limit:
            chunks.append("\n".join(current).strip())
            current = [line]
            current_len = add_len
        else:
            current.append(line)
            current_len += add_len
    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 환경변수가 필요합니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_telegram(text):
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
