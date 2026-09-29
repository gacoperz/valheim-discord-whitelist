"""Slash commands. `register(tree)` adds them all."""
import contextlib

import discord
from discord import app_commands

from .config import is_steamid64
from .embeds import (
    CANT_POST,
    DASHBOARD_POSTED,
    INVALID_STEAMID,
    format_block,
    format_join_attempt,
    format_last_played,
    format_whitelist_entry,
    leaderboard_reply,
    list_embed,
    player_embed,
    status_embed,
)
from .store import StateKey
from .views import BotInteraction, Dashboard, dashboard_message
from .whitelist import AuditAction, WhitelistBlocked

HISTORY_LIMIT = 20
PROTECTED_STAYS = " 🔒 It is a protected owner ID (PROTECTED_STEAMIDS in compose), so it can still join."


# ---- everyone ----
@app_commands.command(description="Server status: online, players, in-game day")
async def status(interaction: BotInteraction):
    bot = interaction.client
    await interaction.response.send_message(embed=status_embed(bot.cfg, bot.server, bot.store))


async def player_autocomplete(interaction: BotInteraction, current: str) -> list[app_commands.Choice[str]]:
    names = [name for name in interaction.client.store.names() if current.lower() in name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in names[:25]]


@app_commands.command(description="Playtime, sessions and deaths – leaderboard or one player")
@app_commands.describe(player="Character name (leave empty for the leaderboard)")
@app_commands.autocomplete(player=player_autocomplete)
async def stats(interaction: BotInteraction, player: str | None = None):
    bot = interaction.client
    if not player:
        await interaction.response.send_message(**leaderboard_reply(bot.cfg, bot.store))
        return
    if rows := bot.store.stats(player):  # several if players on different Steam accounts share the name
        shared = len(rows) > 1
        await interaction.response.send_message(embeds=[player_embed(row, shared) for row in rows[:10]])
    else:
        await interaction.response.send_message(f"No data for **{discord.utils.escape_markdown(player)}** yet.")


# ---- Manage Server ----
@app_commands.command(name="setup-dashboard", description="Post the server dashboard (live status + whitelist) here")
@app_commands.default_permissions(manage_guild=True)  # hidden from members without Manage Server
@app_commands.checks.has_permissions(manage_guild=True)  # enforced even if overridden in Integrations
@app_commands.guild_only()
async def setup_dashboard(interaction: BotInteraction):
    bot = interaction.client
    embed = status_embed(bot.cfg, bot.server, bot.store, join_steps_field=True)
    try:
        message = await interaction.channel.send(embed=embed, view=Dashboard())
    except discord.Forbidden:
        await interaction.response.send_message(CANT_POST, ephemeral=True)
        return
    previous = bot.store.get(StateKey.DASHBOARD)
    bot.store.set(StateKey.DASHBOARD, {"channel": message.channel.id, "message": message.id})
    if previous:  # there is only one dashboard: remove the old one
        with contextlib.suppress(discord.HTTPException):  # already deleted, or no access any more
            await (await dashboard_message(bot, previous)).delete()
    await interaction.response.send_message(DASHBOARD_POSTED, ephemeral=True)


class ManageServerGroup(app_commands.Group):
    """A command group for Manage Server holders only. default_permissions only hides it, and a server's
    Integrations settings can override that, so every subcommand is also checked here when it runs."""

    async def interaction_check(self, interaction: BotInteraction) -> bool:
        if not interaction.permissions.manage_guild:
            raise app_commands.MissingPermissions(["manage_guild"])  # replied to by report_error
        return True


whitelist_admin = ManageServerGroup(
    name="whitelist-admin", description="Manage the Valheim whitelist",
    guild_only=True, default_permissions=discord.Permissions(manage_guild=True),
)


@whitelist_admin.command(name="list", description="Show everyone on the whitelist, with when they last played")
async def whitelist_list(interaction: BotInteraction):
    whitelist = interaction.client.whitelist
    played = interaction.client.store.last_played()
    entries = whitelist.entries()
    listed = {entry.steamid for entry in entries}
    lines = [f"`{steamid}` · 🔒 protected owner ID (always allowed) · {format_last_played(played.get(steamid))}"
             for steamid in whitelist.protected if steamid not in listed]
    lines += [format_whitelist_entry(entry, whitelist.is_protected(entry.steamid), played.get(entry.steamid))
              for entry in entries]
    lines += [format_block(block) for block in whitelist.blocks()]  # banned: shown so they can be unbanned
    embed = list_embed(f"🛡️ Whitelist ({len(lines)})", lines, "*The whitelist is empty — nobody can join.*")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@whitelist_admin.command(name="add", description="Manually whitelist a SteamID64 (never auto-removed)")
@app_commands.describe(steamid="17-digit SteamID64", note="Who is this?")
async def whitelist_add(interaction: BotInteraction, steamid: str, note: str):
    steamid = steamid.strip()
    if not is_steamid64(steamid):
        await interaction.response.send_message(INVALID_STEAMID, ephemeral=True)
        return
    try:
        added = interaction.client.whitelist.add_manual(steamid, note, str(interaction.user))
    except WhitelistBlocked:
        await interaction.response.send_message(f"🚫 `{steamid}` is banned. Unban it first.", ephemeral=True)
        return
    message = f"✅ Added `{steamid}` ({note})." if added else f"`{steamid}` is already whitelisted."
    await interaction.response.send_message(message, ephemeral=True)


