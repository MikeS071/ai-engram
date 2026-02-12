from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from social_scheduler.core.models import PostState, SocialPost
from social_scheduler.core.service import SocialSchedulerService


def _all_posts(service: SocialSchedulerService) -> list[SocialPost]:
    return [SocialPost.model_validate(r) for r in service.posts.read_all()]


def daily_digest(service: SocialSchedulerService) -> str:
    posts = _all_posts(service)
    counts = Counter(p.state.value for p in posts)
    pending = counts[PostState.PENDING_MANUAL.value]
    failed = counts[PostState.FAILED.value]
    scheduled = counts[PostState.SCHEDULED.value]
    posted = counts[PostState.POSTED.value]

    return (
        "Daily Social Scheduler Digest\n"
        f"- Scheduled: {scheduled}\n"
        f"- Posted: {posted}\n"
        f"- Pending manual: {pending}\n"
        f"- Failed: {failed}"
    )


def weekly_summary(service: SocialSchedulerService) -> str:
    posts = _all_posts(service)
    cutoff = datetime.utcnow() - timedelta(days=7)

    def _is_recent(iso: str | None) -> bool:
        if not iso:
            return False
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt >= cutoff

    recent = [p for p in posts if _is_recent(p.updated_at)]
    if not recent:
        return "Weekly Social Scheduler Summary\n- No activity in the last 7 days."

    counts = Counter(p.state.value for p in recent)
    posted = counts[PostState.POSTED.value]
    failed = counts[PostState.FAILED.value]

    return (
        "Weekly Social Scheduler Summary\n"
        f"- Updated posts: {len(recent)}\n"
        f"- Posted: {posted}\n"
        f"- Failed: {failed}"
    )
