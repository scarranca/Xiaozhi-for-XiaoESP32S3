import os
import requests
from datetime import datetime, timedelta
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()
DEFAULT_TIMEZONE = "America/Mexico_City"

# Google Calendar OAuth credentials
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
CALENDAR_API = "https://www.googleapis.com/calendar/v3"


def get_access_token():
    """Exchange refresh token for a fresh access token."""
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_headers():
    token = get_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Tool 1: Get calendar events
# ---------------------------------------------------------------------------

GET_CALENDAR_DESC = {
    "type": "function",
    "function": {
        "name": "get_calendar",
        "description": (
            "Get upcoming events from the user's Google Calendar. "
            "Use this when the user asks about their schedule, meetings, appointments, "
            "or what they have planned. "
            "Examples: 'What's on my schedule today?', 'Do I have any meetings tomorrow?', "
            "'What does my week look like?', 'Am I free at 3pm?'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period to check: 'today', 'tomorrow', or 'week'. Default is 'today'.",
                },
            },
            "required": [],
        },
    },
}


@register_function("get_calendar", GET_CALENDAR_DESC, ToolType.SYSTEM_CTL)
def get_calendar(conn: "ConnectionHandler", period: str = "today"):
    try:
        tz = conn.config.get("timezone", DEFAULT_TIMEZONE)
        now = datetime.utcnow()

        if period == "tomorrow":
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            end = start + timedelta(days=1)
            label = "tomorrow"
        elif period == "week":
            start = now
            end = now + timedelta(days=7)
            label = "this week"
        else:
            start = now.replace(hour=0, minute=0, second=0)
            end = start + timedelta(days=1)
            label = "today"

        params = {
            "timeMin": start.isoformat() + "Z",
            "timeMax": end.isoformat() + "Z",
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 15,
            "timeZone": tz,
        }

        resp = requests.get(
            f"{CALENDAR_API}/calendars/primary/events",
            headers=get_headers(),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json().get("items", [])

        if not events:
            return ActionResponse(
                Action.REQLLM,
                f"No events scheduled for {label}. The calendar is clear.",
                None,
            )

        formatted = f"Calendar events for {label}:\n\n"
        for e in events:
            start_time = e.get("start", {})
            if "dateTime" in start_time:
                t = datetime.fromisoformat(start_time["dateTime"]).strftime("%-I:%M %p")
            else:
                t = "All day"
            summary = e.get("summary", "No title")
            location = e.get("location", "")
            loc_str = f" at {location}" if location else ""
            formatted += f"- {t}: {summary}{loc_str}\n"

        formatted += "\nSummarize the schedule conversationally. This is a voice interface so keep it brief and natural."

        logger.bind(tag=TAG).info(f"Calendar fetched for {label}: {len(events)} events")
        return ActionResponse(Action.REQLLM, formatted, None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"Calendar error: {e}")
        return ActionResponse(Action.REQLLM, f"Sorry, I couldn't access your calendar: {e}", None)


# ---------------------------------------------------------------------------
# Tool 2: Create calendar event
# ---------------------------------------------------------------------------

CREATE_EVENT_DESC = {
    "type": "function",
    "function": {
        "name": "create_calendar_event",
        "description": (
            "Create a new event on the user's Google Calendar. "
            "Use this when the user wants to schedule something. "
            "Examples: 'Schedule a meeting tomorrow at 2pm', 'Add lunch with David on Friday at noon', "
            "'Create a reminder for Monday at 9am'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the event, e.g. 'Meeting with David'",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, e.g. '2026-03-04'",
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in HH:MM 24-hour format, e.g. '14:00' for 2pm",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration in minutes. Default 60 if not specified.",
                },
                "location": {
                    "type": "string",
                    "description": "Optional location for the event",
                },
            },
            "required": ["title", "date", "start_time"],
        },
    },
}


@register_function("create_calendar_event", CREATE_EVENT_DESC, ToolType.SYSTEM_CTL)
def create_calendar_event(
    conn: "ConnectionHandler",
    title: str,
    date: str,
    start_time: str,
    duration_minutes: int = 60,
    location: str = "",
):
    try:
        tz = conn.config.get("timezone", DEFAULT_TIMEZONE)
        start_dt = datetime.fromisoformat(f"{date}T{start_time}:00")
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event_body = {
            "summary": title,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        }
        if location:
            event_body["location"] = location

        resp = requests.post(
            f"{CALENDAR_API}/calendars/primary/events",
            headers=get_headers(),
            json=event_body,
            timeout=10,
        )
        resp.raise_for_status()
        created = resp.json()

        friendly_time = start_dt.strftime("%-I:%M %p")
        friendly_date = start_dt.strftime("%A, %B %-d")
        result = f"Event created: '{title}' on {friendly_date} at {friendly_time}."
        if location:
            result += f" Location: {location}."

        logger.bind(tag=TAG).info(f"Calendar event created: {title} on {date} at {start_time}")
        return ActionResponse(Action.REQLLM, result, None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"Create event error: {e}")
        return ActionResponse(Action.REQLLM, f"Sorry, I couldn't create the event: {e}", None)
