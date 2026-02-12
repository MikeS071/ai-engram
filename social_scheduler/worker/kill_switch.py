from __future__ import annotations

from social_scheduler.core.service import SocialSchedulerService


def is_publish_paused(service: SocialSchedulerService) -> bool:
    return service.is_kill_switch_on()
