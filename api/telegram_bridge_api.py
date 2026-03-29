"""API endpoint: Chat bridge start/stop/status.
URL: POST /api/plugins/telegram/telegram_bridge_api
"""
import logging
from helpers.api import ApiHandler, Request, Response

logger = logging.getLogger("telegram_bridge_api")


class TelegramBridgeApi(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = input.get("action", "status")

        try:
            if action == "status":
                return self._status()
            elif action == "start":
                return await self._start()
            elif action == "stop":
                return await self._stop()
            elif action == "restart":
                return await self._restart()
            else:
                return {"ok": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.error("Bridge API error on '%s': %s", action, type(e).__name__, exc_info=True)
            return {"ok": False, "error": f"Bridge error: {type(e).__name__}"}

    def _status(self) -> dict:
        from usr.plugins.telegram.helpers.telegram_bridge import get_bot_status, get_chat_list
        status = get_bot_status()
        status["chat_count"] = len(get_chat_list())
        return {"ok": True, **status}

    async def _start(self) -> dict:
        from usr.plugins.telegram.helpers.telegram_bridge import get_bot_status, start_chat_bridge
        from usr.plugins.telegram.helpers.telegram_client import get_telegram_config

        status = get_bot_status()
        if status.get("running"):
            return {"ok": True, "message": "Bridge is already running", **status}

        config = get_telegram_config()
        token = (config.get("bot", {}).get("token", "") or "").strip()
        if not token:
            return {"ok": False, "error": "No bot token configured"}

        logger.info(f"Starting bridge with token present={bool(token)}")
        await start_chat_bridge(token)
        final_status = get_bot_status()
        logger.info(f"Bridge start result: {final_status}")
        return {"ok": True, "message": "Bridge started", **final_status}

    async def _stop(self) -> dict:
        from usr.plugins.telegram.helpers.telegram_bridge import get_bot_status, stop_chat_bridge

        await stop_chat_bridge()
        return {"ok": True, "message": "Bridge stopped", **get_bot_status()}

    async def _restart(self) -> dict:
        from usr.plugins.telegram.helpers.telegram_bridge import get_bot_status, start_chat_bridge, stop_chat_bridge
        from usr.plugins.telegram.helpers.telegram_client import get_telegram_config

        await stop_chat_bridge()

        config = get_telegram_config()
        token = (config.get("bot", {}).get("token", "") or "").strip()
        if not token:
            return {"ok": False, "error": "No bot token configured"}

        await start_chat_bridge(token)
        return {"ok": True, "message": "Bridge restarted", **get_bot_status()}
