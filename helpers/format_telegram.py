"""Markdown -> Telegram HTML conversion with tag-aware message splitting.

Telegram supports a limited HTML subset: <b>, <i>, <u>, <s>, <code>,
<pre>, <a href="...">, <blockquote>.  Everything else is approximated.

Conversion map:
  Fenced code blocks  -> <pre><code>     Inline code (`x`)   -> <code>
  Tables (|...|)      -> <pre>           Headings (# ...)    -> <b>
  Blockquotes (>)     -> <blockquote>    HR (---)            -> ———
  Unordered lists     -> bullet char     **bold**            -> <b>
  *italic*            -> <i>             ~~strike~~          -> <s>
  [text](url)         -> <a href>        ![alt](url)         -> link

All raw <, >, & are HTML-escaped.  Falls back to plain text on failure.
"""

from __future__ import annotations

import re

_TELEGRAM_TAGS = frozenset(
    {"b", "i", "u", "s", "code", "pre", "a", "blockquote", "tg-spoiler"}
)
_TAG_RE = re.compile(r"<(/?)(\w[\w-]*)([^>]*)>")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def markdown_to_telegram_html(text: str) -> str:
    """Best-effort Markdown -> Telegram HTML.  Returns escaped plain text on
    any conversion failure so callers always get a safe string."""
    try:
        result = _convert(text)
        if "\x00" in result:
            return _escape_html(text)
        return result
    except Exception:
        import logging
        logging.getLogger("format_telegram").exception(
            "Markdown->HTML conversion failed, falling back to plain text"
        )
        return _escape_html(text)


def split_html_message(html: str, max_length: int = 4096) -> list[str]:
    """Split HTML into chunks <= *max_length*, balancing tags across
    boundaries so every chunk is valid standalone HTML."""
    effective = max_length - 80  # room for closing/reopening tags
    if len(html) <= max_length:
        return [html]

    raw: list[str] = []
    buf = html
    while buf:
        if len(buf) <= effective:
            raw.append(buf)
            break
        cut = _find_safe_cut(buf, effective)
        raw.append(buf[:cut])
        buf = buf[cut:].lstrip("\n")

    return _balance_tags(raw)


def strip_html(html: str) -> str:
    """Remove tags and unescape entities -> plain text (for send fallback)."""
    text = re.sub(r"<[^>]+>", "", html)
    return (
        text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    )


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------

def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Conversion pipeline
# ---------------------------------------------------------------------------

def _convert(text: str) -> str:
    stash: list[tuple[str, str]] = []

    def _put(html: str) -> str:
        key = f"\x00\x02{len(stash)}\x03\x00"
        stash.append((key, html))
        return key

    # -- Phase 1: protect code blocks (must come before HTML escaping) ------

    def _fenced(m: re.Match) -> str:
        lang = (m.group(1) or "").strip()
        code = _escape_html(m.group(2).strip("\n"))
        if lang:
            return _put(
                f'<pre><code class="language-{_escape_html(lang)}">'
                f"{code}</code></pre>"
            )
        return _put(f"<pre>{code}</pre>")

    text = re.sub(r"```(\w*)\n(.*?)```", _fenced, text, flags=re.DOTALL)

    def _inline_code(m: re.Match) -> str:
        return _put(f"<code>{_escape_html(m.group(1))}</code>")

    text = re.sub(r"`([^`\n]+)`", _inline_code, text)

    # -- Phase 2: tables -> pre block ---------------------------------------

    def _table(m: re.Match) -> str:
        lines = m.group(0).strip().split("\n")
        kept = [l for l in lines if not re.match(r"^\s*\|[-:\s|]+\|\s*$", l)]
        return _put(f"<pre>{_escape_html(chr(10).join(kept))}</pre>")

    text = re.sub(
        r"(?:^[ \t]*\|.+\|[ \t]*$\n?){2,}",
        _table,
        text,
        flags=re.MULTILINE,
    )

    # -- Phase 3: escape HTML in remaining text -----------------------------
    text = _escape_html(text)

    # -- Phase 4: block constructs -----------------------------------------

    # Headings -> bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Blockquotes (consecutive > lines)
    def _blockquote(m: re.Match) -> str:
        lines = m.group(0).strip().split("\n")
        inner = "\n".join(re.sub(r"^&gt;\s?", "", l) for l in lines)
        return f"<blockquote>{inner}</blockquote>"

    text = re.sub(
        r"(?:^&gt;\s?.+$\n?)+", _blockquote, text, flags=re.MULTILINE
    )

    # Horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "———", text, flags=re.MULTILINE)

    # Unordered lists
    text = re.sub(r"^([ \t]*)[-*+] ", r"\1• ", text, flags=re.MULTILINE)

    # -- Phase 5: inline constructs (order matters) -------------------------

    # Images before links so ![alt](url) isn't caught as a link
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)", r'🖼 <a href="\2">\1</a>', text
    )
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Bold+italic (*** / ___) before bold (** / __) before italic (* / _)
    text = re.sub(r"\*{3}(.+?)\*{3}", r"<b><i>\1</i></b>", text)
    text = re.sub(r"_{3}(.+?)_{3}", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*{2}(.+?)\*{2}", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Single * / _ — but not mid-word underscores (e.g. variable_name)
    text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![_\w])_([^_\n]+?)_(?![_\w])", r"<i>\1</i>", text)

    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # -- Phase 6: restore stashed content -----------------------------------
    for key, html in stash:
        text = text.replace(key, html)

    return text.strip()


# ---------------------------------------------------------------------------
# HTML-aware splitting helpers
# ---------------------------------------------------------------------------

def _find_safe_cut(text: str, max_len: int) -> int:
    """Pick a split position that avoids landing inside an HTML tag."""
    cut = text.rfind("\n", 0, max_len)
    if cut < max_len // 4:
        cut = text.rfind(" ", 0, max_len)
    if cut < max_len // 4:
        cut = max_len

    # If we're inside a tag, back up to before the '<'
    last_open = text.rfind("<", 0, cut)
    last_close = text.rfind(">", 0, cut)
    if last_open > last_close:
        cut = last_open

    return max(cut, 1)


def _balance_tags(chunks: list[str]) -> list[str]:
    """Close unclosed tags at end of each chunk and reopen them in the next."""
    result: list[str] = []
    carry: list[tuple[str, str]] = []  # (tag_name, full_opening_tag)

    for chunk in chunks:
        if carry:
            chunk = "".join(tag for _, tag in carry) + chunk

        carry = _unclosed_tags(chunk)

        if carry:
            chunk += "".join(f"</{name}>" for name, _ in reversed(carry))

        result.append(chunk)

    return result


def _unclosed_tags(html: str) -> list[tuple[str, str]]:
    """Return (tag_name, full_opening_tag) for tags opened but not closed."""
    stack: list[tuple[str, str]] = []
    for m in _TAG_RE.finditer(html):
        is_close = m.group(1) == "/"
        name = m.group(2).lower()
        if name not in _TELEGRAM_TAGS:
            continue
        if is_close:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    stack.pop(i)
                    break
        else:
            stack.append((name, m.group(0)))
    return stack
