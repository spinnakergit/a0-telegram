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
        """Generate a new random auth key and persist it to config.json.

        Persisting immediately ensures the bridge reads the same key the
        user sees in the UI, even if the outer Save button hasn't been
        clicked yet.
        """
        try:
            from pathlib import Path
            import json
            from usr.plugins.telegram.helpers.sanitize import generate_auth_key, secure_write_json

            key = generate_auth_key()

            # Persist to config.json so the bridge picks it up immediately
            config_candidates = [
                Path("/a0/usr/plugins/telegram/config.json"),
                Path("/a0/plugins/telegram/config.json"),
                Path(__file__).parent.parent / "config.json",
            ]
            for cp in config_candidates:
                if cp.exists():
                    existing = json.loads(cp.read_text())
                    existing.setdefault("chat_bridge", {})["auth_key"] = key
                    secure_write_json(cp, existing)
                    break

            return {"auth_key": key}
        except Exception:
            return {"error": "Failed to generate auth key."}
