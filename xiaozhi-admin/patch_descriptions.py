"""Patch Chinese plugin function descriptions to English inside the xiaozhi container."""

import re
import os

BASE = "/opt/xiaozhi-esp32-server/plugins_func/functions"


def patch(filepath, replacements):
    if not os.path.exists(filepath):
        print(f"  NOT FOUND: {filepath}")
        return False
    with open(filepath, "r") as f:
        content = f.read()
    changed = False
    for old, new in replacements:
        if isinstance(old, re.Pattern):
            new_content = old.sub(new, content, count=1)
            if new_content != content:
                content = new_content
                changed = True
                print(f"  [REGEX] Patched")
            else:
                print(f"  [REGEX] Already patched or no match")
        else:
            if old in content:
                content = content.replace(old, new)
                changed = True
                print(f"  Patched: {old[:50]}...")
            else:
                print(f"  SKIP: {old[:50]}...")
    if changed:
        with open(filepath, "w") as f:
            f.write(content)
    return changed


# --- handle_exit_intent.py ---
print("=== handle_exit_intent.py ===")
patch(os.path.join(BASE, "handle_exit_intent.py"), [
    (
        '"description": "当用户想结束对话或需要退出系统时调用"',
        '"description": "Call when the user wants to end the conversation, say goodbye, or exit. Triggers like: bye, goodbye, see you, goodnight, I\'m done, that\'s all, adios, nos vemos."',
    ),
    (
        '"description": "和用户友好结束对话的告别语"',
        '"description": "A friendly goodbye message to the user"',
    ),
    (
        'say_goodbye = "再见，祝您生活愉快！"',
        'say_goodbye = "Goodbye, have a great day!"',
    ),
])

# --- play_music.py ---
print("=== play_music.py ===")
patch(os.path.join(BASE, "play_music.py"), [
    (
        '"description": "唱歌、听歌、播放音乐的方法。"',
        '"description": "Play music, sing a song, or listen to music. Use when user asks to play, sing, or listen to any song or music."',
    ),
    (
        re.compile(r'"description": "歌曲名称，如果用户没有指定具体歌名.*?"'),
        '"description": "Song name. Use \'random\' if the user did not specify a song name. If a specific song is requested, return the song name."',
    ),
])

# --- change_role.py ---
print("=== change_role.py ===")
patch(os.path.join(BASE, "change_role.py"), [
    (
        re.compile(r'"description": "当用户想切换角色.*?"'),
        '"description": "Switch the assistant personality or role. Call when the user wants to change the assistant character or personality."',
    ),
    (
        '"description": "要切换的角色名字"',
        '"description": "Name for the new role"',
    ),
    (
        '"description": "要切换的角色的职业"',
        '"description": "Role type to switch to"',
    ),
])

# --- get_weather.py ---
print("=== get_weather.py ===")
patch(os.path.join(BASE, "get_weather.py"), [
    (
        re.compile(
            r'"description":\s*\(\s*"获取某个地点的天气.*?\)\s*,',
            re.DOTALL,
        ),
        '"description": "Get the weather for a location. The user should provide a city name. If no location is specified, leave the location parameter empty.",',
    ),
    (
        re.compile(r'"description": "地点名，例如杭州.*?"'),
        '"description": "City or place name, e.g. New York, London, Tokyo. Optional."',
    ),
    (
        '"description": "返回用户使用的语言code，例如zh_CN/zh_HK/en_US/ja_JP等，默认zh_CN"',
        '"description": "Language code for the response, e.g. en_US, es_MX, zh_CN. Default: en_US"',
    ),
])

# --- get_news_from_newsnow.py ---
print("=== get_news_from_newsnow.py ===")
patch(os.path.join(BASE, "get_news_from_newsnow.py"), [
    (
        re.compile(
            r'"description":\s*\(\s*"获取最新新闻.*?\)\s*,',
            re.DOTALL,
        ),
        '"description": "Get the latest news. Randomly selects one headline to report. The user can request a specific news source. If none is specified, use the default source. The user can also ask for detailed content of the last news item.",',
    ),
    (
        re.compile(r'"description":\s*f"新闻源的标准中文名称.*?"'),
        '"description": "News source name. Optional, uses default if not provided."',
    ),
    (
        '"description": "是否获取详细内容，默认为false。如果为true，则获取上一条新闻的详细内容"',
        '"description": "Whether to fetch detailed content. Default false. If true, fetches the full content of the last news item."',
    ),
    (
        '"description": "返回用户使用的语言code，例如zh_CN/zh_HK/en_US/ja_JP等，默认zh_CN"',
        '"description": "Language code for the response, e.g. en_US, es_MX, zh_CN. Default: en_US"',
    ),
])

