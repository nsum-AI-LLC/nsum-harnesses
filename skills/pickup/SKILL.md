---
name: pickup
description: Resume from a prior session's hand-off. Invoked as `/pickup <session-id>`: read that session's handoff, read everything it names, and work autonomously toward its Definition of Done. Use when the user types `/pickup <session-id>`, "pick up from session <id>", or "resume the handoff from <id>".
---

# Pick up

You are resuming work, not starting it. A predecessor spent a full context window reaching the
state you inherit, and most of what it learned is not recoverable by reasoning about the code.

## Read the hand-off, then read everything it names

Read `<handoff-dir>/handoff-<the-id-you-were-given>.md`.

**NON-NEGOTIABLE — open every entry in its "Key Files and Artifacts" before starting work.**
Not skim, not grep: open them. That list is the predecessor's answer to *what would I have to
re-derive if I lost my context*, and it is the one thing a cold start cannot reconstruct.

A session that begins from the Definition of Done alone re-derives the design from the code,
reaches a plausible account of it, and builds on that account. The account is usually
defensible and occasionally wrong, and the wrongness surfaces after the work is built on it.
That is the failure this list exists to prevent.

If an entry is missing, unreadable, or contradicts the summary, say so before working rather
than proceeding on the half you can see.

## The DoD is your success criterion, and it is not a stop signal

Name the DoD and the outcome it serves in your opening note, so the objective is stated rather
than assumed.

**Completing it does not end the session.** If context remains, continue with the next work the
plan calls for. A cold restart rebuilds the warm context you are holding — live traces, design
rationale, coordination state — so continuing is the higher-quality path, and the instinct to
hand off at a milestone to "preserve quality" runs backwards.

## What you inherit is a claim, not a fact

A hand-off is one session's account of the state. Treat its measurements as measured and its
mechanisms as claimed:

- **A number with a command behind it is evidence.** A number without one is a memory, and it
  ages. Re-run what is cheap to re-run.
- **A stated cause is the predecessor's inference** unless it cites a verified trace. The
  symptom is usually measured and the mechanism usually inferred, and the fix gets built on
  the mechanism.
- **A dated claim describes when it was written.** A snapshot embedded in a rule reads as a
  durable property, and the next session propagates it as fact.

Say plainly when you find the hand-off wrong. Correcting the record is part of the work.

## If the DoD is mis-scoped, re-scope it before starting

An inherited DoD is a proposal. Re-scope it — and say you did — when it describes labour rather
than a capability, when it can be satisfied without fixing anything (drained, deferred,
suppressed, the population shrunk), or when meeting it in full would leave the problem it
serves untouched.

Defending an inherited conclusion is the most common way a resumed session wastes its window.

## Ending

Follow the project's hand-off procedure when your own context runs low, writing **your own**
file — never the one you picked up from, and never a shared pointer.
