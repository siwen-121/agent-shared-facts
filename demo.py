"""Rehearse a Shared Facts publication with two temporary Git clones."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
RECORD_ID = "intake"


def run(cwd, env, stage, *command, expected=0):
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"{stage}: {error}") from error
    if result.returncode != expected:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{stage}: expected exit {expected}, got {result.returncode}. {detail}")
    return result.stdout


def rehearse(home):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_AUTHOR_NAME="Demo", GIT_AUTHOR_EMAIL="demo@example.invalid",
               GIT_COMMITTER_NAME="Demo", GIT_COMMITTER_EMAIL="demo@example.invalid")
    upstream = home / "upstream.git"
    writer = home / "writer"
    reader = home / "reader"
    candidate = home / "candidate.json"
    record_path = f"records/{RECORD_ID}.json"

    def git(cwd, *args):
        return run(cwd, env, f"{cwd.name}: git {args[0]}", "git", *args).strip().decode("ascii")

    def facts(cwd, *args, expected=0):
        output = run(cwd, env, f"{cwd.name}: {args[0]}", sys.executable, str(ROOT / "facts.py"),
                     "--repo", str(cwd), *args, expected=expected)
        return json.loads(output) if output else None

    git(home, "init", "--bare", "--initial-branch=main", str(upstream))
    git(home, "clone", str(upstream), str(writer))
    (writer / "records").mkdir()
    (writer / record_path).write_bytes((ROOT / "examples" / "initial.json").read_bytes())
    git(writer, "add", record_path)
    git(writer, "commit", "-m", "Seed synthetic record")
    git(writer, "push", "origin", "main")
    git(home, "clone", str(upstream), str(reader))
    initial = facts(reader, "snapshot", RECORD_ID, "--refresh")

    facts(writer, "candidate", RECORD_ID, str(ROOT / "examples" / "reviewed.json"), "--out", str(candidate))
    git(writer, "switch", "-c", "proposal/demo")
    applied = facts(writer, "apply", str(candidate))
    if applied["status"] != "applied-locally":
        raise RuntimeError("candidate: expected a locally applied change")
    git(writer, "add", record_path)
    git(writer, "commit", "-m", "Propose synthetic review")
    git(writer, "push", "origin", "proposal/demo")
    pending = facts(reader, "verify", str(candidate), expected=3)
    if pending["status"] != "ready" or pending["revision"] != initial["revision"]:
        raise RuntimeError("pending review: the published version changed before merge")

    git(writer, "switch", "main")
    git(writer, "merge", "--no-ff", "-m", "Simulate reviewed publication", "proposal/demo")
    merged_revision = git(writer, "rev-parse", "HEAD")
    git(writer, "push", "origin", "main")
    verified = facts(reader, "verify", str(candidate))
    readback = facts(reader, "snapshot", RECORD_ID)
    intended = json.loads((ROOT / "examples" / "reviewed.json").read_bytes())
    if (verified["status"] != "already-published" or verified["read"] != "fetched"
            or verified["revision"] != merged_revision or readback["revision"] != merged_revision
            or readback["record"] != intended):
        raise RuntimeError("read-back: the reader did not confirm the merged revision and record")

    return {"id": RECORD_ID, "before_merge": {"status": "unpublished", "revision": pending["revision"]},
            "after_merge": {"status": "verified", "revision": verified["revision"],
                            "state": readback["record"]["state"]},
            "environment": "synthetic-local-two-clone"}


def main():
    try:
        with tempfile.TemporaryDirectory(prefix="shared-facts-demo-") as temp:
            receipt = rehearse(Path(temp))
    except (RuntimeError, OSError) as error:
        print(f"Shared Facts demo: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
