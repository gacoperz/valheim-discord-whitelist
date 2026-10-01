"""In-game day from the newest world save header plus the online time since that save."""
import os
import struct

from bot.world import current_day


def save(path, net_time, mtime):
    path.write_bytes(struct.pack("<id", 36, net_time) + b"rest of the save")
    os.utime(path, (mtime, mtime))


def test_day_from_the_newest_save_plus_online_time(tmp_path):
    save(tmp_path / "Old.db", 1800.0 * 2, 1000)
    save(tmp_path / "World.db2", 1800.0 * 10 + 1700, 2000)
    calls = []

    def online_seconds_since(since, now):
        calls.append((since, now))
        return 200.0  # pushes 10 days + 1700 s past day 11

    day = current_day(str(tmp_path), online_seconds_since, 5000.0)
    assert (day.number, day.saved_at, calls) == (11, 2000, [(2000.0, 5000.0)])


def test_no_save_or_unreadable_dir_means_no_day(tmp_path):
    assert current_day(str(tmp_path), lambda since, now: 0.0, 0.0) is None
    (tmp_path / "Broken.db2").mkdir()  # open() fails with an OSError
    assert current_day(str(tmp_path), lambda since, now: 0.0, 0.0) is None


def test_a_save_shorter_than_its_header_means_no_day(tmp_path):
    """The game may be writing the file right now; the status embed must still build."""
    (tmp_path / "World.db2").write_bytes(b"\x24\x00\x00\x00\x00")
    assert current_day(str(tmp_path), lambda since, now: 0.0, 0.0) is None