# --- get_time.py (get_lunar) ---
print("=== get_time.py ===")
patch(os.path.join(BASE, "get_time.py"), [
    (
        re.compile(
            r'"description":\s*\(\s*"用于具体日期的阴历.*?\)\s*,',
            re.DOTALL,
        ),
        '"description": "Get lunar calendar and Chinese almanac information for a specific date. Can look up lunar date, heavenly stems and earthly branches, solar terms, zodiac, constellation, and auspicious/inauspicious activities.",',
    ),
    (
        '"description": "要查询的日期，格式为YYYY-MM-DD，例如2024-01-01。如果不提供，则使用当前日期"',
        '"description": "Date to query in YYYY-MM-DD format, e.g. 2024-01-01. Uses current date if not provided."',
    ),
    (
        '"description": "要查询的内容，例如阴历日期、天干地支、节日、节气、生肖、星座、八字、宜忌等"',
        '"description": "What to look up, e.g. lunar date, heavenly stems, festivals, solar terms, zodiac, constellation, fortune."',
    ),
])

# ===================================================================
# Internal response strings (tool return values sent back to the LLM)
# ===================================================================

# --- get_news_from_newsnow.py defaults (switch to English sources) ---
print("=== get_news_from_newsnow.py (defaults) ===")
patch(os.path.join(BASE, "get_news_from_newsnow.py"), [
    (
        'DEFAULT_NEWS_SOURCES = "澎湃新闻;百度热搜;财联社"',
        'DEFAULT_NEWS_SOURCES = "Hacker News;Product Hunt;Github"',
    ),
    (
        '    source: str = "澎湃新闻",',
        '    source: str = "Hacker News",',
    ),
])

# --- get_news_from_newsnow.py internal prompts ---
print("=== get_news_from_newsnow.py (internals) ===")
patch(os.path.join(BASE, "get_news_from_newsnow.py"), [
    (
        'f"根据下列数据，用{lang}回应用户的新闻详情查询请求：\\n\\n"',
        'f"Based on the following data, respond to the user\'s news detail request. You MUST respond ONLY in {lang} — if the headline or content is in another language, translate it:\\n\\n"',
    ),
    (
        'f"新闻标题: {title}\\n"',
        'f"Headline: {title}\\n"',
    ),
    (
        'f"详细内容: {detail_content}\\n\\n"',
        'f"Full content: {detail_content}\\n\\n"',
    ),
    (
        'f"(请对上述新闻内容进行总结，提取关键信息，以自然、流畅的方式向用户播报，"',
        'f"(Summarize the above news content, extract key information, and deliver it naturally to the user. "',
    ),
    (
        'f"不要提及这是总结，就像是在讲述一个完整的新闻故事)"',
        'f"Do not mention that this is a summary, just tell it like a complete news story.)"',
    ),
    (
        'f"根据下列数据，用{lang}回应用户的新闻查询请求：\\n\\n"',
        'f"Based on the following data, respond to the user\'s news request. You MUST respond ONLY in {lang} — if the headline is in another language, translate it:\\n\\n"',
    ),
    (
        "f\"新闻标题: {selected_news['title']}\\n\"",
        "f\"Headline: {selected_news['title']}\\n\"",
    ),
    (
        'f"(请以自然、流畅的方式向用户播报这条新闻标题，"',
        'f"(Deliver this headline naturally to the user and "',
    ),
    (
        'f"提示用户可以要求获取详细内容，此时会获取新闻的详细内容。)"',
        'f"let them know they can ask for more details.)"',
    ),
    (
        '"抱歉，没有找到最近查询的新闻，请先获取一条新闻。"',
        '"Sorry, no recent news found. Please fetch a news item first."',
    ),
    (
        '"抱歉，该新闻没有可用的链接获取详细内容。"',
        '"Sorry, this news item has no available link for details."',
    ),
    (
        'f"抱歉，无法获取《{title}》的详细内容，可能是链接已失效或网站结构发生变化。"',
        'f"Sorry, could not fetch details for \\"{title}\\". The link may be broken."',
    ),
    (
        'f"抱歉，未能从{source}获取到新闻信息，请稍后再试或尝试其他新闻源。"',
        'f"Sorry, could not fetch news from {source}. Please try again later."',
    ),
    (
        '"抱歉，获取新闻时发生错误，请稍后再试。"',
        '"Sorry, an error occurred while fetching news. Please try again later."',
    ),
])

