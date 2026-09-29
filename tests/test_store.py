"""Events-log parsing (handshake -> session matching) and the online-time merge."""
import pytest

from bot.store import JoinProblem, LastPlayed, StateKey, Store, connect


@pytest.fixture
def store():
    return Store(connect(":memory:"))


@pytest.fixture
def events(tmp_path):
    path = tmp_path / "events.log"
    path.write_text("")

    def add(*lines: str) -> str:
        with path.open("a") as f:
            f.writelines(f"{line}\n" for line in lines)
        return str(path)
    return add


def sessions(store):
    return [tuple(row) for row in store.db.execute("SELECT name, steamid, start, end FROM sessions ORDER BY id")]


def test_characters_are_matched_to_handshakes_in_order(store, events):
    log = events(
        "100 Got handshake from client 111",
        "101 Got handshake from client 222",
        "110 Got character ZDOID from Alice : 5:1",
        "120 Got character ZDOID from Bob : 6:1",
        "200 Closing socket 111",
    )
    assert store.ingest(log) == 5
    assert sessions(store) == [("Alice", "111", 110, 200), ("Bob", "222", 120, None)]
    assert store.online() == [("Bob", 120)]


def test_rejected_connection_does_not_shift_the_matching(store, events):
    log = events(
        "100 Got handshake from client 999",  # not whitelisted: disconnects without a character
        "101 Closing socket 999",
        "102 Got handshake from client 111",
        "110 Got character ZDOID from Alice : 5:1",
    )
    store.ingest(log)
    assert sessions(store) == [("Alice", "111", 110, None)]
    assert store.get(StateKey.PENDING_HANDSHAKES) == []


def test_respawn_keeps_the_session_and_death_is_counted(store, events):
    log = events(
        "100 Got handshake from client 111",
        "110 Got character ZDOID from Alice : 5:1",
        "150 Got character ZDOID from Alice : 0:0",  # died
        "160 Got character ZDOID from Alice : 5:2",  # respawned
    )
    store.ingest(log)
    assert sessions(store) == [("Alice", "111", 110, None)]
    assert store.stats("alice")[0].deaths == 1


def test_server_restart_closes_sessions_and_clears_pending(store, events):
    log = events(
        "100 Got handshake from client 111",
        "110 Got character ZDOID from Alice : 5:1",
        "120 Got handshake from client 222",
        "300 Game server connected",
        "301 Valheim version: l-1.0.16 (network version 40)",
    )
    store.ingest(log)
    assert sessions(store) == [("Alice", "111", 110, 300)]
    assert store.get(StateKey.PENDING_HANDSHAKES) == []
    assert store.get(StateKey.SERVER_STARTED) == 300
    assert store.get(StateKey.VERSION) == "1.0.16"


def attempts(store):
    return [(a.ts, a.steamid, a.name, a.problem, a.detail) for a in reversed(store.join_attempts())]


def test_refusals_are_recorded_with_their_reason(store, events):
    # wording and order as in the game's ZNet code: handshake, refusal, then the socket closes
    log = events(
        "100 Got handshake from client 76561198000000009",
        "101 Player Stranger Danger : 76561198000000009 is blacklisted or not in whitelist.",
        "102 Closing socket 76561198000000009",
        "200 Got handshake from client 76561198000000002",
        "201 Peer 76561198000000002 has incompatible version, mine:1.0.16 (network version 40)   "
        "remote 1.0.15 (network version 39)",
        "202 Closing socket 76561198000000002",
    )
    store.ingest(log)
    assert attempts(store) == [
        (101, "76561198000000009", "Stranger Danger", JoinProblem.NOT_WHITELISTED, None),
        (201, "76561198000000002", None, JoinProblem.WRONG_VERSION, "server 1.0.16, player 1.0.15"),
    ]  # the closes right after a refusal are not recorded again as "dropped"
    assert sessions(store) == []


def test_disconnect_without_character_or_reason_counts_as_dropped(store, events):
    store.ingest(events("100 Got handshake from client 111", "160 Closing socket 111"))
    assert attempts(store) == [(160, "111", None, JoinProblem.DROPPED, None)]


