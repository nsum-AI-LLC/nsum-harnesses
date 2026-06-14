#!/usr/bin/env python3
"""Generate a session-start briefing summarizing current project state.

The briefing is printed to stdout and (when called from a SessionStart hook)
becomes context the model sees at session start. Target: ≤2K tokens.

Sections:
1. Active sprint (number, theme, ticket counts)
2. In-flight work (open PRs, recent commits, recent status updates)
3. Suggested next action (heuristic)
4. Available specs (paths + one-line description; generated index if present)

Convention assumptions:
  CLAUDE_PROJECT_DIR    — project root (falls back to CWD)

This briefing assumes a planning/ layout: planning/sprints/<N>/,
planning/roadmap/in-progress/, planning/specs/. Sections whose paths don't
exist are simply omitted (fail-soft), so it degrades gracefully in projects
with a different layout — adapt the section functions to match yours.

The script is fail-soft: any section that can't be computed is skipped.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

MAX_PRS = 8
MAX_COMMITS = 6
MAX_STATUS_UPDATES = 5
MAX_SPECS_LINES = 30
RECENT_DAYS = 7


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))


def relative_under_project(p: Path) -> str:
    try:
        return str(p.relative_to(project_dir()))
    except ValueError:
        return str(p)


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 5) -> str:
    """Run a shell command and return stdout (empty on failure)."""
    try:
        res = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return res.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


# ---- Section: Active sprint -------------------------------------------------

def current_sprint_number() -> int | None:
    """Parse the in-progress README to find the active sprint number."""
    in_progress = project_dir() / "planning" / "roadmap" / "in-progress" / "README.md"
    if not in_progress.exists():
        return None
    try:
        text = in_progress.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"Sprint\s+(\d+)", text)
    return int(m.group(1)) if m else None


def parse_sprint_plan(sprint_num: int) -> dict:
    """Extract theme, status, and ticket counts from a sprint plan."""
    plan_path = (
        project_dir() / "planning" / "sprints" / str(sprint_num) / "sprint-plan.md"
    )
    info = {"path": plan_path, "exists": plan_path.exists()}
    if not info["exists"]:
        return info
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return info

    theme_match = re.search(r"\*\*Theme:\*\*\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    started_match = re.search(r"\*\*Started:\*\*\s*([0-9-]+)", text)
    status_summary = re.search(
        r"\*\*Total:\*\*\s*(.+?)(?:\n|$)",
        text,
    )

    # Count statuses across sprint plan ticket tables.
    statuses = {"Done": 0, "Abandoned": 0, "Pending": 0, "In Progress": 0, "Blocked": 0}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        for label in statuses:
            if any(label in c for c in cells):
                statuses[label] += 1
                break

    info.update({
        "theme": (theme_match.group(1).strip() if theme_match else None),
        "started": (started_match.group(1) if started_match else None),
        "total_line": (status_summary.group(1).strip() if status_summary else None),
        "statuses": statuses,
    })
    return info


def section_sprint() -> str:
    n = current_sprint_number()
    if n is None:
        return ""
    info = parse_sprint_plan(n)
    if not info.get("exists"):
        return f"## Active sprint\n\nSprint {n} (no sprint-plan.md found)\n"
    parts = [f"## Active sprint", ""]
    parts.append(f"**Sprint {n}** (started {info.get('started', 'unknown')})")
    if info.get("theme"):
        theme = info["theme"]
        if len(theme) > 240:
            theme = theme[:237] + "..."
        parts.append(f"Theme: {theme}")
    if info.get("total_line"):
        parts.append(f"Totals: {info['total_line']}")
    else:
        st = info.get("statuses", {})
        nonzero = {k: v for k, v in st.items() if v}
        if nonzero:
            parts.append("Status counts: " + " · ".join(f"{v} {k}" for k, v in nonzero.items()))
    parts.append(f"Plan: `{relative_under_project(info['path'])}`")
    parts.append("")
    return "\n".join(parts)


# ---- Section: In-flight work -----------------------------------------------

def section_inflight() -> str:
    pd = project_dir()
    parts = ["## In-flight", ""]

    # Open PRs
    if shutil.which("gh"):
        out = run(["gh", "pr", "list", "--state", "open", "--limit", str(MAX_PRS),
                   "--json", "number,title,headRefName"], cwd=pd, timeout=8)
        if out.strip():
            import json
            try:
                prs = json.loads(out)
                if prs:
                    parts.append(f"**Open PRs ({len(prs)}):**")
                    for pr in prs[:MAX_PRS]:
                        parts.append(
                            f"- #{pr.get('number')} `{pr.get('headRefName', '')}` — {pr.get('title', '')}"
                        )
                else:
                    parts.append("**Open PRs:** none")
            except json.JSONDecodeError:
                pass

    # Recent commits
    out = run(["git", "log", f"--since={RECENT_DAYS} days ago",
               f"--max-count={MAX_COMMITS}", "--oneline"], cwd=pd)
    commits = [l for l in out.strip().splitlines() if l]
    if commits:
        parts.append("")
        parts.append(f"**Recent commits (last {RECENT_DAYS}d):**")
        for c in commits:
            parts.append(f"- {c}")

    # Recent status updates
    sprint_num = current_sprint_number()
    if sprint_num is not None:
        su_dir = pd / "planning" / "sprints" / str(sprint_num) / "status_updates"
        if su_dir.is_dir():
            cutoff = datetime.now() - timedelta(days=RECENT_DAYS)
            recent = []
            for f in su_dir.iterdir():
                if not f.is_file() or not f.name.endswith(".md"):
                    continue
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime >= cutoff:
                        recent.append((mtime, f))
                except OSError:
                    continue
            recent.sort(reverse=True)
            if recent:
                parts.append("")
                parts.append(f"**Status updates (last {RECENT_DAYS}d):**")
                for _, f in recent[:MAX_STATUS_UPDATES]:
                    parts.append(f"- `{relative_under_project(f)}`")
    parts.append("")
    return "\n".join(parts)


# ---- Section: Suggested next action ----------------------------------------

def section_suggested() -> str:
    pd = project_dir()
    parts = ["## Suggested next action", ""]

    # Uncommitted changes?
    status = run(["git", "status", "--porcelain"], cwd=pd)
    if status.strip():
        n_changed = len(status.strip().splitlines())
        branch = run(["git", "branch", "--show-current"], cwd=pd).strip()
        parts.append(
            f"You have {n_changed} uncommitted change(s) on `{branch}`. "
            "Consider whether they should be committed, stashed, or discarded "
            "before starting new work."
        )
        parts.append("")
        return "\n".join(parts)

    # Open PRs?
    if shutil.which("gh"):
        out = run(["gh", "pr", "list", "--state", "open", "--limit", "1",
                   "--json", "number"], cwd=pd, timeout=5)
        if out.strip() and out.strip() != "[]":
            parts.append(
                "Open PRs exist (see In-flight above). Review/merge or check on "
                "their status before starting new work."
            )
            parts.append("")
            return "\n".join(parts)

    # Sprint state
    n = current_sprint_number()
    if n is not None:
        info = parse_sprint_plan(n)
        statuses = info.get("statuses", {})
        pending = statuses.get("Pending", 0) + statuses.get("In Progress", 0)
        if pending > 0:
            parts.append(
                f"Sprint {n} has {pending} open ticket(s). Dispatch the next "
                "batch, or audit progress before starting new work."
            )
        else:
            parts.append(
                f"Sprint {n} appears complete (no open tickets). Verify closure "
                "readiness and write the retrospective."
            )
        parts.append("")
        return "\n".join(parts)

    parts.append("No active sprint detected. Consider opening one or working ad-hoc.")
    parts.append("")
    return "\n".join(parts)


# ---- Section: Available specs ----------------------------------------------

def section_specs() -> str:
    pd = project_dir()
    index = pd / "planning" / "specs" / "_index.md"
    if index.exists():
        try:
            text = index.read_text(encoding="utf-8")
            # Truncate if huge
            lines = text.splitlines()
            if len(lines) > MAX_SPECS_LINES:
                lines = lines[:MAX_SPECS_LINES] + [
                    "", f"_(truncated; see `planning/specs/_index.md` for full index)_"
                ]
            return "## Available specs\n\n" + "\n".join(lines) + "\n"
        except OSError:
            pass

    # Fallback: list foundational specs only (most likely to be relevant)
    foundational = pd / "planning" / "specs" / "foundational"
    if not foundational.is_dir():
        return ""
    parts = ["## Available specs (foundational)", ""]
    for f in sorted(foundational.iterdir()):
        if f.suffix != ".md":
            continue
        parts.append(f"- `{relative_under_project(f)}`")
    parts.append("")
    parts.append(
        "_No spec index found; listing foundational specs directly. A generated "
        "index at planning/specs/_index.md, if present, is used instead._"
    )
    parts.append("")
    return "\n".join(parts)


# ---- Main -------------------------------------------------------------------

def main() -> int:
    sections = []
    header = (
        "# Session Briefing\n\n"
        f"_Generated {datetime.now().isoformat(timespec='seconds')} by "
        "`session-start.sh`. Read the local `CLAUDE.md` for the area you're "
        "editing — it has area-specific gotchas._\n"
    )
    sections.append(header)
    sections.append(section_sprint())
    sections.append(section_inflight())
    # Harness-improvement proposals are intentionally NOT surfaced at session
    # start. Collection is automatic (the self-improving Stop hook); review is a
    # pull — run the `review-suggestions` skill on your own schedule. See
    # docs/suggestion-collector.md.
    sections.append(section_suggested())
    sections.append(section_specs())
    print("\n".join(s for s in sections if s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
