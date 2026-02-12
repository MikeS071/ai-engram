import pytest

from social_scheduler.core.models import PostState
from social_scheduler.core.state_machine import can_transition, ensure_transition


def test_valid_transition_draft_to_ready():
    assert can_transition(PostState.DRAFT, PostState.READY_FOR_APPROVAL)


def test_invalid_transition_draft_to_posted():
    assert not can_transition(PostState.DRAFT, PostState.POSTED)
    with pytest.raises(ValueError):
        ensure_transition(PostState.DRAFT, PostState.POSTED)
