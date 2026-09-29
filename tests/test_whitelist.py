"""permittedlist.txt rendering (never empty, owner always on it) and the audit trail."""
import pytest

from bot.store import connect
from bot.whitelist import HEADER, PLACEHOLDER_ID, AuditAction, Whitelist, WhitelistWriteError

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
