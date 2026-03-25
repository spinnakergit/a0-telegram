# Telegram Integration Plugin Documentation

## Overview

Send, receive, and manage messages via Telegram Bot API with real-time chat bridge support.

## Contents

- [Quick Start](QUICKSTART.md) — Installation and first-use guide
- [Setup](SETUP.md) — Detailed setup, credentials, and troubleshooting
- [Development](DEVELOPMENT.md) — Contributing and development setup

## Architecture

```
a0-telegram/
├── plugin.yaml              # Plugin manifest
├── default_config.yaml      # Default settings
├── initialize.py            # Dependency installer (aiohttp, pyyaml, python-telegram-bot)
├── install.sh               # Deployment script
├── hooks.py                 # Plugin lifecycle hooks (install/uninstall)
├── .gitignore
├── helpers/
│   ├── telegram_client.py   # REST API client wrapper (aiohttp)
│   ├── telegram_bridge.py   # Chat bridge bot (python-telegram-bot polling)
│   ├── sanitize.py          # Prompt injection defense, input validation
│   ├── message_store.py     # Persistent message storage
│   └── poll_state.py        # Background polling state
├── tools/                   # 6 tools
├── prompts/                 # 6 prompt files
├── skills/                  # 3 skills
├── api/                     # 3 API endpoints
├── webui/                   # Dashboard + Settings
├── extensions/              # Auto-start chat bridge hook
├── tests/                   # Regression suite + Human verification
└── docs/                    # Documentation
```

### Data Flow

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Agent Zero  │────>│  telegram_client │────>│  Telegram Bot   │
│  (tools)     │<────│  (REST wrapper)  │<────│  API Server     │
└─────────────┘     └─────────────────┘     └─────────────────┘
                           │
                    ┌──────┴──────┐
                    │             │
              ┌─────┴─────┐ ┌────┴─────┐
              │  Tools (6) │ │  APIs (3) │
              │ read/send/ │ │ test/     │
              │ members/   │ │ config/   │
              │ summarize/ │ │ bridge    │
              │ manage/    │ └──────────┘
              │ chat       │
              └────────────┘

Chat Bridge:
┌──────────┐     ┌──────────────────┐     ┌───────────────┐
│ Telegram │────>│ telegram_bridge   │────>│ Agent Zero    │
│ Users    │<────│ (polling bot)     │<────│ LLM / Agent   │
└──────────┘     └──────────────────┘     └───────────────┘
                  │ Restricted: call_utility_model (no tools)
                  │ Elevated:   context.communicate (full agent)
```

### Security Layers

1. **Sanitization** — All external content normalized (NFKC) and checked for injection patterns
2. **CSRF protection** — All API endpoints require CSRF tokens
3. **Token masking** — Bot tokens masked in API responses
4. **User allowlist** — Chat bridge only responds to authorized users
5. **Rate limiting** — Per-user message rate limits in chat bridge
6. **Auth key** — HMAC constant-time comparison for elevated mode authentication
7. **Session timeout** — Elevated sessions auto-expire (default: 5 minutes)

## Tools (6)

| Tool | Description | Actions |
|------|-------------|---------|
| `telegram_read` | Read messages and chat info | messages, chats, chat_info |
| `telegram_send` | Send content | message, photo, reaction, reply, forward |
| `telegram_members` | Group administration | list, search |
| `telegram_summarize` | LLM-powered summaries | summarize (with auto-save to memory) |
| `telegram_manage` | Chat management | pin, unpin, set_title, set_description |
| `telegram_chat` | Chat bridge control | start, stop, status, add, remove, list |

## Skills (3)

| Skill | Category | Triggers |
|-------|----------|----------|
| `telegram-research` | Read & analyze | "read telegram messages", "summarize chat" |
| `telegram-communicate` | Send & manage | "send telegram message", "manage chat" |
| `telegram-chat` | Bridge operation | "start telegram bridge", "chat via telegram" |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plugins/telegram/telegram_test` | POST | Test bot connection |
| `/api/plugins/telegram/telegram_config_api` | POST | Custom actions (auth key generation) |
| `/api/plugins/telegram/telegram_bridge_api` | POST | Chat bridge start/stop/status |

> **Note:** Config load/save is handled by A0's built-in plugin settings framework. The config API endpoint only handles actions requiring server-side logic.

## Verification

- **58/58 regression tests passed**
- **76/76 human verification tests passed** (2026-03-11)
- **Security assessment completed** (Stage 3a — 1 Critical, 1 High found and fixed)
- Results: [tests/HUMAN_TEST_RESULTS.md](../tests/HUMAN_TEST_RESULTS.md)
- Security: [tests/SECURITY_ASSESSMENT_RESULTS.md](../tests/SECURITY_ASSESSMENT_RESULTS.md)

## API Pricing

**Free** — The Telegram Bot API is free for all bots. No paid tiers or rate limit subscriptions.
