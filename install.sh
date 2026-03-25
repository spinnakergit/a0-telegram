#!/bin/bash
# Install the Telegram plugin into an Agent Zero instance.
#
# Usage:
#   ./install.sh                          # Auto-detect Agent Zero root (/a0 or /git/agent-zero)
#   ./install.sh /path/to/agent-zero      # Install to specified path
#
# For Docker:
#   docker exec <container> bash -c "cd /tmp && ./install.sh"
#   Or: docker cp telegram-plugin/ <container>:/a0/usr/plugins/telegram && \
#       docker exec <container> ln -sf /a0/usr/plugins/telegram /a0/plugins/telegram

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-detect A0 root: /a0 is the runtime copy, /git/agent-zero is the source
if [ -n "${1:-}" ]; then
    A0_ROOT="$1"
elif [ -d "/a0/plugins" ]; then
    A0_ROOT="/a0"
elif [ -d "/git/agent-zero/plugins" ]; then
    A0_ROOT="/git/agent-zero"
else
    echo "Error: Cannot find Agent Zero. Pass the path as argument."
    exit 1
fi

PLUGIN_DIR="$A0_ROOT/usr/plugins/telegram"

echo "=== Telegram Plugin Installer ==="
echo "Source:  $SCRIPT_DIR"
echo "Target:  $PLUGIN_DIR"
echo ""

# Create target directory
mkdir -p "$PLUGIN_DIR"

# Copy plugin files (skip if already installed in-place, e.g. via A0 plugin installer)
if [ "$(realpath "$SCRIPT_DIR")" != "$(realpath "$PLUGIN_DIR")" ]; then
    echo "Copying plugin files..."
    cp -r "$SCRIPT_DIR/plugin.yaml" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/default_config.yaml" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/initialize.py" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/helpers" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/tools" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/prompts" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/api" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/webui" "$PLUGIN_DIR/"
    cp -r "$SCRIPT_DIR/extensions" "$PLUGIN_DIR/"

    # Copy docs and README if present
    [ -d "$SCRIPT_DIR/docs" ] && cp -r "$SCRIPT_DIR/docs" "$PLUGIN_DIR/"
    [ -f "$SCRIPT_DIR/README.md" ] && cp "$SCRIPT_DIR/README.md" "$PLUGIN_DIR/"
    [ -f "$SCRIPT_DIR/LICENSE" ] && cp "$SCRIPT_DIR/LICENSE" "$PLUGIN_DIR/"
else
    echo "Files already in place (installed via plugin manager), skipping copy..."
fi

# Create data directory with restrictive permissions
mkdir -p "$PLUGIN_DIR/data"
chmod 700 "$PLUGIN_DIR/data"

# Copy skills to usr/skills
SKILLS_DIR="$A0_ROOT/usr/skills"
echo "Copying skills..."
for skill_dir in "$SCRIPT_DIR/skills"/*/; do
    skill_name="$(basename "$skill_dir")"
    mkdir -p "$SKILLS_DIR/$skill_name"
    cp -r "$skill_dir"* "$SKILLS_DIR/$skill_name/"
done

# Run initialization (install Python deps)
echo "Installing dependencies..."
python3 "$PLUGIN_DIR/initialize.py" || python "$PLUGIN_DIR/initialize.py"

# Enable plugin
touch "$PLUGIN_DIR/.toggle-1"

# Create symlink so 'from plugins.telegram.helpers...' imports work
SYMLINK="$A0_ROOT/plugins/telegram"
if [ ! -e "$SYMLINK" ]; then
    ln -sf "$PLUGIN_DIR" "$SYMLINK"
    echo "Created symlink: $SYMLINK -> $PLUGIN_DIR"
fi

# If /a0 is a runtime copy of /git/agent-zero, also install there
if [ "$A0_ROOT" = "/a0" ] && [ -d "/git/agent-zero/usr" ]; then
    GIT_PLUGIN="/git/agent-zero/usr/plugins/telegram"
    mkdir -p "$(dirname "$GIT_PLUGIN")"
    cp -r "$PLUGIN_DIR" "$GIT_PLUGIN" 2>/dev/null || true
fi

echo ""
echo "=== Installation complete ==="
echo "Plugin installed to: $PLUGIN_DIR"
echo "Skills installed to: $SKILLS_DIR"
echo ""
echo "Next steps:"
echo "  1. Configure your bot token in the Telegram plugin settings (WebUI)"
echo "     Or set TELEGRAM_BOT_TOKEN environment variable"
echo "  2. Restart Agent Zero to load the plugin"
echo "  3. Ask the agent: 'List my Telegram chats'"
