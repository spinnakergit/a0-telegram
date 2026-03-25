"""Plugin lifecycle hooks for the Telegram Integration plugin.

Called by Agent Zero's plugin system during install, uninstall, and update.
See: helpers/plugins.py -> call_plugin_hook()
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("telegram_hooks")


def _get_plugin_dir() -> Path:
    """Return the directory this hooks.py lives in."""
    return Path(__file__).parent.resolve()


def _get_a0_root() -> Path:
    """Detect A0 root directory."""
    if Path("/a0/plugins").is_dir():
        return Path("/a0")
    if Path("/git/agent-zero/plugins").is_dir():
        return Path("/git/agent-zero")
    return Path("/a0")


def _find_python() -> str:
    """Find the appropriate Python interpreter."""
    candidates = ["/opt/venv-a0/bin/python3", sys.executable, "python3"]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "python3"


def install(**kwargs):
    """Post-install hook: set up symlink, data dir, deps, skills, toggle."""
    plugin_dir = _get_plugin_dir()
    a0_root = _get_a0_root()
    plugin_name = "telegram"

    logger.info("Running post-install hook...")

    # 1. Enable plugin
    toggle = plugin_dir / ".toggle-1"
    if not toggle.exists():
        toggle.touch()
        logger.info("Created %s", toggle)

    # 2. Create data directory with restrictive permissions
    data_dir = plugin_dir / "data"
    data_dir.mkdir(exist_ok=True)
    os.chmod(str(data_dir), 0o700)

    # 3. Create symlink so 'from plugins.telegram.helpers...' imports work
    symlink = a0_root / "plugins" / plugin_name
    if not symlink.exists():
        symlink.symlink_to(plugin_dir)
        logger.info("Created symlink: %s -> %s", symlink, plugin_dir)
    elif symlink.is_symlink() and symlink.resolve() != plugin_dir:
        symlink.unlink()
        symlink.symlink_to(plugin_dir)
        logger.info("Updated symlink: %s -> %s", symlink, plugin_dir)
    elif symlink.is_dir() and not symlink.is_symlink():
        import shutil
        shutil.rmtree(str(symlink))
        symlink.symlink_to(plugin_dir)
        logger.info("Replaced directory with symlink: %s -> %s", symlink, plugin_dir)

    # 4. Install skills
    skills_src = plugin_dir / "skills"
    skills_dst = a0_root / "usr" / "skills"
    if skills_src.is_dir():
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir():
                target = skills_dst / skill_dir.name
                target.mkdir(parents=True, exist_ok=True)
                for f in skill_dir.iterdir():
                    dest = target / f.name
                    if f.is_file():
                        dest.write_bytes(f.read_bytes())
                logger.info("Installed skill: %s", skill_dir.name)

    # 5. Install Python dependencies via initialize.py
    init_script = plugin_dir / "initialize.py"
    if init_script.is_file():
        python = _find_python()
        try:
            subprocess.run(
                [python, str(init_script)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            logger.info("Dependencies installed")
        except subprocess.CalledProcessError as e:
            logger.warning("Dependency install failed: %s", e.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("Dependency install timed out")

    # 6. Mirror to /git/agent-zero if running in /a0 runtime
    if str(a0_root) == "/a0" and Path("/git/agent-zero/usr").is_dir():
        git_plugin = Path("/git/agent-zero/usr/plugins") / plugin_name
        if not git_plugin.exists():
            try:
                import shutil
                shutil.copytree(str(plugin_dir), str(git_plugin))
            except Exception:
                pass

    logger.info("Post-install hook complete")


def uninstall(**kwargs):
    """Pre-uninstall hook: clean up symlink, skills, bridge runner."""
    a0_root = _get_a0_root()
    plugin_name = "telegram"

    logger.info("Running uninstall hook...")

    # Remove symlink
    symlink = a0_root / "plugins" / plugin_name
    if symlink.is_symlink():
        symlink.unlink()
        logger.info("Removed symlink: %s", symlink)
    elif symlink.is_dir():
        import shutil
        shutil.rmtree(str(symlink))
        logger.info("Removed directory: %s", symlink)

    # Remove skills
    skills_dst = a0_root / "usr" / "skills"
    for skill_name in ["telegram-chat", "telegram-communicate", "telegram-research"]:
        skill_dir = skills_dst / skill_name
        if skill_dir.is_dir():
            import shutil
            shutil.rmtree(str(skill_dir))
            logger.info("Removed skill: %s", skill_name)

    logger.info("Uninstall hook complete")
