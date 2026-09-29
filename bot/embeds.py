"""Everything the bot says: fixed reply texts, and the functions that build embeds and replies.
Functions returning a dict give keyword arguments for `send_message`."""
import time

import discord

from . import motd
from .config import POLL_SECONDS, STEAMID64_LEN, STEAMID64_PREFIX, Config
from .server import ServerState
from .store import JoinAttempt, JoinProblem, LastPlayed, PlayerStats, StateKey, Store
from .whitelist import Block, Whitelist, WhitelistEntry
from .world import current_day

# Discord's limits are 4096 characters for an embed description and 2000 for a message; 4000 leaves a margin.
EMBED_DESCRIPTION_LIMIT = 4000
MESSAGE_LIMIT = 2000
# How far back before someone was whitelisted a refused stranger may be the same person on another account.
WRONG_ACCOUNT_LOOKBACK = 24 * 3600

# ---- fixed reply texts ----
NOT_WHITELISTED = "You're not on the whitelist."
JOIN_HINT = "Click **Join whitelist** on the dashboard."
NO_STATS = "No stats recorded yet."
CANT_POST = "❌ I can't post here. I need View Channel, Send Messages and Embed Links."
WHITELIST_WRITE_FAILED = "⚠️ The whitelist file couldn't be updated. The admin can check the bot log."
BLOCKED = "🚫 You're blocked from the whitelist. If you think that's a mistake, ask an admin."
INVALID_STEAMID = f"That's not a SteamID64 ({STEAMID64_LEN} digits, starts with {STEAMID64_PREFIX})."
DASHBOARD_POSTED = f"✅ Dashboard posted; it updates every {POLL_SECONDS} s. Pin it if you like."


# ---- embeds and replies ----
def fmt_duration(seconds: float) -> str:
    minutes_total = int(seconds) // 60
    days, rest = divmod(minutes_total, 24 * 60)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def join_steps(cfg: Config) -> str:
    steps = (
        "**1.** Connect Steam to Discord: *User Settings → Connections → Steam*\n"
        "**2.** Click **Join whitelist** → **Link Steam** → **Authorize**\n"
    )
    if cfg.join_address:
        steps += f"**3.** Valheim: **Join Game → Add server** → `{cfg.join_address}`\n"
    return steps + "-# Leave whitelist removes you; so does leaving this Discord."


def status_embed(cfg: Config, server: ServerState, store: Store, *, join_steps_field: bool = False) -> discord.Embed:
    """Live server status. With `join_steps_field` (the dashboard) it also shows the message of the day and
    explains how to join."""
    now = time.time()
    info = server.info
    if info:
        embed = discord.Embed(title=f"🟢 {cfg.server_name} is online", colour=discord.Colour.green())
        players = store.online()
        if players:
            lines = "\n".join(f"• **{name}** — {fmt_duration(now - start)}" for name, start in players)
        elif info.players:
            lines = "*(names appear after their next login)*"
        else:
            lines = "*Nobody online*"
        embed.add_field(name=f"Players {info.players}/{info.max_players}", value=lines, inline=False)
    else:
        embed = discord.Embed(title=f"🔴 {cfg.server_name} is offline", colour=discord.Colour.red())

    if day := current_day(cfg.world_dir, store.online_seconds_since, now):
        embed.add_field(name="In-game day", value=f"Day **{day.number}**", inline=True)
        embed.add_field(name="Last world save", value=f"<t:{day.saved_at}:R>", inline=True)
    if info and (started := store.get(StateKey.SERVER_STARTED)):
        embed.add_field(name="Server up since", value=f"<t:{started}:R>", inline=True)
    if info and info.version:
        embed.add_field(name="Version", value=info.version, inline=True)
    if join_steps_field:
        if about := motd.load(cfg.motd_file):
            embed.add_field(name=f"📜 About {cfg.server_name}", value=motd.for_embed(about), inline=False)
        embed.add_field(name="🛡️ How to join (whitelist only)", value=join_steps(cfg), inline=False)
    elif cfg.join_address:
        embed.add_field(name="Join (Add server)", value=f"`{cfg.join_address}`", inline=True)
    if not info and server.last_ok:
        embed.add_field(name="Last seen online", value=f"<t:{int(server.last_ok)}:R>", inline=True)
    embed.set_footer(text="Updated")
    embed.timestamp = discord.utils.utcnow()
    return embed


