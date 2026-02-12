from __future__ import annotations

import pytest

from social_scheduler.core.models import PostState, SocialPost, utc_now_iso
from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.preflight import validate_post
from social_scheduler.core.service import SocialSchedulerService


def _reset(service: SocialSchedulerService) -> None:
    service.campaigns.delete_where(lambda _: True)
    service.posts.delete_where(lambda _: True)
    service.events.delete_where(lambda _: True)


def _post(content: str, platform: str = "x") -> SocialPost:
    now = utc_now_iso()
    return SocialPost(
        id="p1",
        campaign_id="c1",
        platform=platform,  # type: ignore[arg-type]
        content=content,
        state=PostState.READY_FOR_APPROVAL,
        created_at=now,
        updated_at=now,
    )


def test_preflight_rejects_unresolved_placeholders():
    post = _post("Title line\nThis body has enough words but contains {{TODO}} unresolved marker.")
    result = validate_post(post, stage="pre_approval")
    assert not result.ok
    assert any("unresolved template placeholders" in err for err in result.errors)


def test_preflight_requires_body_content():
    post = _post("Title\nToo short")
    result = validate_post(post, stage="pre_approval")
    assert not result.ok
    assert any("body too short" in err for err in result.errors)


def test_approve_campaign_fails_when_preflight_fails(tmp_path):
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    blog = tmp_path / "blog.md"
    blog.write_text("# Valid Title\nThis body has enough words to make a valid draft source document.", encoding="utf-8")
    campaign = service.create_campaign_from_blog(str(blog), "America/New_York")
    posts = service.list_campaign_posts(campaign.id)
    assert len(posts) == 2

    for post in posts:
        service.edit_post(post.id, "Bad\n{{placeholder}}")

    with pytest.raises(ValueError, match="Preflight failed"):
        service.approve_campaign(campaign.id, editor_user="tester")


def test_service_preflight_posts_returns_failures(tmp_path):
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    blog = tmp_path / "blog2.md"
    blog.write_text("# Valid Title\nThis body has enough words to create baseline posts.", encoding="utf-8")
    campaign = service.create_campaign_from_blog(str(blog), "America/New_York")
    posts = service.list_campaign_posts(campaign.id)
    assert len(posts) == 2

    service.edit_post(posts[0].id, "Bad\n{{placeholder}}")
    failures = service.preflight_posts(stage="pre_approval", campaign_id=campaign.id)
    assert posts[0].id in failures


def test_service_preflight_posts_rejects_mixed_selectors():
    ensure_directories()
    service = SocialSchedulerService()
    with pytest.raises(ValueError, match="campaign_id or post_id"):
        service.preflight_posts(stage="pre_approval", campaign_id="c1", post_id="p1")


def test_query_events_filters_and_limit(tmp_path):
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    blog = tmp_path / "blog3.md"
    blog.write_text("# Title\nThis body has enough words to generate valid draft content quickly.", encoding="utf-8")
    campaign = service.create_campaign_from_blog(str(blog), "America/New_York")
    posts = service.list_campaign_posts(campaign.id)
    assert len(posts) == 2

    # campaign_created + two post_drafted events should exist.
    all_events = service.query_events(limit=100)
    assert len(all_events) >= 3

    filtered_campaign = service.query_events(campaign_id=campaign.id, limit=100)
    assert len(filtered_campaign) >= 3

    filtered_post = service.query_events(post_id=posts[0].id, limit=100)
    assert any(e.get("post_id") == posts[0].id for e in filtered_post)

    limited = service.query_events(campaign_id=campaign.id, limit=1)
    assert len(limited) == 1
