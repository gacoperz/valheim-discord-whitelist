"""Whitelist entries (SQLite) rendered into Valheim's permittedlist.txt.

Valheim treats an EMPTY permitted list as "everyone may join". The server has no password, so the file must
never be empty: with no entries we write a placeholder ID. Protected IDs (the owner) are always written,
whatever happens to their database entries. Every change is logged and recorded in whitelist_audit.
"""
import logging
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger("valheim-bot.whitelist")

PLACEHOLDER_ID = "0"  # keeps the list non-empty (= whitelist active) when nobody is on it
HEADER = (
    "// List permitted players ID ONE per line\n"
    "// Managed by the Discord bot - use its dashboard, manual edits are overwritten.\n"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS whitelist (
    steamid TEXT PRIMARY KEY,
    discord_id INTEGER UNIQUE,      -- NULL for manual entries (never auto-removed)
    discord_name TEXT,
    steam_name TEXT,
    note TEXT,
    guild_id INTEGER,
    added_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS whitelist_audit (
    id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, action TEXT NOT NULL,
    steamid TEXT NOT NULL, subject TEXT, actor TEXT
);
"""


class AuditAction(StrEnum):
    """History labels. They are stored in whitelist_audit, so changing one only affects new rows."""
    LINK = "join (Discord link)"
    RELINK_REPLACED = "unlink (replaced)"  # the user linked a different Steam account
    MANUAL_REPLACED = "manual entry replaced by link"  # a user linked a SteamID that was a manual entry
    ADD_MANUAL = "add (manual)"
    LEAVE = "leave (button)"
    REMOVE_ADMIN = "remove (admin)"
    LEFT_DISCORD = "remove (left Discord)"
    NOT_IN_DISCORD = "remove (not in Discord)"  # found by the hourly member check


class WhitelistWriteError(Exception):
    """The database changed, but permittedlist.txt could not be written."""


@dataclass(frozen=True)
class WhitelistEntry:
    steamid: str
    discord_id: int | None  # None = manual entry
    discord_name: str | None
    steam_name: str | None
    note: str | None
    guild_id: int | None
    added_at: int

    @property
    def is_manual(self) -> bool:
        return self.discord_id is None


@dataclass(frozen=True)
class AuditRecord:
    ts: int
    action: str
    steamid: str
    subject: str | None
    actor: str


ENTRY_COLUMNS = "steamid, discord_id, discord_name, steam_name, note, guild_id, added_at"


class Whitelist:
    def __init__(self, db: sqlite3.Connection, path: str, protected: Sequence[str] = ()):
        self.db, self.path = db, path
        self.protected = [steamid for steamid in protected if steamid]
        self.write_error: str | None = None  # why the last write of permittedlist.txt failed; None = in sync
        db.executescript(SCHEMA)

    # ---- reading ----
    def is_protected(self, steamid: str) -> bool:
        """Always written to permittedlist.txt, so removing its entry doesn't lock it out."""
        return steamid in self.protected

    def entries(self) -> list[WhitelistEntry]:
        rows = self.db.execute(f"SELECT {ENTRY_COLUMNS} FROM whitelist ORDER BY added_at")
        return [WhitelistEntry(**dict(row)) for row in rows]

    def by_discord(self, discord_id: int) -> WhitelistEntry | None:
        return self._one("discord_id", discord_id)

    def by_steam(self, steamid: str) -> WhitelistEntry | None:
        return self._one("steamid", steamid)

    def _one(self, column: str, value: int | str) -> WhitelistEntry | None:
        # `column` goes into the SQL text: it is always a literal from this class, never user input.
        row = self.db.execute(f"SELECT {ENTRY_COLUMNS} FROM whitelist WHERE {column}=?", (value,)).fetchone()
        return WhitelistEntry(**dict(row)) if row else None

    def history(self, limit: int = 20) -> list[AuditRecord]:
        rows = self.db.execute(
            "SELECT ts, action, steamid, subject, actor FROM whitelist_audit ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [AuditRecord(**dict(row)) for row in rows]

    # ---- changes: each one commits together with its audit rows, then rewrites the file ----
    def link(self, discord_id: int, discord_name: str, guild_id: int, steamid: str, steam_name: str) -> None:
        """Link a Discord user to a Steam ID, replacing their previous Steam ID (one per user)."""
        previous = self.by_discord(discord_id)
        manual = self.by_steam(steamid)
        with self.db:
            if previous and previous.steamid != steamid:
                self._audit(AuditAction.RELINK_REPLACED, previous.steamid, discord_name, discord_name)
            if manual and manual.is_manual:
                self._audit(AuditAction.MANUAL_REPLACED, steamid, manual.note, discord_name)
            self.db.execute("DELETE FROM whitelist WHERE discord_id=?", (discord_id,))
            self.db.execute("DELETE FROM whitelist WHERE steamid=? AND discord_id IS NULL", (steamid,))
            self.db.execute(
                "INSERT INTO whitelist (steamid, discord_id, discord_name, steam_name, guild_id, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (steamid, discord_id, discord_name, steam_name, guild_id, int(time.time())),
            )
            self._audit(AuditAction.LINK, steamid, f"{discord_name} / Steam {steam_name}", discord_name)
        self.write_file()

    def add_manual(self, steamid: str, note: str, actor: str) -> bool:
        """Returns False if the SteamID is already on the whitelist."""
        if self.by_steam(steamid):
            return False
        with self.db:
            self.db.execute(
                "INSERT INTO whitelist (steamid, note, added_at) VALUES (?, ?, ?)", (steamid, note, int(time.time()))
            )
            self._audit(AuditAction.ADD_MANUAL, steamid, note, actor)
        self.write_file()
        return True

    def remove_steam(self, steamid: str, action: AuditAction, actor: str) -> WhitelistEntry | None:
        return self._remove(self.by_steam(steamid), action, actor)

    def remove_discord(self, discord_id: int, action: AuditAction, actor: str) -> WhitelistEntry | None:
        return self._remove(self.by_discord(discord_id), action, actor)

    def _remove(self, entry: WhitelistEntry | None, action: AuditAction, actor: str) -> WhitelistEntry | None:
        """Returns the removed entry, or None if there was nothing to remove."""
        if entry:
            with self.db:
                self.db.execute("DELETE FROM whitelist WHERE steamid=?", (entry.steamid,))
                self._audit(action, entry.steamid, entry.discord_name or entry.note, actor)
            self.write_file()
        return entry

    def _audit(self, action: AuditAction, steamid: str, subject: str | None, actor: str) -> None:
        self.db.execute(
            "INSERT INTO whitelist_audit (ts, action, steamid, subject, actor) VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), action, steamid, subject, actor),
        )
        log.info("whitelist %s: steam %s (%s) by %s", action, steamid, subject, actor)

    # ---- permittedlist.txt ----
    def write_file(self) -> None:
        """Render the whitelist into permittedlist.txt. Raises WhitelistWriteError if that fails."""
        steamids = list(dict.fromkeys(self.protected + [entry.steamid for entry in self.entries()]))
        content = HEADER + "".join(f"{steamid}\n" for steamid in steamids or [PLACEHOLDER_ID])
        try:
            # Rewrite in place (same inode): the file is a single-file bind mount into this container.
            with open(self.path, "r+", encoding="utf-8") as f:
                if f.read() == content:
                    self.write_error = None
                    return
                f.seek(0)
                f.write(content)
                f.truncate()
        except OSError as exc:
            log.error("cannot write %s: %s", self.path, exc)
            self.write_error = str(exc)
            raise WhitelistWriteError(str(exc)) from exc
        self.write_error = None
        log.info("permittedlist.txt updated: %d entries", len(steamids))