def leaderboard_reply(cfg: Config, store: Store) -> dict:
    rows = store.stats()
    if not rows:
        return {"content": NO_STATS}
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[rank] if rank < 3 else f'`{rank + 1}.`'} **{row.name}** — {fmt_duration(row.playtime)}"
        f" · {row.sessions} sessions · 💀 {row.deaths}" + (" · 🟢" if row.online else "")
        for rank, row in enumerate(rows[:15])
    ]
    embed = discord.Embed(title=f"📊 {cfg.server_name} leaderboard", description="\n".join(lines),
                          colour=discord.Colour.blurple())
    return {"embed": embed}


def list_embed(title: str, lines: list[str], empty: str) -> discord.Embed:
    """An admin list: one line per item, cut to fit Discord's limit, or `empty` if there are none."""
    text = "\n".join(lines) or empty
    return discord.Embed(title=title, description=text[:EMBED_DESCRIPTION_LIMIT], colour=discord.Colour.blurple())


def player_embed(row: PlayerStats) -> discord.Embed:
    embed = discord.Embed(title=f"📊 {row.name}", colour=discord.Colour.blurple())
    embed.add_field(name="Playtime", value=fmt_duration(row.playtime))
    embed.add_field(name="Sessions", value=str(row.sessions))
    embed.add_field(name="Deaths", value=str(row.deaths))
    embed.add_field(name="First seen", value=f"<t:{row.first_seen}:D>" if row.first_seen else "—")
    if row.online:
        last_seen = "🟢 online now"
    else:
        last_seen = f"<t:{row.last_seen}:R>" if row.last_seen else "—"
    embed.add_field(name="Last seen", value=last_seen)
    return embed


def my_stats_reply(store: Store, whitelist: Whitelist, user_id: int) -> dict:
    """Stats for every character played from the user's linked Steam account."""
    entry = whitelist.by_discord(user_id)
    if not entry:
        return {"content": "Your Discord isn't linked to a Steam account yet, so I can't tell which character "
                           "is yours. " + JOIN_HINT + " Then this button works."}
    names = store.names_for_steam(entry.steamid)
    if not names:
        return {"content": "No playtime recorded for your Steam account yet — go play! ⚔️"}
    embeds = [player_embed(store.player(name)) for name in names[:10]]
    return {"content": f"Your characters ({len(names)}):" if len(names) > 1 else None, "embeds": embeds}


def whitelist_status_message(cfg: Config, whitelist: Whitelist, store: Store, user_id: int) -> str:
    entry = whitelist.by_discord(user_id)
    if not entry:
        return BLOCKED if whitelist.blocked(discord_id=user_id) else f"❌ {NOT_WHITELISTED} {JOIN_HINT}"
    message = (f"✅ Whitelisted: Steam **{entry.steam_name or '?'}** (`{entry.steamid}`) "
               f"since <t:{entry.added_at}:D>.")
    if cfg.join_address:
        message += f"\nIn Valheim: **Join Game → Add server** → `{cfg.join_address}`"
    return message + "\n" + join_diagnosis(store, entry)


