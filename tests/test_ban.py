"""Ban and unban through the real commands, the Join button, the status button and the login page."""
import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot.commands import whitelist_add, whitelist_ban, whitelist_unban
from bot.embeds import BLOCKED, whitelist_status_message
from bot.store import Store, connect
from bot.views import send_join_link
from bot.whitelist import Whitelist

OWNER, ALICE, BOB = "76561198000000001", "76561198000000002", "76561198000000003"


@pytest.fixture
def bot(tmp_path):
    path = tmp_path / "permittedlist.txt"
    path.write_text("")
    db = connect(":memory:")
    whitelist = Whitelist(db, str(path), [OWNER])
    oauth = SimpleNamespace(authorize_url=lambda discord_id, guild_id: "https://discord.example/authorize")
    return SimpleNamespace(whitelist=whitelist, store=Store(db), oauth=oauth,
                           cfg=SimpleNamespace(join_address="1.2.3.4:2456"))


def run(bot, command, user_id=1, **options):
    """Invoke a command or helper with a fake interaction; return the reply text."""
    replies = []

    async def send_message(text=None, **kwargs):
        replies.append(text)
    interaction = SimpleNamespace(client=bot, user=SimpleNamespace(id=user_id, __str__=lambda self: "admin"),
                                  guild_id=1, response=SimpleNamespace(send_message=send_message))
    callback = command.callback if hasattr(command, "callback") else command
    asyncio.run(callback(interaction, **options))
    return replies[0]


def member(user_id, name="alice"):
    return SimpleNamespace(id=user_id, mention=f"<@{user_id}>", __str__=lambda self: name)


def test_ban_by_member_removes_them_and_blocks_their_discord_account(bot):
    bot.whitelist.link(7, "alice", 1, ALICE, "AliceSteam")
    reply = run(bot, whitelist_ban, member=member(7), reason="griefing")
    assert "removed from the whitelist" in reply and ALICE in reply and "<@7>" in reply
    assert bot.whitelist.by_steam(ALICE) is None
    assert run(bot, send_join_link, user_id=7) == BLOCKED  # the Join button refuses before the login
    assert whitelist_status_message(bot.cfg, bot.whitelist, bot.store, 7) == BLOCKED


def test_ban_by_steamid_and_manual_add_is_refused(bot):
    assert "Banned" in run(bot, whitelist_ban, steamid=f" {BOB} ")
    assert "banned. Unban it first" in run(bot, whitelist_add, steamid=BOB, note="bob")


def test_protected_owner_cannot_be_banned(bot):
    assert "can't be banned" in run(bot, whitelist_ban, steamid=OWNER)
    assert bot.whitelist.blocks() == []


def test_invalid_or_missing_target(bot):
    assert "not a SteamID64" in run(bot, whitelist_ban, steamid="123")
    assert "Give a member" in run(bot, whitelist_ban)


def test_unban_then_the_join_button_works_again(bot):
    bot.whitelist.link(7, "alice", 1, ALICE, "AliceSteam")
    run(bot, whitelist_ban, member=member(7))
    assert "Unbanned" in run(bot, whitelist_unban, steamid=ALICE)
    assert run(bot, send_join_link, user_id=7) != BLOCKED
    assert "isn't banned" in run(bot, whitelist_unban, steamid=ALICE)


def test_login_page_refuses_a_banned_steam_account(bot, tmp_path):
    from bot.web import OAuth, OAuthStates
    bot.whitelist.ban(steamid=ALICE, discord_id=None, name="alice", reason=None, actor="admin")
    cfg = SimpleNamespace(public_url="https://example", server_name="Midgard", join_address="1.2.3.4:2456",
                          allowed_guilds=frozenset({1}), client_secret="s", motd_file=str(tmp_path / "none.md"))

    class Guild:
        async def fetch_member(self, discord_id):
            return "member"
    oauth = OAuth(SimpleNamespace(get_guild=lambda guild_id: Guild()), bot.whitelist,
                  OAuthStates(bot.whitelist.db), cfg, 42)

    async def identity(code):
        return SimpleNamespace(user_id="9", connections=[{"type": "steam", "verified": True, "id": ALICE,
                                                          "name": "Alice"}])
    oauth._fetch_identity = identity
    request = SimpleNamespace(query={"code": "c", "state": oauth.states.create(9, 1)})
    response = asyncio.run(oauth.callback(request))
    assert response.status == 403 and "Blocked" in response.text
    assert bot.whitelist.by_steam(ALICE) is None


def test_blocked_error_reply():
    from bot.views import report_error
    from bot.whitelist import Block, WhitelistBlocked
    replies = []

    async def send_message(text, **kwargs):
        replies.append(text)
    interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: False, send_message=send_message))
    asyncio.run(report_error(interaction, WhitelistBlocked(Block(ALICE, None, "a", None, 0, "admin"))))
    assert replies == [BLOCKED]


def test_discord_member_type_is_what_the_command_expects():
    """The ban and unban commands take a discord.Member, like remove."""
    params = {p.name: p for p in whitelist_ban.parameters}
    assert params["member"].type == discord.AppCommandOptionType.user
