"""SQLite storage for sessions, deaths and bot state, plus the parser for the events log.

The Valheim log-filter hook writes each matching server log line to events.log as "<unix ts> <raw line>".
"""
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

RE_HANDSHAKE = re.compile(r"Got handshake from client (\d+)")
RE_ZDOID = re.compile(r"Got character ZDOID from (.+?) : (-?\d+):(-?\d+)")
RE_CLOSE = re.compile(r"Closing socket (\d+)")
RE_STARTED = re.compile(r"Game server connected")
RE_VERSION = re.compile(r"Valheim version: l?-?([\w.]+)")
# Refusals, as worded in the game's ZNet code (RPC_PeerInfo and the permitted-list kick).
RE_NOT_WHITELISTED = re.compile(r"Player (.*) : (\S+) is blacklisted or not in whitelist")
RE_WRONG_VERSION = re.compile(r"Peer (\S+) has incompatible version, mine:(\S+).*remote (\S+)")
RE_KICKED = re.compile(r"Kicking player not in permitted list (.*) host: (\S+)")

# Valheim logs a second "Got character ZDOID" line with user id 0 when a character dies.
DEAD_ZDOID_USER = "0"
# A disconnect without a character only counts as "dropped" if no refusal was logged this recently.
REFUSAL_WINDOW = 120

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, steamid TEXT,
    start INTEGER NOT NULL, end INTEGER,
    zdo_user TEXT  -- the connection's ZDO user id from "Got character ZDOID from <name> : <user>:<n>"
);
CREATE TABLE IF NOT EXISTS deaths (id INTEGER PRIMARY KEY, name TEXT NOT NULL, ts INTEGER NOT NULL, steamid TEXT);
CREATE INDEX IF NOT EXISTS sessions_open ON sessions(end);
CREATE TABLE IF NOT EXISTS join_attempts (
    id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, steamid TEXT NOT NULL,
    name TEXT, problem TEXT NOT NULL, detail TEXT
);
CREATE INDEX IF NOT EXISTS join_attempts_steamid ON join_attempts(steamid, ts);
"""


class StateKey(StrEnum):
    """Keys of the key/value state table. The values are stored in the database, so never rename them."""
    EVENTS_OFFSET = "events_offset"  # bytes of events.log already processed
    PENDING_HANDSHAKES = "pending_handshakes"  # SteamIDs that connected but have no character yet
    SERVER_STARTED = "server_started"
    VERSION = "version"
    DASHBOARD = "status_message"  # {"channel": id, "message": id} of the dashboard message
    ORPHANS_NOTIFIED = "orphan_notified"  # SteamIDs the admin was already DM'd about
    ADMIN_ALERTS = "admin_alerts"  # {alert name: unix time the admin was DM'd} for alerts still active


class JoinProblem(StrEnum):
    """Why a connection didn't become a play session. The values are stored in the database, so never rename
    them."""
    NOT_WHITELISTED = "not whitelisted"
    WRONG_VERSION = "wrong game version"
    KICKED = "kicked (removed from whitelist)"
    DROPPED = "disconnected before loading in"  # no reason in the log (crash, timeout, network)


@dataclass(frozen=True)
class JoinAttempt:
    ts: int
    steamid: str
    name: str | None  # character name, if the log line has one
    problem: str  # a JoinProblem value
    detail: str | None  # e.g. "server 1.0.16, player 1.0.15"


@dataclass(frozen=True)
class LastPlayed:
    ts: int  # end of the latest session, or now if it is still open
    online: bool


def connect(path: str) -> sqlite3.Connection:
    """The bot's single database connection; rows can be read by column name."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


@dataclass(frozen=True)
class PlayerStats:
    """One character: a character name played from one Steam account (steamid None = account unknown)."""
    steamid: str | None
    name: str
    playtime: int  # seconds
    sessions: int
    deaths: int
    last_seen: int | None
    online: bool
    first_seen: int | None


