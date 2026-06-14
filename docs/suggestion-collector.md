# The Suggestion Collector — the harness that improves the harness

> Also called the **Self-Improving Hook**, after the files that implement it
> (`hooks/self-improve.sh` → `scripts/reflect-on-transcript.py`). It's the loop that closes the
> **amnesia** gap: a correction you make in one session becomes a proposal the *next* session sees.

Every other role in this repo checks the *work*. This one checks the *harness itself*. There's no
guarantee your CLAUDE.md rules, hooks, and skills stay correct as your project evolves — so this collects
the evidence that they've drifted and surfaces it for you to act on.

## The loop

```
1. Stop hook fires (after every model turn)
        │   hooks/self-improve.sh
        ▼
2. Reflector scans the session transcript for "teachable moments"
        │   scripts/reflect-on-transcript.py   (conservative; no model in the loop)
        ▼
3. Writes ONE proposal per session  →  ~/.claude/{project}-proposals/{session_id}.md
        │   (deterministic filename, overwritten each firing → always the latest analysis)
        ▼
4. Next session start, ANY project: the briefing counts pending proposals across all projects
        │   hooks/session-start.sh → scripts/session_briefing.py
        ▼
5. You review, decide, act, and clear
            claude_proposals [list | view <prefix> | clear [prefix]]
```

The cadence is automatic: you never have to remember to run anything. The briefing's pending-proposals
count *is* the reminder, and it spans every project — a correction logged in project A shows up in the
next session of project B, which matters when the fix belongs in shared tooling.

## What it detects

The reflector walks the transcript and flags **user turns** that look like a correction or a request for a
process change, optionally paired with evidence that the assistant had just bypassed a reminder. Three
signal classes (the exact regex lists live at the top of `reflect-on-transcript.py`):

- **Corrections** — "you didn't…", "you keep… without/instead of…", "should have…", "next time…", "that's
  not what/how…". Deliberately specific: bare "no" and "wrong" are too broad to be useful.
- **Harness-change requests** — "strengthen/fix the harness/hook/process", "add a hook/skill/gate", "from
  now on", "going forward".
- **Bypass evidence** — when the *preceding assistant turn* contains "system-reminder", "UserPromptSubmit
  hook", "before proceeding, read", or "invoke the … skill", it's captured as context: a sign the model
  talked past an advisory reminder right before the user corrected it.

**Conservative by design.** Missing a lesson is cheaper than crying wolf — false positives erode trust in
the proposals, and untrusted proposals get ignored. The detector errs toward silence. It uses no model
(keeping the Stop hook fast and free); it's plain pattern-matching.

## The proposal file

One Markdown file per session at `~/.claude/{project}-proposals/{session_id}.md` (project name = basename
of `$CLAUDE_PROJECT_DIR`). Because the Stop hook fires after *every* model turn, the filename is
deterministic and each firing **overwrites** it — so you get one current proposal per session, not a pile
of near-duplicates. Each proposal lists, per signal: which patterns matched, an excerpt of the preceding
assistant turn, the user's correction verbatim, and a **suggested action** — review whether this should
become a CLAUDE.md rule, a new hook, or no action.

## Reviewing and acting

```bash
claude_proposals                 # list pending proposals for the current project
claude_proposals view <prefix>   # print one (substring match on the session-id filename)
claude_proposals clear           # delete all pending proposals for this project
claude_proposals clear <prefix>  # delete a specific one
```

For each signal, decide where the fix belongs:

- **A recurring behavior the rules should prevent** → add a rule to `CLAUDE.md` (root, or the sub-area
  closest to the code it governs — see the Context Cascade in [`harness_design.md`](harness_design.md)).
- **Something advice can't reliably enforce** → write a hook that *blocks* it. This is the key judgment
  call: if the model bypassed an advisory reminder, the lesson is usually "make it mechanical," not "say it
  louder." (That insight is the origin of this entire harness.)
- **A one-off, or a false positive** → clear it. Pruning aggressively is correct; it keeps the signal
  high.

**It never auto-applies a change.** The hook proposes; a human disposes. Auto-editing your rules from
pattern matches would be exactly the kind of unchecked, completion-driven action the rest of the harness
exists to prevent.

## Customizing the detector

Everything tunable is at the top of `scripts/reflect-on-transcript.py`:

- **Add patterns** to `CORRECTION_PATTERNS`, `HARNESS_PATTERNS`, or `BYPASS_PATTERNS` to catch phrasings
  your corrections actually use. Keep them specific — every pattern you add trades some precision for
  recall, and this detector's value depends on precision.
- **`proposals_dir()`** controls where proposals are written; the per-project naming is what lets the
  briefing aggregate across projects, so keep that shape if you run more than one repo.
- **`dedupe_signals()`** is a stub today (returns all signals). If your sessions repeat the same correction
  many times, this is where to cluster them.

If you run the harness across several repos, point them all at one shared tooling source so a fix to the
detector propagates everywhere — otherwise each project's copy drifts on its own.

## Where it sits in the system

This is the one loop aimed at the harness itself rather than at the work it produces. See
[checks-and-balances.md](checks-and-balances.md) for how it fits with the rest.
