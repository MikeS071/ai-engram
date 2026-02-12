from __future__ import annotations

from social_scheduler.core.service import SocialSchedulerService


def can_publish_now(service: SocialSchedulerService) -> tuple[bool, str]:
    status = service.health_check()
    if status.overall_status != "pass":
        return False, "Health gate failed. Live publish is blocked."
    return True, "Health gate passed."
