---
name: handoff
description: Prepare a clean session hand-off and end with a greppable <!-- SESSION_HANDOFF_PROMPT --> block. Use when the user types /handoff, or says to wind down / wrap up / close out for the next session. From this point spin up no new agents or workflows — let in-flight work finish, fold it into the project's durable docs, write YOUR OWN handoff file, then emit a runnable first prompt for the next session.
---

# Hand off

A session ends with its context exhausted, not its work finished. The hand-off is the artifact
that decides whether the next session continues the work or starts it again.

## The handshake: one file per session, written only by that session

Write `<handoff-dir>/handoff-<your-session-id>.md`. Yours alone.

**Never rewrite a shared hand-off file.** A single shared file gets rewritten by every session
in turn, and each rewrite compresses to what that author happens to hold — so anything the
current author does not personally know is deleted silently, and nothing reviews a diff of a
file whose convention is rewrite-in-place. Measured in one project: a shared file rewritten 59
times by 16 authors, with a load-bearing finding flickering in and out and absent for 23
consecutive rewrites, including the day the work resumed.

**Never write another session's file.** A concurrent session's output reaches you as its own
artifact, not as an edit to yours.

A fixed pointer file, if the project has one, is created once and never rewritten.

## Before writing: let in-flight work land

Spin up no new agents or workflows. Let running ones finish and fold their results into the
project's durable documents — the plan, the decision record, the ticket. **Chat context
evaporates; only committed files survive.** A result that exists solely in this conversation is
lost at the session boundary whatever the hand-off says about it.

## The file

```
<!-- SESSION_SUMMARY -->
**Title:** <the assignment in a few words> · this session: <what it moved>

**Summary:**
<Paragraph 1 — what the work is for and what finishing looks like, for a reader who has not
followed it. Outcomes a person can picture, not identifiers.>

<Paragraph 2 — where things stand against that picture: what landed, what remains. Plain
language, no commit shas or ticket ids; those belong in the lists below.>

**Key Files and Artifacts:**
- <path> — why it must be opened
<!-- Your successor is REQUIRED to read every entry before starting work. List what it must
     read and nothing else. Link a trace or a measurement rather than summarising it — the
     summary is the thing that gets re-derived. A long list is read the way a short one is
     skimmed, so the discipline is in the leaving-out. -->

**Key Decisions:**
- <the decision, and what settled it>
<!-- /SESSION_SUMMARY -->

## Definition of Done
<the concrete, checkable outcome list for the next session, and what is deliberately out>
```

## Writing the Definition of Done

**Size it to one session's proven throughput** — what this session actually achieved, not what
it hoped to. An oversized DoD produces a successor that hands off mid-task; an undersized one
produces an unnecessary relay. If the remaining work genuinely fits one session, say so
explicitly and say do not hand off part-way.

**A DoD is completion, not success.** It measures whether the list got done. Whether the work
solved the problem is a separate question, and a DoD met in full is not evidence of it. Where
the project states an objective, carry it into the DoD un-narrowed so the successor is checking
against the problem rather than against your list.

**A row count is rarely a DoD.** "Resolve N items", "get the queue under M", "clean up the
backlog" describe labour, not a capability. Re-scope to the thing that stops the items being
produced. An item already produced may still need handling — the point is what gets BUILT.

## Arming an automatic successor

If the project runs a relaunch supervisor (`relaunch/`), write its spec as the last step, after
in-flight work has finished — a spec armed early resumes from a stale snapshot.

**Arming is self-administered at the moment a session is least reliable**, and its failure is
silent: no spec, no successor, and an empty directory nobody checks. Treat it as owed the
moment you decide to hand off, not as a reminder to weigh.

## Finish by posting the prompt

End your reply — in the chat, not only in the file — with a greppable block so the next session
resumes in one command:

```
<!-- SESSION_HANDOFF_PROMPT -->
/pickup <your-session-id>
```

The file is the record; the posted block is what a person copies. Post both.
