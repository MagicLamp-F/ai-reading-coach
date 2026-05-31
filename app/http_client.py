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


@dataclass(frozen=True)
class TextHttpResponse:
    status: int
    body: str
    final_url: str
    content_type: str


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

    def get_text(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        max_bytes: int = 200_000,
    ) -> TextHttpResponse:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "ai-reading-coach/0.1 source-collector", **(headers or {})},
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read(max_bytes + 1)
                    content_type = resp.headers.get("Content-Type", "")
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return TextHttpResponse(
                        status=resp.status,
                        body=raw[:max_bytes].decode(charset, errors="replace"),
                        final_url=resp.geturl(),
                        content_type=content_type,
                    )
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    raw = exc.read(max_bytes).decode("utf-8", errors="replace")
                    return TextHttpResponse(
                        status=exc.code,
                        body=raw,
                        final_url=exc.geturl(),
                        content_type=exc.headers.get("Content-Type", ""),
                    )
                last_error = exc
            except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(0.6 * (attempt + 1))

        logger.warning("HTTP text request failed after retries: %s", last_error)
        raise RuntimeError(f"HTTP text request failed: {last_error}")

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
