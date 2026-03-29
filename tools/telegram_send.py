from helpers.tool import Tool, Response
from usr.plugins.telegram.helpers.telegram_client import (
    TelegramClient, TelegramAPIError, get_telegram_config,
)
from usr.plugins.telegram.helpers.sanitize import require_auth, validate_chat_id


class TelegramSend(Tool):
    """Send messages, photos, reactions, or forward messages via Telegram bot."""

    async def execute(self, **kwargs) -> Response:
        chat_id = self.args.get("chat_id", "")
        content = self.args.get("content", "")
        reply_to = self.args.get("reply_to", "")
        action = self.args.get("action", "send")
        parse_mode = self.args.get("parse_mode", "")

        try:
            chat_id = validate_chat_id(chat_id)
        except ValueError as e:
            return Response(message=f"Error: {e}", break_loop=False)

        config = get_telegram_config(self.agent)
        try:
            require_auth(config)
        except ValueError as e:
            return Response(message=f"Auth error: {e}", break_loop=False)

        try:
            client = TelegramClient.from_config(agent=self.agent)

            if action == "send":
                if not content:
                    return Response(message="Error: content is required for sending.", break_loop=False)

                chunks = _split_message(content)
                sent_ids = []
                for i, chunk in enumerate(chunks):
                    ref = int(reply_to) if i == 0 and reply_to else None
                    result = await client.send_message(
                        chat_id=chat_id, text=chunk,
                        parse_mode=parse_mode or None,
                        reply_to_message_id=ref,
                    )
                    sent_ids.append(str(result.get("message_id", "?")))

                await client.close()
                if len(sent_ids) == 1:
                    return Response(message=f"Message sent (ID: {sent_ids[0]}).", break_loop=False)
                return Response(
                    message=f"Message sent in {len(sent_ids)} parts (IDs: {', '.join(sent_ids)}).",
                    break_loop=False,
                )

            elif action == "reply":
                if not content or not reply_to:
                    return Response(
                        message="Error: content and reply_to are required for replying.",
                        break_loop=False,
                    )
                result = await client.send_message(
                    chat_id=chat_id, text=content,
                    parse_mode=parse_mode or None,
                    reply_to_message_id=int(reply_to),
                )
                await client.close()
                return Response(
                    message=f"Reply sent (ID: {result.get('message_id', '?')}).",
                    break_loop=False,
                )

            elif action == "forward":
                from_chat_id = self.args.get("from_chat_id", "")
                message_id = self.args.get("message_id", "")
                if not from_chat_id or not message_id:
                    return Response(
                        message="Error: from_chat_id and message_id are required for forwarding.",
                        break_loop=False,
                    )
                result = await client.forward_message(
                    chat_id=chat_id, from_chat_id=from_chat_id,
                    message_id=int(message_id),
                )
                await client.close()
                return Response(
                    message=f"Message forwarded (ID: {result.get('message_id', '?')}).",
                    break_loop=False,
                )

            elif action == "react":
                emoji = self.args.get("emoji", "")
                message_id = self.args.get("message_id", "")
                if not emoji or not message_id:
                    return Response(
                        message="Error: emoji and message_id required for reactions.",
                        break_loop=False,
                    )
                await client.set_message_reaction(chat_id, int(message_id), emoji)
                await client.close()
                return Response(
                    message=f"Reaction {emoji} added to message {message_id}.",
                    break_loop=False,
                )

            elif action == "photo":
                photo_url = self.args.get("photo_url", "")
                if not photo_url:
                    return Response(message="Error: photo_url is required.", break_loop=False)
                result = await client.send_photo(
                    chat_id=chat_id, photo_url=photo_url,
                    caption=content or None,
                    parse_mode=parse_mode or None,
                )
                await client.close()
                return Response(
                    message=f"Photo sent (ID: {result.get('message_id', '?')}).",
                    break_loop=False,
                )

            else:
                return Response(
                    message=f"Unknown action '{action}'. Use 'send', 'reply', 'forward', 'react', or 'photo'.",
                    break_loop=False,
                )

        except TelegramAPIError as e:
            return Response(message=f"Telegram API error: {e}", break_loop=False)
        except Exception as e:
            return Response(message=f"Error sending to Telegram: {type(e).__name__}", break_loop=False)


def _split_message(content: str, max_length: int = 4096) -> list[str]:
    if len(content) <= max_length:
        return [content]
    chunks = []
    while content:
        if len(content) <= max_length:
            chunks.append(content)
            break
        split_at = content.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = content.rfind(" ", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(content[:split_at])
        content = content[split_at:].lstrip("\n")
    return chunks
