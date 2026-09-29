"""Discord OAuth2 return page: reads the user's verified Steam connection and whitelists it."""
import html
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web

from . import motd
from .config import OAUTH_STATE_TTL, Config
from .whitelist import Whitelist, WhitelistWriteError

log = logging.getLogger("valheim-bot.web")
API = "https://discord.com/api/v10"
CALLBACK_PATH = "/discord/callback"
TRY_AGAIN = "Click <b>Join whitelist</b> on the dashboard in Discord to try again."

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{server} whitelist</title>
<style>body{{font-family:system-ui,sans-serif;background:#1e1f22;color:#dbdee1;display:grid;place-items:center;
min-height:100vh;margin:0;padding:16px;box-sizing:border-box}}main{{max-width:28rem;background:#2b2d31;
border-radius:12px;padding:2rem;text-align:center}}h1{{font-size:1.4rem;margin:.5rem 0}}p{{line-height:1.5}}
.icon{{font-size:3rem}}
.about{{display:block;text-align:left;border-top:1px solid #3f4147;margin-top:1.5rem;padding-top:1.5rem}}
code{{background:#1e1f22;padding:0 .3em;border-radius:4px}}</style></head>
<body><main><div class="icon">{icon}</div><h1>{title}</h1>
<p>{body}</p></main></body></html>"""

OAUTH_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY, discord_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, expires INTEGER NOT NULL
);
"""


class OAuthStates:
    """One-time tokens tying an OAuth round trip to the Discord user and server that started it."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        db.executescript(OAUTH_STATE_SCHEMA)

    def create(self, discord_id: int, guild_id: int) -> str:
        state, now = secrets.token_urlsafe(32), int(time.time())
        with self.db:  # also drops expired tokens and this user's older ones
            self.db.execute("DELETE FROM oauth_states WHERE expires < ? OR discord_id = ?", (now, discord_id))
            self.db.execute("INSERT INTO oauth_states VALUES (?, ?, ?, ?)",
                            (state, discord_id, guild_id, now + OAUTH_STATE_TTL))
        return state

    def take(self, state: str) -> tuple[int, int] | None:
        """(discord_id, guild_id) if the token is valid. A token works only once."""
        with self.db:
            row = self.db.execute(
                "SELECT discord_id, guild_id FROM oauth_states WHERE state=? AND expires >= ?",
                (state, int(time.time())),
            ).fetchone()
            self.db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
        return (row["discord_id"], row["guild_id"]) if row else None


@dataclass
class Identity:
    user_id: str
    connections: list[dict]


class Refusal(Exception):
    """Stops the callback early and shows `response` to the user."""

    def __init__(self, response: web.Response):
        self.response = response


class OAuth:
    def __init__(self, client: discord.Client, whitelist: Whitelist, states: OAuthStates, cfg: Config,
                 client_id: int):
        self.client, self.whitelist, self.states, self.cfg = client, whitelist, states, cfg
        self.client_id = client_id
        self.redirect_uri = cfg.public_url.rstrip("/") + CALLBACK_PATH
        self.runner: web.AppRunner | None = None

    def page(self, icon: str, title: str, body: str, status: int = 200) -> web.Response:
        return web.Response(
            text=PAGE.format(server=html.escape(self.cfg.server_name), icon=icon, title=html.escape(title), body=body),
            content_type="text/html", status=status,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"},
        )

    def refuse(self, icon: str, title: str, body: str, status: int) -> Refusal:
        return Refusal(self.page(icon, title, body, status))

    def authorize_url(self, discord_id: int, guild_id: int) -> str:
        return "https://discord.com/oauth2/authorize?" + urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "scope": "identify connections", "state": self.states.create(discord_id, guild_id), "prompt": "none",
        })

    async def start(self, port: int = 8080) -> None:
        app = web.Application()
        app.router.add_get(CALLBACK_PATH, self.callback)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", port).start()
        log.info("OAuth callback listening on :%d (redirect URI %s)", port, self.redirect_uri)

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()

    # ---- the return page ----
    async def callback(self, request: web.Request) -> web.Response:
        try:
            if request.query.get("error"):
                return self.page("✋", "Cancelled", "Nothing was changed. " + TRY_AGAIN)
            discord_id, guild_id = self._claim_state(request)
            identity = await self._fetch_identity(request.query["code"])
            if identity.user_id != str(discord_id):
                raise self.refuse("🚫", "Wrong Discord account",
                                  "You authorized with a different Discord account than the one that clicked "
                                  "<b>Join whitelist</b>. Log into the right account and try again.", 403)
            member = await self._member(guild_id, discord_id)
            steamid, steam_name = self._verified_steam(identity)
            self._check_not_linked_elsewhere(steamid, discord_id)
            self.whitelist.link(discord_id, str(member), guild_id, steamid, steam_name)
        except Refusal as refusal:
            return refusal.response
        except WhitelistWriteError:
            return self.page("⚠️", "Server problem", "Your account was verified, but the whitelist file couldn't "
                             "be updated. Please tell the server admin.", 500)
        else:
            log.info("whitelisted %s (%s) -> steam %s (%s)", member, discord_id, steamid, steam_name)
            return self.page("✅", "You're on the whitelist!",
                             f"Steam account <b>{html.escape(steam_name)}</b> can now join "
                             f"<b>{html.escape(self.cfg.server_name)}</b>.<br><br>In Valheim: <b>Join Game → Add "
                             f"server</b> → <code>{html.escape(self.cfg.join_address)}</code>"
                             + self._about() + "<br><br>You can close this tab.")

    def _about(self) -> str:
        """The message of the day as an HTML section, or nothing."""
        text = motd.load(self.cfg.motd_file)
        return f'<span class="about">{motd.to_html(text)}</span>' if text else ""  # a span: it sits inside <p>

    def _claim_state(self, request: web.Request) -> tuple[int, int]:
        code, state = request.query.get("code"), request.query.get("state")
        claim = self.states.take(state) if code and state else None
        if not claim:
            raise self.refuse("⌛", "Link expired", f"This link was already used or is older than "
                              f"{OAUTH_STATE_TTL // 60} minutes. " + TRY_AGAIN, 400)
        discord_id, guild_id = claim
        if guild_id not in self.cfg.allowed_guilds:
            log.warning("refused whitelist link for %s from guild %s (not allowed)", discord_id, guild_id)
            raise self.refuse("🚫", "Not allowed", f"Whitelist links only work from the "
                              f"{html.escape(self.cfg.server_name)} Discord servers.", 403)
        return discord_id, guild_id

    async def _fetch_identity(self, code: str) -> Identity:
        """Swap the code for a token, read the user and their connections, then revoke the token."""
        auth = aiohttp.BasicAuth(str(self.client_id), self.cfg.client_secret)
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{API}/oauth2/token", auth=auth, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            }) as resp:
                if resp.status != 200:
                    log.warning("token exchange failed: %s %s", resp.status, await resp.text())
                    raise self._login_failed()
                token = (await resp.json())["access_token"]
            try:
                headers = {"Authorization": f"Bearer {token}"}
                me = await self._get_json(http, "/users/@me", headers)
                connections = await self._get_json(http, "/users/@me/connections", headers)
            finally:  # we never keep the user's token
                await http.post(f"{API}/oauth2/token/revoke", auth=auth,
                                data={"token": token, "token_type_hint": "access_token"})
        if me is None or not isinstance(connections, list):
            raise self._login_failed()
        return Identity(str(me.get("id")), connections)

    def _login_failed(self) -> Refusal:
        return self.refuse("⚠️", "Discord login failed", TRY_AGAIN, 502)

    @staticmethod
    async def _get_json(http: aiohttp.ClientSession, path: str, headers: dict):
        async with http.get(API + path, headers=headers) as resp:
            if resp.status != 200:
                log.warning("GET %s failed: %s %s", path, resp.status, await resp.text())
                return None
            return await resp.json()

    async def _member(self, guild_id: int, discord_id: int) -> discord.Member:
        guild = self.client.get_guild(guild_id)
        if guild:
            try:
                return await guild.fetch_member(discord_id)
            except discord.NotFound:
                pass
        raise self.refuse("🚫", "Not a member",
                          f"You need to be in the {html.escape(self.cfg.server_name)} Discord.", 403)

    def _verified_steam(self, identity: Identity) -> tuple[str, str]:
        steam = [connection for connection in identity.connections
                 if connection.get("type") == "steam" and connection.get("verified")]
        if not steam:
            raise self.refuse("🔗", "No Steam account linked",
                              "Your Discord has no verified Steam connection. Add it in Discord under "
                              "<b>User Settings → Connections → Steam</b>. " + TRY_AGAIN, 400)
        return steam[0]["id"], steam[0].get("name", "")

    def _check_not_linked_elsewhere(self, steamid: str, discord_id: int) -> None:
        entry = self.whitelist.by_steam(steamid)
        if entry and entry.discord_id not in (None, discord_id):
            raise self.refuse("🚫", "Steam account already linked",
                              "This Steam account is already whitelisted for another Discord member. "
                              "Ask an admin if that's wrong.", 409)
