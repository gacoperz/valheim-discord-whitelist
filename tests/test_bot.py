"""Config parsing, formatting, and guards on things the live Discord messages depend on."""
import asyncio

import pytest

from bot.config import Config, is_steamid64
from bot.embeds import fmt_duration
from bot.server import ServerState


def test_config_reads_lists_split_by_spaces_or_commas(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_GUILDS", "1, 2 3")
    monkeypatch.setenv("PROTECTED_STEAMIDS", "76561198000000001")
    monkeypatch.delenv("NOTIFY_USER_ID", raising=False)
    cfg = Config.from_env()
    assert cfg.allowed_guilds == {1, 2, 3}
    assert cfg.protected_steamids == ("76561198000000001",)
    assert cfg.notify_user_id is None
    assert not cfg.oauth_enabled


@pytest.mark.parametrize(("value", "valid"), [
    ("76561198000000042", True),
    ("7656119801290003", False),  # 16 digits
    ("12345678901234567", False),  # wrong prefix
    ("7656119x012900033", False),  # not all digits
])
def test_steamid64_validation(value, valid):
    assert is_steamid64(value) is valid


@pytest.mark.parametrize(("seconds", "text"), [(59, "0m"), (61, "1m"), (3720, "1h 2m"), (90000, "1d 1h")])
def test_fmt_duration(seconds, text):
    assert fmt_duration(seconds) == text


def test_server_goes_offline_only_after_repeated_failed_probes():
    server = ServerState()
    server.record_probe(True, 100)
    server.record_probe(False, 130)
    assert server.online  # one miss is tolerated
    server.record_probe(False, 160)
    assert not server.online and not server.confirmed_offline
    server.record_probe(False, 190)
    assert server.confirmed_offline


def test_offline_since_is_the_first_failed_probe():
    """Stale sessions are closed at this time, and the offline alert counts from it."""
    server = ServerState()
    server.record_probe(True, 100)
    for probe_time in (130, 160, 190):
        server.record_probe(False, probe_time)
    assert server.offline_since == 130 and server.last_ok == 100
    assert server.offline_for(700) == 570
    server.record_probe(True, 720)
    assert server.offline_since is None and server.offline_for(750) == 0


def test_a_single_failed_probe_does_not_count_as_offline():
    server = ServerState()
    server.record_probe(True, 100)
    server.record_probe(False, 130)
    assert server.offline_for(1000) == 0  # still online
    server.record_probe(True, 160)
    assert server.offline_since is None


def test_poll_survives_errors_and_only_a_good_poll_writes_the_heartbeat(tmp_path, monkeypatch):
    from bot import main

    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setattr(main, "HEARTBEAT_FILE", str(heartbeat))

    class FakeBot:
        def __init__(self, fail):
            self.fail = fail

        async def poll_once(self):
            if self.fail:
                raise RuntimeError("database is locked")

    asyncio.run(main.Bot.poll.coro(FakeBot(fail=True)))  # must not raise: the loop keeps running
    assert not heartbeat.exists()
    asyncio.run(main.Bot.poll.coro(FakeBot(fail=False)))
    assert heartbeat.exists()


def test_hourly_member_check_survives_errors():
    from bot import main

    class FakeBot:
        async def member_check(self):
            raise RuntimeError("cannot write permittedlist.txt")

    asyncio.run(main.Bot.hourly_member_check.coro(FakeBot()))  # must not raise: the loop keeps running


def remove_reply(tmp_path, protected_member: bool, **target) -> str:
    """Run /whitelist-admin remove with a fake interaction; return what the bot replied."""
    from types import SimpleNamespace

    from bot.commands import whitelist_remove
    from bot.store import connect
    from bot.whitelist import Whitelist

    owner, player = "76561198000000001", "76561198000000002"
    path = tmp_path / "permittedlist.txt"
    path.write_text("")
    whitelist = Whitelist(connect(":memory:"), str(path), [owner])
    whitelist.link(7, "someone", 1, owner if protected_member else player, "Steam")
    replies = []

    async def send_message(text, **kwargs):
        replies.append(text)
    interaction = SimpleNamespace(client=SimpleNamespace(whitelist=whitelist), user="admin",
                                  response=SimpleNamespace(send_message=send_message))
    asyncio.run(whitelist_remove.callback(interaction, **target))
    return replies[0]


def test_removing_the_owner_by_member_says_they_can_still_join(tmp_path):
    from types import SimpleNamespace
    member = SimpleNamespace(id=7, mention="<@7>")
    assert "protected owner ID" in remove_reply(tmp_path, True, member=member)
    assert "protected owner ID" not in remove_reply(tmp_path, False, member=member)


def test_removing_the_owner_by_steamid_says_they_can_still_join(tmp_path):
    assert "protected owner ID" in remove_reply(tmp_path, True, steamid="76561198000000001")
    assert "protected owner ID" not in remove_reply(tmp_path, False, steamid="76561198000000002")


def test_dashboard_button_ids_never_change():
    """The posted dashboard message stores these IDs; renaming one breaks that button."""
    from bot.views import Dashboard

    async def ids():
        return [(item.label, item.custom_id) for item in Dashboard().children]
    assert asyncio.run(ids()) == [
        ("Join whitelist", "wl:join"), ("Leave whitelist", "wl:leave"), ("Whitelist status", "wl:me"),
        ("Leaderboard", "st:top"), ("My stats", "st:me"),
    ]


def test_commands_register():
    import discord
    from discord import app_commands

    from bot import commands

    async def names():
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        commands.register(tree)
        return sorted(command.name for command in tree.get_commands())
    assert asyncio.run(names()) == ["setup-dashboard", "stats", "status", "whitelist-admin"]


def test_the_bot_never_pings():
    """Replies can echo user input, e.g. /stats player:<@&role>; the client must not turn that into a ping."""
    from bot import main
    from bot.config import Config
    from bot.store import connect

    cfg = Config(token="t", client_secret="", public_url="", server_name="H", join_address="", a2s_host="h",
                 a2s_port=1, max_players=10, events_log="", world_dir="", db_path=":memory:", whitelist_file="",
                 motd_file="", protected_steamids=(), allowed_guilds=frozenset(), notify_user_id=None)

    async def mentions():
        return main.Bot(cfg, connect(":memory:"), members_intent=False).allowed_mentions
    allowed = asyncio.run(mentions())
    assert (allowed.everyone, allowed.users, allowed.roles, allowed.replied_user) == (False, False, False, False)


@pytest.mark.parametrize(("manage_guild", "allowed"), [(True, True), (False, False)])
def test_whitelist_admin_checks_manage_server_when_run(manage_guild, allowed):
    """Hiding the group isn't enough: an Integrations override could show it to anyone."""
    from types import SimpleNamespace

    import discord
    from discord import app_commands

    from bot.commands import whitelist_admin

    interaction = SimpleNamespace(permissions=discord.Permissions(manage_guild=manage_guild))
    if allowed:
        assert asyncio.run(whitelist_admin.interaction_check(interaction)) is True
    else:
        with pytest.raises(app_commands.MissingPermissions):
            asyncio.run(whitelist_admin.interaction_check(interaction))


def test_every_admin_command_is_protected():
    """Each admin command either lives in the checked group or has its own runtime check."""
    from bot.commands import ManageServerGroup, setup_dashboard, whitelist_admin

    assert isinstance(whitelist_admin, ManageServerGroup)
    assert sorted(command.name for command in whitelist_admin.commands) == [
        "add", "attempts", "ban", "history", "list", "remove", "unban"]
    assert setup_dashboard.checks  # has_permissions(manage_guild=True)
