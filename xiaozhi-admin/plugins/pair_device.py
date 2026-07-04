import requests
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

ADMIN_URL = "http://xiaozhi-admin:8081"

PAIR_DEVICE_DESC = {
    "type": "function",
    "function": {
        "name": "pair_device",
        "description": (
            "Pair this device with a user account using a pairing code. "
            "Use this when the user says a pairing code to link their device. "
            "Examples: 'My pairing code is K7X3M9', 'Pair me with code ABC123', "
            "'Code is H4J8N2', 'Link my device with K7X3M9'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The 6-character pairing code spoken by the user, e.g. 'K7X3M9'",
                },
            },
            "required": ["code"],
        },
    },
}


@register_function("pair_device", PAIR_DEVICE_DESC, ToolType.SYSTEM_CTL)
def pair_device(conn: "ConnectionHandler", code: str):
    try:
        device_id = conn.device_id
        if not device_id:
            return ActionResponse(
                Action.REQLLM,
                "I couldn't identify your device. Please try reconnecting.",
                None,
            )

        clean_code = code.strip().upper().replace(" ", "")
        logger.bind(tag=TAG).info(f"Pairing attempt: device={device_id}, code={clean_code}")

        resp = requests.post(
            f"{ADMIN_URL}/api/pair",
            json={"code": clean_code, "device_id": device_id},
            timeout=10,
        )
        data = resp.json()

        if resp.status_code == 200 and data.get("ok"):
            username = data.get("username", "your account")
            return ActionResponse(
                Action.REQLLM,
                f"Device successfully paired to {username}'s account! "
                f"Tell the user their device is now linked and they're all set.",
                None,
            )
        else:
            error = data.get("error", "Unknown error")
            return ActionResponse(
                Action.REQLLM,
                f"Pairing failed: {error}. Ask the user to check the code and try again.",
                None,
            )

    except Exception as e:
        logger.bind(tag=TAG).error(f"Pair device error: {e}")
        return ActionResponse(
            Action.REQLLM,
            f"Sorry, I couldn't complete the pairing: {e}",
            None,
        )
