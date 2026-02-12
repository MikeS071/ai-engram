from __future__ import annotations

import os

import httpx


class TelegramNotifier:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.allowed_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID")

    def send_message(self, text: str, critical: bool = False) -> None:
        if not self.token or not self.allowed_user_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.allowed_user_id,
            "text": text,
            "disable_notification": not critical,
        }
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
