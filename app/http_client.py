from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: dict[str, Any]


class HttpClient:
    def __init__(self, timeout_seconds: float = 20, retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> HttpResponse:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return self._request(req)

    def get_json(self, url: str) -> HttpResponse:
        req = urllib.request.Request(url, method="GET")
        return self._request(req)

    def _request(self, req: urllib.request.Request) -> HttpResponse:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8")
                    return HttpResponse(status=resp.status, body=json.loads(raw) if raw else {})
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    body = json.loads(raw) if raw else {"error": raw}
                except json.JSONDecodeError:
                    body = {"error": raw}
                if 400 <= exc.code < 500:
                    return HttpResponse(status=exc.code, body=body)
                last_error = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(0.6 * (attempt + 1))

        logger.warning("HTTP request failed after retries: %s", last_error)
        raise RuntimeError(f"HTTP request failed: {last_error}")

