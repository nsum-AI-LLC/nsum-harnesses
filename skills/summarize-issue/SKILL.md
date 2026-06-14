---
name: summarize-issue
description: >-
  Produce a concise, self-contained "door-knock" briefing whenever you need to raise an open question,
  escalate a decision, or ask the user to choose between options — especially while operating autonomously
  (under /orchestrate, /stepping-away, or any long-running solo task the user hasn't followed step by step).
  Invoke it the moment you catch yourself about to surface a decision, blocker, fork, or trade-off —
  especially when you're about to name it in shorthand you picked up mid-session, as if the user had been
  following along. It enforces a five-part format so a
  busy, context-switched reader can decide in under two minutes, and it first checks whether the decision is
  genuinely the user's to make. Use it even for a single question.
---

# Summarize an issue for the user — the door-knock

You're deep in the work with all the context; the user is not. After a long run you build up your own
shorthand — names for decisions, threads, and tickets that mean everything to you and nothing to someone
who wasn't there. Lean on it and the user gets a line like "just waiting on your go-ahead on the
loose-entity-strain question and I can wrap up," and thinks *what question are you even talking about?* A
one-sentence update trips this just as easily as a long one; the problem is the assumption that the user
has been following along. This skill forces a self-contained briefing — the decision named in plain terms,
with no reference the reader would have had to be present to follow — that a context-switched person can
act on in under two minutes.

Picture it literally — you're knocking on the door of a busy person who's been away. You have about ninety
seconds of their attention. Lead with the ask, give them just enough to judge it, and make saying "yes, do
A" easy.

## Before you knock: is this actually theirs to decide?

The briefing only earns the interruption if the decision genuinely needs the user. Most don't — when
you're autonomous, the strong default is to decide on merit and keep moving. Knock only when the decision
is one of:

- **Irreversible or outward-facing** — it ships to production, mutates real or shared data, sends or
  publishes something, or is otherwise hard to undo.
- **Dependent on direction you don't have** — the answer turns on product strategy or priorities the user
  hasn't set and you can't derive from the docs.
- **A change to something the user explicitly ratified** — you'd be narrowing, deferring, or altering a
  deliverable they signed off on.
- **A genuine deadlock** — an independent check (a reviewer, a panel) and your own analysis disagree on a
  blocking point, and merit doesn't settle it.

If instead the choice is merit-decidable from the documented principles, reversible, and low-blast-radius,
decide it, record your reasoning, and proceed. Surfacing a fork you could have resolved yourself spends the
user's attention on something you were equipped to handle. Gut check: *would I still need them if I had
unlimited time to think it through?* If no, don't knock.

## The briefing: five parts, in this order

1. **The ask + a time estimate, up front.** One line naming the decision and roughly how long it takes to
   weigh ("~2 min"). Putting it first lets the reader triage — engage now or come back later — instead of
   hunting for the point.
2. **The issue, assuming zero prior reading.** Explain the situation in plain language as if they've seen
   none of the session: no "as noted above," no unexplained codenames, no shorthand you coined mid-session,
   no bare ticket IDs. If they have to scroll back to follow it, the briefing failed. Include only the facts that bear on the decision, and
   flag any fact that *reframes* it.
3. **Why you can't decide it yourself.** What makes the knock legitimate. Name which gate applies
   (irreversible / direction-you-lack / changes-what-they-ratified / deadlock). If you can't state this
   crisply, reconsider whether you should be knocking at all.
4. **The options you weighed — including the ones you rejected.** A short list, recommendation first and
   labeled as such. Include ruled-out options with the one-line reason they're out, so the reader sees the
   space was explored and doesn't re-suggest a dead end.
5. **Objectives and constraints you're working within.** The frame you optimized against — the goal, the
   hard limits, what's reversible, what's gated. This lets the reader correct your *premise* if it's wrong,
   often the most valuable thing they can add.

Close with the specific input you need and, where possible, a safe default: *"Approve A, or tell me B.
Absent a reply I'll <safe holding action>, since <nothing is at risk / it's gated downstream>."* A stated
default turns a blocking question into a non-blocking one — the user engages on their own timeline without
the work stalling.

## Match depth to stakes

The five parts are a checklist of what to *consider*, not a fixed length. A small clarification might be
three sentences. A consequential, irreversible fork deserves the full treatment. Keep the order; scale the
prose to the stakes.

## Writing style

- **Plain, specific, scannable.** Short paragraphs or bullets. Bold the ask and the options. A reader
  skimming only the bold text should still get the gist.
- **Honest about uncertainty and about your own reasoning** — including where your first instinct was wrong
  or a check corrected you. The user is calibrating how much to trust your autonomy.
- **Recommend.** "Here are five options, you pick" is abdication. Take a position and defend it. Being
  overruled is cheap; making the user redo the analysis you already did is expensive.

## Template

> **[Decision needed]: \<one-line ask>. ~\<N> min.**
>
> **The issue.** \<Plain-language, self-contained situation — assume no prior reading. The facts that bear
> on the call, plus any that reframe it.>
>
> **Why this is your call.** \<Which gate applies, in a sentence or two.>
>
> **Options I weighed:**
> 1. **(Recommended) \<option>** — \<what it does; why it wins.>
> 2. **\<alternative>** — \<what it does; the trade-off.>
> 3. ~~\<rejected option>~~ — \<one-line reason it's out.>
>
> **Objectives & constraints.** \<The goal; the hard limits; what's reversible; what's gated.>
>
> **What I need:** \<the specific input> — or, absent a reply, \<safe default> (\<why that's safe>).

## Why this matters

Autonomy helps the user only when it reduces their cognitive load. Every interruption is a withdrawal from
their attention; this format makes each one worth it, and the "should I even knock?" gate keeps the
withdrawals rare. When you knock, it's real, it's framed, and it's a ninety-second decision — which is
what lets the user hand you more.
