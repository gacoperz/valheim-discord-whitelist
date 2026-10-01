"""Orphaned whitelist entries: players who linked Steam from a Discord server the bot can no longer serve.

They stay whitelisted (the user's choice), but can't manage their entry via the bot and aren't auto-removed
when they leave that server, so the admin is DM'd once per entry.
"""
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import discord

from .whitelist import WhitelistEntry


@dataclass(frozen=True)
class Orphan:
    entry: WhitelistEntry
    server_name: str
    reason: str


def find_orphans(entries: Iterable[WhitelistEntry], allowed_guilds: frozenset[int],
                 get_guild: Callable[[int], discord.Guild | None],
                 left_guild: discord.Guild | None = None) -> list[Orphan]:
    """Linked entries whose Discord server the bot is not in, or that is not in ALLOWED_GUILDS.
    `left_guild` is the server the bot was just removed from, so the DM can still name it."""
    orphans = []
    for entry in entries:
        if entry.is_manual:
            continue
        guild = get_guild(entry.guild_id)
        if guild and entry.guild_id in allowed_guilds:
            continue
        if guild:
            orphans.append(Orphan(entry, guild.name, "not in ALLOWED_GUILDS"))
        elif left_guild and left_guild.id == entry.guild_id:
            orphans.append(Orphan(entry, left_guild.name, "bot not in it"))
        else:
            orphans.append(Orphan(entry, "a server I'm no longer in", "bot not in it"))
    return orphans


def split_notified(orphans: list[Orphan], notified: set[str]) -> tuple[list[Orphan], set[str]]:
    """(orphans the admin hasn't been told about, SteamIDs to keep remembering). Entries that recovered are
    forgotten, so if one breaks again it is reported again."""
    current = {orphan.entry.steamid for orphan in orphans}
    new = [orphan for orphan in orphans if orphan.entry.steamid not in notified]
    return new, notified & current


def format_orphan_dm(server_name: str, orphans: list[Orphan]) -> str:
    lines = [f"• **{orphan.entry.discord_name}** · Steam {orphan.entry.steam_name or '?'} "
             f"(`{orphan.entry.steamid}`) · {orphan.server_name} (`{orphan.entry.guild_id}`, {orphan.reason})"
             for orphan in orphans]
    return (f"⚠️ **{server_name} whitelist:** these players linked Steam from a Discord server I can't "
            "serve any more. They **stay whitelisted**, but can't leave or check their entry via the bot, "
            "and won't be auto-removed if they leave that server:\n" + "\n".join(lines) +
            "\nRemove one with `/whitelist-admin remove steamid:<id>`, or they can re-link with "
            "**Join whitelist** in a server I'm in.")