class Store:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Databases from before v1.1.0: sessions don't record the ZDO user id, and deaths have no Steam ID,
        which is filled in from the session of that character that was open at the time."""
        if "zdo_user" not in self._columns("sessions"):
            with self.db:
                self.db.execute("ALTER TABLE sessions ADD COLUMN zdo_user TEXT")
        if "steamid" in self._columns("deaths"):
            return
        with self.db:
            self.db.execute("ALTER TABLE deaths ADD COLUMN steamid TEXT")
            self.db.execute("""
                UPDATE deaths SET steamid = (
                    SELECT sessions.steamid FROM sessions
                    WHERE sessions.name = deaths.name AND sessions.start <= deaths.ts
                      AND (sessions.end IS NULL OR sessions.end >= deaths.ts)
                    ORDER BY sessions.start DESC LIMIT 1)
            """)

    def _columns(self, table: str) -> list[str]:
        return [row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")]

    # ---- key/value state ----
    # Values are stored as JSON, so anything JSON-serialisable works.
    def get(self, key: StateKey, default: Any = None) -> Any:
        row = self.db.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
        return json.loads(row["v"]) if row else default

    def set(self, key: StateKey, value: Any) -> None:
        with self.db:
            self._put(key, value)

    def _put(self, key: StateKey, value: Any) -> None:
        """Write without committing, for use inside a transaction."""
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value)))

    # ---- events log ----
    def ingest(self, path: str) -> int:
        """Process the complete lines added to the events log since the last call. Returns how many."""
        try:
            size = os.path.getsize(path)
        except FileNotFoundError:
            return 0
        offset = self.get(StateKey.EVENTS_OFFSET, 0)
        if size < offset:  # the file was truncated or replaced
            offset = 0
        if size == offset:
            return 0
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # leave a half-written last line for the next call
        count = 0
        with self.db:  # the whole batch, its pending handshakes and the new offset commit together
            pending = self.get(StateKey.PENDING_HANDSHAKES, [])
            for raw in chunk[:end].decode("utf-8", "replace").splitlines():
                ts, _, line = raw.partition(" ")
                if ts.isdigit():
                    self._handle(int(ts), line, pending)
                    count += 1
            self._put(StateKey.PENDING_HANDSHAKES, pending)
            self._put(StateKey.EVENTS_OFFSET, offset + end)
        return count

    def _handle(self, ts: int, line: str, pending: list[str]) -> None:
        """Apply one log line. `pending` holds SteamIDs that connected but have no character yet, oldest first:
        the next new character is matched to the oldest pending handshake."""
        if RE_STARTED.search(line):
            self._close_open_sessions(ts)
            self._put(StateKey.SERVER_STARTED, ts)
            pending.clear()
        elif match := RE_VERSION.search(line):
            self._put(StateKey.VERSION, match[1])
        elif match := RE_NOT_WHITELISTED.search(line):
            self._add_attempt(ts, match[2], match[1].strip(), JoinProblem.NOT_WHITELISTED)
        elif match := RE_WRONG_VERSION.search(line):
            self._add_attempt(ts, match[1], None, JoinProblem.WRONG_VERSION,
                              f"server {match[2]}, player {match[3]}")
        elif match := RE_KICKED.search(line):
            self._add_attempt(ts, match[2], match[1].strip(), JoinProblem.KICKED)
        elif match := RE_HANDSHAKE.search(line):
            pending.append(match[1])
        elif match := RE_ZDOID.search(line):
            name, user_id = match[1].strip(), match[2]  # user_id: same across respawns, differs between players
            if user_id == DEAD_ZDOID_USER:
                self.db.execute("INSERT INTO deaths (name, ts, steamid) VALUES (?, ?, ?)",
                                (name, ts, self._open_session_steamid(name)))
            elif not self._has_open_session(name, user_id):  # a respawn repeats the line with the same user id
                steamid = pending.pop(0) if pending else None
                self.db.execute("INSERT INTO sessions (name, steamid, start, zdo_user) VALUES (?, ?, ?, ?)",
                                (name, steamid, ts, user_id))
        elif match := RE_CLOSE.search(line):
            steamid = match[1]
            if steamid in pending:  # disconnected before getting a character (e.g. not whitelisted)
                pending.remove(steamid)
                if not self._refused_recently(steamid, ts):
                    self._add_attempt(ts, steamid, None, JoinProblem.DROPPED)
            self.db.execute("UPDATE sessions SET end=? WHERE steamid=? AND end IS NULL", (ts, steamid))

    def _add_attempt(self, ts: int, steamid: str, name: str | None, problem: JoinProblem,
                     detail: str | None = None) -> None:
        self.db.execute("INSERT INTO join_attempts (ts, steamid, name, problem, detail) VALUES (?, ?, ?, ?, ?)",
                        (ts, steamid, name, problem, detail))

    def _refused_recently(self, steamid: str, ts: int) -> bool:
        return self.db.execute("SELECT 1 FROM join_attempts WHERE steamid=? AND ts >= ?",
                               (steamid, ts - REFUSAL_WINDOW)).fetchone() is not None

    def _open_session_steamid(self, name: str) -> str | None:
        """Steam ID of the character's open session (the newest, if two players share the name)."""
        row = self.db.execute("SELECT steamid FROM sessions WHERE name=? AND end IS NULL ORDER BY start DESC",
                              (name,)).fetchone()
        return row["steamid"] if row else None

    def _has_open_session(self, name: str, user_id: str) -> bool:
        """Is this character already in a session on this connection? Two players may share a character name, so
        the ZDO user id tells them apart. Sessions opened before v1.1.0 have none and match by name."""
        return self.db.execute(
            "SELECT 1 FROM sessions WHERE name=? AND end IS NULL AND (zdo_user = ? OR zdo_user IS NULL)",
            (name, user_id)).fetchone() is not None

    def _close_open_sessions(self, ts: int) -> int:
        return self.db.execute("UPDATE sessions SET end=? WHERE end IS NULL", (ts,)).rowcount

    def close_all(self, ts: int) -> int:
        with self.db:
            return self._close_open_sessions(ts)

    # ---- queries ----
    def online(self) -> list[tuple[str, int]]:
        """(character name, session start) for everyone online, longest-playing first."""
        rows = self.db.execute("SELECT name, start FROM sessions WHERE end IS NULL ORDER BY start")
        return [(row["name"], row["start"]) for row in rows]

    def online_seconds_since(self, since: float, now: float) -> float:
        """Seconds in [since, now] during which at least one player was online (overlapping sessions merged)."""
        rows = self.db.execute(
            "SELECT start, COALESCE(end, :now) AS end FROM sessions WHERE COALESCE(end, :now) > :since "
            "ORDER BY start",
            {"now": now, "since": since},
        )
        total = 0.0
        span_start = span_end = None  # the merged interval being built
        for row in rows:
            start, end = max(row["start"], since), row["end"]
            if span_end is not None and start <= span_end:
                span_end = max(span_end, end)
                continue
            if span_end is not None:
                total += span_end - span_start
            span_start, span_end = start, end
        if span_end is not None:
            total += span_end - span_start
        return total

    def stats(self, name: str | None = None, steamid: str | None = None) -> list[PlayerStats]:
        """Per-character stats, most playtime first. A character is a name played from one Steam account, so two
        players who both call their character "Bob" are counted apart. `name` (case-insensitive) and `steamid`
        narrow it down."""
        rows = self.db.execute(
            """
            WITH characters AS (SELECT steamid, name FROM sessions UNION SELECT steamid, name FROM deaths),
            played AS (
                SELECT steamid, name,
                       SUM(COALESCE(end, :now) - start) AS playtime,
                       COUNT(*)                          AS sessions,
                       MAX(COALESCE(end, :now))          AS last_seen,
                       SUM(end IS NULL) > 0              AS online,
                       MIN(start)                        AS first_seen
                FROM sessions GROUP BY steamid, name
            ),
            died AS (SELECT steamid, name, COUNT(*) AS deaths FROM deaths GROUP BY steamid, name)
            SELECT characters.steamid, characters.name,
                   COALESCE(played.playtime, 0) AS playtime,
                   COALESCE(played.sessions, 0) AS sessions,
                   COALESCE(died.deaths, 0)     AS deaths,
                   played.last_seen,
                   COALESCE(played.online, 0)   AS online,
                   played.first_seen
            FROM characters
            LEFT JOIN played ON played.name = characters.name AND played.steamid IS characters.steamid
            LEFT JOIN died ON died.name = characters.name AND died.steamid IS characters.steamid
            WHERE (:name IS NULL OR characters.name = :name COLLATE NOCASE)
              AND (:steamid IS NULL OR characters.steamid = :steamid)
            ORDER BY playtime DESC, characters.name, characters.steamid
            """,
            {"now": int(time.time()), "name": name, "steamid": steamid},
        )
        players = []
        for row in rows:
            values = dict(row)
            values["online"] = bool(values["online"])  # SQLite returns 0/1
            players.append(PlayerStats(**values))
        return players

    def names(self) -> list[str]:
        rows = self.db.execute("SELECT name FROM sessions UNION SELECT name FROM deaths ORDER BY 1")
        return [row["name"] for row in rows]

    def last_played(self) -> dict[str, LastPlayed]:
        """Per Steam ID: when its latest session ended (now, if it is still online)."""
        rows = self.db.execute(
            "SELECT steamid, MAX(COALESCE(end, :now)) AS ts, SUM(end IS NULL) > 0 AS online FROM sessions "
            "WHERE steamid IS NOT NULL GROUP BY steamid",
            {"now": int(time.time())},
        )
        return {row["steamid"]: LastPlayed(row["ts"], bool(row["online"])) for row in rows}

    def join_attempts(self, limit: int = 20, *, since: int = 0,
                      steamid: str | None = None, problem: JoinProblem | None = None) -> list[JoinAttempt]:
        """Failed connections, newest first."""
        rows = self.db.execute(
            "SELECT ts, steamid, name, problem, detail FROM join_attempts WHERE ts >= :since "
            "AND (:steamid IS NULL OR steamid = :steamid) AND (:problem IS NULL OR problem = :problem) "
            "ORDER BY ts DESC, id DESC LIMIT :limit",
            {"since": since, "steamid": steamid, "problem": problem, "limit": limit},
        )
        return [JoinAttempt(**dict(row)) for row in rows]
