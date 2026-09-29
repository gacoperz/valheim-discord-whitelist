"""Advice on the Whitelist status button, taken from the player's failed joins and sessions."""
import time

import pytest

from bot.embeds import format_whitelist_entry, join_diagnosis
from bot.store import LastPlayed, Store, connect
from bot.whitelist import WhitelistEntry

ALICE = "76561198000000002"
STRANGER = "76561198000000009"


@pytest.fixture
def store():
    return Store(connect(":memory:"))


def entry(added_at=1000):
    return WhitelistEntry(ALICE, 42, "alice", "AliceSteam", None, 1, added_at)


def ingest(store, tmp_path, *lines):
    path = tmp_path / "events.log"
    path.write_text("".join(f"{line}\n" for line in lines))
    store.ingest(str(path))


def test_never_connected(store):
    assert "hasn't connected to the server yet" in join_diagnosis(store, entry())


def test_wrong_version_explains_the_versions(store, tmp_path):
    ingest(store, tmp_path, f"2000 Peer {ALICE} has incompatible version, mine:1.0.16 (network version 40)   "
                            "remote 1.0.15 (network version 39)")
    text = join_diagnosis(store, entry())
    assert "doesn't match" in text and "server 1.0.16, player 1.0.15" in text


def test_refusal_before_whitelisting_says_try_again(store, tmp_path):
    ingest(store, tmp_path, f"500 Player Alice : {ALICE} is blacklisted or not in whitelist.")
    assert "before you were whitelisted" in join_diagnosis(store, entry(added_at=1000))


def test_refusal_while_whitelisted_asks_for_the_admin(store, tmp_path):
    ingest(store, tmp_path, f"2000 Player Alice : {ALICE} is blacklisted or not in whitelist.")
    assert "Tell the admin" in join_diagnosis(store, entry(added_at=1000))


def test_a_later_session_hides_an_old_failure(store, tmp_path):
    now = int(time.time())
    ingest(store, tmp_path,
           f"{now - 300} Player Alice : {ALICE} is blacklisted or not in whitelist.",
           f"{now - 200} Got handshake from client {ALICE}",
           f"{now - 190} Got character ZDOID from Alice : 5:1",
           f"{now - 100} Closing socket {ALICE}")
    assert join_diagnosis(store, entry(added_at=now - 1000)) == f"Last played <t:{now - 100}:R>."


@pytest.mark.parametrize(("played", "text"), [
    (None, "never played"),
    (LastPlayed(500, False), "played <t:500:R>"),
    (LastPlayed(500, True), "🟢 online now"),
])
def test_whitelist_list_line_shows_last_played(played, text):
    line = format_whitelist_entry(entry(), protected=False, played=played)
    assert line.endswith(text) and "<@42>" in line and "added <t:1000:d>" in line


def test_hints_at_a_different_steam_account(store, tmp_path):
    ingest(store, tmp_path, f"900 Player Alice Viking : {STRANGER} is blacklisted or not in whitelist.")
    text = join_diagnosis(store, entry(added_at=1000))
    assert "**Alice Viking**" in text and "different Steam account" in text
    assert STRANGER not in text  # other people's Steam IDs are not shown to players