@whitelist_admin.command(name="remove", description="Remove someone from the whitelist")
@app_commands.describe(member="Discord member to remove", steamid="…or a SteamID64")
async def whitelist_remove(interaction: BotInteraction, member: discord.Member | None = None,
                           steamid: str | None = None):
    whitelist, actor = interaction.client.whitelist, str(interaction.user)
    if member:
        entry = whitelist.remove_discord(member.id, AuditAction.REMOVE_ADMIN, actor)
        message = (f"Removed {member.mention} (`{entry.steamid}`)." if entry
                   else f"{member.mention} isn't whitelisted.")
        if entry and whitelist.is_protected(entry.steamid):
            message += PROTECTED_STAYS
    elif steamid:
        steamid = steamid.strip()
        entry = whitelist.remove_steam(steamid, AuditAction.REMOVE_ADMIN, actor)
        message = f"Removed `{steamid}`." if entry else f"`{steamid}` has no whitelist entry."
        if whitelist.is_protected(steamid):
            message += PROTECTED_STAYS
    else:
        message = "Give a member or a SteamID64."
    await interaction.response.send_message(message, ephemeral=True)


@whitelist_admin.command(name="ban", description="Remove someone and stop them from joining again")
@app_commands.describe(member="Discord member to ban (also blocks their Discord account)", steamid="…or a SteamID64",
                       reason="Why (shown in the admin list and history)")
async def whitelist_ban(interaction: BotInteraction, member: discord.Member | None = None, steamid: str | None = None,
                        reason: str | None = None):
    whitelist = interaction.client.whitelist
    if member:
        entry = whitelist.by_discord(member.id)
        target_steamid, discord_id, name, who = entry.steamid if entry else None, member.id, str(member), member.mention
    elif steamid:
        target_steamid = steamid.strip()
        if not is_steamid64(target_steamid):
            await interaction.response.send_message(INVALID_STEAMID, ephemeral=True)
            return
        entry = whitelist.by_steam(target_steamid)
        discord_id = entry.discord_id if entry else None
        name, who = (entry.discord_name or entry.note) if entry else None, f"`{target_steamid}`"
    else:
        await interaction.response.send_message("Give a member or a SteamID64.", ephemeral=True)
        return
    if target_steamid and whitelist.is_protected(target_steamid):
        await interaction.response.send_message(
            f"🔒 {who} is a protected owner ID (PROTECTED_STEAMIDS), which is always whitelisted and can't be banned.",
            ephemeral=True)
        return
    removed = whitelist.ban(steamid=target_steamid, discord_id=discord_id, name=name, reason=reason,
                            actor=str(interaction.user))
    blocked = " and ".join(part for part in (f"Steam `{target_steamid}`" if target_steamid else None,
                                             f"Discord <@{discord_id}>" if discord_id else None) if part)
    await interaction.response.send_message(
        f"🚫 Banned {who}: {'removed from the whitelist and ' if removed else ''}blocked ({blocked}) until "
        "`/whitelist-admin unban`.", ephemeral=True)


@whitelist_admin.command(name="unban", description="Lift a ban (they can then join again themselves)")
@app_commands.describe(steamid="SteamID64 to unban", member="…or a Discord member (for a Discord-only ban)")
async def whitelist_unban(interaction: BotInteraction, steamid: str | None = None,
                          member: discord.Member | None = None):
    if not steamid and not member:
        await interaction.response.send_message("Give a SteamID64 or a member.", ephemeral=True)
        return
    block = interaction.client.whitelist.unban(steamid=steamid.strip() if steamid else None,
                                               discord_id=member.id if member else None, actor=str(interaction.user))
    target = f"`{steamid.strip()}`" if steamid else member.mention
    message = (f"✅ Unbanned {target}. They aren't re-added: they can click **Join whitelist** again." if block
               else f"{target} isn't banned.")
    await interaction.response.send_message(message, ephemeral=True)


@whitelist_admin.command(name="history", description="Recent whitelist changes (who, what, when)")
async def whitelist_history(interaction: BotInteraction):
    records = interaction.client.whitelist.history(HISTORY_LIMIT)
    lines = [f"<t:{record.ts}:f> · **{record.action}** · `{record.steamid}` ({record.subject or '—'}) · "
             f"by {record.actor}" for record in records]
    embed = list_embed(f"📜 Whitelist history (latest {HISTORY_LIMIT})", lines, "*No changes recorded yet.*")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@whitelist_admin.command(name="attempts", description="Recent failed joins (not whitelisted, wrong version, …)")
async def whitelist_attempts(interaction: BotInteraction):
    bot = interaction.client
    attempts = bot.store.join_attempts(HISTORY_LIMIT)
    lines = [format_join_attempt(attempt, bot.whitelist) for attempt in attempts]
    embed = list_embed(f"🚪 Failed joins (latest {HISTORY_LIMIT})", lines, "*No failed joins recorded yet.*")
    embed.set_footer(text="Taken from the server log. \"disconnected before loading in\" has no reason in the log.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


def register(tree: app_commands.CommandTree) -> None:
    for command in (status, stats, setup_dashboard, whitelist_admin):
        tree.add_command(command)
