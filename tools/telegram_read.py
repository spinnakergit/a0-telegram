import json
import os

from helpers.tool import Tool, Response
from usr.plugins.telegram.helpers.telegram_client import (
    TelegramClient, TelegramAPIError, format_messages, get_telegram_config,
)
from usr.plugins.telegram.helpers.sanitize import require_auth, sanitize_chat_title


# Persistent chat registry — survives across getUpdates calls
def _chat_registry_path():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "known_chats.json")


def _load_chat_registry() -> dict:
    path = _chat_registry_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_chat_registry(chats: dict):
    path = _chat_registry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(chats, f, indent=2)


def _update_chat_registry(updates: list) -> dict:
    """Extract chats from updates and merge into persistent registry."""
    registry = _load_chat_registry()
    for update in updates:
        msg = update.get("message") or update.get("channel_post")
        if msg and msg.get("chat"):
            chat = msg["chat"]
            cid = str(chat.get("id"))
            registry[cid] = {
                "title": chat.get("title") or chat.get("first_name", ""),
                "username": chat.get("username", ""),
                "type": chat.get("type", "unknown"),
                "last_seen": msg.get("date", 0),
            }
    _save_chat_registry(registry)
    return registry


class TelegramRead(Tool):
    """Read messages from Telegram chats, list chats, or get chat info."""

    async def execute(self, **kwargs) -> Response:
        chat_id = self.args.get("chat_id", "")
        limit = int(self.args.get("limit", "50"))
        action = self.args.get("action", "messages")

        config = get_telegram_config(self.agent)
        try:
            require_auth(config)
        except ValueError as e:
            return Response(message=f"Auth error: {e}", break_loop=False)

        try:
            client = TelegramClient.from_config(agent=self.agent)

            if action == "chat_info":
                if not chat_id:
                    return Response(message="Error: chat_id is required for chat_info.", break_loop=False)
                chat = await client.get_chat(chat_id)
                await client.close()
                return Response(message=_format_chat_info(chat), break_loop=False)

            elif action == "chats":
                # Check message store first (populated by bridge)
                from usr.plugins.telegram.helpers.message_store import get_all_chats
                store_chats = get_all_chats()

                # Only try getUpdates if the bridge is NOT actively polling.
                # Concurrent getUpdates calls cause a Conflict error that crashes
                # the bridge's polling loop.
                try:
                    from usr.plugins.telegram.helpers.telegram_bridge import is_bridge_polling
                    bridge_active = is_bridge_polling()
                except Exception:
                    bridge_active = False

                if not bridge_active:
                    try:
                        updates = await client.get_updates(limit=100)
                        _update_chat_registry(updates)
                    except Exception:
                        updates = []
                await client.close()

                # Merge: message store + chat registry
                registry = _load_chat_registry()
                for cid, info in store_chats.items():
                    if cid not in registry:
                        registry[cid] = info
                    else:
                        # Update with latest info from store
                        if info.get("last_seen", 0) > registry[cid].get("last_seen", 0):
                            registry[cid].update(info)
                _save_chat_registry(registry)

                if not registry:
                    return Response(
                        message="No chats found. Send a message to the bot in Telegram first, "
                                "then try again.",
                        break_loop=False,
                    )
                lines = [f"Known chats ({len(registry)}):"]
                for cid, info in registry.items():
                    title = sanitize_chat_title(info.get("title", info.get("username", cid)))
                    chat_type = info.get("type", "unknown")
                    msg_count = info.get("message_count", "")
                    count_str = f", {msg_count} messages" if msg_count else ""
                    lines.append(f"  - {title} (ID: {cid}, type: {chat_type}{count_str})")
                return Response(message="\n".join(lines), break_loop=False)

            elif action == "messages":
                if not chat_id:
                    return Response(message="Error: chat_id is required for reading messages.", break_loop=False)

                # Try message store first (populated by bridge)
                from usr.plugins.telegram.helpers.message_store import get_messages
                messages = get_messages(str(chat_id), limit=limit)

                # Only fall back to getUpdates if bridge is NOT actively polling.
                # Concurrent getUpdates calls cause a Conflict error that crashes
                # the bridge's polling loop.
                if not messages:
                    try:
                        from usr.plugins.telegram.helpers.telegram_bridge import is_bridge_polling
                        bridge_active = is_bridge_polling()
                    except Exception:
                        bridge_active = False

                    if not bridge_active:
                        updates = await client.get_updates(limit=100)
                        _update_chat_registry(updates)

                        for update in updates:
                            msg = update.get("message") or update.get("channel_post")
                            if msg and str(msg.get("chat", {}).get("id")) == str(chat_id):
                                messages.append(msg)

                        messages = messages[-limit:]

                await client.close()

                if not messages:
                    return Response(
                        message="No recent messages found for this chat. If the chat bridge is "
                                "running, new messages will be stored automatically. Otherwise, "
                                "send a message to the bot and try again.",
                        break_loop=False,
                    )

                result = format_messages(messages, include_ids=True)
                return Response(
                    message=f"Retrieved {len(messages)} messages from chat {chat_id}:\n\n{result}",
                    break_loop=False,
                )

            else:
                return Response(
                    message=f"Unknown action '{action}'. Use 'messages', 'chats', or 'chat_info'.",
                    break_loop=False,
                )

        except TelegramAPIError as e:
            return Response(message=f"Telegram API error: {e}", break_loop=False)
        except Exception as e:
            return Response(message=f"Error reading Telegram: {type(e).__name__}", break_loop=False)


def _format_chat_info(chat: dict) -> str:
    title = sanitize_chat_title(
        chat.get("title") or chat.get("first_name", "") + " " + chat.get("last_name", "")
    )
    lines = [
        f"Chat: {title}",
        f"  ID: {chat.get('id')}",
        f"  Type: {chat.get('type', 'unknown')}",
    ]
    if chat.get("username"):
        lines.append(f"  Username: @{chat['username']}")
    if chat.get("description"):
        lines.append(f"  Description: {sanitize_chat_title(chat['description'], max_length=200)}")
    if chat.get("invite_link"):
        lines.append(f"  Invite link: {chat['invite_link']}")
    return "\n".join(lines)
