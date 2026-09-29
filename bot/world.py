"""In-game day from the newest Valheim world save (header: int32 version, float64 world time)."""
import glob
import os
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

DAY_LENGTH = 1800.0  # seconds of world time per in-game day


@dataclass
class WorldSave:
    path: str
    saved_at: float  # file mtime (unix time)
    net_time: float  # world time in seconds at save


class WorldDay(NamedTuple):
    number: int
    saved_at: int  # unix time of the save it is based on


def latest_save(world_dir: str) -> WorldSave | None:
    files = glob.glob(os.path.join(world_dir, "*.db2")) + glob.glob(os.path.join(world_dir, "*.db"))
    if not files:
        return None
    path = max(files, key=os.path.getmtime)
    with open(path, "rb") as f:
        _version, net_time = struct.unpack("<id", f.read(12))
    return WorldSave(path, os.path.getmtime(path), net_time)


def day_of(net_time: float) -> int:
    return int(net_time // DAY_LENGTH)


def current_day(world_dir: str, online_seconds_since: Callable[[float, float], float],
                now: float) -> WorldDay | None:
    """Estimate today's day: world time only runs while someone is online, so add the online time
    since the last save to the time stored in that save."""
    try:
        save = latest_save(world_dir)
    except OSError:
        return None
    if not save:
        return None
    net_time = save.net_time + online_seconds_since(save.saved_at, now)
    return WorldDay(day_of(net_time), int(save.saved_at))