def test_kick_from_permitted_list_ends_the_session(store, events):
    log = events(
        "100 Got handshake from client 111",
        "110 Got character ZDOID from Alice : 5:1",
        "300 Kicking player not in permitted list Alice host: 111",
        "301 Closing socket 111",
    )
    store.ingest(log)
    assert attempts(store) == [(300, "111", "Alice", JoinProblem.KICKED, None)]
    assert sessions(store) == [("Alice", "111", 110, 301)]


def test_join_attempts_filters(store, events):
    store.ingest(events(
        "100 Player A : 1 is blacklisted or not in whitelist.",
        "200 Player B : 2 is blacklisted or not in whitelist.",
        "300 Peer 1 has incompatible version, mine:1 (network version 40)   remote 0 (network version 39)",
    ))
    assert [a.ts for a in store.join_attempts(steamid="1")] == [300, 100]
    assert [a.ts for a in store.join_attempts(problem=JoinProblem.NOT_WHITELISTED, since=150)] == [200]
    assert [a.ts for a in store.join_attempts(1)] == [300]


def test_last_played_per_steamid(store, events):
    store.ingest(events(
        "100 Got handshake from client 111",
        "110 Got character ZDOID from Alice : 5:1",
        "200 Closing socket 111",
        "300 Got handshake from client 222",
        "310 Got character ZDOID from Bob : 6:1",
    ))
    played = store.last_played()
    assert played["111"] == LastPlayed(200, False)
    assert played["222"].online


def test_half_written_line_waits_for_the_next_read(store, tmp_path):
    path = tmp_path / "events.log"
    path.write_text("100 Got handshake from client 111\n110 Got character ZDOID fr")
    assert store.ingest(str(path)) == 1
    with path.open("a") as f:
        f.write("om Alice : 5:1\n")
    assert store.ingest(str(path)) == 1
    assert sessions(store) == [("Alice", "111", 110, None)]


def test_truncated_log_is_read_from_the_start(store, tmp_path):
    path = tmp_path / "events.log"
    path.write_text("100 Got handshake from client 111\n110 Got character ZDOID from Alice : 5:1\n")
    store.ingest(str(path))
    path.write_text("200 Closing socket 111\n")  # shorter than the stored offset
    assert store.ingest(str(path)) == 1
    assert sessions(store) == [("Alice", "111", 110, 200)]


def add_session(store, name, start, end):
    store.db.execute("INSERT INTO sessions (name, start, end) VALUES (?, ?, ?)", (name, start, end))


@pytest.mark.parametrize(("since", "expected"), [
    (0, 200),  # [0,150] merged from two overlapping sessions + [200,250]
    (120, 80),  # clipped: [120,150] + [200,250]
    (260, 0),  # nothing after 260 except the gap
])
def test_online_seconds_merges_overlapping_sessions(store, since, expected):
    add_session(store, "Alice", 0, 100)
    add_session(store, "Bob", 50, 150)
    add_session(store, "Alice", 200, 250)
    assert store.online_seconds_since(since, 300) == expected


def test_online_seconds_counts_open_sessions_until_now(store):
    add_session(store, "Alice", 100, None)
    assert store.online_seconds_since(0, 160) == 60


def test_stats_include_death_only_characters_and_sort_by_playtime(store):
    add_session(store, "Alice", 0, 100)
    add_session(store, "Bob", 0, 500)
    store.db.execute("INSERT INTO deaths (name, ts) VALUES ('Ghost', 5)")
    rows = store.stats()
    assert [(r.name, r.playtime, r.sessions, r.deaths, r.online) for r in rows] == [
        ("Bob", 500, 1, 0, False), ("Alice", 100, 1, 0, False), ("Ghost", 0, 0, 1, False),
    ]
    assert rows[2].first_seen is None and rows[2].last_seen is None


def test_player_is_case_insensitive_and_none_when_unknown(store):
    add_session(store, "Alice", 0, 100)
    assert store.player("ALICE").playtime == 100
    assert store.player("Nobody") is None


def test_state_values_round_trip(store):
    store.set(StateKey.DASHBOARD, {"channel": 1, "message": 2})
    assert store.get(StateKey.DASHBOARD) == {"channel": 1, "message": 2}
    assert store.get(StateKey.ORPHANS_NOTIFIED, []) == []
