from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tavily import AsyncTavilyClient

from app.core.config import Settings
from app.research.models import SearchSource


@dataclass(frozen=True)
class SearchRequest:
    query: str
    topic: str = "general"
    search_depth: str = "basic"
    days: int | None = None
    include_domains: list[str] = field(default_factory=list)


class TavilySearch:
    def __init__(self, settings: Settings) -> None:
        api_key = settings.tavily_api_key.get_secret_value()
        if not api_key:
            raise ValueError("TAVILY_API_KEY is required for live research")
        self._client = AsyncTavilyClient(api_key=api_key)
        self._max_results = settings.search_results_per_agent

    async def search(self, request: SearchRequest) -> list[SearchSource]:
        options: dict[str, Any] = {
            "query": request.query,
            "topic": request.topic,
            "search_depth": request.search_depth,
            "max_results": self._max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        if request.days is not None:
            options["days"] = request.days
        if request.include_domains:
            options["include_domains"] = request.include_domains

        response = await self._client.search(**options)
        return [self._to_source(item) for item in response.get("results", [])]

    @staticmethod
    def _to_source(item: dict[str, Any]) -> SearchSource:
        published_at = None
        raw_date = item.get("published_date")
        if raw_date:
            try:
                published_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                pass
        return SearchSource(
            title=item.get("title") or "Untitled source",
            url=item["url"],
            snippet=item.get("content") or "",
            published_at=published_at,
        )
