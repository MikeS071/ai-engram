from __future__ import annotations

import hashlib
import re


def canonicalize_content(content: str) -> str:
    """Normalize text to ensure stable hashes across harmless formatting edits."""
    text = content.replace("\r\n", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def content_hash(content: str) -> str:
    normalized = canonicalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def idempotency_key(campaign_id: str, platform: str, approved_content_hash: str) -> str:
    raw = f"{campaign_id}:{platform}:{approved_content_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
