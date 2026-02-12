from __future__ import annotations

import os
import uuid


class LinkedInClient:
    def __init__(self) -> None:
        self.client_id = os.getenv("LINKEDIN_CLIENT_ID")
        self.client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")

    def publish_article(self, content: str, dry_run: bool = True) -> str:
        if dry_run:
            return f"li_dry_{uuid.uuid4().hex[:10]}"
        if not self.client_id or not self.client_secret:
            raise RuntimeError("LinkedIn credentials not configured")
        # Placeholder for real API call integration.
        return f"li_live_{uuid.uuid4().hex[:10]}"
