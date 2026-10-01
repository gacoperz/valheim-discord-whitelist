"""Admin alert conditions, and that each alert is DM'd once when it starts and once when it clears."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from bot import main
from bot.alerts import Alert, active_alerts
from bot.config import EVENTS_STALE_SECONDS, OFFLINE_ALERT_SECONDS, POLL_SECONDS
from bot.server import ServerState
from bot.store import StateKey, Store, connect
from bot.whitelist import Whitelist

NOW = 1_000_000.0


@pytest.fixture
def store():
    return Store(connect(":memory:"))


@pytest.fixture
def whitelist(tmp_path, store):
    path = tmp_path / "permittedlist.txt"
    path.write_text("")
    return Whitelist(store.db, str(path))


def online_server():
    server = ServerState()
    server.record_probe(True)
    return server


def offline_server(seconds, now=NOW):
    """A server whose probes have failed every poll for `seconds` up to `now`."""
    server = online_server()
    for probe_time in range(int(now - seconds), int(now) + 1, POLL_SECONDS):
        server.record_probe(False, probe_time)
    return server


def test_no_alerts_when_all_is_well(store, whitelist):
    store.set(StateKey.SERVER_STARTED, int(NOW) - 3600)
    assert active_alerts("H", online_server(), store, whitelist, NOW) == {}


def test_offline_alert_only_after_the_threshold(store, whitelist):
    assert Alert.SERVER_OFFLINE not in active_alerts("H", offline_server(OFFLINE_ALERT_SECONDS - POLL_SECONDS),
                                                     store, whitelist, NOW)
    assert Alert.SERVER_OFFLINE in active_alerts("H", offline_server(OFFLINE_ALERT_SECONDS), store, whitelist, NOW)


def test_whitelist_write_error_alert(store, whitelist):
    whitelist.write_error = "Permission denied"
    assert "Permission denied" in active_alerts("H", online_server(), store, whitelist, NOW)[Alert.WHITELIST_WRITE]


def test_events_stale_only_while_online(store, whitelist):
    store.set(StateKey.SERVER_STARTED, int(NOW - EVENTS_STALE_SECONDS - 60))
    assert Alert.EVENTS_STALE in active_alerts("H", online_server(), store, whitelist, NOW)
    assert Alert.EVENTS_STALE not in active_alerts("H", offline_server(60), store, whitelist, NOW)


class FakeBot:
    """Just what Bot.check_alerts uses."""

    def __init__(self, store, whitelist, server, dm_works=True):
        self.cfg = SimpleNamespace(server_name="Midgard")
        self.store, self.whitelist, self.server = store, whitelist, server
        self.dm_works, self.sent = dm_works, []
        self._alert_dm_retry_at = 0.0

    async def dm_admin(self, text):
        if self.dm_works:
            self.sent.append(text)
        return self.dm_works


def check(bot):
    asyncio.run(main.Bot.check_alerts(bot))


def test_alert_is_sent_once_then_cleared_once(store, whitelist):
    store.set(StateKey.SERVER_STARTED, int(time.time()))
    bot = FakeBot(store, whitelist, offline_server(OFFLINE_ALERT_SECONDS, time.time()))
    check(bot)
    check(bot)
    assert len(bot.sent) == 1 and "offline" in bot.sent[0]

    # the bot restarted mid-outage
    restarted = FakeBot(store, whitelist, offline_server(OFFLINE_ALERT_SECONDS, time.time()))
    check(restarted)
    assert restarted.sent == []

    bot.server = online_server()
    check(bot)
    check(bot)
    assert len(bot.sent) == 2 and "back online" in bot.sent[1]
    assert store.get(StateKey.ADMIN_ALERTS) == {}


def test_failed_dm_is_retried_later_not_every_poll(store, whitelist):
    bot = FakeBot(store, whitelist, offline_server(OFFLINE_ALERT_SECONDS, time.time()), dm_works=False)
    check(bot)
    assert store.get(StateKey.ADMIN_ALERTS, {}) == {}  # not marked as sent
    assert bot._alert_dm_retry_at > time.time()
    bot.dm_works = True
    check(bot)  # still inside the retry delay
    assert bot.sent == []
    bot._alert_dm_retry_at = 0.0
    check(bot)
    assert len(bot.sent) == 1
