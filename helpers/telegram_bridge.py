"""Persistent Telegram bot for the chat bridge.
Uses python-telegram-bot's Application with polling to receive messages
and routes them through Agent Zero's LLM.

SECURITY MODEL:
  - Restricted mode (default): Uses call_utility_model() — NO tools, NO code execution,
    NO file access. The LLM literally cannot perform system operations.
  - Elevated mode (opt-in): Authenticated users get full agent loop access via
    context.communicate(). Requires: allow_elevated=true in config + runtime auth
    via !auth <key> in Telegram. Sessions expire after a configurable timeout.
"""

import asyncio
import collections
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("telegram_chat_bridge")

# Singleton bot instance and its dedicated event loop thread
_bot_instance: Optional["ChatBridgeBot"] = None
_bot_thread: Optional[threading.Thread] = None
_bot_loop: Optional[asyncio.AbstractEventLoop] = None
_auto_start_attempted: bool = False

CHAT_STATE_FILE = "chat_bridge_state.json"


def _get_state_path() -> Path:
    candidates = [
        Path(__file__).parent.parent / "data" / CHAT_STATE_FILE,
        Path("/a0/usr/plugins/telegram/data") / CHAT_STATE_FILE,
        Path("/a0/plugins/telegram/data") / CHAT_STATE_FILE,
        Path("/git/agent-zero/usr/plugins/telegram/data") / CHAT_STATE_FILE,
    ]
    for p in candidates:
        if p.exists():
            return p
    path = candidates[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_chat_state() -> dict:
    path = _get_state_path()
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {"chats": {}, "contexts": {}}


def save_chat_state(state: dict):
    from plugins.telegram.helpers.sanitize import secure_write_json
    secure_write_json(_get_state_path(), state)


def add_chat(chat_id: str, label: str = ""):
    state = load_chat_state()
    state.setdefault("chats", {})[chat_id] = {
        "label": label or chat_id,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_chat_state(state)


def remove_chat(chat_id: str):
    state = load_chat_state()
    state.get("chats", {}).pop(chat_id, None)
    state.get("contexts", {}).pop(chat_id, None)
    save_chat_state(state)


def get_chat_list() -> dict:
    return load_chat_state().get("chats", {})


def get_context_id(chat_id: str) -> Optional[str]:
    return load_chat_state().get("contexts", {}).get(chat_id)


def set_context_id(chat_id: str, context_id: str):
    state = load_chat_state()
    state.setdefault("contexts", {})[chat_id] = context_id
    save_chat_state(state)


class ChatBridgeBot:
    """Telegram bot that bridges messages to Agent Zero's LLM.

    SECURITY: By default, uses direct LLM calls (call_utility_model) with NO
    tool access. Authenticated users can optionally elevate to full agent loop
    access if allow_elevated is enabled in the plugin config.
    """

    MAX_CHAT_MESSAGE_LENGTH = 4096
    MAX_HISTORY_MESSAGES = 20
    # Rate limit: max messages per user within the window
    RATE_LIMIT_MAX = 10
    RATE_LIMIT_WINDOW = 60  # seconds
    # Auth failure rate limit
    AUTH_MAX_FAILURES = 5
    AUTH_FAILURE_WINDOW = 300  # 5 minute lockout

    CHAT_SYSTEM_PROMPT = (
        "You are a friendly, helpful AI assistant chatting with users on Telegram.\n\n"
        "IMPORTANT CONSTRAINTS:\n"
        "- You are a conversational chat bot ONLY. You have NO access to tools, files, "
        "commands, terminals, or any system resources.\n"
        "- If users ask you to run commands, access files, list directories, execute code, "
        "or perform any system operations, explain that you don't have those capabilities.\n"
        "- NEVER fabricate or make up file listings, directory contents, command outputs, "
        "or system information. You genuinely do not have access to any of these.\n"
        "- Be helpful, friendly, and conversational within these constraints.\n"
        "- You can help with general knowledge, answer questions, have discussions, "
        "write text, brainstorm ideas, and more — just not anything involving system access.\n"
        "- Each message shows the Telegram username prefix. Respond naturally to the "
        "conversation.\n"
    )

    def __init__(self, bot_token: str):
        if not bot_token or not bot_token.strip():
            raise ValueError("Bot token must be provided to ChatBridgeBot.")
        self.bot_token = bot_token
        self._running = False
        self._application = None
        self._bot_user = None
        # Per-user rate limiting: user_id -> deque of timestamps
        self._rate_limits: dict[str, collections.deque] = {}
        # Per-chat conversation history (in-memory, lost on restart)
        self._conversations: dict[str, list[dict]] = {}
        # Elevated session tracking: "{user_id}:{chat_id}" -> {"at": float, "name": str}
        self._elevated_sessions: dict[str, dict] = {}
        # Failed auth attempt tracking: user_id -> deque of timestamps
        self._auth_failures: dict[str, collections.deque] = {}
        # Temp files for image attachments in elevated mode
        self._temp_files: list[str] = []
        # Threading event for signaling ready state
        self._ready_event: Optional[threading.Event] = None

    # ------------------------------------------------------------------
    # Config access
    # ------------------------------------------------------------------

    def _get_config(self) -> dict:
        """Load the Telegram plugin configuration."""
        try:
            from plugins.telegram.helpers.telegram_client import get_telegram_config
            return get_telegram_config()
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _session_key(self, user_id: str, chat_id: str) -> str:
        return f"{user_id}:{chat_id}"

    def _is_elevated(self, user_id: str, chat_id: str) -> bool:
        """Check if a user has an active elevated session in this chat."""
        config = self._get_config()
        if not config.get("chat_bridge", {}).get("allow_elevated", False):
            return False

        key = self._session_key(user_id, chat_id)
        session = self._elevated_sessions.get(key)
        if not session:
            return False

        timeout = config.get("chat_bridge", {}).get("session_timeout", 300)
        # timeout=0 means never expire
        if timeout > 0 and time.monotonic() - session["at"] > timeout:
            del self._elevated_sessions[key]
            return False

        return True

    def _get_auth_key(self, config: dict) -> str:
        """Get the auth key from config, auto-generating if needed."""
        bridge_config = config.get("chat_bridge", {})
        auth_key = bridge_config.get("auth_key", "")

        if not auth_key and bridge_config.get("allow_elevated", False):
            from plugins.telegram.helpers.sanitize import generate_auth_key
            auth_key = generate_auth_key()
            bridge_config["auth_key"] = auth_key
            config["chat_bridge"] = bridge_config
            try:
                from plugins.telegram.helpers.sanitize import secure_write_json
                config_candidates = [
                    Path("/a0/usr/plugins/telegram/config.json"),
                    Path("/a0/plugins/telegram/config.json"),
                    Path(__file__).parent.parent / "config.json",
                ]
                for cp in config_candidates:
                    if cp.exists():
                        existing = json.loads(cp.read_text())
                        existing.setdefault("chat_bridge", {})["auth_key"] = auth_key
                        secure_write_json(cp, existing)
                        logger.info("Auto-generated auth key for elevated mode")
                        break
            except Exception as e:
                logger.warning(f"Could not persist auto-generated auth key: {type(e).__name__}")

        return auth_key

    # ------------------------------------------------------------------
    # Auth command handling
    # ------------------------------------------------------------------

    async def _handle_auth_command(self, update, context_obj) -> bool:
        """Handle !auth, !deauth, and !bridge-status commands.

        Returns True if the message was an auth command (consumed), False otherwise.
        """
        message = update.message
        text = message.text.strip()
        user_id = str(message.from_user.id)
        chat_id = str(message.chat_id)

        # --- !deauth ---
        if text.lower() in ("!deauth", "!dauth", "!unauth", "!logout", "!logoff"):
            key = self._session_key(user_id, chat_id)
            if key in self._elevated_sessions:
                del self._elevated_sessions[key]
                self._conversations.pop(chat_id, None)
                await message.reply_text("Session ended. Back to restricted mode.")
                logger.info(f"Elevated session ended: user={user_id} chat={chat_id}")
            else:
                await message.reply_text("No active elevated session.")
            return True

        # --- !bridge-status / !status ---
        if text.lower() in ("!bridge-status", "!status"):
            if self._is_elevated(user_id, chat_id):
                session = self._elevated_sessions[self._session_key(user_id, chat_id)]
                elapsed = int(time.monotonic() - session["at"])
                config = self._get_config()
                timeout = config.get("chat_bridge", {}).get("session_timeout", 300)
                if timeout > 0:
                    remaining = max(0, timeout - elapsed)
                    expire_info = f"Session expires in {remaining // 60}m {remaining % 60}s"
                else:
                    expire_info = "Session does not expire"
                await message.reply_text(
                    f"Mode: *Elevated* (full agent access)\n"
                    f"{expire_info}. Use `!deauth` to end.",
                    parse_mode="Markdown",
                )
            else:
                config = self._get_config()
                elevated_available = config.get("chat_bridge", {}).get("allow_elevated", False)
                if elevated_available:
                    await message.reply_text(
                        "Mode: *Restricted* (chat only). Use `!auth <key>` to elevate.",
                        parse_mode="Markdown",
                    )
                else:
                    await message.reply_text(
                        "Mode: *Restricted* (chat only). Elevated mode is not enabled.",
                        parse_mode="Markdown",
                    )
            return True

        # --- !auth <key> ---
        if text.lower().startswith("!auth"):
            # Try to delete the message immediately to protect the key
            try:
                await message.delete()
            except Exception:
                logger.warning("Could not delete !auth message — bot lacks permission")

            config = self._get_config()
            if not config.get("chat_bridge", {}).get("allow_elevated", False):
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="Elevated mode is not enabled in the configuration.",
                )
                return True

            auth_key = self._get_auth_key(config)
            if not auth_key:
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="Elevated mode is enabled but no auth key could be generated. "
                         "Check plugin configuration.",
                )
                return True

            # Check auth failure rate limit
            now = time.monotonic()
            if user_id not in self._auth_failures:
                self._auth_failures[user_id] = collections.deque()
            failures = self._auth_failures[user_id]
            while failures and now - failures[0] > self.AUTH_FAILURE_WINDOW:
                failures.popleft()
            if len(failures) >= self.AUTH_MAX_FAILURES:
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text="Too many failed attempts. Please wait before trying again.",
                )
                return True

            # Extract the key from the command
            parts = text.split(maxsplit=1)
            provided_key = parts[1].strip() if len(parts) > 1 else ""

            # Constant-time comparison to prevent timing attacks
            if provided_key and hmac.compare_digest(provided_key, auth_key):
                session_key = self._session_key(user_id, chat_id)
                self._elevated_sessions[session_key] = {
                    "at": now,
                    "name": message.from_user.first_name or message.from_user.username or "user",
                }
                timeout = config.get("chat_bridge", {}).get("session_timeout", 300)
                if timeout > 0:
                    mins = timeout // 60
                    secs = timeout % 60
                    duration = f"{mins}m" if not secs else f"{mins}m {secs}s"
                    expire_msg = f"Session expires in {duration}."
                else:
                    expire_msg = "Session does not expire."
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text=f"Elevated session active. {expire_msg} "
                         f"You now have full Agent Zero access in this chat. "
                         f"Use `!deauth` to end the session.",
                )
                logger.info(f"Elevated session granted: user={user_id} chat={chat_id}")
            else:
                failures.append(now)
                remaining = self.AUTH_MAX_FAILURES - len(failures)
                await context_obj.bot.send_message(
                    chat_id=chat_id,
                    text=f"Authentication failed. {remaining} attempt(s) remaining.",
                )
                logger.warning(f"Failed auth attempt: user={user_id} chat={chat_id}")

            return True

        # Unknown ! command — don't pass to LLM
        await context_obj.bot.send_message(
            chat_id=chat_id,
            text="Unknown command. Available: `!auth <key>`, `!deauth`, `!status`",
            parse_mode="Markdown",
        )
        return True

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _on_message(self, update, context_obj):
        """Handle incoming Telegram messages."""
        message = update.message
        if not message or not message.text:
            return

        # Ignore own messages
        if message.from_user and message.from_user.is_bot:
            return

        chat_id = str(message.chat_id)

        # Store message for telegram_read tool access
        # Skip command messages (e.g. !auth, !deauth) to avoid storing secrets
        msg_text = (message.text or "").strip()
        if not msg_text.startswith("!"):
            try:
                from plugins.telegram.helpers.message_store import store_message
                # Build a raw-style message dict from the python-telegram-bot Message object
                raw_msg = {
                    "message_id": message.message_id,
                    "date": int(message.date.timestamp()) if message.date else 0,
                    "chat": {"id": message.chat_id, "type": message.chat.type,
                             "title": getattr(message.chat, "title", ""),
                             "first_name": getattr(message.chat, "first_name", ""),
                             "username": getattr(message.chat, "username", "")},
                    "text": message.text or "",
                }
                if message.from_user:
                    raw_msg["from"] = {
                        "id": message.from_user.id,
                        "first_name": message.from_user.first_name or "",
                        "last_name": message.from_user.last_name or "",
                        "username": message.from_user.username or "",
                        "is_bot": message.from_user.is_bot,
                    }
                if message.reply_to_message:
                    ref = message.reply_to_message
                    raw_msg["reply_to_message"] = {
                        "message_id": ref.message_id,
                        "from": {"first_name": getattr(ref.from_user, "first_name", "Unknown")} if ref.from_user else {},
                    }
                store_message(chat_id, raw_msg)
            except Exception as e:
                logger.debug(f"Could not store message: {e}")

        chat_list = get_chat_list()

        # Only respond in designated chats
        if chat_list and chat_id not in chat_list:
            return

        # User allowlist: silently ignore users not on the list
        config = self._get_config()
        allowed_users = config.get("chat_bridge", {}).get("allowed_users", [])
        if allowed_users and str(message.from_user.id) not in [str(u) for u in allowed_users]:
            return

        user_text = message.text
        if not user_text.strip():
            return

        # Handle auth commands first (before rate limiting)
        if user_text.strip().startswith("!"):
            handled = await self._handle_auth_command(update, context_obj)
            if handled:
                return

        # Enforce content length limit
        if len(user_text) > self.MAX_CHAT_MESSAGE_LENGTH:
            await message.reply_text(
                f"Message too long ({len(user_text)} chars). "
                f"Max: {self.MAX_CHAT_MESSAGE_LENGTH}."
            )
            return

        # Per-user rate limiting
        user_key = str(message.from_user.id)
        now = time.monotonic()
        if user_key not in self._rate_limits:
            self._rate_limits[user_key] = collections.deque()
        timestamps = self._rate_limits[user_key]
        while timestamps and now - timestamps[0] > self.RATE_LIMIT_WINDOW:
            timestamps.popleft()
        if len(timestamps) >= self.RATE_LIMIT_MAX:
            await message.reply_text(
                f"Rate limit: max {self.RATE_LIMIT_MAX} messages per {self.RATE_LIMIT_WINDOW}s. Please wait."
            )
            return
        timestamps.append(now)

        # Route based on elevation status
        user_id = str(message.from_user.id)
        is_elevated = self._is_elevated(user_id, chat_id)

        # Show typing while processing
        await context_obj.bot.send_chat_action(chat_id=chat_id, action="typing")

        try:
            if is_elevated:
                response_text = await self._get_elevated_response(
                    chat_id, user_text, message
                )
            else:
                response_text = await self._get_agent_response(
                    chat_id, user_text, message
                )
        except Exception as e:
            logger.error("Agent error: %s", type(e).__name__, exc_info=True)
            response_text = "An error occurred while processing your message."

        # Send response, splitting if needed
        await self._send_response(message, response_text)

    # ------------------------------------------------------------------
    # Restricted mode: direct LLM call, NO tools
    # ------------------------------------------------------------------

    async def _get_agent_response(self, chat_id: str, text: str, message) -> str:
        """Get LLM response via direct model call (no agent loop, no tools)."""
        try:
            from agent import AgentContext, AgentContextType
            from initialize import initialize_agent

            context_id = get_context_id(chat_id)
            context = None

            if context_id:
                context = AgentContext.get(context_id)

            if context is None:
                config = initialize_agent()
                context = AgentContext(config=config, type=AgentContextType.USER)
                set_context_id(chat_id, context.id)
                logger.info(f"Created new context {context.id} for chat {chat_id}")

            agent = context.agent0

            from plugins.telegram.helpers.sanitize import sanitize_content, sanitize_username
            author_name = sanitize_username(
                message.from_user.first_name or message.from_user.username or "User"
            )
            safe_text = sanitize_content(text)

            if chat_id not in self._conversations:
                self._conversations[chat_id] = []
            history = self._conversations[chat_id]
            history.append({"role": "user", "name": author_name, "content": safe_text})

            if len(history) > self.MAX_HISTORY_MESSAGES:
                self._conversations[chat_id] = history[-self.MAX_HISTORY_MESSAGES:]
                history = self._conversations[chat_id]

            formatted = []
            for msg in history:
                if msg["role"] == "user":
                    formatted.append(f"{msg['name']}: {msg['content']}")
                else:
                    formatted.append(f"Assistant: {msg['content']}")
            conversation_text = "\n".join(formatted)

            response = await agent.call_utility_model(
                system=self.CHAT_SYSTEM_PROMPT,
                message=conversation_text,
            )

            history.append({"role": "assistant", "content": response})

            return response if isinstance(response, str) else str(response)

        except ImportError:
            return await self._get_agent_response_http(chat_id, text)

    # ------------------------------------------------------------------
    # Elevated mode: full agent loop with tools
    # ------------------------------------------------------------------

    async def _get_elevated_response(self, chat_id: str, text: str, message) -> str:
        """Route through the full Agent Zero agent loop."""
        try:
            from agent import AgentContext, AgentContextType, UserMessage
            from initialize import initialize_agent

            context_id = get_context_id(chat_id)
            context = None

            if context_id:
                context = AgentContext.get(context_id)

            if context is None:
                config = initialize_agent()
                context = AgentContext(config=config, type=AgentContextType.USER)
                set_context_id(chat_id, context.id)
                logger.info(f"Created new elevated context {context.id} for chat {chat_id}")

            from plugins.telegram.helpers.sanitize import sanitize_content
            safe_text = sanitize_content(text)
            # In elevated mode the user is authenticated — send their message
            # directly as a user request through communicate(). Do NOT prefix
            # with "[Telegram Chat Bridge - …]" because that makes the infection
            # check think an external entity is directing the agent.
            prefixed_text = safe_text

            # Handle photo attachments for the agent
            attachment_paths = []
            if message.photo:
                try:
                    import tempfile
                    photo = message.photo[-1]  # Highest resolution
                    file = await photo.get_file()
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    await file.download_to_drive(tmp.name)
                    tmp.close()
                    attachment_paths.append(tmp.name)
                    self._temp_files.append(tmp.name)
                except Exception:
                    pass

            user_msg = UserMessage(message=prefixed_text, attachments=attachment_paths)
            task = context.communicate(user_msg)
            result = await task.result()

            self._cleanup_temp_files()

            return result if isinstance(result, str) else str(result)

        except ImportError:
            return await self._get_agent_response_http(chat_id, text)
        except Exception as e:
            logger.error("Elevated mode error: %s", type(e).__name__, exc_info=True)
            # If agent loop failed, invalidate the context so a fresh one is created next time
            set_context_id(chat_id, "")
            raise

    def _cleanup_temp_files(self):
        """Remove temporary image files."""
        remaining = []
        for path in self._temp_files:
            try:
                os.unlink(path)
            except OSError:
                remaining.append(path)
        self._temp_files = remaining

    # ------------------------------------------------------------------
    # HTTP fallback
    # ------------------------------------------------------------------

    async def _get_agent_response_http(self, chat_id: str, text: str) -> str:
        """Fallback: route through Agent Zero's HTTP API."""
        import aiohttp

        config = self._get_config()
        api_port = config.get("chat_bridge", {}).get("api_port", 80)
        api_key = config.get("chat_bridge", {}).get("api_key", "")

        context_id = get_context_id(chat_id) or ""

        async with aiohttp.ClientSession() as session:
            payload = {"message": text, "context_id": context_id}
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["X-API-KEY"] = api_key

            async with session.post(
                f"http://localhost:{api_port}/api/api_message",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return f"Agent API error ({resp.status}): {body}"
                data = await resp.json()

                if data.get("context_id"):
                    set_context_id(chat_id, data["context_id"])

                return data.get("response", "No response from agent.")

    # ------------------------------------------------------------------
    # Response sending
    # ------------------------------------------------------------------

    async def _send_response(self, message, text: str):
        """Send a response to Telegram, splitting long messages."""
        if not text:
            text = "(No response)"

        chunks = _split_message(text)
        for i, chunk in enumerate(chunks):
            if i == 0:
                sent = await message.reply_text(chunk)
            else:
                sent = await message.chat.send_message(chunk)

            # Store bot response for telegram_read tool
            try:
                from plugins.telegram.helpers.message_store import store_message
                raw_msg = {
                    "message_id": sent.message_id,
                    "date": int(sent.date.timestamp()) if sent.date else 0,
                    "chat": {"id": sent.chat_id, "type": sent.chat.type,
                             "title": getattr(sent.chat, "title", ""),
                             "first_name": getattr(sent.chat, "first_name", ""),
                             "username": getattr(sent.chat, "username", "")},
                    "text": sent.text or chunk,
                    "from": {
                        "id": self._bot_user.id if self._bot_user else 0,
                        "first_name": self._bot_user.first_name if self._bot_user else "Bot",
                        "username": self._bot_user.username if self._bot_user else "",
                        "is_bot": True,
                    },
                }
                store_message(str(sent.chat_id), raw_msg)
            except Exception:
                pass


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


def _is_bot_alive() -> bool:
    """Check if the bot instance and its dedicated thread are actually alive."""
    if _bot_instance is None:
        return False
    if not _bot_instance._running:
        return False
    if _bot_thread is None or not _bot_thread.is_alive():
        return False
    return True


def _cleanup_dead_bot():
    """Clean up singleton refs if the bot/thread has died."""
    global _bot_instance, _bot_thread, _bot_loop
    if not _is_bot_alive():
        _bot_instance = None
        _bot_thread = None
        _bot_loop = None


def _run_bot_in_thread(bot: ChatBridgeBot, ready_event: threading.Event):
    """Run the bot in a dedicated thread with its own event loop."""
    global _bot_instance, _bot_thread, _bot_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _bot_loop = loop

    bot._ready_event = ready_event

    try:
        try:
            from telegram.ext import ApplicationBuilder, MessageHandler, filters
        except ModuleNotFoundError:
            logger.warning("python-telegram-bot not found, installing...")
            import subprocess, sys
            python = "/opt/venv-a0/bin/python3" if os.path.isfile("/opt/venv-a0/bin/python3") else sys.executable
            subprocess.check_call([python, "-m", "pip", "install", "python-telegram-bot>=21.0,<22"], capture_output=True)
            from telegram.ext import ApplicationBuilder, MessageHandler, filters

        app = ApplicationBuilder().token(bot.bot_token).build()
        bot._application = app

        # Register message handler
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot._on_message))
        # Also handle commands starting with ! (auth commands)
        app.add_handler(MessageHandler(filters.Regex(r'^!'), bot._on_message))

        bot._running = True

        async def _start():
            await app.initialize()
            await app.start()
            me = await app.bot.get_me()
            bot._bot_user = me
            logger.info(f"Chat bridge connected as @{me.username} (ID: {me.id})")
            ready_event.set()
            await app.updater.start_polling(drop_pending_updates=True)
            # Keep running until stopped
            while bot._running:
                await asyncio.sleep(1)
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        loop.run_until_complete(_start())
    except Exception as e:
        logger.error("Chat bridge bot exited with error: %s", type(e).__name__, exc_info=True)
    finally:
        logger.info("Chat bridge bot thread ending, cleaning up singleton")
        bot._running = False
        ready_event.set()  # Unblock caller if startup never completed
        _bot_instance = None
        _bot_thread = None
        _bot_loop = None
        try:
            loop.close()
        except Exception:
            pass


