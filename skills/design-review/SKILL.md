---
name: design-review
description: Decide whether a change is the right approach before any of its code is reviewed. Layer 1 of review — SHOULD, not DOES. Emits a SOUND or UNSOUND verdict; UNSOUND returns the ticket to the orchestrator to re-groom and re-instruct, and blocks the code-review skill from running. Invoke on every review round of a PR, including fix rounds.
---

# Design review — is this the right approach?

The question is whether the change should exist in this form. Not whether the code is correct;
not whether the tests pass. A change can be flawless and still be the wrong thing built.

**This runs before `code-review` on every round, including fix rounds.** A verdict is required
each time. An approach that was sound against the first draft can be refuted by what later
rounds discover, and the round that discovers it is the round that must say so.

## 1. State the outcome with no mechanism in it

Read the ticket, its epic, and the specs in its § Key Specs. Then write the outcome the work
must produce **as a sentence containing no mechanism** — no file, no surface, no gate, no
command.

> A developer or an agent must not be able to spend money by accident.

That is an outcome. "Gate the pytest invocation surface" is a mechanism. "Stop the queue
emitting thousands of exceptions" is an outcome; "drain the anchored-title band" is a
mechanism.

**If the outcome cannot be stated without naming the mechanism, the ticket's framing has been
inherited and this review has not started yet.** A ticket names one approach. It is one
candidate, written before the code was read, and it is the thing under review — not the
premise of the review. A title that names a mechanism is an approach wearing a requirement's
clothes.

## 2. Enumerate the chokepoints from the code, before judging the approach

For that outcome, find every place in the codebase where it can be enforced. Read the code to
find them; do not reason about where they ought to be.

For each: how many call sites does it cover, is the set closed, and does it already carry a
related concern — a log, a counter, a cost record — that shows it is the real seam?

Rank them by narrowness. The narrowest closed chokepoint is the layer that owns the outcome.

Only now read the approach. It is SOUND if it acts at that layer or at one indistinguishable
from it in coverage.

## 3. Judge the approach against that layer

| Ask | UNSOUND when |
|---|---|
| Does it act at the narrowest closed chokepoint? | A narrower one exists and is not used |
| Is the surface it defends closed? | A new route can reach the outcome without touching this code |
| Does an existing seam already carry it? | It builds a parallel mechanism beside one that exists |
| Is it one concern? | It spans concerns that would be tested and reverted separately |
| Does its size fit its concern? | Reviewing it in one pass is not possible |

**A defended surface with an unbounded tail is UNSOUND.** If any route reaches the outcome and
cannot be gated, the approach narrows the requirement rather than delivering it. Name the route.

**The cost of reaching the right layer is not a reason to act at a lesser one.** An approach that
identifies the correct layer and declines it on packaging, migration, effort or timeline is
UNSOUND. Name the correct layer and the work it needs as two separate statements. Whether to pay
for that work is the owner's decision, and it is not answered by building somewhere cheaper.

**A fork resolved correctly inside a wrong approach is still UNSOUND.** Verifying that one
candidate mechanism was properly rejected says nothing about whether the family of mechanisms
is the right one. Judging the approach against the ticket's framing is the failure this layer
exists to prevent.

## 4. On a fix round, read the accumulated findings as evidence about the design

Findings are data about the approach, not only a work list. These patterns are UNSOUND
verdicts, not further fixes:

- **Churn without movement.** Two consecutive rounds whose changes land mostly in tests. The
  implementation has stopped changing while work continues.
- **Guards outgrowing the thing guarded.** Test volume exceeding the implementation it covers
  by more than roughly 1.5×, while findings still arrive.
- **A limitation that is the requirement.** Any finding documented as an accepted limitation
  which, restated, says the change does not achieve what the ticket asked.
- **Round count.** By the third round, state explicitly why the approach is still right. The
  default at that point is UNSOUND: three rounds of findings on one approach is evidence
  about the approach.

## 5. Emit the verdict

End the review with one of these tokens on its own line. The token is the gate; nothing
downstream proceeds without it.

```
⟦DESIGN-REVIEW: SOUND⟧
```

The approach acts at the right layer, the surface is closed, no existing seam is duplicated,
and it is one reviewable concern. `code-review` may run.

```
⟦DESIGN-REVIEW: UNSOUND⟧
```

Followed by, in this order:

1. **The refutation** — the named route, layer, or existing seam that defeats this approach.
   One sentence, citing `file:line`.
2. **Where the requirement lives** — the layer that owns it, cited from the code.
3. **What the ticket should ask for instead** — the shape, not the implementation.

Stop there: no implementation findings, no proposed patches. Not because the implementation is
someone else's concern — you own whether this requirement gets met — but because findings
against a refuted approach describe code that will not ship. The verdict returns the ticket to
the orchestrator to re-groom and re-instruct a developer, and it is the most useful thing you
can hand over.

If you saw something in passing that survives a change of approach — a defect in code the new
shape will still use — say so in one line under the three items. Judgement you are holding is
worth more written down than carried.

## Boundaries

These bound where a decision is made, not what you are responsible for. You own the outcome the
ticket exists to produce, the whole way through.

Assess the approach, not the merge. The merge disposition is the orchestrator's.

Judge what the change does, not who wrote it or how much of it exists. Work already invested
in a refuted approach is not a reason to sustain it, and neither is the round number.

State UNSOUND on evidence you can cite. An approach you would have designed differently is
SOUND if it acts at the right layer and closes its surface — preference is not refutation.
