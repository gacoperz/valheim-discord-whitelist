"""Private admin alerts: problems nobody would notice otherwise, DM'd to NOTIFY_USER_ID once when they start
and once when they clear. Not player announcements; nothing is posted in a channel."""
import time
from enum import StrEnum

from .config import EVENTS_STALE_SECONDS, OFFLINE_ALERT_SECONDS, POLL_SECONDS
from .server import ServerState
from .store import StateKey, Store
from .whitelist import Whitelist


class Alert(StrEnum):
    """Active alerts are stored by these values (state key admin_alerts), so never rename them."""
    SERVER_OFFLINE = "server_offline"
    WHITELIST_WRITE = "whitelist_write"
    EVENTS_STALE = "events_stale"


def _ago(seconds: float) -> str:
    hours, minutes = divmod(int(seconds) // 60, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def active_alerts(server_name: str, server: ServerState, store: Store, whitelist: Whitelist,
                  now: float) -> dict[Alert, str]:
    """Every alert whose condition holds right now, with the DM text that announces it."""
    alerts = {}
    offline_for = server.offline_for(now)
    if offline_for >= OFFLINE_ALERT_SECONDS:
        seen = f" Last seen online <t:{int(server.last_ok)}:R>." if server.last_ok else ""
        alerts[Alert.SERVER_OFFLINE] = (
            f"🔴 **{server_name} has been offline for {_ago(offline_for)}.**{seen} Check it with "
            "`docker ps` and `docker compose logs --tail 50 valheim` in /opt/valheim.")
    if whitelist.write_error:
        alerts[Alert.WHITELIST_WRITE] = (
            f"⚠️ **{server_name}: I can't write permittedlist.txt** ({whitelist.write_error}). Whitelist changes "
            "aren't reaching the game server, so newly linked players are refused. I retry every "
            f"{POLL_SECONDS} s. See *Troubleshooting* in the bot README.")
    started = store.get(StateKey.SERVER_STARTED)
    if server.online and started and now - started > EVENTS_STALE_SECONDS:
        alerts[Alert.EVENTS_STALE] = (
            f"⚠️ **{server_name}: no server restart in the events log for {_ago(now - started)}**, although the "
            "server restarts daily at 05:10 when empty. The log copy to `config/bot/events.log` is probably "
            "broken, so player sessions and stats aren't being recorded. Check "
            "`VALHEIM_LOG_FILTER_REGEXP_DiscordBot` in the Valheim compose.")
    return alerts


RECOVERED = {
    Alert.SERVER_OFFLINE: "🟢 **{name} is back online** (alerted {ago} ago).",
    Alert.WHITELIST_WRITE: "✅ **{name}: permittedlist.txt is writable again** and up to date.",
    Alert.EVENTS_STALE: "✅ **{name}: the events log is being written again.**",
}


def recovered_text(alert: Alert, server_name: str, alerted_at: float, now: float | None = None) -> str:
    return RECOVERED[alert].format(name=server_name, ago=_ago((now or time.time()) - alerted_at))
