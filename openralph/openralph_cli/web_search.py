from __future__ import annotations

from typing import Iterable

from .settings import OpenRalphSettings


def _format_results(results: Iterable[dict]) -> str:
    lines: list[str] = []
    for idx, item in enumerate(results, start=1):
        title = str(item.get("title") or item.get("name") or "(no title)")
        url = str(item.get("url") or item.get("href") or "")
        snippet = str(item.get("snippet") or item.get("body") or item.get("description") or "")
        lines.append(f"{idx}. {title}")
        if url:
            lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
    return "\n".join(lines) if lines else "No results."


def _duckduckgo_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        return "[error] duckduckgo-search is not installed. Install duckduckgo-search>=6.0.0."
    if not query:
        return "[error] Missing query."
    results: list[dict] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=5):
            if isinstance(r, dict):
                results.append(r)
    return _format_results(results)


def _tavily_search(query: str, api_key: str) -> str:
    try:
        from tavily import TavilyClient
    except Exception:
        return "[error] tavily-python is not installed. Install tavily-python>=0.3.0."
    if not query:
        return "[error] Missing query."
    if not api_key:
        return "[error] Missing Tavily API key. Set web_search.tavily_api_key or TAVILY_API_KEY."
    client = TavilyClient(api_key=api_key)
    resp = client.search(query, max_results=5)
    results = resp.get("results", []) if isinstance(resp, dict) else []
    if isinstance(resp, dict) and resp.get("answer"):
        answer = str(resp.get("answer"))
        return answer + "\n\nSources:\n" + _format_results(results)
    return _format_results(results)


def web_search(query: str, settings: OpenRalphSettings) -> str:
    provider = (settings.web_search_provider or "duckduckgo").lower()
    if provider == "tavily" and settings.tavily_api_key:
        return _tavily_search(query, settings.tavily_api_key)
    return _duckduckgo_search(query)
