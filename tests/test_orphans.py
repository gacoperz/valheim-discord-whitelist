"""Which whitelist entries are orphaned, and that the admin hears about each one once."""
from types import SimpleNamespace

from bot.orphans import find_orphans, format_orphan_dm, split_notified
from bot.whitelist import WhitelistEntry

ALLOWED, NOT_ALLOWED, GONE = 1, 2, 3
GUILDS = {ALLOWED: SimpleNamespace(id=ALLOWED, name="Friends"), NOT_ALLOWED: SimpleNamespace(id=NOT_ALLOWED,
                                                                                              name="Other")}


def entry(steamid, guild_id, discord_id=10):
    return WhitelistEntry(steamid, discord_id, "someone", "SteamName", None, guild_id, 0)


def orphans(entries, left_guild=None):
    return find_orphans(entries, frozenset({ALLOWED}), GUILDS.get, left_guild)


def test_entries_from_allowed_servers_and_manual_entries_are_fine():
    assert orphans([entry("a", ALLOWED), entry("m", None, discord_id=None)]) == []


def test_entry_from_a_server_that_is_not_allowed():
    [orphan] = orphans([entry("a", NOT_ALLOWED)])
    assert (orphan.server_name, orphan.reason) == ("Other", "not in ALLOWED_GUILDS")


def test_entry_from_a_server_the_bot_left_names_it_only_when_just_left():
    assert orphans([entry("a", GONE)])[0].server_name == "a server I'm no longer in"
    just_left = SimpleNamespace(id=GONE, name="Old server")
    assert orphans([entry("a", GONE)], left_guild=just_left)[0].server_name == "Old server"


def test_each_orphan_is_reported_once_and_forgotten_after_recovery():
    first, second = orphans([entry("a", GONE), entry("b", GONE)])
    new, keep = split_notified([first, second], notified={"a", "recovered"})
    assert new == [second]  # "a" was already reported
    assert keep == {"a"}  # "recovered" is no longer an orphan, so it is forgotten


def test_dm_lists_every_orphan():
    text = format_orphan_dm("Midgard", orphans([entry("76561198000000001", GONE)]))
    assert "76561198000000001" in text and "stay whitelisted" in text
