"""Telegram message delivery."""

from __future__ import annotations

import os
import time

import requests

from env_loader import load_repo_env


load_repo_env()


def split_telegram(text: str, limit: int = 3900) -> list[str]:
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        if len(line) + 1 > limit:
            if current:
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit].strip())
            continue
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


def send_telegram(text: str, retries: int = 2) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 환경변수가 필요합니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_telegram(text):
        last_error = None
        for attempt in range(retries + 1):
            try:
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
                last_error = None
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        if last_error is not None:
            raise last_error
