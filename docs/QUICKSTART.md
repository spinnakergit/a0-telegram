# Telegram Integration Plugin — Quick Start

## Prerequisites

- Agent Zero instance (Docker or local)
- Telegram account

## Step 1: Create a Bot with BotFather

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Choose a name (e.g., "My Agent Zero Bot")
4. Choose a username (must end in `bot`, e.g., `my_a0_bot`)
5. Copy the bot token (looks like `1234567890:ABCDefGHIJklmnoPQRSTuvwxyz`)

### Optional: Configure Bot Settings

Send these commands to @BotFather:
- `/setprivacy` — Set to "Disable" if the bot should read all group messages
- `/setjoingroups` — Set to "Enable" to allow adding to groups
- `/setcommands` — Not needed (the plugin uses `!` commands, not `/` commands)

## Step 2: Install the Plugin

**Via Plugin Hub (Recommended):**
1. Open Agent Zero WebUI > Settings > Plugins
2. Find "Telegram Integration" and click **Install**
3. Dependencies install automatically

**Via Script:**
```bash
docker cp a0-telegram/. a0-container:/a0/usr/plugins/telegram/
docker exec a0-container bash /a0/usr/plugins/telegram/install.sh
```

## Step 3: Configure

1. Open Agent Zero WebUI
2. Go to Settings > External Services > Telegram Integration
3. Paste your bot token in the **Bot Token** field
4. Click the **Save** button (outer framework Save)
5. Click **"Open"** to view the dashboard
6. Click **"Test Connection"** — should show green "Connected as @botname"

### Credential Mapping

| What You Need | Where to Get It | Plugin Config Field |
|---|---|---|
| Bot Token | @BotFather after `/newbot` | Settings > **Bot Token** |
| Chat IDs | Ask agent: "List my Telegram chats" | Settings > **Allowed Chat IDs** |
| User IDs | Forward a message to @userinfobot | Chat Bridge > **User Allowlist** |

Or set the environment variable:
```bash
export TELEGRAM_BOT_TOKEN="1234567890:ABCDefGHIJklmnoPQRSTuvwxyz"
```

## Step 4: First Use

Ask the agent:

> "List my Telegram chats"

> "Read the last 20 messages from Telegram chat -1001234567890"

> "Send 'Hello from Agent Zero!' to Telegram chat -1001234567890"

> "Summarize the last 50 messages in Telegram chat -1001234567890"

> "List administrators of Telegram group -1001234567890"

## Step 5: Set Up Chat Bridge (Optional)

The chat bridge turns Telegram into a conversational interface for Agent Zero.

1. Add the bot to a Telegram group, or start a private chat with it
2. Tell the agent: "Add Telegram chat -1001234567890 to the chat bridge"
3. Tell the agent: "Start the Telegram chat bridge"
4. Send a message to the bot — it will respond via Agent Zero's LLM

### Elevated Mode (Optional)

By default, the bridge operates in restricted mode (LLM chat only, no tools). To enable full agent access:

1. Enable "Allow elevated mode" in plugin settings
2. Set a User Allowlist (recommended)
3. Share the Auth Key securely with trusted users
4. Users type `!auth <key>` in Telegram to elevate
5. Sessions expire after the configured timeout (default: 5 minutes)

## Getting Chat IDs

- **Private chats**: Send a message to the bot, then use `telegram_read` with `action: chats`
- **Groups**: Add the bot to the group, send a message, then use `telegram_read` with `action: chats`
- **Via @userinfobot**: Forward a message from the chat to [@userinfobot](https://t.me/userinfobot)
- Group/supergroup IDs are negative numbers (e.g., `-1001234567890`)

## Known Behaviors

- **getUpdates conflict:** When the chat bridge is running (polling), the `telegram_read` and `telegram_summarize` tools cannot use `getUpdates` simultaneously. They automatically fall back to reading from the persistent message store instead. This means recent messages may have a slight delay in appearing for tool queries while the bridge is active.

- **Bot privacy in groups:** By default, Telegram bots can only see messages that mention them or are replies to their messages. To read all group messages, set privacy to "Disable" via @BotFather (`/setprivacy`). This must be done **before** adding the bot to the group.

- **Long message splitting:** Messages exceeding Telegram's 4096-character limit are automatically split into multiple messages. The agent handles this transparently.

- **Infection check with elevated mode:** A0's safety system (infection_check) monitors agent output. In elevated mode, certain message patterns may trigger the safety check. The plugin mitigates this by sending authenticated messages as plain text through `context.communicate()` — the same path as WebUI messages.

- **Auto-start and preload:** The chat bridge auto-start extension (`_10_telegram_chat.py`) uses a deduplication flag because A0 creates multiple agent contexts during startup (~28 during preload). The bridge starts exactly once.

- **Bridge sessions are in-memory:** Elevated sessions, conversation history, and bridge state are stored in memory only. A `run_ui` restart or bridge restart clears all sessions.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Plugin not visible in settings | Check `.toggle-1` exists: `ls /a0/usr/plugins/telegram/.toggle-1` |
| Import errors on dashboard | Run `initialize.py`: `/opt/venv-a0/bin/python /a0/usr/plugins/telegram/initialize.py` |
| "No bot token configured" | Enter token in settings and click the outer Save button |
| "Unauthorized (401)" on Test | Token is invalid — regenerate via @BotFather |
| Test shows "API unavailable" | Ensure `run_ui` is running: `supervisorctl status run_ui` |
| Bridge says "Stopped" after Start | Verify `python-telegram-bot` is installed: `/opt/venv-a0/bin/python -c "import telegram"` |
| "Conflict: terminated by other getUpdates" | Only one bridge can poll per token — stop duplicate instances or other bots using the same token |
| Bot doesn't respond in group | Set privacy to Disable via @BotFather (`/setprivacy`) — must be done before adding bot to group |
| "An error occurred while processing your message" | Check LLM is configured in Agent Zero settings (Settings > LLM) |
| Bridge starts but no responses | Verify the chat is added to the bridge: ask agent "List Telegram bridge chats" |
| Config not saving | Use the outer framework Save button at the top of the settings panel |
