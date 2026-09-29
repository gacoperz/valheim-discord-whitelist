"""Entry point: the Discord client with its background tasks (server poll, hourly member check)."""
import asyncio
import contextlib
import logging
import sqlite3
import time

import discord
from discord import app_commands
from discord.ext import tasks

from . import a2s, commands
from .alerts import Alert, active_alerts, recovered_text
from .config import ALERT_DM_RETRY_SECONDS, HEARTBEAT_FILE, POLL_SECONDS, Config
from .embeds import MESSAGE_LIMIT, status_embed
from .orphans import find_orphans, format_orphan_dm, split_notified
from .server import ServerState
from .store import StateKey, Store, connect
from .views import BotInteraction, Dashboard, dashboard_message, guild_allowed, report_error
from .web import OAuth, OAuthStates
from .whitelist import AuditAction, Whitelist, WhitelistWriteError

log = logging.getLogger("valheim-bot")


class Tree(app_commands.CommandTree):
    async def interaction_check(self, interaction: BotInteraction) -> bool:
        if interaction.type == discord.InteractionType.autocomplete:
            return interaction.guild_id in interaction.client.cfg.allowed_guilds
        return await guild_allowed(interaction)

    async def on_error(self, interaction: BotInteraction, error: app_commands.AppCommandError) -> None:
        await report_error(interaction, error)


