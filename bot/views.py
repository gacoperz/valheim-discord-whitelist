"""Dashboard buttons, the leave confirmation, and checks shared by buttons and slash commands."""
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from .config import OAUTH_STATE_TTL
from .embeds import (
    BLOCKED,
    CANT_POST,
    NOT_WHITELISTED,
    WHITELIST_WRITE_FAILED,
    leaderboard_reply,
    left_whitelist_message,
    my_stats_reply,
    whitelist_status_message,
)
from .whitelist import AuditAction, WhitelistBlocked, WhitelistWriteError

if TYPE_CHECKING:  # only for type checkers: main imports this module, so a real import would be circular
    from .main import Bot

log = logging.getLogger("valheim-bot")

# An interaction whose `client` is the running Bot, so editors know about its cfg, store, whitelist, server, oauth.
type BotInteraction = discord.Interaction[Bot]  # lazy: Bot is only looked up by type checkers


async def guild_allowed(interaction: BotInteraction) -> bool:
    """Refuse (and log) interactions from Discord servers that are not in ALLOWED_GUILDS."""
    if interaction.guild_id in interaction.client.cfg.allowed_guilds:
        return True
    log.warning("refused interaction from %s (%s) in guild %s", interaction.user, interaction.user.id,
                interaction.guild_id)
    await interaction.response.send_message(
        f"⛔ This bot only works in the {interaction.client.cfg.server_name} Discord servers.", ephemeral=True)
    return False


async def report_error(interaction: BotInteraction, error: Exception) -> None:
    """The one place that turns an error from a command or button into a reply."""
    error = getattr(error, "original", error)  # app command errors wrap the real exception
    if isinstance(error, app_commands.MissingPermissions):
        message = "⛔ You need the Manage Server permission to use this command."
    elif isinstance(error, WhitelistBlocked):
        message = BLOCKED
    elif isinstance(error, WhitelistWriteError):
        message = WHITELIST_WRITE_FAILED
    elif isinstance(error, discord.Forbidden):
        message = CANT_POST
    else:
        log.exception("interaction failed", exc_info=error)
        message = "⚠️ Something went wrong. The admin can check the bot log."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def send_join_link(interaction: BotInteraction) -> None:
    """Reply privately with a personal "Link Steam" button that starts the OAuth round trip."""
    bot = interaction.client
    if not bot.oauth:
        await interaction.response.send_message("Whitelist linking isn't configured yet.", ephemeral=True)
        return
    if bot.whitelist.blocked(discord_id=interaction.user.id):
        await interaction.response.send_message(BLOCKED, ephemeral=True)
        return
    current = bot.whitelist.by_discord(interaction.user.id)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Link Steam", emoji="🔗", url=bot.oauth.authorize_url(interaction.user.id, interaction.guild_id)
    ))
    note = (f"\nYou're already whitelisted as `{current.steamid}`; linking again replaces it." if current else "")
    await interaction.response.send_message(
        "Click **Link Steam** and then **Authorize**. I only read your Steam connection "
        "(Discord → User Settings → Connections) to get your Steam ID. The link is valid for "
        f"{OAUTH_STATE_TTL // 60} minutes and only works for you." + note,
        view=view, ephemeral=True,
    )


class ConfirmLeave(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    async def on_error(self, interaction: BotInteraction, error: Exception, item: discord.ui.Item) -> None:
        await report_error(interaction, error)

    @discord.ui.button(label="Yes, remove me", style=discord.ButtonStyle.danger)
    async def on_confirm(self, interaction: BotInteraction, button: discord.ui.Button):
        whitelist = interaction.client.whitelist
        entry = whitelist.remove_discord(interaction.user.id, AuditAction.LEAVE, str(interaction.user))
        await interaction.response.edit_message(content=left_whitelist_message(whitelist, entry), view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def on_cancel(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Nothing changed — you're still on the whitelist.", view=None)


async def dashboard_message(client: discord.Client, ref: dict) -> discord.PartialMessage:
    """The message a stored {"channel": id, "message": id} reference points to."""
    channel = client.get_channel(ref["channel"]) or await client.fetch_channel(ref["channel"])
    return channel.get_partial_message(ref["message"])


class Dashboard(discord.ui.View):
    """Buttons under the dashboard message. Persistent (fixed custom_ids, no timeout): registered once at
    startup, they keep working on the posted message across restarts. Never change the custom_ids."""

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: BotInteraction) -> bool:
        return await guild_allowed(interaction)

    async def on_error(self, interaction: BotInteraction, error: Exception, item: discord.ui.Item) -> None:
        await report_error(interaction, error)

    @discord.ui.button(label="Join whitelist", emoji="✅", style=discord.ButtonStyle.success,
                       custom_id="wl:join", row=0)
    async def on_join(self, interaction: BotInteraction, button: discord.ui.Button):
        await send_join_link(interaction)

    @discord.ui.button(label="Leave whitelist", emoji="👋", style=discord.ButtonStyle.danger,
                       custom_id="wl:leave", row=0)
    async def on_leave(self, interaction: BotInteraction, button: discord.ui.Button):
        entry = interaction.client.whitelist.by_discord(interaction.user.id)
        if not entry:
            await interaction.response.send_message(NOT_WHITELISTED, ephemeral=True)
            return
        await interaction.response.send_message(
            f"Remove Steam **{entry.steam_name or entry.steamid}** from the whitelist? You won't be able to join "
            "until you join again.", view=ConfirmLeave(), ephemeral=True,
        )

    @discord.ui.button(label="Whitelist status", emoji="ℹ️", style=discord.ButtonStyle.secondary,
                       custom_id="wl:me", row=0)
    async def on_whitelist_status(self, interaction: BotInteraction, button: discord.ui.Button):
        bot = interaction.client
        await interaction.response.send_message(
            whitelist_status_message(bot.cfg, bot.whitelist, bot.store, interaction.user.id), ephemeral=True)

    @discord.ui.button(label="Leaderboard", emoji="🏆", style=discord.ButtonStyle.secondary,
                       custom_id="st:top", row=1)
    async def on_leaderboard(self, interaction: BotInteraction, button: discord.ui.Button):
        bot = interaction.client
        await interaction.response.send_message(**leaderboard_reply(bot.cfg, bot.store), ephemeral=True)

    @discord.ui.button(label="My stats", emoji="📊", style=discord.ButtonStyle.primary,
                       custom_id="st:me", row=1)
    async def on_my_stats(self, interaction: BotInteraction, button: discord.ui.Button):
        bot = interaction.client
        await interaction.response.send_message(
            **my_stats_reply(bot.store, bot.whitelist, interaction.user.id), ephemeral=True)
