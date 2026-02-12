from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class PostState(str, Enum):
    DRAFT = "draft"
    READY_FOR_APPROVAL = "ready_for_approval"
    PENDING_MANUAL = "pending_manual"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    POSTED = "posted"
    FAILED = "failed"
    CANCELED = "canceled"


class AttemptResult(str, Enum):
    SUCCESS = "success"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"


class Campaign(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    source_blog_path: str
    audience_timezone: str
    campaign_time_utc: str | None = None
    generation_prompt_version: str = "v1"
    generation_model_version: str = "v1"
    created_at: str
    updated_at: str


class SocialPost(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    campaign_id: str
    platform: Literal["linkedin", "x"]
    content: str
    state: PostState = PostState.DRAFT
    edited_at: str | None = None
    approved_content_hash: str | None = None
    recommended_for_utc: str | None = None
    recommended_confidence: float | None = None
    recommended_reasoning: str | None = None
    recommendation_fallback_used: bool = False
    scheduled_for_utc: str | None = None
    approved_at: str | None = None
    posted_at: str | None = None
    external_post_id: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str


class SocialPostAttempt(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    social_post_id: str
    attempt_number: int
    started_at: str
    finished_at: str | None = None
    result: AttemptResult | None = None
    error_code: str | None = None
    error_message_redacted: str | None = None


class ApprovalRule(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    name: str
    enabled: bool = True
    conditions_json: dict = Field(default_factory=dict)
    action: Literal["auto_approve", "manual"] = "manual"
    updated_at: str


class TelegramDecisionAudit(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    campaign_id: str | None = None
    social_post_id: str | None = None
    telegram_user_id: str
    telegram_message_id: str | None = None
    action: str
    decision_token_id: str | None = None
    created_at: str


class TelegramRateLimitEvent(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    telegram_user_id: str
    command: str
    window_start_utc: str
    window_end_utc: str
    action_taken: Literal["allowed", "rejected"]
    created_at: str


class TelegramDecisionRequest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    campaign_id: str | None = None
    social_post_id: str | None = None
    request_type: Literal["approval", "confirmation", "health_gate", "kill_switch"]
    message: str
    status: Literal["open", "resolved", "expired"] = "open"
    created_at: str
    expires_at: str
    resolved_at: str | None = None
    resolution_action: str | None = None


class ConfirmationToken(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    action: str
    target_id: str
    created_at: str
    expires_at: str
    used_at: str | None = None
    used_by: str | None = None


class HealthCheckStatus(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    date_local: str
    checked_at: str
    overall_status: Literal["pass", "fail"]
    token_status: str
    worker_status: str
    kill_switch_status: str
    critical_failure_status: str
    notes: str | None = None


class ManualOverrideAudit(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    campaign_id: str | None = None
    social_post_id: str
    telegram_user_id: str
    reason: str
    confirmation_token_id: str
    created_at: str


class SystemControl(BaseModel):
    schema_version: int = SCHEMA_VERSION
    key: str
    value: str
    updated_at: str


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
