"""Settings, read once from environment variables at startup, plus fixed tuning constants."""
import os
from dataclasses import dataclass

POLL_SECONDS = 30  # how often the bot probes the server, reads the events log and refreshes the dashboard
MISSES_BEFORE_OFFLINE = 2  # consecutive failed probes before the server counts as offline
OAUTH_STATE_TTL = 600  # seconds a personal "Link Steam" link stays valid
# Touched after every successful poll; the compose healthcheck reports "unhealthy" when it gets old.
HEARTBEAT_FILE = "/tmp/heartbeat"

# Admin alerts (DM to NOTIFY_USER_ID)
OFFLINE_ALERT_SECONDS = 600  # game server offline this long; the daily restart and updates take under a minute
# The server restarts daily at 05:10 when empty and logs "Game server connected"; two missed restarts in a row
# while it is up means the events log copy is broken.
EVENTS_STALE_SECONDS = 50 * 3600
ALERT_DM_RETRY_SECONDS = 600  # after a failed DM, wait this long before trying again

STEAMID64_PREFIX = "7656119"
STEAMID64_LEN = 17


def _env_list(name: str) -> list[str]:
    """A space- or comma-separated environment variable as a list."""
    return os.environ.get(name, "").replace(",", " ").split()


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


@dataclass(frozen=True)
class Config:
    token: str
    client_secret: str  # empty = whitelist linking disabled
    public_url: str  # base URL of the OAuth return page, e.g. https://bot.example.org
    server_name: str
    join_address: str  # shown to players, e.g. 203.0.113.7:2456
    a2s_host: str
    a2s_port: int
    max_players: int
    events_log: str
    world_dir: str
    db_path: str
    whitelist_file: str
    motd_file: str  # message of the day (Discord markdown); missing or empty = not shown
    protected_steamids: tuple[str, ...]  # always whitelisted (the owner)
    # Discord servers the bot serves. Commands, buttons and the OAuth page are refused everywhere else, so
    # "Manage Server" in some other server never grants whitelist admin. Empty = refuse everywhere (fail closed).
    allowed_guilds: frozenset[int]
    notify_user_id: int | None  # Discord user DM'd about whitelist entries the bot can no longer manage

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            token=os.environ["DISCORD_TOKEN"],
            client_secret=os.environ.get("DISCORD_CLIENT_SECRET", ""),
            public_url=os.environ.get("PUBLIC_URL", ""),
            server_name=os.environ.get("SERVER_NAME", "Valheim"),
            join_address=os.environ.get("JOIN_ADDRESS", ""),
            a2s_host=os.environ.get("A2S_HOST", "valheim"),
            a2s_port=int(os.environ.get("A2S_PORT", "2457")),
            max_players=int(os.environ.get("MAX_PLAYERS", "10")),
            events_log=os.environ.get("EVENTS_LOG", "/events/events.log"),
            world_dir=os.environ.get("WORLD_DIR", "/world"),
            db_path=os.environ.get("DB_PATH", "/data/bot.db"),
            whitelist_file=os.environ.get("WHITELIST_FILE", "/whitelist/permittedlist.txt"),
            motd_file=os.environ.get("MOTD_FILE", "/motd/motd.md"),
            protected_steamids=tuple(_env_list("PROTECTED_STEAMIDS")),
            allowed_guilds=frozenset(int(g) for g in _env_list("ALLOWED_GUILDS")),
            notify_user_id=_env_int("NOTIFY_USER_ID"),
        )

    @property
    def oauth_enabled(self) -> bool:
        return bool(self.client_secret and self.public_url)


def is_steamid64(value: str) -> bool:
    return value.isdigit() and len(value) == STEAMID64_LEN and value.startswith(STEAMID64_PREFIX)
