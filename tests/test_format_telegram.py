"""Unit tests for helpers/format_telegram.py — converter, sanitizer, splitter."""
import sys
from pathlib import Path

# Make helpers importable directly (no A0 container needed)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers.format_telegram import (
    markdown_to_telegram_html,
    split_html_message,
    strip_html,
)

PASSED = 0
FAILED = 0


def check(name: str, got, expected):
    global PASSED, FAILED
    if got == expected:
        PASSED += 1
        print(f"  \033[32mPASS\033[0m {name}")
    else:
        FAILED += 1
        print(f"  \033[31mFAIL\033[0m {name}")
        print(f"       expected: {expected!r}")
        print(f"            got: {got!r}")


def contains(name: str, haystack: str, needle: str):
    global PASSED, FAILED
    if needle in haystack:
        PASSED += 1
        print(f"  \033[32mPASS\033[0m {name}")
    else:
        FAILED += 1
        print(f"  \033[31mFAIL\033[0m {name}")
        print(f"       expected to find: {needle!r}")
        print(f"       in: {haystack!r}")


def not_contains(name: str, haystack: str, needle: str):
    global PASSED, FAILED
    if needle not in haystack:
        PASSED += 1
        print(f"  \033[32mPASS\033[0m {name}")
    else:
        FAILED += 1
        print(f"  \033[31mFAIL\033[0m {name}")
        print(f"       should NOT contain: {needle!r}")
        print(f"       in: {haystack!r}")


# ── URL Sanitization (items 1 & 2 from PR review) ─────────────────────────

print("\n=== URL Sanitization ===")

# Double-quote injection in link URL
result = markdown_to_telegram_html('[click](http://x.com" onmouseover="alert(1))')
contains("link: quote in URL escaped", result, "&quot;")
not_contains("link: no raw quote in href", result, 'href="http://x.com" onmouseover')

# Double-quote injection in image URL
result = markdown_to_telegram_html('![pic](http://x.com" bad="y)')
contains("image: quote in URL escaped", result, "&quot;")
not_contains("image: no raw quote in href", result, 'href="http://x.com" bad')

# Ampersand in URL (& is escaped by Phase 3's _escape_html before link regex)
result = markdown_to_telegram_html("[link](http://x.com?a=1&b=2)")
contains("link: ampersand escaped in URL", result, "a=1&amp;b=2")
not_contains("link: no double-escaped ampersand", result, "&amp;amp;")

# Angle brackets in URL (< > escaped by Phase 3 before link regex)
result = markdown_to_telegram_html("[link](http://x.com/<script>)")
contains("link: < escaped in URL", result, "&lt;script&gt;")
not_contains("link: no double-escaped angle bracket", result, "&amp;lt;")

# Normal link still works
result = markdown_to_telegram_html("[Google](https://google.com)")
contains("link: normal href intact", result, 'href="https://google.com"')
contains("link: text preserved", result, ">Google</a>")


# ── Null Byte Handling (item 5) ────────────────────────────────────────────

print("\n=== Null Byte Handling ===")

result = markdown_to_telegram_html("hello\x00world")
not_contains("null bytes stripped from output", result, "\x00")
contains("text around null bytes preserved", result, "helloworld")

result = markdown_to_telegram_html("**bold\x00text**")
contains("null byte in bold: still converts", result, "<b>")


# ── Basic Formatting ──────────────────────────────────────────────────────

print("\n=== Basic Formatting ===")

check("bold", markdown_to_telegram_html("**hello**"), "<b>hello</b>")
check("italic star", markdown_to_telegram_html("*hello*"), "<i>hello</i>")
check("strikethrough", markdown_to_telegram_html("~~gone~~"), "<s>gone</s>")
check("inline code", markdown_to_telegram_html("`code`"), "<code>code</code>")
check("bold italic", markdown_to_telegram_html("***both***"), "<b><i>both</i></b>")

# Heading
result = markdown_to_telegram_html("## Title")
check("heading -> bold", result, "<b>Title</b>")

# Fenced code block
result = markdown_to_telegram_html("```python\nprint('hi')\n```")
contains("fenced code: pre tag", result, "<pre>")
contains("fenced code: language class", result, 'language-python')
contains("fenced code: content preserved", result, "print(")

# Blockquote
result = markdown_to_telegram_html("> quoted text")
contains("blockquote tag", result, "<blockquote>")
contains("blockquote content", result, "quoted text")

# Unordered list
result = markdown_to_telegram_html("- item one\n- item two")
contains("list: bullet char", result, "•")

# HTML entities escaped in body text
result = markdown_to_telegram_html("1 < 2 & 3 > 0")
contains("less-than escaped", result, "&lt;")
contains("ampersand escaped", result, "&amp;")
contains("greater-than escaped", result, "&gt;")

# Mid-word underscore NOT treated as italic
result = markdown_to_telegram_html("my_variable_name")
not_contains("mid-word underscore: no italic", result, "<i>")


# ── Splitter ───────────────────────────────────────────────────────────────

print("\n=== HTML Splitter ===")

# Short message: no split
chunks = split_html_message("short", max_length=4096)
check("short message: single chunk", len(chunks), 1)

# Long message: splits
long_msg = "word " * 1000  # ~5000 chars
chunks = split_html_message(long_msg, max_length=200)
for c in chunks:
    check(f"chunk len <= 200 (got {len(c)})", len(c) <= 200, True)

# Tag balancing across chunks
html = "<b>" + ("x" * 300) + "</b>"
chunks = split_html_message(html, max_length=200)
for i, c in enumerate(chunks):
    # Each chunk should have balanced <b>...</b>
    opens = c.count("<b>")
    closes = c.count("</b>")
    check(f"chunk {i}: balanced b tags (open={opens}, close={closes})", opens, closes)


# ── strip_html ─────────────────────────────────────────────────────────────

print("\n=== strip_html ===")

check("strips tags", strip_html("<b>bold</b> and <i>italic</i>"), "bold and italic")
check("unescapes entities", strip_html("1 &lt; 2 &amp; 3 &gt; 0"), "1 < 2 & 3 > 0")


# ── Summary ────────────────────────────────────────────────────────────────

print(f"\n{'='*40}")
total = PASSED + FAILED
print(f"Results: {PASSED}/{total} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
