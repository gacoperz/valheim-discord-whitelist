"""The message of the day: a short intro to the server, shown on the dashboard and the whitelist success page.

Admins edit motd/motd.md on the server (Discord markdown). It is read on every use, so a change shows on the
dashboard within one poll; no restart needed. A missing or empty file simply hides it.
"""
import html
import logging
import re

log = logging.getLogger("valheim-bot.motd")

FIELD_LIMIT = 1024  # Discord's limit for an embed field value
_warned_about: str | None = None  # the too-long text last warned about, so the log isn't repeated every poll


def load(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("cannot read the message of the day %s: %s", path, exc)
        return None
    return text or None


def for_embed(text: str) -> str:
    """The text cut to fit an embed field."""
    global _warned_about
    if len(text) <= FIELD_LIMIT:
        return text
    if text != _warned_about:
        log.warning("message of the day is %d characters; the dashboard shows the first %d", len(text), FIELD_LIMIT)
        _warned_about = text
    return text[:FIELD_LIMIT - 1] + "…"


def to_html(text: str) -> str:
    """Safe HTML for the web page: everything is escaped first, then **bold**, `code`, "- " / "• " bullets and
    line breaks are turned into tags. Other Discord markdown shows as plain text."""
    lines = []
    for line in html.escape(text).splitlines():
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
        line = re.sub(r"^\s*[-•*]\s+", "• ", line)
        lines.append(line)
    return "<br>".join(lines)
