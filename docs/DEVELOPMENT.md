# Telegram Integration Plugin — Development Guide

## Project Structure

```
a0-telegram/
├── plugin.yaml              # Plugin manifest
├── default_config.yaml      # Default settings
├── initialize.py            # Dependency installer (aiohttp, pyyaml, python-telegram-bot)
├── hooks.py                 # Plugin lifecycle hooks (install/uninstall)
├── install.sh               # Deployment script
├── .gitignore
├── helpers/
│   ├── __init__.py
│   ├── telegram_client.py   # REST API client wrapper (aiohttp)
│   ├── telegram_bridge.py   # Chat bridge bot (python-telegram-bot polling)
│   ├── sanitize.py          # Prompt injection defense, input validation
│   ├── message_store.py     # Persistent message storage (JSON)
│   └── poll_state.py        # Background polling state
├── tools/
│   ├── telegram_read.py     # Read messages, list chats, get chat info
│   ├── telegram_send.py     # Send messages, photos, reactions, forward
│   ├── telegram_members.py  # List group administrators
│   ├── telegram_summarize.py # LLM-powered conversation summaries
│   ├── telegram_manage.py   # Pin/unpin, set title/description
│   └── telegram_chat.py     # Chat bridge control
├── prompts/
│   ├── agent.system.tool.telegram_read.md
│   ├── agent.system.tool.telegram_send.md
│   ├── agent.system.tool.telegram_members.md
│   ├── agent.system.tool.telegram_summarize.md
│   ├── agent.system.tool.telegram_manage.md
│   └── agent.system.tool.telegram_chat.md
├── skills/
│   ├── telegram-research/SKILL.md
│   ├── telegram-communicate/SKILL.md
│   └── telegram-chat/SKILL.md
├── api/
│   ├── telegram_test.py         # Connection test endpoint
│   ├── telegram_config_api.py   # Custom actions (auth key generation)
│   └── telegram_bridge_api.py   # Chat bridge start/stop/status
├── webui/
│   ├── main.html            # Dashboard (status, bridge control)
│   └── config.html          # Settings (Alpine.js x-model bindings)
├── extensions/
│   └── python/agent_init/_10_telegram_chat.py  # Auto-start bridge
├── tests/
│   ├── regression_test.sh
│   ├── HUMAN_TEST_PLAN.md
│   ├── HUMAN_TEST_RESULTS.md
│   └── SECURITY_ASSESSMENT_RESULTS.md
└── docs/
    ├── README.md
    ├── QUICKSTART.md
    ├── SETUP.md
    └── DEVELOPMENT.md
```

## Development Setup

1. Start the dev container:
   ```bash
   docker start agent-zero-dev
   ```

2. Install the plugin:
   ```bash
   docker cp a0-telegram/. agent-zero-dev:/a0/usr/plugins/telegram/
   docker exec agent-zero-dev bash /a0/usr/plugins/telegram/install.sh
   ```

3. For iterative development (push changes without full reinstall):
   ```bash
   docker cp a0-telegram/. agent-zero-dev:/a0/usr/plugins/telegram/
   docker exec agent-zero-dev supervisorctl restart run_ui
   ```

4. Run tests:
   ```bash
   bash tests/regression_test.sh agent-zero-dev 50083
   ```

## Adding a New Tool

1. Create `tools/telegram_<action>.py` with a Tool subclass
2. Create `prompts/agent.system.tool.telegram_<action>.md` with JSON examples
3. Add API method to `helpers/telegram_client.py` if needed
4. Add import test and prompt test to `tests/regression_test.sh`
5. Update `docs/README.md` tools table

## Code Patterns

### Tool Implementation

```python
from helpers.tool import Tool, Response
from plugins.telegram.helpers.telegram_client import TelegramClient, get_telegram_config
from plugins.telegram.helpers.sanitize import require_auth

class TelegramAction(Tool):
    async def execute(self, **kwargs) -> Response:
        config = get_telegram_config(self.agent)
        try:
            require_auth(config)
        except ValueError as e:
            return Response(message=f"Auth error: {e}", break_loop=False)

        client = TelegramClient.from_config(agent=self.agent)
        try:
            # ... use client ...
            result = await client.get_me()
        finally:
            await client.close()
        return Response(message=str(result), break_loop=False)
```

### Config Access

