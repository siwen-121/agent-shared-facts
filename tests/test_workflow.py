import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from facts import encode


class SharedFactsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.remote = self.home / "remote.git"
        self.writer = self.home / "writer"
        self.reader = self.home / "reader"
        self.env = {
            **os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Synthetic Writer", "GIT_AUTHOR_EMAIL": "writer@example.invalid",
            "GIT_COMMITTER_NAME": "Synthetic Writer", "GIT_COMMITTER_EMAIL": "writer@example.invalid",
        }
        self.run_git(self.home, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.run_git(self.home, "clone", str(self.remote), str(self.writer))
        (self.writer / "records").mkdir()
        shutil.copyfile(ROOT / "examples/initial.json", self.writer / "records/intake.json")
        self.run_git(self.writer, "add", "records/intake.json")
        self.run_git(self.writer, "commit", "-m", "Synthetic intake")
        self.run_git(self.writer, "push", "origin", "main")
        self.run_git(self.home, "clone", str(self.remote), str(self.reader))

    def run_git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True, env=self.env, timeout=10).stdout.strip()

    def cli(self, repo, *args, code=0):
        result = subprocess.run([sys.executable, str(ROOT / "facts.py"), "--repo", str(repo), *args],
                                capture_output=True, env=self.env, timeout=40)
        self.assertEqual(result.returncode, code, result.stderr.decode())
        return json.loads(result.stdout) if result.stdout else None

    def candidate(self, key="intake", name="candidate.json"):
        path = self.home / name
        self.cli(self.reader, "candidate", key, str(ROOT / "examples/reviewed.json"), "--out", str(path))
        return str(path)

    def publish(self, key, state):
        (self.writer / f"records/{key}.json").write_bytes(
            encode({"state": state, "summary": "Another synthetic change.", "evidence": ["demo-change"]}))
        self.run_git(self.writer, "add", f"records/{key}.json")
        self.run_git(self.writer, "commit", "-m", "Change synthetic record")
        self.run_git(self.writer, "push", "origin", "main")

    def test_end_to_end_and_idempotence(self):
        base = self.cli(self.reader, "snapshot", "intake", "--refresh")
        self.assertEqual(base["read"], "fetched")
        candidate = self.candidate()
        self.assertEqual(self.cli(self.reader, "verify", candidate, code=3)["status"], "ready")
        self.cli(self.writer, "apply", candidate, code=1)
        self.run_git(self.writer, "switch", "-c", "proposal/review")
        self.assertEqual(self.cli(self.writer, "apply", candidate)["status"], "applied-locally")
        self.run_git(self.writer, "add", "records/intake.json")
        self.run_git(self.writer, "commit", "-m", "Review synthetic intake")
        self.run_git(self.writer, "push", "origin", "proposal/review")
        self.assertEqual(self.cli(self.reader, "verify", candidate, code=3)["status"], "ready")
        self.run_git(self.writer, "switch", "main")
        self.run_git(self.writer, "merge", "--no-ff", "proposal/review")
        self.run_git(self.writer, "push", "origin", "main")
        cached = self.cli(self.reader, "snapshot", "intake")
        self.assertEqual(cached["read"], "cache-freshness-unknown")
        self.assertEqual(cached["revision"], base["revision"])
        result = self.cli(self.reader, "verify", candidate)
        self.assertEqual(result["status"], "already-published")
        self.assertNotEqual(result["revision"], base["revision"])
        self.assertEqual(self.cli(self.writer, "apply", candidate)["status"], "already-published")

    def test_offline_candidate_and_same_record_conflict(self):
        self.run_git(self.reader, "remote", "set-url", "origin", str(self.home / "offline"))
        candidate = self.candidate()
        self.cli(self.reader, "plan", candidate, code=1)
        self.publish("intake", "cancelled")
        self.run_git(self.reader, "remote", "set-url", "origin", str(self.remote))
        self.assertEqual(self.cli(self.reader, "plan", candidate, code=2)["status"], "conflict")
        self.assertEqual(self.cli(self.reader, "apply", candidate, code=2)["status"], "conflict")

    def test_disjoint_update_and_clean_proposal(self):
        candidate = self.candidate("second")
        self.publish("intake", "changed")
        self.assertEqual(self.cli(self.reader, "plan", candidate)["status"], "ready")
        self.run_git(self.reader, "switch", "-c", "proposal/create-second")
        self.cli(self.reader, "apply", candidate, code=1)
        self.run_git(self.reader, "reset", "--hard", "origin/main")
        (self.reader / "unrelated.txt").write_text("dirty")
        self.cli(self.reader, "apply", candidate, code=1)
        (self.reader / "unrelated.txt").unlink()
        self.assertEqual(self.cli(self.reader, "apply", candidate)["status"], "applied-locally")

    def test_reject_path_and_tampered_base(self):
        self.cli(self.reader, "snapshot", "../private", code=1)
        candidate = Path(self.candidate())
        proposal = json.loads(candidate.read_bytes())
        proposal["before"] = "0" * 64
        candidate.write_bytes(encode(proposal))
        self.cli(self.reader, "plan", str(candidate), code=1)

    def mcp_command(self):
        return [sys.executable, str(ROOT / "facts-mcp.py"), "--repo", str(self.reader), "--allow", "intake"]

    def test_stdio_mcp(self):
        import anyio
        from mcp import ClientSession, StdioServerParameters, stdio_client

        async def scenario():
            with anyio.fail_after(15):
                command, *args = self.mcp_command()
                params = StdioServerParameters(command=command, args=args)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = {item.name for item in (await session.list_tools()).tools}
                        self.assertEqual(tools, {"list_record_ids", "get_published_record"})
                        record = await session.call_tool("get_published_record", {"record_id": "intake"})
                        self.assertFalse(record.isError, str(record.content))
                        self.assertEqual(record.structuredContent["record"]["state"], "queued")
                        denied = await session.call_tool("get_published_record", {"record_id": "unlisted"})
                        self.assertTrue(denied.isError)
        anyio.run(scenario)

    def test_http_mcp_requires_auth_and_rejects_untrusted_host(self):
        import anyio
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import secrets

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        token = secrets.token_urlsafe(32)
        server = subprocess.Popen([*self.mcp_command(), "--http", "--port", str(port)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  env={**self.env, "SHARED_FACTS_HTTP_TOKEN": token})
        try:
            url = f"http://127.0.0.1:{port}/mcp"
            for _ in range(80):
                try:
                    urllib.request.urlopen(url, timeout=0.4).close()
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 401)
                    break
                except urllib.error.URLError:
                    if server.poll() is not None:
                        self.fail("MCP HTTP server exited early")
                    time.sleep(0.1)
                else:
                    self.fail("Unauthenticated request accepted")
            else:
                self.fail("MCP HTTP server never became ready")

            async def scenario():
                with anyio.fail_after(15):
                    headers = {"Authorization": "Bearer " + token}
                    async with httpx.AsyncClient(headers=headers, trust_env=False) as client:
                        bad = await client.post(url, headers={"Host": "untrusted.example.invalid"}, json={})
                        self.assertEqual(bad.status_code, 421)
                        self.assertIn("Invalid Host", bad.text)
                        async with streamable_http_client(url, http_client=client) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                record = await session.call_tool("get_published_record", {"record_id": "intake"})
                                self.assertFalse(record.isError, str(record.content))
                                self.assertEqual(record.structuredContent["record"]["state"], "queued")
            anyio.run(scenario)
            probe = subprocess.run([sys.executable, str(ROOT / "probe-mcp.py"), url, "intake"],
                                   capture_output=True, check=True, timeout=20,
                                   env={**self.env, "SHARED_FACTS_HTTP_TOKEN": token})
            result = json.loads(probe.stdout)
            self.assertEqual(result["unauthenticated_status"], 401)
            self.assertEqual(result["state"], "queued")
            self.assertEqual(result["revision"], self.run_git(self.writer, "rev-parse", "HEAD"))
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
