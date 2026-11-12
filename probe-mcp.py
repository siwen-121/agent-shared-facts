"""Verify an HTTP MCP route using a synthetic allowlisted record."""
import argparse
import json
import os
from urllib.parse import urlsplit

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("record_id")
    parser.add_argument("--cloudflare", action="store_true")
    args = parser.parse_args()
    url = urlsplit(args.url)
    loopback = url.hostname in {"127.0.0.1", "localhost"}
    if (url.scheme != "https" and not (url.scheme == "http" and loopback)) or (
        not url.hostname or url.username or url.password or url.query or url.fragment or url.path != "/mcp"
    ):
        parser.error("Provide an HTTPS URL ending in /mcp, or HTTP on loopback.")
    token = os.environ.get("SHARED_FACTS_HTTP_TOKEN")
    if not token:
        parser.error("Set SHARED_FACTS_HTTP_TOKEN for this session.")
    headers = {"Authorization": f"Bearer {token}"}
    if args.cloudflare:
        for header, variable in (("CF-Access-Client-Id", "CF_ACCESS_CLIENT_ID"),
                                 ("CF-Access-Client-Secret", "CF_ACCESS_CLIENT_SECRET")):
            if not os.environ.get(variable):
                parser.error(f"Set {variable} for this session.")
            headers[header] = os.environ[variable]

    async def probe():
        with anyio.fail_after(50):
            timeout = httpx.Timeout(40, connect=10)
            async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=timeout) as client:
                request = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "shared-facts-probe", "version": "1"}}}
                denied = await client.post(args.url, json=request,
                                           headers={"Accept": "application/json, text/event-stream"})
                if denied.status_code not in {302, 303, 307, 401, 403}:
                    raise RuntimeError(f"Unexpected status without credentials: {denied.status_code}")
                client.headers.update(headers)
                async with streamable_http_client(args.url, http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        if names != {"list_record_ids", "get_published_record"}:
                            raise RuntimeError("Unexpected MCP tool set.")
                        result = await session.call_tool(
                            "get_published_record", {"record_id": args.record_id, "refresh": True})
                        if result.isError or not result.structuredContent:
                            raise RuntimeError("Record read failed.")
                        data = result.structuredContent
                        if data["record"] is None or data["read"] != "fetched":
                            raise RuntimeError("No published record was fetched.")
                        print(json.dumps({"unauthenticated_status": denied.status_code, "id": data["id"],
                                          "revision": data["revision"], "state": data["record"]["state"]}))

    anyio.run(probe)


if __name__ == "__main__":
    main()
