"""Cancel-callback HTTP endpoint (RFC-0001 §7.2 Option A).

The examples-service's ``BootstrapPayload.cancel_callback`` field asks
each agent to listen on ``http://host:port{path}`` for a ``POST`` whose
JSON body is ``{"runId": ..., "reason": ...}``. Receipt of the POST
should stop the participant cleanly — typically by calling
``Participant.stop()``.

Before this module every agent had to hand-roll the HTTP endpoint (see
``examples-service/src/example-agents/runtime/risk-decider.worker.ts``
for the TS reference). ``start_cancel_callback_server`` encapsulates
that so callers only supply the ``on_cancel`` callback; the server
runs in a daemon thread backed by the stdlib ``http.server`` — no new
dependencies.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

from .._logging import logger

_OnCancel = Callable[[str, str], None]


@dataclass
class CancelCallbackServer:
    """Handle returned by :func:`start_cancel_callback_server`."""

    address: tuple[str, int]
    _httpd: HTTPServer
    _thread: threading.Thread

    def close(self) -> None:
        """Stop accepting requests and tear down the HTTP server.

        Safe to call from any thread — including from the very handler
        that just fired ``on_cancel`` (which is the normal case when a
        ``Participant.stop()`` call bubbles back here). Calling
        ``httpd.shutdown()`` directly from the server thread would
        self-deadlock because ``shutdown()`` blocks until
        ``serve_forever()`` exits, so spawn a one-shot thread to
        perform the teardown.
        """
        shutter = threading.Thread(
            target=self._shutdown_once,
            name=f"macp-cancel-callback-shutdown-{self.address[1]}",
            daemon=True,
        )
        shutter.start()
        # Only block if we're not on the server thread (avoid deadlock).
        if threading.current_thread() is not self._thread:
            shutter.join(timeout=2.0)

    def _shutdown_once(self) -> None:
        try:
            self._httpd.shutdown()
        except Exception:
            logger.debug("cancel_callback shutdown already in progress")
        with contextlib.suppress(Exception):
            self._httpd.server_close()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)

    @property
    def port(self) -> int:
        return self.address[1]


def start_cancel_callback_server(
    *,
    host: str,
    port: int,
    path: str,
    on_cancel: _OnCancel,
) -> CancelCallbackServer:
    """Start a minimal HTTP server that invokes ``on_cancel`` on POST.

    The server binds to ``(host, port)`` — pass ``port=0`` to let the OS
    pick a free port; the actual port is available on the returned
    handle's ``address`` tuple. Only the exact ``path`` is honoured;
    other paths respond with 404.

    ``on_cancel`` receives ``(run_id, reason)`` parsed from the JSON
    body. Either argument is ``""`` when missing. The callback is
    invoked on the HTTP server thread, so it must not block the event
    loop of the thing it's cancelling — typically it calls
    ``participant.stop()``, which only sets a flag.
    """
    normalised_path = path if path.startswith("/") else "/" + path

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            logger.debug("cancel_callback %s - %s", self.address_string(), fmt % args)

        def do_POST(self) -> None:
            if self.path != normalised_path:
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                body = {}

            run_id = str(body.get("runId") or body.get("run_id") or "")
            reason = str(body.get("reason") or "")
            logger.info("cancel_callback invoked (run=%s reason=%s)", run_id, reason)

            try:
                on_cancel(run_id, reason)
            except Exception:
                logger.exception("cancel_callback handler raised")
                self.send_response(500)
                self.end_headers()
                return

            self.send_response(202)  # Accepted — cancellation acknowledged, async
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    httpd = HTTPServer((host, port), _Handler)
    # ``server_address`` is typed as a variant union on stdlib stubs; normalise
    # to the plain ``(host, port)`` pair we expose on the handle.
    bound_host = str(httpd.server_address[0])
    bound_port = int(httpd.server_address[1])
    address: tuple[str, int] = (bound_host, bound_port)
    thread = threading.Thread(
        target=httpd.serve_forever,
        name=f"macp-cancel-callback-{bound_host}-{bound_port}",
        daemon=True,
    )
    thread.start()
    logger.debug(
        "cancel_callback listening on http://%s:%d%s",
        bound_host,
        bound_port,
        normalised_path,
    )
    return CancelCallbackServer(address=address, _httpd=httpd, _thread=thread)
