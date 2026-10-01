"""What the bot currently knows about the game server, updated by every poll."""
import time
from dataclasses import dataclass

from .config import MISSES_BEFORE_OFFLINE


@dataclass
class ServerState:
    online: bool = False
    last_ok: float | None = None  # unix time of the last successful probe
    offline_since: float | None = None  # unix time of the first failed probe since the last good one
    misses: int = 0  # consecutive failed probes

    def record_probe(self, up: bool, now: float | None = None) -> None:
        """One failed probe is not enough to call the server offline."""
        now = time.time() if now is None else now
        if up:
            self.online, self.last_ok, self.offline_since, self.misses = True, now, None, 0
            return
        if self.misses == 0:
            self.offline_since = now
        self.misses += 1
        if self.misses >= MISSES_BEFORE_OFFLINE:
            self.online = False

    @property
    def confirmed_offline(self) -> bool:
        """Still down on the poll after it was declared offline, so open sessions can be closed."""
        return self.misses > MISSES_BEFORE_OFFLINE

    def offline_for(self, now: float) -> float:
        """Seconds since the first failed probe, while the server counts as offline; 0 when it is online."""
        if self.online or self.offline_since is None:
            return 0.0
        return now - self.offline_since