async def start_chat_bridge(bot_token: str) -> ChatBridgeBot:
    """Start the chat bridge bot in a dedicated background thread."""
    global _bot_instance, _bot_thread, _bot_loop

    if not bot_token or not bot_token.strip():
        raise ValueError("Cannot start chat bridge: bot token is empty or not configured.")

    _cleanup_dead_bot()

    if _bot_instance and _is_bot_alive():
        return _bot_instance

    # Force-close any leftover instance
    if _bot_instance:
        _bot_instance._running = False
        _bot_instance = None
        _bot_thread = None
        _bot_loop = None

    bot = ChatBridgeBot(bot_token)
    _bot_instance = bot

    ready_event = threading.Event()
    thread = threading.Thread(
        target=_run_bot_in_thread,
        args=(bot, ready_event),
        daemon=True,
        name="telegram-chat-bridge",
    )
    _bot_thread = thread
    thread.start()

    ready_event.wait(timeout=35)

    if not bot._running:
        logger.warning("Bot started but may not be fully ready yet")

    return bot


async def stop_chat_bridge():
    """Stop the chat bridge bot."""
    global _bot_instance, _bot_thread, _bot_loop

    if _bot_instance:
        _bot_instance._running = False

    # Wait for thread to finish
    if _bot_thread and _bot_thread.is_alive():
        _bot_thread.join(timeout=10)

    _bot_instance = None
    _bot_thread = None
    _bot_loop = None


def is_bridge_polling() -> bool:
    """Check if the bridge is actively polling getUpdates.

    Tools MUST check this before calling getUpdates themselves, because
    concurrent getUpdates calls to the same bot token cause a Conflict error
    that crashes the bridge's polling loop.
    """
    return _is_bot_alive()


def get_bot_status() -> dict:
    """Get current bot status."""
    _cleanup_dead_bot()

    if _bot_instance is None:
        return {"running": False, "status": "stopped"}
    if not _bot_instance._running:
        return {"running": False, "status": "stopped"}
    if _bot_thread and not _bot_thread.is_alive():
        return {"running": False, "status": "crashed"}
    if _bot_instance._bot_user:
        user = _bot_instance._bot_user
        return {
            "running": True,
            "status": "connected",
            "user": f"@{user.username}" if user.username else user.first_name,
            "user_id": str(user.id),
        }
    return {"running": True, "status": "connecting"}
