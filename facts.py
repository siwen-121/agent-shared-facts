"""Read published Git snapshots and prepare changes on proposal branches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

KEY = re.compile(r"[a-z][a-z0-9-]{0,47}")
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
DIGEST = re.compile(r"[0-9a-f]{64}")
RECORD_FIELDS = {"state", "summary", "evidence"}
MAX_BYTES = 16384


class FactError(Exception):
    pass


def valid_key(key):
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise FactError("Use a lowercase record ID with letters, digits and hyphens.")
    return key


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def strict_json(data):
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise FactError("Duplicate JSON keys.")
        return result

    if len(data) > MAX_BYTES:
        raise FactError("JSON exceeds 16 KiB.")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise FactError("Expected a valid UTF-8 JSON document.") from exc


def validate_record(record):
    if not isinstance(record, dict) or record.keys() != RECORD_FIELDS:
        raise FactError("Record requires exactly state, summary and evidence.")
    for field, maximum in (("state", 48), ("summary", 800)):
        value = record[field]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise FactError(f"Invalid {field} text.")
        if any(not character.isprintable() for character in value):
            raise FactError(f"{field} must contain printable characters only.")
    if not KEY.fullmatch(record["state"]):
        raise FactError("State must be a lowercase slug.")
    evidence = record["evidence"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 12:
        raise FactError("Provide 1–12 shareable evidence IDs.")
    for entry in evidence:
        valid_key(entry)
    if len(set(evidence)) != len(evidence):
        raise FactError("Evidence IDs must be unique.")
    return record


def fingerprint(record):
    return hashlib.sha256(encode(record)).hexdigest() if record is not None else None


def atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".facts-")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Store:
    def __init__(self, repo, remote="origin", branch="main"):
        self.repo = Path(repo).resolve()
        self.remote = valid_key(remote)
        self.branch = valid_key(branch)
        self.ref = f"refs/remotes/{remote}/{branch}"

    def git(self, *args, timeout=15):
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FactError(f"Git {args[0]} unavailable or timed out.") from exc
        if result.returncode:
            raise FactError(f"Git {args[0]} failed. Check repository, refs or credentials locally.")
        return result.stdout

    def pin(self, refresh):
        if refresh:
            self.git("fetch", "--no-tags", "--no-write-fetch-head", self.remote,
                     f"+refs/heads/{self.branch}:{self.ref}", timeout=30)
        return self.git("rev-parse", "--verify", f"{self.ref}^{{commit}}").decode().strip()

    def record(self, revision, key):
        valid_key(key)
        path = f"records/{key}.json"
        entry = self.git("ls-tree", revision, "--", path)
        if not entry:
            return None
        if not entry.startswith(b"100644 blob "):
            raise FactError("Record must be a regular non-executable Git file.")
        if int(self.git("cat-file", "-s", f"{revision}:{path}")) > MAX_BYTES:
            raise FactError("Published record exceeds 16 KiB.")
        raw = self.git("show", f"{revision}:{path}")
        record = validate_record(strict_json(raw))
        if raw != encode(record):
            raise FactError("Published record must be canonical single-line JSON.")
        return record

    def snapshot(self, key, refresh=False):
        valid_key(key)
        revision = self.pin(refresh)
        record = self.record(revision, key)
        return {"id": key, "revision": revision, "record": record,
                "read": "fetched" if refresh else "cache-freshness-unknown"}

    def candidate(self, key, record, refresh=False):
        snapshot = self.snapshot(key, refresh)
        return {"id": key, "base": snapshot["revision"], "before": fingerprint(snapshot["record"]),
                "record": validate_record(record)}

    def plan(self, proposal, refresh=True):
        if not isinstance(proposal, dict) or proposal.keys() != {"id", "base", "before", "record"}:
            raise FactError("Candidate requires id, base, before and record.")
        key = valid_key(proposal["id"])
        base, before = proposal["base"], proposal["before"]
        if not isinstance(base, str) or not SHA.fullmatch(base):
            raise FactError("Invalid base commit.")
        if before is not None and (not isinstance(before, str) or not DIGEST.fullmatch(before)):
            raise FactError("Invalid base record digest.")
        intended = validate_record(proposal["record"])
        current = self.snapshot(key, refresh)
        if before != fingerprint(self.record(base, key)):
            raise FactError("Candidate digest disagrees with its base commit.")
        self.git("merge-base", "--is-ancestor", base, current["revision"])
        if current["record"] == intended:
            state = "already-published"
        elif fingerprint(current["record"]) != before:
            state = "conflict"
        else:
            state = "ready"
        return {"status": state, "id": key, "revision": current["revision"], "read": current["read"]}

    def apply(self, proposal):
        result = self.plan(proposal)
        if result["status"] != "ready":
            return result
        branch = self.git("symbolic-ref", "--short", "HEAD").decode().strip()
        if not branch.startswith("proposal/"):
            raise FactError("Switch to a dedicated proposal/ branch.")
        head = self.git("rev-parse", "HEAD").decode().strip()
        if head != result["revision"] or self.git("status", "--porcelain", "--untracked-files=all"):
            raise FactError("Use a clean proposal branch at the fetched revision.")
        records = self.repo / "records"
        target = records / f'{result["id"]}.json'
        if records.is_symlink() or records.is_junction() or target.is_symlink():
            raise FactError("Records must stay inside the checkout.")
        atomic_write(target, encode(proposal["record"]))
        return {**result, "status": "applied-locally"}


def file_json(filename):
    with Path(filename).open("rb") as file:
        return strict_json(file.read(MAX_BYTES + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("snapshot", "candidate"):
        command = sub.add_parser(name)
        command.add_argument("id")
        command.add_argument("--refresh", action="store_true")
        if name == "candidate":
            command.add_argument("record")
            command.add_argument("--out", type=Path, help="Write UTF-8 JSON to a new file.")
    for name in ("plan", "apply", "verify"):
        sub.add_parser(name).add_argument("candidate")
    args = parser.parse_args()
    try:
        store = Store(args.repo, args.remote, args.branch)
        if args.action == "snapshot":
            result = store.snapshot(args.id, args.refresh)
        elif args.action == "candidate":
            result = store.candidate(args.id, file_json(args.record), args.refresh)
        else:
            proposal = file_json(args.candidate)
            if args.action == "apply":
                result = store.apply(proposal)
            else:
                result = store.plan(proposal)
        payload = encode(result)
        if args.action == "candidate" and args.out:
            with args.out.open("xb") as file:
                file.write(payload)
        else:
            sys.stdout.buffer.write(payload)
    except (FactError, OSError) as exc:
        print(f"facts: {exc}", file=sys.stderr)
        return 1
    if result.get("status") == "conflict":
        return 2
    if args.action == "verify" and result["status"] != "already-published":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
