"""permittedlist.txt rendering (never empty, owner always on it) and the audit trail."""
import pytest

from bot.store import connect
from bot.whitelist import HEADER, PLACEHOLDER_ID, AuditAction, Whitelist, WhitelistBlocked, WhitelistWriteError

OWNER = "76561198000000001"
ALICE = "76561198000000002"
BOB = "76561198000000003"


@pytest.fixture
def listfile(tmp_path):
    path = tmp_path / "permittedlist.txt"
    path.write_text("")
    return path


def make(listfile, protected=()):
    return Whitelist(connect(":memory:"), str(listfile), protected)


def ids_in(listfile):
    return listfile.read_text().removeprefix(HEADER).split()


def actions(whitelist):
    return [record.action for record in reversed(whitelist.history())]


def test_empty_whitelist_writes_the_placeholder(listfile):
    make(listfile).write_file()
    assert ids_in(listfile) == [PLACEHOLDER_ID]  # an empty file would let everyone in


def test_protected_ids_are_always_written(listfile):
    whitelist = make(listfile, protected=[OWNER])
    whitelist.link(1, "owner", 10, OWNER, "Owner")
    whitelist.remove_discord(1, AuditAction.LEAVE, "owner")
    assert ids_in(listfile) == [OWNER]


def test_link_replaces_a_manual_entry_and_records_it(listfile):
    whitelist = make(listfile)
    whitelist.add_manual(ALICE, "Alice's PC", "admin")
    whitelist.link(1, "alice", 10, ALICE, "Alice")
    entry = whitelist.by_steam(ALICE)
    assert entry.discord_id == 1 and not entry.is_manual
    assert actions(whitelist) == [AuditAction.ADD_MANUAL, AuditAction.MANUAL_REPLACED, AuditAction.LINK]


def test_relinking_another_account_replaces_the_old_one(listfile):
    whitelist = make(listfile)
    whitelist.link(1, "alice", 10, ALICE, "Alice")
    whitelist.link(1, "alice", 10, BOB, "Alice2")
    assert ids_in(listfile) == [BOB]
    assert AuditAction.RELINK_REPLACED in actions(whitelist)


def test_remove_returns_the_entry_and_is_audited(listfile):
    whitelist = make(listfile)
    whitelist.add_manual(ALICE, "note", "admin")
    removed = whitelist.remove_steam(ALICE, AuditAction.REMOVE_ADMIN, "admin")
    assert removed.steamid == ALICE
    assert whitelist.remove_steam(ALICE, AuditAction.REMOVE_ADMIN, "admin") is None
    assert actions(whitelist)[-1] == AuditAction.REMOVE_ADMIN
    assert ids_in(listfile) == [PLACEHOLDER_ID]


def test_add_manual_refuses_duplicates(listfile):
    whitelist = make(listfile)
    assert whitelist.add_manual(ALICE, "a", "admin")
    assert not whitelist.add_manual(ALICE, "b", "admin")


def test_unwritable_file_raises_whitelist_write_error(tmp_path):
    whitelist = Whitelist(connect(":memory:"), str(tmp_path / "missing" / "permittedlist.txt"))
    with pytest.raises(WhitelistWriteError):
        whitelist.add_manual(ALICE, "a", "admin")
    assert whitelist.by_steam(ALICE)  # the database change is kept and written on the next change


def test_write_error_is_remembered_until_a_write_succeeds(tmp_path):
    folder = tmp_path / "later"
    whitelist = Whitelist(connect(":memory:"), str(folder / "permittedlist.txt"))
    with pytest.raises(WhitelistWriteError):
        whitelist.add_manual(ALICE, "a", "admin")
    assert whitelist.write_error
    folder.mkdir()
    (folder / "permittedlist.txt").write_text("")
    whitelist.write_file()  # what the poll's retry does
    assert whitelist.write_error is None
    assert ALICE in (folder / "permittedlist.txt").read_text()


def test_ban_removes_and_blocks_relinking_and_manual_adding(listfile):
    whitelist = make(listfile)
    whitelist.link(7, "alice", 1, ALICE, "AliceSteam")
    removed = whitelist.ban(steamid=ALICE, discord_id=7, name="alice", reason="griefing", actor="admin")
    assert [entry.steamid for entry in removed] == [ALICE]
    assert ids_in(listfile) == [PLACEHOLDER_ID]
    with pytest.raises(WhitelistBlocked):
        whitelist.link(7, "alice", 1, ALICE, "AliceSteam")  # same accounts
    with pytest.raises(WhitelistBlocked):
        whitelist.link(7, "alice", 1, BOB, "Alt")  # same Discord user, another Steam account
    with pytest.raises(WhitelistBlocked):
        whitelist.add_manual(ALICE, "sneaky", "admin")
    assert actions(whitelist)[-1] == AuditAction.BAN


def test_steam_only_ban_does_not_block_other_discord_users(listfile):
    whitelist = make(listfile)
    whitelist.ban(steamid=ALICE, discord_id=None, name="alice", reason=None, actor="admin")
    whitelist.link(8, "bob", 1, BOB, "BobSteam")  # unrelated account still works
    assert whitelist.by_steam(BOB)


def test_discord_only_ban_blocks_that_user(listfile):
    whitelist = make(listfile)
    whitelist.ban(steamid=None, discord_id=7, name="alice", reason=None, actor="admin")
    with pytest.raises(WhitelistBlocked):
        whitelist.link(7, "alice", 1, ALICE, "AliceSteam")
    assert whitelist.history(1)[0].steamid == "-"


def test_unban_lifts_the_block_but_does_not_rewhitelist(listfile):
    whitelist = make(listfile)
    whitelist.link(7, "alice", 1, ALICE, "AliceSteam")
    whitelist.ban(steamid=ALICE, discord_id=7, name="alice", reason=None, actor="admin")
    lifted = whitelist.unban(steamid=ALICE, actor="admin")
    assert lifted.discord_id == 7  # the Discord block goes with it
    assert whitelist.blocked(ALICE, 7) is None and whitelist.by_steam(ALICE) is None
    whitelist.link(7, "alice", 1, ALICE, "AliceSteam")  # can join again the normal way
    assert actions(whitelist)[-2:] == [AuditAction.UNBAN, AuditAction.LINK]
    assert whitelist.unban(steamid=BOB, actor="admin") is None


def test_banning_again_replaces_the_block(listfile):
    whitelist = make(listfile)
    whitelist.ban(steamid=ALICE, discord_id=None, name="alice", reason="one", actor="admin")
    whitelist.ban(steamid=ALICE, discord_id=7, name="alice", reason="two", actor="admin")
    assert [(b.steamid, b.discord_id, b.reason) for b in whitelist.blocks()] == [(ALICE, 7, "two")]


def test_protected_ids_cannot_be_banned(listfile):
    whitelist = make(listfile, protected=[OWNER])
    whitelist.write_file()
    with pytest.raises(ValueError):
        whitelist.ban(steamid=OWNER, discord_id=None, name="owner", reason=None, actor="admin")
    assert whitelist.blocks() == [] and OWNER in ids_in(listfile)
