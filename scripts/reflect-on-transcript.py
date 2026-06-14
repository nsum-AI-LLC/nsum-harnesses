#!/usr/bin/env python3
"""Reflect on a Claude Code session transcript and propose harness improvements.

Reads a JSONL transcript, walks the conversation for signals that the session
encountered a teachable moment (user corrections, hook bypasses, repeated
mistakes), and writes structured proposals to
~/.claude/{project_name}-proposals/ for the user to review. The project name
is derived from the basename of $CLAUDE_PROJECT_DIR (or --project-dir arg).

Conservative by design: missing a lesson is cheaper than crying wolf.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def proposals_dir(project_dir: str | None = None) -> Path:
    """Return the per-project proposals directory.

    Project name = basename of $CLAUDE_PROJECT_DIR (or arg). Falls back to
    'unknown-project' if neither is set.
    """
    pd = project_dir or os.environ.get("CLAUDE_PROJECT_DIR", "")
    name = os.path.basename(pd.rstrip("/")) if pd else "unknown-project"
    return Path.home() / ".claude" / f"{name}-proposals"

# Correction signals — phrases that indicate the user is correcting the assistant.
# These are intentionally specific; "no" and "wrong" alone are too broad.
CORRECTION_PATTERNS = [
    r"\byou (?:didn'?t|did not)\b",
    r"\byou (?:keep|continue to|still)\b.+\b(?:without|instead of|ignoring)\b",
    r"\bwhy don'?t you\b",
    r"\bshould have\b",
    r"\bwrong to\b",
    r"\binstead of\b",
    r"\bactually,?\s+(?:no|that's|you|the)\b",
    r"\byou (?:disregarded|ignored|bypassed|skipped)\b",
    r"\bnext time,?\b",
    r"\bin the future,?\b",
    r"\bthat's not\b.+\b(?:what|how|right|correct)\b",
]

# Signals that the user is asking for a process or harness change
HARNESS_PATTERNS = [
    r"\b(?:strengthen|fix|improve)\s+(?:the\s+)?(?:harness|hook|process)\b",
    r"\b(?:add|create|build)\s+(?:a\s+)?(?:hook|skill|gate|enforcement)\b",
    r"\bgoing forward\b",
    r"\bfrom now on\b",
]

# Signals that the assistant bypassed a hook/reminder
BYPASS_PATTERNS = [
    r"\bsystem-reminder\b",
    r"\bUserPromptSubmit hook\b",
    r"\bbefore proceeding,? read\b",
    r"\binvoke the .+ skill\b",
]


def load_transcript(path: Path) -> list[dict]:
    """Load a JSONL transcript into a list of turn dicts."""
    turns = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return turns


def turn_text(turn: dict) -> str:
    """Extract the textual content from a transcript turn, regardless of shape."""
    # Try common Claude Code transcript field shapes
    msg = turn.get("message", {})
    if isinstance(msg, dict):
        content = msg.get("content", "")
    else:
        content = turn.get("content", "")

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "text" in block:
                    parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    if isinstance(content, str):
        return content
    return ""


def turn_role(turn: dict) -> str:
    """Best-effort role extraction (user, assistant, system, tool)."""
    msg = turn.get("message", {})
    if isinstance(msg, dict) and "role" in msg:
        return msg["role"]
    return turn.get("type") or turn.get("role") or "unknown"


def find_matches(text: str, patterns: list[str]) -> list[str]:
    """Return the patterns that matched (case-insensitive)."""
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def detect_signals(turns: list[dict]) -> list[dict]:
    """Walk turns and emit signal records for teachable moments."""
    signals = []
    for i, turn in enumerate(turns):
        role = turn_role(turn)
        if role != "user":
            continue

        text = turn_text(turn)
        if not text or len(text) < 20:
            continue

        correction_hits = find_matches(text, CORRECTION_PATTERNS)
        harness_hits = find_matches(text, HARNESS_PATTERNS)

        if not correction_hits and not harness_hits:
            continue

        # Capture the preceding assistant turn for context
        preceding = ""
        for j in range(i - 1, max(-1, i - 4), -1):
            if turn_role(turns[j]) == "assistant":
                preceding = turn_text(turns[j])
                break

        bypass_hits = find_matches(preceding, BYPASS_PATTERNS) if preceding else []

        signals.append({
            "turn_index": i,
            "user_text": text[:1500],
            "preceding_assistant_text": preceding[:1500] if preceding else "",
            "correction_patterns": correction_hits,
            "harness_patterns": harness_hits,
            "bypass_patterns": bypass_hits,
        })
    return signals


def dedupe_signals(signals: list[dict]) -> list[dict]:
    """If the user repeats a correction, keep only the last (most recent) instance."""
    if not signals:
        return []
    # For v1, return all signals; future: cluster similar corrections.
    return signals


def write_proposal(
    signals: list[dict],
    session_id: str,
    transcript_path: Path,
    project_dir: str | None = None,
) -> Path | None:
    """Write a single proposal file summarizing all signals from this session."""
    if not signals:
        return None

    out_dir = proposals_dir(project_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # One proposal file per session. The Stop hook fires after every model
    # turn; using a deterministic filename means each firing overwrites with
    # the latest analysis instead of accumulating duplicates. File mtime
    # gives chronological ordering across sessions.
    proposal_path = out_dir / f"{session_id}.md"

    lines = []
    lines.append(f"# Harness Improvement Proposal")
    lines.append("")
    lines.append(f"**Session:** `{session_id}`  ")
    lines.append(f"**Date:** {datetime.now().isoformat(timespec='seconds')}  ")
    lines.append(f"**Transcript:** `{transcript_path}`  ")
    lines.append(f"**Signal count:** {len(signals)}")
    lines.append("")
    lines.append("This proposal was generated by the Self-Improving Hook ("
                 "`.claude/hooks/self-improve.sh`). It identifies moments where the user "
                 "corrected the assistant or asked for harness changes. Review each "
                 "signal and decide whether it warrants a CLAUDE.md update, a new hook, "
                 "or no action.")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, sig in enumerate(signals, 1):
        lines.append(f"## Signal {idx} (turn {sig['turn_index']})")
        lines.append("")
        if sig["correction_patterns"]:
            lines.append(f"**Correction patterns matched:** {', '.join('`'+p+'`' for p in sig['correction_patterns'])}")
        if sig["harness_patterns"]:
            lines.append(f"**Harness-change patterns matched:** {', '.join('`'+p+'`' for p in sig['harness_patterns'])}")
        if sig["bypass_patterns"]:
            lines.append(f"**Bypass patterns in preceding assistant turn:** {', '.join('`'+p+'`' for p in sig['bypass_patterns'])}")
        lines.append("")
        if sig["preceding_assistant_text"]:
            lines.append("**Preceding assistant turn (excerpt):**")
            lines.append("")
            lines.append("> " + sig["preceding_assistant_text"].replace("\n", "\n> "))
            lines.append("")
        lines.append("**User correction:**")
        lines.append("")
        lines.append("> " + sig["user_text"].replace("\n", "\n> "))
        lines.append("")
        lines.append("**Suggested action:** review whether this pattern should become "
                     "a rule in `CLAUDE.md` (root or a sub-area), a new hook, or a "
                     "skill description update. If no action is warranted, delete this "
                     "proposal.")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## To dismiss this proposal")
    lines.append("")
    lines.append("```bash")
    lines.append(f"rm '{proposal_path}'")
    lines.append("```")
    lines.append("")
    lines.append("## To review all pending proposals")
    lines.append("")
    lines.append("```bash")
    lines.append(f"ls -la '{out_dir}/'")
    lines.append("```")
    lines.append("")

    proposal_path.write_text("\n".join(lines), encoding="utf-8")
    return proposal_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True, help="Path to JSONL transcript")
    parser.add_argument("--session-id", default="unknown", help="Claude Code session ID")
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR", ""),
        help="Project root (defaults to $CLAUDE_PROJECT_DIR); used to derive proposals dir name",
    )
    args = parser.parse_args()

    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        print(f"reflect: transcript not found: {transcript_path}", file=sys.stderr)
        return 0

    turns = load_transcript(transcript_path)
    if not turns:
        return 0

    signals = dedupe_signals(detect_signals(turns))
    if not signals:
        return 0

    proposal_path = write_proposal(
        signals, args.session_id, transcript_path, args.project_dir or None
    )
    if proposal_path:
        print(f"reflect: wrote {len(signals)} signal(s) to {proposal_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
