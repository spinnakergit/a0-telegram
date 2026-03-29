"""Auto-start the Telegram chat bridge on agent initialization.

Only starts if:
  - A bot token is configured
  - chat_bridge.auto_start is true in config
  - At least one bridge chat is registered

NOTE: agent_init is dispatched via call_extensions_sync(), so execute()
must be synchronous.  start_chat_bridge() is async, so we schedule it on
the running event loop with create_task().

The dedup flag lives on the bridge module (a true singleton) rather than
on this extension module, which A0 may reimport from multiple search paths.
"""

import asyncio
import logging

from helpers.extension import Extension

logger = logging.getLogger("telegram_chat_bridge")


class TelegramChatBridgeInit(Extension):

    def execute(self, **kwargs):
        if not self.agent:
            return

        # Only run for the main agent, not subordinates
        if self.agent.number != 0:
            return

        try:
            import usr.plugins.telegram.helpers.telegram_bridge as bridge

            # Only attempt once per process lifetime (flag lives on the
            # bridge module so it survives reimports of this extension)
            if bridge._auto_start_attempted or bridge.is_bridge_polling():
                return

            bridge._auto_start_attempted = True

            from helpers import plugins

            config = plugins.get_plugin_config("telegram", agent=self.agent)
            bot_token = config.get("bot", {}).get("token", "")

            if not bot_token:
                return  # No token, skip

            bridge_config = config.get("chat_bridge", {})
            if not bridge_config.get("auto_start", False):
                return  # Auto-start disabled

            chats = bridge.get_chat_list()
            if not chats:
                return  # No chats configured

            logger.warning(
                f"Auto-starting Telegram chat bridge ({len(chats)} chat(s))..."
            )

            # start_chat_bridge is async — schedule it on the running loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(bridge.start_chat_bridge(bot_token))
            except RuntimeError:
                asyncio.run(bridge.start_chat_bridge(bot_token))

            logger.warning("Telegram chat bridge auto-start scheduled.")

        except Exception as e:
            logger.warning("Telegram chat bridge auto-start failed: %s", type(e).__name__, exc_info=True)
