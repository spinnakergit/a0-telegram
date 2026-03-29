from helpers.tool import Tool, Response
from usr.plugins.telegram.helpers.telegram_client import (
    TelegramClient, TelegramAPIError, get_telegram_config,
)
from usr.plugins.telegram.helpers.sanitize import require_auth, sanitize_username, validate_chat_id


class TelegramMembers(Tool):
    """List or search group/supergroup members via Telegram Bot API."""

    async def execute(self, **kwargs) -> Response:
        chat_id = self.args.get("chat_id", "")
        search_query = self.args.get("search_query", "")

        try:
            chat_id = validate_chat_id(chat_id, "chat_id")
        except ValueError as e:
            return Response(message=f"Error: {e}", break_loop=False)

        config = get_telegram_config(self.agent)
        try:
            require_auth(config)
        except ValueError as e:
            return Response(message=f"Auth error: {e}", break_loop=False)

        try:
            client = TelegramClient.from_config(agent=self.agent)

            # Get administrators (most reliable way to list members via Bot API)
            admins = await client.get_chat_administrators(chat_id)
            member_count = await client.get_chat_member_count(chat_id)
            await client.close()

            if not admins:
                return Response(
                    message=f"No administrators found or insufficient permissions for chat {chat_id}.",
                    break_loop=False,
                )

            lines = [f"Chat {chat_id} — {member_count} total members"]
            lines.append(f"Administrators ({len(admins)}):")

            for admin in admins:
                user = admin.get("user", {})
                first_name = sanitize_username(user.get("first_name", "Unknown"))
                username = user.get("username", "")
                user_id = user.get("id", "?")
                status = admin.get("status", "")
                bot_tag = " [BOT]" if user.get("is_bot") else ""
                at_name = f" (@{username})" if username else ""

                # Filter by search query if provided
                if search_query:
                    search_lower = search_query.lower()
                    searchable = f"{first_name} {username}".lower()
                    if search_lower not in searchable:
                        continue

                lines.append(
                    f"  - {first_name}{at_name} (ID: {user_id}){bot_tag} — {status}"
                )

            if search_query and len(lines) == 2:
                return Response(
                    message=f"No administrators matching '{search_query}' in chat {chat_id}.",
                    break_loop=False,
                )

            lines.append(
                f"\nNote: Telegram Bot API only provides administrator lists. "
                f"Full member listing requires Telegram user API (not supported)."
            )

            return Response(message="\n".join(lines), break_loop=False)

        except TelegramAPIError as e:
            return Response(message=f"Telegram API error: {e}", break_loop=False)
        except Exception as e:
            return Response(message=f"Error listing members: {type(e).__name__}", break_loop=False)
