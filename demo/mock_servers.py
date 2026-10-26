"""Local mock target + webhook receiver used by the tests and the demo.

``MockServer`` exposes ``/svc/<name>`` whose behaviour can be switched at runtime:

  up    -> 200 OK
  down  -> 503 Service Unavailable
  slow  -> 200 OK after ``delay_ms``
  drop  -> connection closed without any response (simulates a crashed service)
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MockServer:
    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.modes = {}
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _respond(self, head_only=False):
                path = self.path.split("?")[0]
                if path.startswith("/status/"):
                    try:
                        code = int(path.rsplit("/", 1)[1])
                    except ValueError:
                        code = 400
                    return self._send(code, f"status {code}", head_only)
                if path == "/text":
                    return self._send(200, "hello world from mock", head_only)
                if path.startswith("/svc/"):
                    name = path[len("/svc/"):]
                    mode, delay_ms = outer.get_mode(name)
                    if mode == "drop":
                        self.close_connection = True
                        try:
                            self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        return
                    if mode == "slow":
                        time.sleep(delay_ms / 1000.0)
                    if mode == "down":
                        return self._send(503, "service unavailable", head_only)
                    return self._send(200, f"OK {name}", head_only)
                return self._send(404, "not found", head_only)

            def _send(self, code, body, head_only=False):
                data = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if not head_only:
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def do_GET(self):
                self._respond()

            def do_HEAD(self):
                self._respond(head_only=True)

        self._httpd = _QuietServer((host, port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    # -- control ---------------------------------------------------------
    def set_mode(self, name, mode, delay_ms=0):
        assert mode in ("up", "down", "slow", "drop")
        with self._lock:
            self.modes[name] = (mode, delay_ms)

    def get_mode(self, name):
        with self._lock:
            return self.modes.get(name, ("up", 0))

    def url(self, name="ok"):
        return f"http://{self.host}:{self.port}/svc/{name}"

    def base(self):
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


class WebhookReceiver:
    """Collects JSON POST bodies. ``fail_codes`` are returned first (FIFO)."""

    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.payloads = []
        self.fail_codes = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                with outer._lock:
                    code = outer.fail_codes.pop(0) if outer.fail_codes else 200
                    if code == 200:
                        outer.payloads.append(json.loads(raw.decode() or "{}"))
                self.send_response(code)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        self._httpd = _QuietServer((host, port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://{self.host}:{self.port}/hook"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def free_port():
    """A TCP port nothing is listening on (for connection-refused tests)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
