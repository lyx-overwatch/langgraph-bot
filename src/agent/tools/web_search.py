"""Zhipu MCP web search tool.

Bridges the Zhipu MCP server (SSE transport) into a LangChain tool.
Requires ZHIPU_API_KEY environment variable.
"""
import os
import requests

from langchain_core.tools import tool


ZHIPU_SEARCH_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/web_search"

@tool
def zhipu_web_search(query: str) -> str:
    """Search the web for up-to-date information using Zhipu AI web search.

    Use this tool to look up current events, real-time facts, news, or any
    information that may have changed after the model's training data.

    Args:
        query: The search query (in Chinese or English).

    Returns:
        Search results with titles, URLs, and snippets.
    """
    api_key = os.getenv("ZHIPU_API_KEY")
    if not api_key:
        return (
            "ZHIPU_API_KEY environment variable is not set. "
            "Please set it to your Zhipu API key to enable web search."
        )

    payload = {
        "search_query": query,
        "search_engine": "search_std",
        "search_intent": False,
        "count": 10,
        "search_recency_filter": "noLimit",
        "content_size": "medium",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(ZHIPU_SEARCH_ENDPOINT, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        return f"Web search failed: {type(e).__name__}: {e}"

    try:
        data = response.json()
    except Exception:
        return "Web search failed: failed to parse response as JSON"

    results = data.get("search_result", [])
    if not results:
        return "No search results found."

    lines = []
    for i, item in enumerate(results, 1):
        title = item.get("title", "")
        content = item.get("content", "")
        link = item.get("link", "")
        publish_date = item.get("publish_date", "")
        refer = item.get("refer", "")

        snippet = f"[{i}] {title}\n"
        if publish_date:
            snippet += f"Date: {publish_date}\n"
        if content:
            snippet += f"{content}\n"
        if link:
            snippet += f"Link: {link}\n"
        if refer:
            snippet += f"Source: {refer}\n"
        lines.append(snippet)

    return "\n".join(lines)
