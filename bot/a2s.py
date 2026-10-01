"""Liveness probe of the game server's query port (game port + 1).

An unlisted Valheim server (-public 0) never answers Steam A2S queries. A UDP packet to a CLOSED port, however,
comes back as ICMP "port unreachable" (ConnectionRefusedError on a connected socket), so "no answer" means the
server is listening and "refused"/unknown host means it is down. Players and version come from the events log.
"""
import socket

QUERY = b"\xff\xff\xff\xffTSource Engine Query\x00"  # A2S_INFO: a public server answers it, which also means up


def probe(host: str, port: int, timeout: float = 2.0) -> bool:
    """True if the server is up. Other OSErrors (e.g. no route) are left to the caller."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))  # connected UDP socket, so ICMP errors surface as exceptions
            sock.send(QUERY)
            sock.recv(1400)
        except (ConnectionRefusedError, socket.gaierror):
            return False
        except TimeoutError:
            pass
    return True
