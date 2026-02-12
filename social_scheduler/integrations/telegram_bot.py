from __future__ import annotations

import os
import time

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
        delays = [0.5, 1.5, 3.0]
        last_exc: Exception | None = None
        for idx, delay in enumerate(delays, start=1):
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if idx < len(delays):
                    time.sleep(delay)
        raise RuntimeError(f"Telegram send failed after retries: {last_exc}")
