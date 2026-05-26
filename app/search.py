from __future__ import annotations

import logging
from dataclasses import dataclass

from app.http_client import HttpClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


class TavilySearch:
    def __init__(self, api_key: str, http: HttpClient):
        self.api_key = api_key
        self.http = http

    def search_books(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            return []
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        response = self.http.post_json("https://api.tavily.com/search", payload)
        if response.status >= 400:
            logger.warning("Tavily search failed: status=%s body=%s", response.status, response.body)
            return []
        results = response.body.get("results", [])
        return [
            SearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                content=str(item.get("content", "")),
            )
            for item in results
        ]

