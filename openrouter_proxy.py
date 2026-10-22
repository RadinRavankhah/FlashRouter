"""A small local OpenAI-compatible proxy.

Configure the upstream with UPSTREAM_BASE_URL, UPSTREAM_API_KEY, and
UPSTREAM_MODEL, then point OpenCode at http://127.0.0.1:8765/v1.
The proxy forwards requests and replaces the model on chat/completions calls.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    upstream_base_url = ""
    upstream_api_key = ""
    upstream_model = ""
    upstream_http_referer = ""
    upstream_title = ""

    def do_GET(self) -> None:
        self._proxy_request()

    def do_POST(self) -> None:
        self._proxy_request()

    def _proxy_request(self) -> None:
        content_length = self.headers.get("Content-Length", "0")
        try:
            body_size = int(content_length)
        except ValueError:
            self._send_json_error(400, "Invalid Content-Length header")
            return
        if body_size < 0:
            self._send_json_error(400, "Content-Length cannot be negative")
            return
        body = self.rfile.read(body_size)

        parsed_path = urlsplit(self.path)
        upstream_path = parsed_path.path
        if upstream_path == "/v1":
            upstream_path = ""
        elif upstream_path.startswith("/v1/"):
            upstream_path = upstream_path[3:]

        upstream_url = self.upstream_base_url.rstrip("/") + upstream_path
        if parsed_path.query:
            upstream_url += "?" + parsed_path.query

        if self.command == "POST" and upstream_path.rstrip("/").endswith(
            ("/chat/completions", "/completions", "/responses")
        ):
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json_error(400, "Request body must be valid JSON")
                return
            if not isinstance(payload, dict):
                self._send_json_error(400, "Request body must be a JSON object")
                return
            payload["model"] = self.upstream_model
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        headers: dict[str, str] = {}
        connection_tokens = {
            token.strip().lower()
            for token in self.headers.get("Connection", "").split(",")
        }
        hop_by_hop_headers = {
            "connection",
            "content-length",
            "host",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }
        for name, value in self.headers.items():
            lowered_name = name.lower()
            if lowered_name not in hop_by_hop_headers | connection_tokens:
                headers[name] = value

        headers["Authorization"] = f"Bearer {self.upstream_api_key}"
        if self.upstream_http_referer:
            headers["HTTP-Referer"] = self.upstream_http_referer
        if self.upstream_title:
            headers["X-OpenRouter-Title"] = self.upstream_title

        request = Request(
            upstream_url,
            data=body if self.command == "POST" else None,
            headers=headers,
            method=self.command,
        )

        try:
            try:
                upstream_response = urlopen(request, timeout=180)
            except HTTPError as error:
                upstream_response = error
        except URLError as error:
            self._send_json_error(502, f"Upstream request failed: {error.reason}")
            return
        except OSError as error:
            self._send_json_error(502, f"Upstream connection failed: {error}")
            return

        with upstream_response:
            self.send_response(upstream_response.status)
            response_connection_tokens = {
                token.strip().lower()
                for token in upstream_response.headers.get("Connection", "").split(",")
            }
            for name, value in upstream_response.headers.items():
                lowered_name = name.lower()
                if lowered_name not in hop_by_hop_headers | response_connection_tokens:
                    self.send_header(name, value)
            self.end_headers()

            while True:
                chunk = upstream_response.read1(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

    def _send_json_error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    required_settings = {
        "UPSTREAM_BASE_URL": os.getenv("UPSTREAM_BASE_URL", "").strip(),
        "UPSTREAM_API_KEY": os.getenv("UPSTREAM_API_KEY", "").strip(),
        "UPSTREAM_MODEL": os.getenv("UPSTREAM_MODEL", "").strip(),
    }
    missing_settings = [name for name, value in required_settings.items() if not value]
    if missing_settings:
        names = ", ".join(missing_settings)
        raise SystemExit(f"Set the following environment variables: {names}")

    ProxyHandler.upstream_base_url = required_settings["UPSTREAM_BASE_URL"]
    ProxyHandler.upstream_api_key = required_settings["UPSTREAM_API_KEY"]
    ProxyHandler.upstream_model = required_settings["UPSTREAM_MODEL"]
    ProxyHandler.upstream_http_referer = os.getenv("UPSTREAM_HTTP_REFERER", "").strip()
    ProxyHandler.upstream_title = os.getenv("UPSTREAM_TITLE", "").strip()

    host = os.getenv("PROXY_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("PROXY_PORT", "8765"))
    except ValueError as error:
        raise SystemExit("PROXY_PORT must be an integer") from error

    server = ThreadingHTTPServer((host, port), ProxyHandler)
    print(f"Proxy listening at http://{host}:{port}/v1")
    print(f"Forwarding to {ProxyHandler.upstream_base_url} using model {ProxyHandler.upstream_model}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProxy stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
