#!/usr/bin/env python3
"""Classify worktrees as SAFE-to-prune, REVIEW, HOLD or UNKNOWN.

WHY THIS EXISTS (BW-5055, 2026-09-04)

Worktrees accumulated to 341 because the only bulk cleanup mode,
`prune_worktrees.sh --sprint N`, matches worktrees whose BRANCH NAME contains
`bw-N`. The platform creates agent worktrees as `agent-<hash>` with a detached
HEAD, so 238 of 341 (70%) were structurally unmatchable — and the mode reports
"0 matched" rather than erroring, so every sprint close looked clean while
reclaiming nothing.

The reason nobody just deleted the rest is the hazard BW-5055 documents: a dirty
worktree LOOKS like unharvested work, and some of it is residue from mutation
testing — including staged REVERTS. Harvesting one would have re-shipped an old
prompt version and deleted a live rule. So the missing piece was never a bigger
hammer; it was a test that separates residue from work MECHANICALLY, instead of
in a reader's head.

THE CLASSIFICATION. KEEP wins on any doubt.

  SAFE    every commit is on a remote, nothing uncommitted, nothing untracked,
          and idle — losing the directory loses nothing.
  REVIEW  has uncommitted or untracked content. NEVER auto-pruned: this is the
          BW-5055 class, and a human decides. Flagged when the content EQUALS AN
          OLDER REVISION of that file on main — the mechanical revert test.
          Note the intuitive signal does NOT work: a net-negative line count
          misses BW-5055's own example, because downgrading a versioned file
          (v2.15 -> v2.14) rewrites the same number of lines and nets to zero.
          Both are reported; neither subsumes the other (measured 2026-09-04:
          one worktree is -1,395 lines with no revert, another is +/-0 with three).
  HOLD    touched recently — an agent may be working in it right now.
  UNKNOWN HEAD is on no remote. Usually squash-merge residue (a squash makes a
          new commit, so branch commits are never reachable from main even
          though the work shipped) — but not always, so it is never auto-pruned.
          A ticket-id match against main's subjects is reported as a hint only.

Usage:
    classify_worktrees.py                # human-readable report
    classify_worktrees.py --print-safe   # SAFE paths, one per line (for xargs)
    classify_worktrees.py --json         # full classification as JSON
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

# Recent activity means an agent may be live in there. Generous on purpose: the
# cost of waiting is a directory surviving one more cycle; the cost of being
# wrong is deleting a running agent's tree.
ACTIVE_WINDOW_SECONDS = 24 * 3600

TICKET_RE = re.compile(r"\b([A-Z]{2,4}-\d{3,5})\b", re.IGNORECASE)


def git(*args, cwd=None):
    """Run git read-only.

    `--no-optional-locks` is load-bearing, not hygiene. `git status` REFRESHES
    AND REWRITES the index, so a plain status call bumps the worktree's index
    mtime — which is the very signal this script uses to decide "is an agent
    working in here?". Measured 2026-09-04: a worktree read as SAFE on one run
    and HOLD on the next, because the first run's own probe had marked it
    active. An instrument that changes what it measures reads its own footprint.
    """
    return subprocess.run(
        ["git", "--no-optional-locks", *(["-C", cwd] if cwd else []), *args],
        capture_output=True, text=True).stdout


def main_dir():
    """git worktree list always names the main working tree first.

    Captured whole before slicing: piping to `head -1` closes the pipe after one
    line and, with hundreds of worktrees, kills the writer with SIGPIPE.
    """
    first = git("worktree", "list", "--porcelain").split("\n", 1)[0]
    return first[len("worktree "):] if first.startswith("worktree ") else os.getcwd()


def worktrees(root):
    out, cur = [], {}
    for line in git("worktree", "list", "--porcelain", cwd=root).splitlines():
        if line.startswith("worktree "):
            if cur:
                out.append(cur)
            cur = {"path": line[9:], "head": None, "branch": None}
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "")
    if cur:
        out.append(cur)
    return out


def reverted_files(path, tracked, root, depth=300):
    """Files whose worktree content equals an OLDER revision of that file on main.

    The mechanical residue test. For each modified file, hash what the worktree
    holds and compare it against every historical blob of that path on
    origin/main. A match that is NOT main's current blob means the worktree is
    holding content main has already moved past — a revert, not new work.

    Deliberately narrow: it answers "is this content old?", never "is this
    content good?". A file legitimately being restored to an earlier state would
    also match, which is why this classifies for REVIEW and never auto-prunes.
    """
    out = []
    for entry in tracked:
        rel = entry[3:].strip()
        if "->" in rel:                       # a rename: "old -> new"
            rel = rel.split("->")[-1].strip()
        rel = rel.strip('"')
        full = os.path.join(path, rel)
        if not os.path.isfile(full):
            continue
        blob = git("hash-object", full, cwd=path).strip()
        if not blob:
            continue
        history = git("log", f"-{depth}", "--format=%H", "origin/main", "--",
                      rel, cwd=root).split()
        if not history:
            continue
        current = git("rev-parse", f"{history[0]}:{rel}", cwd=root).strip()
        if blob == current:
            continue                          # matches main's tip: not a revert
        for commit in history[1:]:
            if git("rev-parse", f"{commit}:{rel}", cwd=root).strip() == blob:
                out.append(rel)
                break
    return out


def classify(root):
    pushed = set(git("rev-list", "--remotes", cwd=root).split())
    # Ticket ids already represented on main, for the squash hint. A squash
    # merge keeps the ticket id in its subject even though the commits differ.
    shipped = set()
    for subject in git("log", "origin/main", "--format=%s", cwd=root).splitlines():
        shipped.update(m.upper() for m in TICKET_RE.findall(subject))

    now = time.time()
    rows = []
    for wt in worktrees(root):
        path = wt["path"]
        if path == root:
            continue
        if not os.path.isdir(path):
            rows.append({**wt, "verdict": "SAFE", "why": "directory already gone",
                         "net_lines": 0})
            continue

        gd = git("rev-parse", "--git-dir", cwd=path).strip()
        index = os.path.join(gd, "index") if gd else ""
        idle = now - os.path.getmtime(index) if os.path.exists(index) else 1e9

        status = git("status", "--porcelain", cwd=path).splitlines()
        tracked = [l for l in status if not l.startswith("??")]
        untracked = [l for l in status if l.startswith("??")]

        # Net line delta, measured against HEAD so STAGED changes count. Plain
        # `git diff` sees only unstaged content, and BW-5055's revert case is
        # staged — measured 2026-09-04, it read +0 lines through that blind spot.
        net = 0
        if tracked:
            for line in git("diff", "--numstat", "HEAD", cwd=path).splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    net += int(parts[0]) - int(parts[1])

        # The real revert signature. Net line count does NOT find it: downgrading
        # a versioned file (v2.15 -> v2.14) rewrites the same number of lines, so
        # BW-5055's own example nets to zero. What identifies it is that the
        # worktree's content for a file EQUALS AN OLDER REVISION OF THAT FILE ON
        # MAIN — content that main has already moved past. That is mechanically
        # checkable by blob hash, and it is what "residue, not work" means.
        reverts = reverted_files(path, tracked, root) if tracked else []

        ident = wt["branch"] or git("log", "-1", "--format=%s", cwd=path).strip()
        tickets = {m.upper() for m in TICKET_RE.findall(ident or "")}
        squash_hint = bool(tickets & shipped)

        if idle < ACTIVE_WINDOW_SECONDS:
            verdict, why = "HOLD", f"active {idle / 3600:.1f}h ago"
        elif tracked or untracked:
            verdict = "REVIEW"
            bits = []
            if tracked:
                bits.append(f"{len(tracked)} tracked ({net:+d} lines)")
            if untracked:
                bits.append(f"{len(untracked)} untracked")
            why = ", ".join(bits)
            if reverts:
                names = ", ".join(os.path.basename(f) for f in reverts[:3])
                more = f" +{len(reverts) - 3}" if len(reverts) > 3 else ""
                why += f" — REVERTS to an older revision on main: {names}{more}"
            elif net < 0:
                why += " — net-negative, inspect before harvesting"
        elif wt["head"] and wt["head"] not in pushed:
            verdict = "UNKNOWN"
            why = ("HEAD on no remote; ticket already on main — likely squash residue"
                   if squash_hint else "HEAD on no remote and no ticket match on main")
        else:
            verdict, why = "SAFE", "pushed, clean, idle"

        rows.append({**wt, "verdict": verdict, "why": why, "net_lines": net,
                     "squash_hint": squash_hint, "reverts": reverts if tracked else []})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print-safe", action="store_true",
                    help="print SAFE paths only, one per line")
    ap.add_argument("--json", action="store_true", help="full JSON output")
    args = ap.parse_args()

    root = main_dir()
    rows = classify(root)

    if args.print_safe:
        for r in rows:
            if r["verdict"] == "SAFE":
                print(r["path"])
        return 0
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0

    order = ["SAFE", "REVIEW", "UNKNOWN", "HOLD"]
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in order}
    print(f"{len(rows)} worktrees under {root}\n")
    for v in order:
        print(f"  {v:8s} {counts[v]:4d}")
    print("\nOnly SAFE is ever auto-pruned. REVIEW is the BW-5055 class — a human")
    print("decides. A REVERTS flag means the content equals an OLDER revision on")
    print("main; harvesting it would un-ship whatever main has since moved to.\n")
    for v in ("REVIEW", "UNKNOWN"):
        shown = [r for r in rows if r["verdict"] == v]
        if not shown:
            continue
        print(f"--- {v} ({len(shown)}) " + "-" * 40)
        for r in shown[:12]:
            print(f"  {os.path.basename(r['path']):38s} {r['why']}")
        if len(shown) > 12:
            print(f"  … and {len(shown) - 12} more (--json for all)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