# --- get_weather.py internal prompts ---
print("=== get_weather.py (internals) ===")
patch(os.path.join(BASE, "get_weather.py"), [
    (
        'f"未找到相关的城市: {location}，请确认地点是否正确"',
        'f"City not found: {location}. Please check the location name."',
    ),
    (
        '"请求失败"',
        '"Weather request failed"',
    ),
    (
        'f"您查询的位置是：{city_name}\\n\\n当前天气: {current_abstract}\\n"',
        'f"Location: {city_name}\\n\\nCurrent weather: {current_abstract}\\n"',
    ),
    (
        'weather_report += "详细参数：\\n"',
        'weather_report += "Details:\\n"',
    ),
    (
        'weather_report += "\\n未来7天预报：\\n"',
        'weather_report += "\\n7-day forecast:\\n"',
    ),
    (
        'weather_report += "\\n（如需某一天的具体天气，请告诉我日期）"',
        'weather_report += "\\n(Ask me about a specific day for more details.)"',
    ),
])

# --- get_time.py (get_lunar) internal prompts ---
print("=== get_time.py (internals) ===")
patch(os.path.join(BASE, "get_time.py"), [
    (
        'f"日期格式错误，请使用YYYY-MM-DD格式，例如：2024-01-01"',
        'f"Invalid date format. Please use YYYY-MM-DD, e.g. 2024-01-01."',
    ),
    (
        'f"根据以下信息回应用户的查询请求，并提供与{query}相关的信息：\\n"',
        'f"Based on the following information, respond to the user about {query}:\\n"',
    ),
])

# --- Strengthen translation instructions (patches already-English strings) ---
print("=== get_news_from_newsnow.py (strengthen translation) ===")
patch(os.path.join(BASE, "get_news_from_newsnow.py"), [
    (
        "respond to the user's news detail request in {lang}:",
        "respond to the user's news detail request. You MUST respond ONLY in {lang} — if the headline or content is in another language, translate it:",
    ),
    (
        "respond to the user's news request in {lang}:",
        "respond to the user's news request. You MUST respond ONLY in {lang} — if the headline is in another language, translate it:",
    ),
])

# ===================================================================
# Core error messages — translate Chinese errors that kill TTS
# ===================================================================

CORE_BASE = "/opt/xiaozhi-esp32-server/core"

# --- unified_tool_manager.py (tool not found / error messages) ---
print("=== unified_tool_manager.py ===")
patch(os.path.join(CORE_BASE, "providers/tools/unified_tool_manager.py"), [
    (
        'response=f"工具 {tool_name} 不存在"',
        'response=f"Tool {tool_name} is not available."',
    ),
    (
        'response=f"工具类型 {tool_type.value} 的执行器未注册"',
        'response=f"No executor registered for tool type {tool_type.value}."',
    ),
    (
        'f"执行工具 {tool_name} 时出错: {e}"',
        'f"Error executing tool {tool_name}: {e}"',
    ),
])

# --- unified_tool_handler.py ---
print("=== unified_tool_handler.py ===")
patch(os.path.join(CORE_BASE, "providers/tools/unified_tool_handler.py"), [
    (
        '"无法解析函数参数"',
        '"Could not parse function arguments."',
    ),
    (
        'response="无响应"',
        'response="No response from tools."',
    ),
])

# --- connection.py: add fallback when LLM produces no output ---
print("=== connection.py (empty response fallback) ===")
patch(os.path.join(CORE_BASE, "connection.py"), [
    (
        '        # 存储对话内容\n        if len(response_message) > 0:',
        '        # Fallback: if LLM produced no output at all, send a generic reply\n'
        '        if not tool_call_flag and len(response_message) == 0:\n'
        '            fallback = "Sorry, I couldn\'t process that. Could you try rephrasing?"\n'
        '            response_message.append(fallback)\n'
        '            self.tts.tts_text_queue.put(\n'
        '                TTSMessageDTO(\n'
        '                    sentence_id=self.sentence_id,\n'
        '                    sentence_type=SentenceType.MIDDLE,\n'
        '                    content_type=ContentType.TEXT,\n'
        '                    content_detail=fallback,\n'
        '                )\n'
        '            )\n'
        '            self.logger.bind(tag=TAG).warning("LLM produced no output, using fallback")\n\n'
        '        # 存储对话内容\n        if len(response_message) > 0:',
    ),
])

print("\nDone!")
