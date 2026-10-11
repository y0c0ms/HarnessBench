"""TCP -> unix-socket relay, run INSIDE the sandbox.

The sandbox has its own network namespace with no route anywhere. This relay gives the harness a loopback
port (127.0.0.1:PORT) whose only destination is the run's logging proxy socket. It is the sole network path.

    python3 relay.py PORT SOCKET_PATH
"""
import socket
import sys
import threading


def _pump(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s, how in ((dst, socket.SHUT_WR), (src, socket.SHUT_RD)):
            try:
                s.shutdown(how)
            except OSError:
                pass


def main(port: int, sock_path: str) -> None:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)
    while True:
        c, _ = srv.accept()
        u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            u.connect(sock_path)
        except OSError:
            c.close()
            u.close()
            continue
        threading.Thread(target=_pump, args=(c, u), daemon=True).start()
        threading.Thread(target=_pump, args=(u, c), daemon=True).start()


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
