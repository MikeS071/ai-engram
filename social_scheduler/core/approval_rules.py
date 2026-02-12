from __future__ import annotations

from social_scheduler.core.models import ApprovalRule, SocialPost


def should_auto_approve(post: SocialPost, rules: list[ApprovalRule]) -> bool:
    """Simple v1 rules: platform/content_length/min_confidence."""
    for rule in rules:
        if not rule.enabled or rule.action != "auto_approve":
            continue
        cond = rule.conditions_json or {}
        platform = cond.get("platform")
        if platform and platform != post.platform:
            continue

        min_len = cond.get("min_content_length")
        if isinstance(min_len, int) and len(post.content) < min_len:
            continue

        min_conf = cond.get("min_confidence")
        if isinstance(min_conf, (float, int)):
            if post.recommended_confidence is None or post.recommended_confidence < float(min_conf):
                continue

        return True
    return False
