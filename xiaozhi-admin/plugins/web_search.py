import requests
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

WEB_SEARCH_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use this when the user asks about "
            "recent events, news, facts you're unsure about, prices, scores, releases, "
            "or anything that requires up-to-date information. "
            "Examples: 'What's the latest on...', 'Search for...', 'Look up...', "
            "'What happened with...', 'How much does X cost', 'Who won the game'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the web",
                },
            },
            "required": ["query"],
        },
    },
}

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_API_KEY = "BSAHF5qwMHXdLOlXuYVAubM3jYVHzlp"


@register_function("web_search", WEB_SEARCH_FUNCTION_DESC, ToolType.WAIT)
def web_search(query: str):
    try:
        api_key = BRAVE_API_KEY

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = {
            "q": query,
            "count": 5,
        }

        response = requests.get(BRAVE_API_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = data.get("web", {}).get("results", [])
        if not results:
            return ActionResponse(
                Action.REQLLM,
                f"No search results found for: {query}",
                None,
            )

        # Format results for the LLM
        formatted = f"Web search results for: {query}\n\n"
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "No title")
            description = r.get("description", "No description")
            url = r.get("url", "")
            formatted += f"{i}. {title}\n   {description}\n   Source: {url}\n\n"

        formatted += "Summarize the most relevant information for the user in a concise, conversational way. This is a voice interface so keep it brief."

        logger.bind(tag=TAG).info(f"Web search completed for: {query}")
        return ActionResponse(Action.REQLLM, formatted, None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"Web search error: {e}")
        return ActionResponse(
            Action.REQLLM,
            f"Sorry, the web search failed: {str(e)}",
            None,
        )
