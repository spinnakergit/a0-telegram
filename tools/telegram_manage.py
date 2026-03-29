from helpers.tool import Tool, Response
from usr.plugins.telegram.helpers.telegram_client import (
    TelegramClient, TelegramAPIError, get_telegram_config,
)
from usr.plugins.telegram.helpers.sanitize import require_auth, validate_chat_id


class TelegramManage(Tool):
    """Manage Telegram chats: pin/unpin messages, set chat title/description."""

    async def execute(self, **kwargs) -> Response:
        chat_id = self.args.get("chat_id", "")
        action = self.args.get("action", "")
        message_id = self.args.get("message_id", "")
        value = self.args.get("value", "")

        try:
            chat_id = validate_chat_id(chat_id)
        except ValueError as e:
            return Response(message=f"Error: {e}", break_loop=False)

        if not action:
            return Response(
                message="Error: action is required. Use: pin, unpin, set_title, set_description.",
                break_loop=False,
            )

        config = get_telegram_config(self.agent)
        try:
            require_auth(config)
        except ValueError as e:
            return Response(message=f"Auth error: {e}", break_loop=False)

        try:
            client = TelegramClient.from_config(agent=self.agent)

            if action == "pin":
                if not message_id:
                    return Response(message="Error: message_id is required for pinning.", break_loop=False)
                await client.pin_chat_message(chat_id, int(message_id))
                await client.close()
                return Response(message=f"Message {message_id} pinned in chat {chat_id}.", break_loop=False)

            elif action == "unpin":
                if not message_id:
                    return Response(message="Error: message_id is required for unpinning.", break_loop=False)
                await client.unpin_chat_message(chat_id, int(message_id))
                await client.close()
                return Response(message=f"Message {message_id} unpinned in chat {chat_id}.", break_loop=False)

            elif action == "set_title":
                if not value:
                    return Response(message="Error: value is required for set_title.", break_loop=False)
                await client.set_chat_title(chat_id, value)
                await client.close()
                return Response(message=f"Chat title set to '{value}'.", break_loop=False)

            elif action == "set_description":
                await client.set_chat_description(chat_id, value or "")
                await client.close()
                msg = f"Chat description updated." if value else "Chat description cleared."
                return Response(message=msg, break_loop=False)

            else:
                return Response(
                    message=f"Unknown action '{action}'. Use: pin, unpin, set_title, set_description.",
                    break_loop=False,
                )

        except TelegramAPIError as e:
            return Response(message=f"Telegram API error: {e}", break_loop=False)
        except Exception as e:
            return Response(message=f"Error managing chat: {type(e).__name__}", break_loop=False)
