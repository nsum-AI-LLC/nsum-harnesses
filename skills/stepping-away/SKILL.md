---
name: stepping-away
description: "Hand the session an autonomous operating mandate — complete the current plan without the user's input, reasoning from the project's documented principles, logging decisions in a reviewable artifact, and blocking only on high-blast-radius (hard-to-reverse, outward-facing, production-affecting, destructive) decisions. Use when the user says they're stepping away, going offline, or wants the work driven to completion autonomously."
---

# Stepping Away — autonomous operating mandate

The user is stepping away. **Aim to complete the current plan autonomously, without their input.** Do not
pause to ask questions you can answer yourself by reasoning from the project's documented principles. Keep
working the plan to completion; the user reviews your decisions and final status when they return.

If the user named a scope or return window ("finish the migration, back in ~3h"), treat it as the bound on
this mandate.

## How to reason when you hit a question

At a decision point, before treating it as a blocker:

1. **Read the project's own context first** — the relevant `CLAUDE.md`(s), the foundational specs, the
   product strategy. The answer to most questions is already written down.
2. **Decide on the merits** — correctness, architectural fit, long-term quality. Never let effort,
   timeline, or sunk cost gate which option is right; choose as if you had unlimited time and resources.
   (If you catch cost-gating creeping in, run `architect-reminder`.)
3. **Make the well-reasoned decision and proceed.** A defensible decision you can justify beats waiting.

## What to document

Keep a **decision-log artifact** as you go — a durable file the user can review alongside your final status
report. For each non-trivial decision, record: the question, the options weighed, the principle or spec
that settled it, and what you chose. This is what the user reads on return instead of having been in the
loop.

## When you *may* block on the user's return

Stop and wait only at a genuinely high-stakes decision with a large blast radius — something hard to
reverse, outward-facing, production-affecting, or destructive (irreversible data changes, anything that
ships to or mutates production, security- or money-affecting actions). At those points: stop cleanly, leave
the system in a safe paused state, record the decision and your recommended path in the decision log, and
surface it.

When you surface it, write the briefing with the `summarize-issue` skill — a self-contained door-knock the
user can act on in two minutes, not a decision buried inside a long status update. Prepare everything *up
to* the gate so that the moment the user says "go," execution is one step.

For everything else — analysis, design, reviewed-and-tested changes, validation, local and staging work —
proceed on your own judgment.

## You are part of the control loop

Operating autonomously does not mean lowering the bar. You still run the full
[checks-and-balances loop](../../docs/checks-and-balances.md): groom against acceptance criteria, verify
current behavior before relying on it, review every change, and disposition every finding. You are
empowered to hit the brakes and rewind the moment you notice the work veering from process — that
self-correction is the point of operating autonomously, not a reason to push past it.

Now continue executing the current plan.
