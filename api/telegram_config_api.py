"""API endpoint: Telegram plugin custom actions.
URL: POST /api/plugins/telegram/telegram_config_api

Config load/save is handled by A0's built-in plugin settings framework.
This endpoint only handles actions that need server-side logic (key generation).
"""
from helpers.api import ApiHandler, Request, Response


class TelegramConfigApi(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = input.get("action", "")
        if action == "generate_auth_key":
            return self._generate_auth_key()
        return {"error": "Unknown action"}

    def _generate_auth_key(self) -> dict:
        """Generate a new random auth key for elevated mode."""
        try:
            from plugins.telegram.helpers.sanitize import generate_auth_key
            return {"auth_key": generate_auth_key()}
        except Exception:
            return {"error": "Failed to generate auth key."}