```python
from plugins.telegram.helpers.telegram_client import get_telegram_config

# In a tool:
config = get_telegram_config(self.agent)
token = config.get("bot", {}).get("token", "")
bridge_config = config.get("chat_bridge", {})
```

### API Handler

```python
from helpers.api import ApiHandler, Request, Response

class TelegramMyApi(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return True  # MANDATORY — never return False

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = input.get("action", "")
        if action == "my_action":
            return {"ok": True}
        return {"error": "Unknown action"}
```

### Sanitization

```python
from plugins.telegram.helpers.sanitize import (
    sanitize_content,
    sanitize_username,
    require_auth,
    generate_auth_key,
)

# Sanitize user input before passing to LLM
clean_text = sanitize_content(raw_text, config)

# Sanitize display names
safe_name = sanitize_username(raw_name)
```

### WebUI — config.html (Alpine.js Standard)

Config pages use A0's built-in plugin settings framework with Alpine.js `x-model` bindings. The `config` variable is provided by the parent scope — no custom load/save logic needed.

```html
<html>
<head><title>Plugin Name</title></head>
<body>
    <div x-data x-init="if (!config.section) config.section = {};">
        <template x-if="config">
            <div>
                <div class="section-title">Section Name</div>
                <div class="field">
                    <div class="field-label">
                        <div class="field-title">Field Title</div>
                        <div class="field-description">Help text.</div>
                    </div>
                    <div class="field-control">
                        <input type="text" x-model="config.section.field" />
                    </div>
                </div>
            </div>
        </template>
    </div>
</body>
</html>
```

### WebUI — main.html (Dashboard)

Dashboard pages use vanilla JS with `data-tgm=` prefixed attributes and `window._tgMain` namespace.

```javascript
// Lazy fetchApi — resolves at call time, not at script init
function fetchApi(url, opts) { return (globalThis.fetchApi || fetch)(url, opts); }

// Use inline onclick handlers (not addEventListener) to survive component reloads
// <button onclick="window._tgMain.myAction()">

window._tgMain = { myAction: myAction };
```

## Code Style

- Follow existing patterns from other published plugins (Discord, Signal, Bluesky)
- Use `async/await` for all I/O operations
- Always close client connections in `try/finally`
- Return `Response(message=..., break_loop=False)` from tools
- Use `logging.getLogger()` — never bare `print()`
- Use `self.set_progress()` for long operations
- Sanitize ALL external content before passing to LLM
- All API handlers must have `requires_csrf() -> True`
- WebUI main.html: use `data-tgm=` attributes, not bare IDs
- WebUI config.html: use Alpine.js `x-model` bindings (standard framework)

## Key Architecture Decisions

### Two Client Libraries

The plugin uses two different approaches for Telegram API access:
- **`telegram_client.py`** — Lightweight REST wrapper using `aiohttp` for tool operations (read, send, manage). Simple, no polling, async-friendly.
- **`telegram_bridge.py`** — Uses `python-telegram-bot` library for the chat bridge. Provides the polling loop, message handlers, and bot lifecycle management needed for real-time operation.

### getUpdates Conflict Resolution

Telegram enforces single-consumer semantics on `getUpdates` — only one caller can poll at a time per bot token. When the bridge is polling, tools fall back to reading from the persistent `message_store.json` instead of calling `getUpdates` directly. The `is_bridge_polling()` guard function coordinates this.

### Elevated Mode and Infection Check

A0's infection_check monitors agent output for suspicious patterns. The chat bridge sends authenticated (elevated) messages as plain text through `context.communicate()` — the same path as WebUI messages — to avoid triggering false positives from prefixed message formats.

## Testing

### Regression Tests
```bash
bash tests/regression_test.sh <container> <port>
```
58+ automated tests covering container health, installation, imports, API endpoints, sanitization, tool loading, prompts, skills, WebUI, framework compatibility, and security.

### Human Verification
Follow `tests/HUMAN_TEST_PLAN.md` for the 76-test manual verification covering all tools, bridge modes, authentication, security, and edge cases.

## Telegram Bot API Reference

- **Official docs:** https://core.telegram.org/bots/api
- **Key methods used:** getMe, getUpdates, sendMessage, sendPhoto, getChat, getChatAdministrators, pinChatMessage, unpinChatMessage, setChatDescription, setChatTitle, forwardMessage, setMessageReaction
- **Rate limits:** 30 messages/second global, 1 message/second per chat, 20 messages/minute per group
