"""The UDP liveness probe: no answer or any answer = up, ICMP "port unreachable" = down."""
import socket
import threading

from bot import a2s


def udp_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def online(result) -> bool:
    return result[0] if isinstance(result, tuple) else result  # v1.1.2 returned (online, info)


def test_a_silent_port_is_up():
    with udp_socket() as server:
        assert online(a2s.probe("127.0.0.1", server.getsockname()[1], timeout=0.2))


def test_a_closed_port_is_down():
    with udp_socket() as closed:
        port = closed.getsockname()[1]
    assert not online(a2s.probe("127.0.0.1", port, timeout=0.2))


def test_any_reply_is_up():
    """A public server, or anything else on the port, may answer with a reply the bot doesn't parse."""
    with udp_socket() as server:
        def reply():
            _, client = server.recvfrom(1400)
            server.sendto(b"\xff\xff\xff\xffX", client)
        thread = threading.Thread(target=reply)
        thread.start()
        assert online(a2s.probe("127.0.0.1", server.getsockname()[1], timeout=1))
        thread.join()
