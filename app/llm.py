from __future__ import annotations

import json
import logging
from typing import Any

from app.http_client import HttpClient

logger = logging.getLogger(__name__)


class OpenAIChatClient:
    def __init__(self, api_key: str, model: str, base_url: str, http: HttpClient):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.http = http

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }
        response = self.http.post_json(
            f"{self.base_url}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if response.status >= 400:
            logger.warning("Model request failed: status=%s body=%s", response.status, response.body)
            return None
        content = (
            response.body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Model returned non-JSON content: %s", content[:500])
            return None

