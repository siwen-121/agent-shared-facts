import importlib.util
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("setup_devices", ROOT / "setup-devices.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class DeviceSetupTests(unittest.TestCase):
    def cli(self, *args, code=0, launcher=None):
        command = launcher or [sys.executable, str(ROOT / "setup-devices.py")]
        result = subprocess.run([*command, *args, "--json"], cwd=ROOT,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, code, result.stderr.decode(errors="replace"))
        return json.loads(result.stdout)

    def test_macos_desktop_and_ssh_use_private_network(self):
        desktop = self.cli("--goal", "desktop", "--target-os", "macos")
        terminal = self.cli("--goal", "terminal", "--target-os", "macos")
        self.assertEqual((desktop["route"], desktop["network"]), ("screen-sharing", "tailscale"))
        self.assertEqual((terminal["route"], terminal["network"]), ("ssh", "tailscale"))

    def test_windows_desktop_requires_confirmed_rdp_host(self):
        for capability, route, code in (("unknown", "check-rdp-host", 2),
                                        ("no", "rdp-unavailable", 2), ("yes", "rdp", 0)):
            with self.subTest(capability=capability):
                result = self.cli("--goal", "desktop", "--target-os", "windows",
                                  "--rdp-host", capability, code=code)
                self.assertEqual(result["route"], route)
                self.assertEqual(result["blocked"], code == 2)

    def test_cloud_project_requires_oauth_compatibility(self):
        for status in ("unknown", "incompatible"):
            result = self.cli("--goal", "project", "--origin", "cloud", "--oauth", status)
            self.assertEqual(result["route"], "github-read")
            self.assertIsNone(result["network"])
        result = self.cli("--goal", "project", "--origin", "cloud", "--oauth", "compatible")
        self.assertEqual((result["route"], result["network"]), ("devspace-public", "cloudflare"))

    def test_project_target_detects_current_os(self):
        result = self.cli("--goal", "project", "--role", "target")
        self.assertEqual(result["target_os"], setup.SYSTEMS[platform.system()])
        self.assertEqual(result["route"], "devspace-private")

    def test_platform_launcher_and_facts_plan(self):
        launcher = ["cmd.exe", "/d", "/c", "setup.cmd"] if os.name == "nt" else ["sh", "setup.sh"]
        result = self.cli("--goal", "facts", launcher=launcher)
        self.assertEqual(result["route"], "shared-facts")
        self.assertNotIn("prepared", result)

    def test_project_install_refuses_on_client(self):
        result = self.cli("--goal", "project", "--prepare", code=1)
        self.assertIn("error", result)
        self.assertNotIn("prepared", result)

    def test_facts_setup_rejects_source_checkout_subdirectory(self):
        if not (ROOT / ".git").exists():
            self.skipTest("Requires a Git checkout to test parent discovery.")
        result = self.cli("--goal", "facts", "--prepare", "--data-repo", str(ROOT / "docs"),
                          "--record", "intake", code=1)
        self.assertIn("仓库根目录", result["error"])

    def test_devspace_audit_stops_high_risk_or_unavailable_results(self):
        report = {"metadata": {"vulnerabilities": {"high": 1, "critical": 0}}}
        for payload in (json.dumps(report).encode(), b""):
            with self.subTest(payload=payload):
                result = subprocess.CompletedProcess(["npm"], 1, stdout=payload)
                with patch.object(setup.subprocess, "run", return_value=result):
                    with self.assertRaises(RuntimeError):
                        setup.audit_devspace("npm", ROOT)
        report["metadata"]["vulnerabilities"]["high"] = 0
        result = subprocess.CompletedProcess(["npm"], 0, stdout=json.dumps(report).encode())
        with patch.object(setup.subprocess, "run", return_value=result):
            setup.audit_devspace("npm", ROOT)

    def test_private_tcp_probe_accepts_loopback_and_rejects_public_address(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            self.assertEqual(setup.probe_private_host("127.0.0.1", port)["address"], "127.0.0.1")
        with patch.object(setup.socket, "create_connection") as connect:
            with self.assertRaises(RuntimeError):
                setup.probe_private_host("203.0.113.7", 22)
            connect.assert_not_called()
