# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared local HTTP/1.1 Range-request fixture server for chunked_download.py
and bulk_fetch.py tests.

Not a test module itself (no test_ prefix -- pytest/unittest discovery skips
it). Binds to 127.0.0.1 on an OS-assigned ephemeral port: loopback only, no
external network, but exercises REAL urllib.request + http.client wire
behavior (actual Range/Content-Range/ETag headers, actual socket framing)
rather than a hand-rolled fake response object -- the failure modes this
connector must detect (a server that ignores Range, a truncated response
body, a mid-transfer ETag flip) are wire-level phenomena that a fake opener
can only approximate.
"""
from __future__ import annotations

import http.server
import threading
from typing import List, Optional, Tuple, Type


class RangeHandler(http.server.BaseHTTPRequestHandler):
    payload: bytes = b""
    etag: str = '"fixture-etag-1"'
    last_modified: str = "Mon, 01 Jan 2026 00:00:00 GMT"
    ignore_range: bool = False
    ignore_range_after: Optional[int] = None
    truncate_last_n_bytes: int = 0
    flip_etag_after: Optional[int] = None
    flip_payload_after: Optional[int] = None
    flipped_payload: bytes = b""
    force_status: Optional[int] = None
    hostile_content_range: Optional[Tuple[int, int, int]] = None  # (start, end, total) sent
    # verbatim regardless of what was requested, with a synthetic body of that
    # claimed length -- for reproducing a server (hostile or merely broken) that
    # answers a small requested range with a much larger Content-Range.
    hostile_content_range_after: int = 0  # requests 1..N behave normally (honouring
    # the real payload/Range semantics); requests N+1 on send hostile_content_range
    # verbatim. Lets a hostile response be isolated to a chunk whose requested
    # start is nonzero, without also tripping the "wrong start" check.
    request_log: List[Optional[str]] = []

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silence default stderr logging
        pass

    def do_GET(self):
        cls = type(self)
        range_header = self.headers.get("Range")
        cls.request_log.append(range_header)
        n = len(cls.request_log)

        if cls.force_status is not None:
            body = b"forced-status-body"
            self.send_response(cls.force_status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return

        if cls.hostile_content_range is not None and n > cls.hostile_content_range_after:
            h_start, h_end, h_total = cls.hostile_content_range
            h_body = bytes((i * 13 + 5) % 256 for i in range(h_end - h_start + 1))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {h_start}-{h_end}/{h_total}")
            self.send_header("Content-Length", str(len(h_body)))
            self.send_header("ETag", cls.etag)
            self.send_header("Last-Modified", cls.last_modified)
            self.end_headers()
            self.wfile.write(h_body)
            self.wfile.flush()
            return

        etag = cls.etag
        if cls.flip_etag_after is not None and n > cls.flip_etag_after:
            etag = cls.etag + "-flipped"

        body = cls.payload
        if cls.flip_payload_after is not None and n > cls.flip_payload_after:
            body = cls.flipped_payload

        ignore_range_now = cls.ignore_range or (
            cls.ignore_range_after is not None and n > cls.ignore_range_after
        )

        if ignore_range_now or not range_header:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", cls.last_modified)
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return

        start, end = self._parse_range(range_header, len(body))
        chunk = body[start : end + 1]

        is_final = (end + 1) >= len(body)
        truncate = bool(cls.truncate_last_n_bytes) and is_final
        send_len = len(chunk) - cls.truncate_last_n_bytes if truncate else len(chunk)
        send_len = max(send_len, 0)

        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", cls.last_modified)
        self.end_headers()
        self.wfile.write(chunk[:send_len])
        self.wfile.flush()
        if truncate:
            # Force the socket closed now so the client sees EOF/IncompleteRead
            # promptly instead of hanging on a keep-alive connection.
            self.close_connection = True

    @staticmethod
    def _parse_range(range_header: str, total: int) -> Tuple[int, int]:
        spec = range_header.split("=", 1)[1]
        start_s, end_s = spec.split("-", 1)
        start = int(start_s)
        end = int(end_s) if end_s else total - 1
        end = min(end, max(total - 1, 0))
        return start, end


def start_server(payload: bytes, **handler_attrs) -> Tuple[http.server.HTTPServer, threading.Thread, str, Type[RangeHandler]]:
    handler_cls = type("Handler", (RangeHandler,), {})
    handler_cls.payload = payload
    handler_cls.request_log = []
    for k, v in handler_attrs.items():
        setattr(handler_cls, k, v)
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/payload.bin"
    return server, thread, url, handler_cls


def stop_server(server: http.server.HTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def flaky_opener(fail_after: int):
    """Wraps the real urllib.request.urlopen: lets the first `fail_after` real
    requests through unmodified, then raises ConnectionError -- simulates a
    dropped connection client-side while the server stays fully healthy."""
    import urllib.request

    real_urlopen = urllib.request.urlopen
    count = {"n": 0}

    def _opener(request, timeout=60):
        count["n"] += 1
        if count["n"] > fail_after:
            raise ConnectionError("simulated dropped connection")
        return real_urlopen(request, timeout=timeout)

    return _opener