class Bot(discord.Client):
    def __init__(self, cfg: Config, db: sqlite3.Connection, members_intent: bool):
        intents = discord.Intents.default()
        intents.members = members_intent
        # Never ping anyone: replies can echo text users typed (e.g. /stats player:<@&role>). Mentions still
        # display, and embeds never ping anyway.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.cfg = cfg
        self.store = Store(db)
        self.whitelist = Whitelist(db, cfg.whitelist_file, cfg.protected_steamids)
        self.oauth_states = OAuthStates(db)
        self.server = ServerState()
        self.oauth: OAuth | None = None
        self._presence: str | None = None
        self._alert_dm_retry_at = 0.0  # after a failed alert DM, don't retry before this time
        # server installs only, used inside servers only (no user installs, no DMs)
        self.tree = Tree(self, allowed_installs=app_commands.AppInstallationType(guild=True, user=False),
                         allowed_contexts=app_commands.AppCommandContext(guild=True))
        commands.register(self.tree)

    async def setup_hook(self):
        with contextlib.suppress(WhitelistWriteError):  # logged; retried on the next whitelist change
            self.whitelist.write_file()
        if self.cfg.oauth_enabled:
            app_id = (await self.application_info()).id
            self.oauth = OAuth(self, self.whitelist, self.oauth_states, self.cfg, app_id)
            await self.oauth.start()
        else:
            log.warning("DISCORD_CLIENT_SECRET / PUBLIC_URL not set: whitelist linking is disabled")
        await self.tree.sync()  # global commands
        self.add_view(Dashboard())  # route dashboard button clicks, also on messages posted before a restart
        self.poll.start()
        self.hourly_member_check.start()

    async def on_ready(self):
        log.info("logged in as %s (%s)", self.user, self.user.id)
        if not self.cfg.allowed_guilds:
            log.warning("ALLOWED_GUILDS is empty: every command, button and whitelist link is refused")
        for guild in self.guilds:
            if guild.id not in self.cfg.allowed_guilds:
                log.warning("in guild %s (%s), which is not in ALLOWED_GUILDS: ignoring it", guild.name, guild.id)
        perms = discord.Permissions(view_channel=True, send_messages=True, embed_links=True,
                                    read_message_history=True)
        log.info("invite link: %s",
                 discord.utils.oauth_url(self.user.id, permissions=perms, scopes=("bot", "applications.commands")))

    async def close(self):
        if self.oauth:
            await self.oauth.stop()
        await super().close()

    # ---- whitelist upkeep ----
    async def on_member_remove(self, member: discord.Member):
        entry = self.whitelist.by_discord(member.id)
        if entry and entry.guild_id == member.guild.id:
            self.whitelist.remove_discord(member.id, AuditAction.LEFT_DISCORD, "bot")

    async def on_guild_remove(self, guild: discord.Guild):
        log.warning("removed from guild %s (%s)", guild.name, guild.id)
        await self.notify_orphans(left_guild=guild)

    @tasks.loop(hours=1)
    async def hourly_member_check(self):
        """Catch people who left their Discord server while the bot was down (works without the members
        intent), and tell the admin about entries the bot can no longer manage."""
        await self.notify_orphans()
        for entry in self.whitelist.entries():
            guild = self.get_guild(entry.guild_id) if entry.discord_id else None
            if not guild:
                continue
            try:
                await guild.fetch_member(entry.discord_id)
            except discord.NotFound:
                self.whitelist.remove_discord(entry.discord_id, AuditAction.NOT_IN_DISCORD, "bot hourly check")
            except discord.HTTPException as exc:
                log.warning("member check failed for %s: %s", entry.discord_name, exc)

    @hourly_member_check.before_loop
    async def before_member_check(self):
        await self.wait_until_ready()

    async def notify_orphans(self, left_guild: discord.Guild | None = None):
        """DM the admin once per orphaned entry. An entry that recovers and breaks again is reported again."""
        orphans = find_orphans(self.whitelist.entries(), self.cfg.allowed_guilds, self.get_guild, left_guild)
        notified = set(self.store.get(StateKey.ORPHANS_NOTIFIED, []))
        new, still_notified = split_notified(orphans, notified)
        if new and await self.dm_admin(format_orphan_dm(self.cfg.server_name, new)):
            still_notified |= {orphan.entry.steamid for orphan in new}
            log.info("sent orphaned-entry DM about %d entries", len(new))
        if still_notified != notified:
            self.store.set(StateKey.ORPHANS_NOTIFIED, sorted(still_notified))

    async def dm_admin(self, text: str) -> bool:
        """DM NOTIFY_USER_ID. False if nobody is configured or the DM failed (the caller retries later)."""
        if not self.cfg.notify_user_id:
            return False
        try:
            user = self.get_user(self.cfg.notify_user_id) or await self.fetch_user(self.cfg.notify_user_id)
            await user.send(text[:MESSAGE_LIMIT])
            return True
        except discord.HTTPException as exc:
            log.warning("could not DM %s: %s", self.cfg.notify_user_id, exc)
            return False

    # ---- admin alerts ----
    async def check_alerts(self):
        """DM the admin when an alert starts and when it clears. Active alerts are stored, so a bot restart
        during an outage doesn't repeat the DM."""
        now = time.time()
        if now < self._alert_dm_retry_at:
            return
        current = active_alerts(self.cfg.server_name, self.server, self.store, self.whitelist, now)
        notified = self.store.get(StateKey.ADMIN_ALERTS, {})
        changed = False
        for alert, text in current.items():
            if alert not in notified:
                if not await self.dm_admin(text):
                    self._alert_dm_retry_at = now + ALERT_DM_RETRY_SECONDS
                    break
                log.warning("admin alert: %s", alert)
                notified[alert], changed = now, True
        for name in [name for name in notified if name not in current]:
            alert = Alert(name)
            if not await self.dm_admin(recovered_text(alert, self.cfg.server_name, notified[name], now)):
                self._alert_dm_retry_at = now + ALERT_DM_RETRY_SECONDS
                break
            log.info("admin alert cleared: %s", alert)
            del notified[name]
            changed = True
        if changed:
            self.store.set(StateKey.ADMIN_ALERTS, notified)

    # ---- server status ----
    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        # An exception would stop this loop for good (discord.ext.tasks), freezing the dashboard: log it and
        # try again next time. The heartbeat is only written after a good poll, so the healthcheck sees
        # repeated failures.
        try:
            await self.poll_once()
        except Exception:
            log.exception("poll failed; retrying in %d s", POLL_SECONDS)
            return
        with contextlib.suppress(OSError), open(HEARTBEAT_FILE, "w") as f:
            f.write(str(int(time.time())))

    async def poll_once(self):
        if count := self.store.ingest(self.cfg.events_log):
            log.info("ingested %d event lines", count)
        self.server.record_probe(await self.server_info())
        if self.server.confirmed_offline and self.store.online():
            # the log had no clean disconnect (crash, container restart): end sessions at the first failed probe
            closed = self.store.close_all(int(self.server.offline_since))
            log.info("closed %d stale sessions", closed)
        if self.whitelist.write_error:  # a whitelist change didn't reach the file: keep retrying
            with contextlib.suppress(WhitelistWriteError):
                self.whitelist.write_file()
        await self.check_alerts()
        await self.update_presence()
        await self.update_dashboard()

    @poll.before_loop
    async def before_poll(self):
        await self.wait_until_ready()

    async def server_info(self) -> a2s.ServerInfo | None:
        """Probe the game server: None if it is down, else its info. A public server answers A2S with its
        info; an unlisted one (ours) only proves it is up, so the info is built from the events log instead
        (players online, version)."""
        try:
            online, info = await asyncio.to_thread(a2s.probe, self.cfg.a2s_host, self.cfg.a2s_port)
        except OSError as exc:
            log.debug("probe failed: %s", exc)
            return None
        if not online:
            return None
        return info or a2s.ServerInfo(self.cfg.server_name, len(self.store.online()), self.cfg.max_players,
                                      self.store.get(StateKey.VERSION, ""))

    async def update_presence(self):
        info = self.server.info
        if info:
            text, status = f"{info.players}/{info.max_players} on {self.cfg.server_name}", discord.Status.online
        else:
            text, status = f"{self.cfg.server_name} offline", discord.Status.dnd
        if text != self._presence:
            self._presence = text
            await self.change_presence(status=status,
                                       activity=discord.Activity(type=discord.ActivityType.watching, name=text))

    async def update_dashboard(self):
        ref = self.store.get(StateKey.DASHBOARD)
        if not ref:
            return
        embed = status_embed(self.cfg, self.server, self.store, join_steps_field=True)
        try:
            await (await dashboard_message(self, ref)).edit(embed=embed, view=Dashboard())
        except discord.NotFound:
            log.warning("dashboard message is gone; run /setup-dashboard again")
            self.store.set(StateKey.DASHBOARD, None)
        except discord.HTTPException as exc:
            log.warning("could not edit the dashboard: %s", exc)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    db = connect(cfg.db_path)  # one connection, reused if the bot has to start again without the members intent
    try:
        Bot(cfg, db, members_intent=True).run(cfg.token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        log.warning("Server Members Intent is not enabled in the Developer Portal - running without it; "
                    "people leaving the Discord are removed from the whitelist by the hourly check instead")
        Bot(cfg, db, members_intent=False).run(cfg.token, log_handler=None)
    finally:
        db.close()


if __name__ == "__main__":
    main()
