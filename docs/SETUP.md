# Telegram Integration Plugin — Setup Guide

## Requirements

- Agent Zero v2026-03-13 or later
- Docker or local Python 3.10+
- Telegram account

## Dependencies

Installed automatically by `initialize.py`:
- `aiohttp` — Async HTTP client for Bot API calls
- `pyyaml` — YAML configuration parsing
- `python-telegram-bot` — Official Telegram bot library (used by chat bridge)

## Installation

### Option A: Plugin Hub (Recommended)

1. Open Agent Zero WebUI
2. Go to Settings > Plugins
3. Find "Telegram Integration" and click **Install**
4. Dependencies install automatically via `hooks.py` → `initialize.py`
5. Restart Agent Zero

### Option B: Install Script

```bash
# Copy plugin to container and run install
docker cp a0-telegram/. a0-container:/a0/usr/plugins/telegram/
docker exec a0-container bash /a0/usr/plugins/telegram/install.sh
```

### Option C: Manual Installation

```bash
# Copy files
docker cp a0-telegram/. a0-container:/a0/usr/plugins/telegram/

# Create symlink
docker exec a0-container ln -sf /a0/usr/plugins/telegram /a0/plugins/telegram

# Install dependencies
docker exec a0-container /opt/venv-a0/bin/python /a0/usr/plugins/telegram/initialize.py

# Enable the plugin
docker exec a0-container touch /a0/usr/plugins/telegram/.toggle-1

# Restart
docker exec a0-container supervisorctl restart run_ui
```

## Telegram Bot Setup

### 1. Create a Bot with @BotFather

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Choose a display name (e.g., "My Agent Zero Bot")
4. Choose a username — must end in `bot` (e.g., `my_a0_bot`)
5. Copy the bot token (format: `1234567890:ABCDefGHIJklmnoPQRSTuvwxyz`)

> **Important:** The bot token is a secret. Do not share it publicly. If compromised, regenerate it via @BotFather with `/revoke`.

### 2. Configure Bot Privacy (Optional)

Send these commands to @BotFather:
- `/setprivacy` → Set to **Disable** if the bot should read all group messages (required for `telegram_read` in groups)
- `/setjoingroups` → Set to **Enable** to allow adding the bot to groups
- `/setcommands` → Not needed (the plugin uses `!` commands, not `/` commands)

### 3. Get Chat IDs

Chat IDs are required for sending messages, reading history, and setting up the chat bridge.

- **Private chats:** Start a private chat with the bot, send a message, then ask the agent: "List my Telegram chats"
- **Groups:** Add the bot to the group, send a message, then ask: "List my Telegram chats"
- **Via @userinfobot:** Forward a message from the chat to [@userinfobot](https://t.me/userinfobot)
- Group/supergroup IDs are negative numbers (e.g., `-1001234567890`)
- User IDs are positive numbers (e.g., `123456789`)

## Credential Mapping Reference

| What You Need | Source | Plugin Config Field |
|---|---|---|
| Bot Token | @BotFather after `/newbot` | Settings > **Bot Token** |
| Chat IDs | `telegram_read` with `action: chats` or @userinfobot | Settings > **Allowed Chat IDs** |
| User IDs | @userinfobot (forward a user's message) | Settings > Chat Bridge > **User Allowlist** |
| Auth Key | Auto-generated when elevated mode enabled | Settings > Elevated Mode > **Auth Key** |

## Verifying Installation

1. Open Agent Zero WebUI
2. Go to Settings > External Services
3. Confirm "Telegram Integration" appears in the plugin list
4. Click the plugin
5. Enter your bot token and click the outer **Save** button
6. Click **"Open"** to view the dashboard
7. Click **"Test Connection"**
8. Expected: green "Connected as @botname" badge

## How Authentication Works

1. Bot token is stored in `config.json` (0600 permissions) inside the plugin directory
2. All API calls use the token via `https://api.telegram.org/bot<TOKEN>/method`
3. The token authenticates the bot to Telegram's servers
4. Token can also be set via `TELEGRAM_BOT_TOKEN` environment variable (overrides config)

### Chat Bridge Authentication

The chat bridge has a separate two-tier authentication system:

1. **User Allowlist** — Only listed Telegram user IDs can interact with the bot (empty = allow all)
2. **Elevated Mode Auth Key** — Users send `!auth <key>` to unlock full agent access
   - Key is auto-generated (258-bit entropy) or can be set manually
   - Comparison uses `hmac.compare_digest` (constant-time, timing-attack resistant)
   - Brute-force protection: 5 failed attempts per 5-minute window

## Rate Limits

The Telegram Bot API enforces these limits:

| Limit | Value |
|-------|-------|
| Messages per second (global) | 30 |
| Messages per second (per chat) | 1 |
| Messages per minute (per group) | 20 |
| Bulk messages per second | 30 (across different chats) |

The plugin does not implement client-side rate limiting — Telegram returns HTTP 429 if exceeded, and the plugin reports the error.

The chat bridge enforces its own limits:
- **Message rate limit:** 10 messages per 60-second window per user
- **Auth failure rate limit:** 5 failed attempts per 5-minute window per user

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Plugin not visible | Check `.toggle-1` exists: `ls /a0/usr/plugins/telegram/.toggle-1` |
| Import errors | Run `initialize.py` again: `/opt/venv-a0/bin/python /a0/usr/plugins/telegram/initialize.py` |
| "No bot token configured" | Enter token in plugin settings and click Save |
| "Unauthorized (401)" | Token is invalid — regenerate via @BotFather `/revoke` then `/newbot` or `/token` |
| Test shows "API unavailable" | Ensure `run_ui` is running: `supervisorctl status run_ui` |
| Bridge says "Stopped" after Start | Check `python-telegram-bot` installed: `/opt/venv-a0/bin/python -c "import telegram"` |
| Bridge "Conflict: terminated by other getUpdates" | Only one bridge instance can poll per bot token — stop duplicate instances |
| Bot doesn't respond in group | Set privacy to Disable via @BotFather (`/setprivacy`) |
| "Infection check terminated" | See Known Behaviors in [QUICKSTART.md](QUICKSTART.md) |
| Config not saving | Use the outer framework Save button, not a custom button |
