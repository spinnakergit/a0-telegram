# Telegram Integration Plugin for Agent Zero

Send, receive, and manage messages via Telegram Bot API with real-time chat bridge support.

## Features

- **Read messages** from chats, groups, and channels
- **Send messages** with text, photos, reactions, replies, and forwarding
- **List members** (administrators) of groups and supergroups
- **Summarize conversations** using LLM with auto-save to memory
- **Manage chats** — pin/unpin messages, set title/description
- **Chat bridge** — real-time Telegram-to-Agent Zero LLM conversation
- **Elevated mode** — authenticated users can access full Agent Zero tools from Telegram

## Quick Start

1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram
2. Install the plugin:
   ```bash
   ./install.sh
   ```
3. Configure the bot token in WebUI (Settings > External Services > Telegram Integration)
4. Restart Agent Zero
5. Ask the agent: "List my Telegram chats"

## Tools

| Tool | Description |
|------|-------------|
| `telegram_read` | Read messages, list chats, get chat info |
| `telegram_send` | Send messages, photos, reactions, forward |
| `telegram_members` | List group administrators |
| `telegram_summarize` | Summarize chat conversations with LLM |
| `telegram_manage` | Pin/unpin messages, set title/description |
| `telegram_chat` | Chat bridge control (start/stop/status) |

## Chat Bridge

The chat bridge turns Telegram into a chat interface for Agent Zero:

1. Add the bot to a group or start a private chat
2. Tell the agent: "Add Telegram chat -1001234567890 to the chat bridge"
3. Tell the agent: "Start the Telegram chat bridge"

## Security

### Two-Mode Architecture

The chat bridge operates in two distinct security modes:

**Restricted Mode** (default)
- All Telegram messages are routed through `call_utility_model()` — a direct LLM call with **no tools, no code execution, no file access**.
- The LLM cannot perform any system operations, even if the user asks.
- This is the default for all users, including those on the allowlist.

**Elevated Mode** (opt-in, requires configuration + runtime authentication)
- Messages are routed through the full Agent Zero agent loop via `context.communicate()`, giving access to all tools the agent has.
- Requires **three conditions**: `allow_elevated: true` in config, user on the allowlist, and runtime authentication via `!auth`.

### Authentication System

| Command | Description |
|---------|-------------|
| `!auth <key>` | Authenticate for elevated mode. The message is automatically deleted to protect the key. |
| `!deauth` | End the elevated session immediately, returning to restricted mode. Aliases: `!dauth`, `!unauth`, `!logout`, `!logoff` |
| `!status` | Show current mode (restricted/elevated) and session expiry countdown. Alias: `!bridge-status` |

- The **auth key** is generated automatically when elevated mode is enabled, or can be set manually in config. It is displayed in the WebUI settings panel.
- Authentication uses **constant-time comparison** (`hmac.compare_digest`) to prevent timing attacks.
- **Brute-force protection**: After 5 failed attempts within 5 minutes, the user is locked out until the window expires.

### Session Management

- Elevated sessions expire after a configurable timeout (default: **5 minutes**). Set `session_timeout: 0` to disable expiry.
- Sessions are **per-user, per-chat** — elevating in one chat does not grant access in another.
- Sessions are stored **in memory only** — a bridge restart or `run_ui` restart ends all sessions.
- On `!deauth`, conversation history for the chat is also cleared.

### User Allowlist

The `allowed_users` list in config restricts who can interact with the bot at all. Messages from users not on the list are silently ignored (no response, no error). When the list is empty, all users are allowed.

### Input Sanitization

All incoming messages pass through `sanitize_content()` which strips:
- Prompt injection patterns (system prompt overrides, role-play attempts)
- Markdown/HTML injection
- Excessively long messages (capped at 4096 characters)

Usernames are also sanitized to prevent display-name-based injection.

### Rate Limiting

- **Message rate limit**: 10 messages per 60-second window per user.
- **Auth failure rate limit**: 5 failed attempts per 5-minute window per user.
- Exceeding either limit returns a brief error message; the request is not processed.

### Recommendations

1. **Always use a User Allowlist** — restrict who can interact with the bot
2. **Keep session timeouts short** — default 5 minutes is a good starting point
3. **Use private chats or private groups** — don't add the bot to public groups
4. **Rotate auth keys regularly** — generate new keys in WebUI settings
5. **Monitor usage** — check bot status and logs via the WebUI dashboard

## Configuration

Set `TELEGRAM_BOT_TOKEN` environment variable, or configure in WebUI settings.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for detailed setup instructions.

## Verification

- **58/58 regression tests passed**
- **76/76 human verification tests passed** (2026-03-11)
- **Security assessment completed** (Stage 3a — all Critical/High findings remediated)
- Results: [tests/HUMAN_TEST_RESULTS.md](tests/HUMAN_TEST_RESULTS.md)
- Security: [tests/SECURITY_ASSESSMENT_RESULTS.md](tests/SECURITY_ASSESSMENT_RESULTS.md)

## Documentation

- [Quick Start Guide](docs/QUICKSTART.md)
- [Setup Guide](docs/SETUP.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Full Documentation](docs/README.md)

## Testing

```bash
bash tests/regression_test.sh [container_name] [port]
```

58+ automated tests covering container health, installation, imports, API endpoints,
sanitization, tool imports, prompts, skills, WebUI, framework compatibility, and security.

## License

MIT — see [LICENSE](LICENSE)
