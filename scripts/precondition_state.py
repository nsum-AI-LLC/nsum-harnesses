#!/usr/bin/env python3
"""Shared state library for the precondition-gate harness.

Per-session state lives at:
    ~/.cache/claude-harness/sessions/{session_id}/
        reads.jsonl         — append-log of Read tool calls
        preconditions.json  — required reads not yet satisfied
        bypass.jsonl        — logged bypasses with structured reason

This module provides the read/write primitives. Hooks shell into the CLI;
other Python code can import the functions directly.

Design principles:
- FAIL-OPEN: any error in reading/writing state returns the empty/safe value.
  A broken gate that blocks every tool call is worse than no gate.
- Path normalization: required_reads can be relative or absolute; reads.jsonl
  is absolute. Matching normalizes via os.path.realpath.
- Idempotent: adding the same precondition twice is a no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

CACHE_ROOT = Path.home() / ".cache" / "claude-harness" / "sessions"
BYPASS_CATEGORIES = {
    "false_positive",
    "scope_limited",
    "already_familiar",
    "urgent_user_request",
    "other",
}


def session_dir(session_id: str) -> Path:
    """Return the per-session state directory, creating it if needed."""
    if not session_id or session_id == "unknown":
        # Fall back to a "no-session" bucket so hooks still function during
        # tests or contexts where session_id is missing.
        session_id = "_no_session"
    d = CACHE_ROOT / session_id
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_path(p: str, project_dir: str | None = None) -> str:
    """Resolve a path to a canonical absolute form for matching."""
    if not p:
        return ""
    pth = Path(p)
    if not pth.is_absolute() and project_dir:
        pth = Path(project_dir) / pth
    try:
        return str(pth.resolve(strict=False))
    except (OSError, RuntimeError):
        return str(pth)


# --- reads.jsonl ---

def record_read(session_id: str, path: str) -> None:
    """Append a Read entry to reads.jsonl. FAIL-OPEN."""
    if not path:
        return
    try:
        entry = {"ts": now_iso(), "path": normalize_path(path)}
        f = session_dir(session_id) / "reads.jsonl"
        with f.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def list_reads(session_id: str) -> set[str]:
    """Return the set of absolute paths Read this session."""
    f = session_dir(session_id) / "reads.jsonl"
    if not f.exists():
        return set()
    out = set()
    try:
        with f.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "path" in obj:
                        out.add(obj["path"])
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


# --- preconditions.json ---

def load_preconditions(session_id: str) -> list[dict]:
    """Return the list of precondition entries (may be empty)."""
    f = session_dir(session_id) / "preconditions.json"
    if not f.exists():
        return []
    try:
        with f.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data.get("required_reads", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_preconditions(session_id: str, entries: list[dict]) -> None:
    """Overwrite the preconditions file. FAIL-OPEN."""
    f = session_dir(session_id) / "preconditions.json"
    try:
        with f.open("w", encoding="utf-8") as fp:
            json.dump({"required_reads": entries}, fp, indent=2)
    except OSError:
        pass


def add_precondition(
    session_id: str,
    path: str,
    reason: str,
    set_by: str,
    project_dir: str | None = None,
) -> None:
    """Add a required read; idempotent on (normalized) path."""
    norm = normalize_path(path, project_dir)
    if not norm:
        return
    entries = load_preconditions(session_id)
    for e in entries:
        if e.get("path") == norm:
            return  # already present
    entries.append({
        "path": norm,
        "reason": reason,
        "set_by": set_by,
        "set_at": now_iso(),
    })
    save_preconditions(session_id, entries)


def unsatisfied_preconditions(
    session_id: str,
    project_dir: str | None = None,
) -> list[dict]:
    """Return preconditions not yet satisfied by a Read in this session."""
    entries = load_preconditions(session_id)
    if not entries:
        return []
    reads = list_reads(session_id)
    bypassed = bypassed_paths(session_id)
    unsatisfied = []
    for e in entries:
        p = e.get("path", "")
        norm = normalize_path(p, project_dir)
        if norm and (norm in reads or norm in bypassed):
            continue
        unsatisfied.append(e)
    return unsatisfied


# --- bypass.jsonl ---

def record_bypass(
    session_id: str,
    path: str,
    category: str,
    reason: str,
    project_dir: str | None = None,
) -> str | None:
    """Log a bypass. Returns the normalized path that was bypassed, or None on error."""
    if category not in BYPASS_CATEGORIES:
        return None
    norm = normalize_path(path, project_dir)
    if not norm:
        return None
    try:
        entry = {
            "ts": now_iso(),
            "path": norm,
            "category": category,
            "reason": reason or "",
        }
        f = session_dir(session_id) / "bypass.jsonl"
        with f.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry) + "\n")
        return norm
    except OSError:
        return None


def bypassed_paths(session_id: str) -> set[str]:
    """Return the set of normalized paths bypassed this session."""
    f = session_dir(session_id) / "bypass.jsonl"
    if not f.exists():
        return set()
    out = set()
    try:
        with f.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "path" in obj:
                        out.add(obj["path"])
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


# --- CLI ---

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_read = sub.add_parser("record-read", help="Append a Read entry to reads.jsonl")
    p_read.add_argument("--session-id", required=True)
    p_read.add_argument("--path", required=True)

    p_add = sub.add_parser("add", help="Add a required-read precondition")
    p_add.add_argument("--session-id", required=True)
    p_add.add_argument("--path", required=True)
    p_add.add_argument("--reason", required=True)
    p_add.add_argument("--set-by", required=True)
    p_add.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR", ""))

    p_check = sub.add_parser("check", help="Print unsatisfied preconditions (one per line)")
    p_check.add_argument("--session-id", required=True)
    p_check.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR", ""))
    p_check.add_argument("--exit-code-on-block", type=int, default=2)

    p_bypass = sub.add_parser("bypass", help="Log a precondition bypass")
    p_bypass.add_argument("--session-id", required=True)
    p_bypass.add_argument("--path", required=True)
    p_bypass.add_argument(
        "--category",
        required=True,
        choices=sorted(BYPASS_CATEGORIES),
    )
    p_bypass.add_argument("--reason", default="")
    p_bypass.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR", ""))

    p_list = sub.add_parser("list", help="Print all preconditions and their status")
    p_list.add_argument("--session-id", required=True)
    p_list.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR", ""))

    p_clear = sub.add_parser("clear", help="Clear all preconditions for this session")
    p_clear.add_argument("--session-id", required=True)

    args = parser.parse_args()

    if args.cmd == "record-read":
        record_read(args.session_id, args.path)
        return 0

    if args.cmd == "add":
        add_precondition(
            args.session_id,
            args.path,
            args.reason,
            args.set_by,
            args.project_dir or None,
        )
        return 0

    if args.cmd == "check":
        unsatisfied = unsatisfied_preconditions(
            args.session_id,
            args.project_dir or None,
        )
        if not unsatisfied:
            return 0
        # Stderr is what the model sees when the hook blocks
        print("PRECONDITION BLOCK — required reads not yet completed:",
              file=sys.stderr)
        print("", file=sys.stderr)
        for e in unsatisfied:
            print(f"  • {e.get('path')}", file=sys.stderr)
            if e.get("reason"):
                print(f"    Reason: {e['reason']}", file=sys.stderr)
            if e.get("set_by"):
                print(f"    Required by: {e['set_by']}", file=sys.stderr)
        print("", file=sys.stderr)
        print("To proceed: Read each file above.", file=sys.stderr)
        print("To bypass (logged): claude_bypass <path> <category> [reason]",
              file=sys.stderr)
        print(f"Valid categories: {', '.join(sorted(BYPASS_CATEGORIES))}",
              file=sys.stderr)
        return args.exit_code_on_block

    if args.cmd == "bypass":
        norm = record_bypass(
            args.session_id,
            args.path,
            args.category,
            args.reason,
            args.project_dir or None,
        )
        if norm:
            print(f"Bypassed: {norm} (category={args.category})")
        else:
            print("Bypass failed (invalid path or category)", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "list":
        entries = load_preconditions(args.session_id)
        if not entries:
            print("No preconditions set.")
            return 0
        reads = list_reads(args.session_id)
        bypassed = bypassed_paths(args.session_id)
        for e in entries:
            norm = normalize_path(e.get("path", ""), args.project_dir or None)
            if norm in reads:
                status = "READ"
            elif norm in bypassed:
                status = "BYPASSED"
            else:
                status = "PENDING"
            print(f"[{status}] {e.get('path')}")
            if e.get("reason"):
                print(f"        reason: {e['reason']}")
        return 0

    if args.cmd == "clear":
        save_preconditions(args.session_id, [])
        print("Preconditions cleared.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
