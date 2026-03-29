"""API endpoint: Test Telegram bot connection.
URL: POST /api/plugins/telegram/telegram_test
"""
from helpers.api import ApiHandler, Request, Response


class TelegramTest(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.telegram.helpers.telegram_client import TelegramClient, get_telegram_config

            config = get_telegram_config()
            token = (config.get("bot", {}).get("token", "") or "").strip()
            if not token:
                return {"ok": False, "error": "No bot token configured"}

            client = TelegramClient(token=token)
            me = await client.get_me()
            await client.close()

            username = me.get("username", "")
            first_name = me.get("first_name", "")
            user_label = f"@{username}" if username else first_name

            return {
                "ok": True,
                "user": user_label,
                "user_id": me.get("id"),
                "username": username,
                "first_name": first_name,
            }
        except Exception as e:
            return {"ok": False, "error": f"Connection failed: {type(e).__name__}: {e}"}