def join_diagnosis(store: Store, entry: WhitelistEntry) -> str:
    """What the server log says about this player's latest connection, as advice for them."""
    played = store.last_played().get(entry.steamid)
    attempts = store.join_attempts(1, steamid=entry.steamid)
    failed = attempts[0] if attempts and (not played or attempts[0].ts > played.ts) else None
    if failed:
        when = f"<t:{failed.ts}:R>"
        if failed.problem == JoinProblem.WRONG_VERSION:
            return (f"⚠️ Your last try ({when}) was refused: your Valheim version doesn't match the server "
                    f"({failed.detail}). Update Valheim in Steam (restart Steam if no update shows), then try again.")
        if failed.problem == JoinProblem.DROPPED:
            return (f"⚠️ Your last try ({when}) disconnected before loading in. Try again; if it keeps happening, "
                    "tell the admin.")
        if failed.ts < entry.added_at:
            return f"ℹ️ Your last try ({when}) was before you were whitelisted, so it was refused. Try again now."
        return (f"⚠️ Your last try ({when}) was refused ({failed.problem}) even though you're on the list. "
                "Tell the admin.")
    if played:
        return "🟢 You're online now." if played.online else f"Last played <t:{played.ts}:R>."
    message = "ℹ️ Your Steam account hasn't connected to the server yet."
    strangers = [a for a in store.join_attempts(5, since=entry.added_at - WRONG_ACCOUNT_LOOKBACK,
                                                problem=JoinProblem.NOT_WHITELISTED)
                 if a.steamid != entry.steamid]
    if strangers:
        latest = strangers[0]
        message += (f"\n🔎 Someone tried to join <t:{latest.ts}:R> as **{latest.name or '?'}** from a Steam account "
                    "that isn't on the whitelist. If that was you, you play on a different Steam account than the "
                    "one connected to your Discord: connect that one in *User Settings → Connections*, then click "
                    "**Join whitelist** again.")
    return message


def left_whitelist_message(whitelist: Whitelist, entry: WhitelistEntry | None) -> str:
    if not entry:
        return NOT_WHITELISTED
    message = f"👋 Removed `{entry.steamid}` from the whitelist."
    if whitelist.is_protected(entry.steamid):
        message += "\n🔒 This Steam ID is a protected owner ID, so it can still join the server."
    return message


def format_join_attempt(attempt: JoinAttempt, whitelist: Whitelist) -> str:
    """One line of /whitelist-admin attempts, with who that Steam ID belongs to now."""
    entry = whitelist.by_steam(attempt.steamid)
    if entry:
        now = f"✅ now whitelisted ({f'<@{entry.discord_id}>' if entry.discord_id else entry.note or 'manual'})"
    elif whitelist.is_protected(attempt.steamid):
        now = "✅ protected owner ID"
    else:
        now = "❌ not whitelisted"
    name = f" as **{attempt.name}**" if attempt.name else ""
    detail = f" ({attempt.detail})" if attempt.detail else ""
    return f"<t:{attempt.ts}:f> · {attempt.problem}{detail} · `{attempt.steamid}`{name} · {now}"


def format_last_played(played: LastPlayed | None) -> str:
    if not played:
        return "never played"
    return "🟢 online now" if played.online else f"played <t:{played.ts}:R>"


def format_block(block: Block) -> str:
    """One blocked line of /whitelist-admin list."""
    who = [f"`{block.steamid}`" if block.steamid else None, f"<@{block.discord_id}>" if block.discord_id else None]
    reason = f" · {block.reason}" if block.reason else ""
    return (f"🚫 {' · '.join(part for part in who if part)} ({block.name or '?'}){reason} · banned "
            f"<t:{block.blocked_at}:d> by {block.actor}")


def format_whitelist_entry(entry: WhitelistEntry, protected: bool, played: LastPlayed | None) -> str:
    who = f"<@{entry.discord_id}>" if entry.discord_id else f"manual — {entry.note or 'no note'}"
    steam = f" ({entry.steam_name})" if entry.steam_name else ""
    return (f"`{entry.steamid}`{steam} · {who} · added <t:{entry.added_at}:d> · {format_last_played(played)}"
            + (" · 🔒" if protected else ""))
