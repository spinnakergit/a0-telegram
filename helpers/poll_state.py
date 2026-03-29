"""Persistent polling state for background message watching.

Tracks last-seen update IDs per watched chat so that polling
resumes from where it left off across restarts.
"""

import json
import time
from pathlib import Path
from typing import Optional

STATE_FILE = "poll_state.json"


def _get_state_path() -> Path:
    candidates = [
        Path(__file__).parent.parent / "data" / STATE_FILE,
        Path("/a0/usr/plugins/telegram/data") / STATE_FILE,
        Path("/a0/plugins/telegram/data") / STATE_FILE,
    ]
    for p in candidates:
        if p.exists():
            return p
    path = candidates[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_state() -> dict:
    """Load the polling state from disk."""
    path = _get_state_path()
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {"watch_chats": {}, "last_update_id": 0}


def save_state(state: dict):
    """Save the polling state to disk."""
    from usr.plugins.telegram.helpers.sanitize import secure_write_json
    secure_write_json(_get_state_path(), state)


def get_watch_chats() -> dict:
    """Get the list of chats being watched for new messages."""
    return load_state().get("watch_chats", {})


def add_watch_chat(chat_id: str, label: str = ""):
    """Add a chat to the watch list."""
    state = load_state()
    state.setdefault("watch_chats", {})[chat_id] = {
        "label": label or chat_id,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_seen_id": 0,
    }
    save_state(state)


def remove_watch_chat(chat_id: str):
    """Remove a chat from the watch list."""
    state = load_state()
    state.get("watch_chats", {}).pop(chat_id, None)
    save_state(state)


def get_last_update_id() -> int:
    """Get the last processed update ID."""
    return load_state().get("last_update_id", 0)


def set_last_update_id(update_id: int):
    """Set the last processed update ID."""
    state = load_state()
    state["last_update_id"] = update_id
    save_state(state)
