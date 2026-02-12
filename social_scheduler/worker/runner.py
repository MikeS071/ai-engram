from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from social_scheduler.core.models import PostState
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.telegram_control import TelegramControl
from social_scheduler.integrations.linkedin_client import LinkedInClient
from social_scheduler.integrations.telegram_bot import TelegramNotifier
from social_scheduler.integrations.x_client import XClient
from social_scheduler.worker.kill_switch import is_publish_paused


class WorkerRunner:
    def __init__(self, service: SocialSchedulerService) -> None:
        self.service = service
        self.linkedin = LinkedInClient()
        self.x = XClient()
        self.telegram = TelegramNotifier()
        self.telegram_control = TelegramControl(
            service,
            allowed_user_id=os.getenv("TELEGRAM_ALLOWED_USER_ID", ""),
        )

    def run_once(self, dry_run: bool = True) -> int:
        expired = self.telegram_control.expire_decision_requests()
        if expired:
            self.telegram.send_message(f"{expired} Telegram decision request(s) expired.", critical=True)
        for req in self.telegram_control.reminder_candidates():
            self.telegram.send_message(f"Reminder: {req.message}", critical=False)

        if is_publish_paused(self.service):
            self.telegram.send_message("Publish worker run skipped: kill switch is ON.", critical=True)
            return 0

        due = self.service.due_posts(datetime.now(tz=ZoneInfo("UTC")))
        processed = 0
        for post in due:
            try:
                if post.state != PostState.SCHEDULED:
                    continue
                if post.platform == "linkedin":
                    external_id = self.linkedin.publish_article(post.content, dry_run=dry_run)
                elif post.platform == "x":
                    external_id = self.x.publish_article(post.content, dry_run=dry_run)
                else:
                    raise RuntimeError(f"Unsupported platform: {post.platform}")

                self.service.mark_post_result(post, success=True, external_post_id=external_id)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                self.service.mark_post_result(post, success=False, error_message=str(exc))
                self.telegram.send_message(
                    f"Post failed for {post.platform} ({post.id}): {exc}", critical=True
                )

        return processed

    def run_forever(self, interval_seconds: int = 60, dry_run: bool = True) -> None:
        while True:
            self.run_once(dry_run=dry_run)
            time.sleep(interval_seconds)
