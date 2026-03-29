"""Telegram Bot API client wrapper.

Uses aiohttp for direct REST calls to the Telegram Bot API.
This avoids the overhead of python-telegram-bot's Application for
simple one-shot operations (tools, API handlers).
"""

import asyncio
import aiohttp
import os
from typing import Optional

TELEGRAM_API_BASE = "https://api.telegram.org"


def get_telegram_config(agent=None):
    """Load Telegram config through the plugin framework with env var overrides."""
    try:
        from helpers import plugins
        config = plugins.get_plugin_config("telegram", agent=agent) or {}
    except Exception:
        config = {}

    # Environment variable overrides file config
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config.setdefault("bot", {})["token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    return config


class TelegramClient:
    """Lightweight Telegram Bot API REST client."""

    def __init__(self, token: str):
        self.token = token
        self._session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def from_config(cls, agent=None) -> "TelegramClient":
        config = get_telegram_config(agent)
        token = config.get("bot", {}).get("token")
        if not token:
            raise ValueError(
                "Bot token not configured. Set TELEGRAM_BOT_TOKEN env var "
                "or configure in Telegram plugin settings."
            )
        return cls(token=token)

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "AgentZero-TelegramPlugin/1.0",
                }
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, api_method: str, **kwargs) -> dict:
        """Make a request to the Telegram Bot API."""
        await self._ensure_session()
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/{api_method}"

        async with self._session.request(method, url, **kwargs) as resp:
            data = await resp.json()

            if not data.get("ok"):
                error_code = data.get("error_code", resp.status)
                description = data.get("description", "Unknown error")
                raise TelegramAPIError(error_code, description, api_method)

            return data.get("result")

    async def _get(self, api_method: str, params: dict = None) -> dict:
        kwargs = {}
        if params:
            kwargs["params"] = params
        return await self._request("GET", api_method, **kwargs)

    async def _post(self, api_method: str, data: dict = None) -> dict:
        kwargs = {}
        if data:
            kwargs["json"] = data
        return await self._request("POST", api_method, **kwargs)

    # --- Bot info ---

    async def get_me(self) -> dict:
        return await self._get("getMe")

    # --- Messages ---

    async def send_message(
        self, chat_id: str, text: str,
        parse_mode: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> dict:
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        return await self._post("sendMessage", payload)

    async def forward_message(
        self, chat_id: str, from_chat_id: str, message_id: int,
    ) -> dict:
        return await self._post("forwardMessage", {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        })

    async def send_photo(
        self, chat_id: str, photo_url: str,
        caption: Optional[str] = None, parse_mode: Optional[str] = None,
    ) -> dict:
        payload = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await self._post("sendPhoto", payload)

    async def set_message_reaction(
        self, chat_id: str, message_id: int, emoji: str,
    ) -> dict:
        return await self._post("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        })

    # --- Chat history (getUpdates-based or getChat for info) ---

    async def get_updates(
        self, offset: int = 0, limit: int = 100, timeout: int = 0,
        allowed_updates: list = None,
    ) -> list:
        params = {"offset": offset, "limit": limit, "timeout": timeout}
        if allowed_updates:
            import json
            params["allowed_updates"] = json.dumps(allowed_updates)
        return await self._get("getUpdates", params)

    # --- Chat info ---

    async def get_chat(self, chat_id: str) -> dict:
        return await self._post("getChat", {"chat_id": chat_id})

    async def get_chat_member_count(self, chat_id: str) -> int:
        return await self._post("getChatMemberCount", {"chat_id": chat_id})

    async def get_chat_member(self, chat_id: str, user_id: int) -> dict:
        return await self._post("getChatMember", {
            "chat_id": chat_id, "user_id": user_id,
        })

    async def get_chat_administrators(self, chat_id: str) -> list:
        return await self._post("getChatAdministrators", {"chat_id": chat_id})

    # --- Chat management ---

    async def pin_chat_message(self, chat_id: str, message_id: int) -> bool:
        return await self._post("pinChatMessage", {
            "chat_id": chat_id, "message_id": message_id,
        })

    async def unpin_chat_message(self, chat_id: str, message_id: int) -> bool:
        return await self._post("unpinChatMessage", {
            "chat_id": chat_id, "message_id": message_id,
        })

    async def set_chat_title(self, chat_id: str, title: str) -> bool:
        return await self._post("setChatTitle", {
            "chat_id": chat_id, "title": title,
        })

    async def set_chat_description(self, chat_id: str, description: str) -> bool:
        return await self._post("setChatDescription", {
            "chat_id": chat_id, "description": description,
        })


class TelegramAPIError(Exception):
    def __init__(self, error_code: int, description: str, method: str):
        self.error_code = error_code
        self.description = description
        self.method = method
        super().__init__(f"Telegram API error {error_code} on {method}: {description}")


def format_messages(messages: list, include_ids: bool = False) -> str:
    """Format Telegram messages into readable text for LLM consumption.

    All external content (usernames, message text, captions, filenames) is
    sanitized to neutralise prompt injection attempts.
    """
    from usr.plugins.telegram.helpers.sanitize import (
        sanitize_content, sanitize_username, sanitize_caption, sanitize_filename,
    )

    lines = []
    for msg in messages:
        sender = msg.get("from", {})
        first_name = sender.get("first_name", "")
        last_name = sender.get("last_name", "")
        username = sanitize_username(
            f"{first_name} {last_name}".strip() or sender.get("username", "Unknown")
        )
        timestamp = ""
        if msg.get("date"):
            import datetime
            dt = datetime.datetime.fromtimestamp(msg["date"], tz=datetime.timezone.utc)
            timestamp = dt.strftime("%Y-%m-%d %H:%M")
        content = sanitize_content(msg.get("text", ""))

        caption_text = ""
        if msg.get("caption"):
            caption_text = f" [Caption: {sanitize_caption(msg['caption'])}]"

        # Photo/document/audio indicators
        media_text = ""
        if msg.get("photo"):
            media_text = " [Photo]"
        elif msg.get("document"):
            doc = msg["document"]
            fname = sanitize_filename(doc.get("file_name", "document"))
            media_text = f" [Document: {fname}]"
        elif msg.get("audio"):
            media_text = " [Audio]"
        elif msg.get("video"):
            media_text = " [Video]"
        elif msg.get("voice"):
            media_text = " [Voice message]"
        elif msg.get("sticker"):
            emoji = msg["sticker"].get("emoji", "")
            media_text = f" [Sticker{': ' + emoji if emoji else ''}]"

        reply_text = ""
        if msg.get("reply_to_message"):
            ref = msg["reply_to_message"]
            ref_sender = ref.get("from", {})
            ref_name = sanitize_username(
                ref_sender.get("first_name", "Unknown")
            )
            reply_text = f" (replying to {ref_name})"

        prefix = f"[{msg.get('message_id', '?')}] " if include_ids else ""
        lines.append(
            f"{prefix}[{timestamp}] {username}{reply_text}: {content}{caption_text}{media_text}"
        )

    return "\n".join(lines)
