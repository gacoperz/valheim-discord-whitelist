"""Minimal Steam A2S_INFO query (game port + 1), plus a liveness probe.

An unlisted Valheim server (-public 0) never answers A2S. A UDP packet to a CLOSED port, however,
comes back as ICMP "port unreachable" (ConnectionRefusedError on a connected socket), so
"no answer" means the server is listening and "refused"/unknown host means it is down.
"""
import socket
from dataclasses import dataclass

QUERY = b"\xff\xff\xff\xffTSource Engine Query\x00"
S2C_CHALLENGE = 0x41  # reply type: resend the query with this challenge token
S2A_INFO = 0x49  # reply type: server info

# "Extra data flag" bits: which optional fields follow the version string
EDF_PORT = 0x80  # 2 bytes
EDF_STEAMID = 0x10  # 8 bytes
EDF_SOURCETV = 0x40  # 2-byte port + name string
EDF_KEYWORDS = 0x20  # string, e.g. "g=1.0.16,n=40"


@dataclass
class ServerInfo:
    name: str
    players: int
    max_players: int
    version: str  # game version from the keywords, e.g. "1.0.16"


def _cstr(buf: bytes, pos: int) -> tuple[str, int]:
    """Read a NUL-terminated string; returns it and the position after it."""
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def query(host: str, port: int, timeout: float = 3.0) -> ServerInfo:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, port))  # connected UDP socket, so ICMP errors surface as exceptions
        sock.send(QUERY)
        data = sock.recv(1400)
        if data[4] == S2C_CHALLENGE:
            sock.send(QUERY + data[5:9])
            data = sock.recv(1400)
    if data[4] != S2A_INFO:
        raise ValueError(f"unexpected A2S reply type {data[4]:#x}")
    pos = 6  # header (4) + type (1) + protocol (1)
    name, pos = _cstr(data, pos)
    _map, pos = _cstr(data, pos)
    _folder, pos = _cstr(data, pos)
    _game, pos = _cstr(data, pos)
    pos += 2  # app id
    players, max_players = data[pos], data[pos + 1]
    pos += 7  # players, max players, bots, server type, environment, visibility, VAC
    _version, pos = _cstr(data, pos)

    version = ""
    extra_data_flags = data[pos] if pos < len(data) else 0
    pos += 1
    if extra_data_flags & EDF_PORT:
        pos += 2
    if extra_data_flags & EDF_STEAMID:
        pos += 8
    if extra_data_flags & EDF_SOURCETV:
        pos += 2
        _, pos = _cstr(data, pos)
    if extra_data_flags & EDF_KEYWORDS:
        keywords, pos = _cstr(data, pos)
        for keyword in keywords.split(","):
            if keyword.startswith("g="):
                version = keyword[2:]
    return ServerInfo(name, players, max_players, version)


def probe(host: str, port: int, timeout: float = 2.0) -> tuple[bool, ServerInfo | None]:
    """(online, info). info is only available if the server answers A2S (public servers)."""
    try:
        return True, query(host, port, timeout)
    except (ConnectionRefusedError, socket.gaierror):
        return False, None
    except TimeoutError:
        return True, None
