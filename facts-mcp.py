"""Serve allowlisted Git records through read-only MCP."""
import argparse
import hmac
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import uvicorn

from facts import FactError, Store, valid_key


class RequireBearer:
    def __init__(self, app, token):
        self.app = app
        self.expected = b"Bearer " + token.encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = [value for name, value in scope["headers"] if name == b"authorization"]
            if len(supplied) != 1 or not hmac.compare_digest(supplied[0], self.expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"www-authenticate", b"Bearer"),
                                        (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": b""})
                return
        async def send_uncached(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message["headers"] if key != b"cache-control"]
                message = {**message, "headers": [*headers, (b"cache-control", b"no-store")]}
            await send(message)

        await self.app(scope, receive, send_uncached)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--allow", action="append", required=True, help="Repeat for each shareable record ID.")
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--hostname", action="append", default=[], help="Exact reverse proxy hostname.")
    args = parser.parse_args()
    allowed = frozenset(valid_key(key) for key in args.allow)
    store = Store(args.repo, args.remote, args.branch)
    hostname = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
    if any(not hostname.fullmatch(name) for name in args.hostname):
        parser.error("Use exact lowercase DNS hostnames.")
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"127.0.0.1:{args.port}", f"localhost:{args.port}", *args.hostname],
        allowed_origins=[],
    )
    server = FastMCP("Shared Facts", stateless_http=True, json_response=True, transport_security=security)

    @server.tool()
    def list_record_ids() -> list[str]:
        """List the IDs approved for this connector."""
        return sorted(allowed)

    @server.tool()
    def get_published_record(record_id: str, refresh: bool = False) -> dict[str, Any]:
        """Read a shareable record and its pinned Git revision. Refresh for a current upstream read."""
        if record_id not in allowed:
            raise ValueError("Record ID is outside this connector's allowlist.")
        try:
            return store.snapshot(record_id, refresh)
        except (FactError, OSError) as exc:
            raise ValueError("Published snapshot unavailable. Check the repository connection.") from exc

    if args.http:
        token = os.environ.get("SHARED_FACTS_HTTP_TOKEN", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            parser.error("Set SHARED_FACTS_HTTP_TOKEN to a randomly generated URL-safe token.")
        app = RequireBearer(server.streamable_http_app(), token)
        uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
