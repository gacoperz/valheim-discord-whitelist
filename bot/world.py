"""In-game day from the newest Valheim world save (header: int32 version, float64 world time)."""
import glob
import os
import struct
from collections.abc import Callable
from typing import NamedTuple

DAY_LENGTH = 1800.0  # seconds of world time per in-game day


class WorldDay(NamedTuple):
    number: int
    saved_at: int  # unix time of the save it is based on


def current_day(world_dir: str, online_seconds_since: Callable[[float, float], float],
                now: float) -> WorldDay | None:
    """Estimate today's day: world time only runs while someone is online, so add the online time
    since the last save to the time stored in that save."""
    files = glob.glob(os.path.join(world_dir, "*.db2")) + glob.glob(os.path.join(world_dir, "*.db"))
    try:
        path = max(files, key=os.path.getmtime, default=None)
        if not path:
            return None
        saved_at = os.path.getmtime(path)
        with open(path, "rb") as f:
            _version, net_time = struct.unpack("<id", f.read(12))
    except OSError:
        return None
    net_time += online_seconds_since(saved_at, now)
    return WorldDay(int(net_time // DAY_LENGTH), int(saved_at))
