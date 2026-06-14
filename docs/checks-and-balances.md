# Checks and Balances

The reliability of this harness comes from how the roles are arranged, not from any one agent being
careful. Understand this before adopting the individual pieces.

## The premise

A capable coding agent has predictable weaknesses over a long development loop:

- **Sycophancy** — it trusts your framing, a ticket's claims, and its own earlier reasoning too readily.
- **Amnesia** — every session starts cold, so conventions get re-learned each time.
- **Compounding errors** — an early wrong assumption snowballs across an autonomous run.
- **Completion drive** — hand it "definition of done" and it will declare done.

You can't prompt these away. "Always verify," "always follow best practices" are advice, and the failure
that prompted this harness was an agent reading exactly that kind of advice and proceeding anyway.

So the harness doesn't ask one agent to get everything right. Each fact is checked by a different role than
the one that produced it, and the hand-off between them runs through a mechanism — a hook that blocks, a
signature that's grepped for, a checklist row that must be filled.

## The pattern

For every "there's no guarantee that X," a different role verifies X, and a gate makes that verification
visible:

- No guarantee a ticket has testable acceptance criteria → the orchestrator's readiness gate and the
  developer both refuse to build a half-groomed ticket.
- No guarantee the author traced the code they describe → the system-analyst traces it and signs the
  result; the developer and reviewer reject an unsigned claim.
- No guarantee the chosen approach is right → the adversarial panel attacks the ticket before a developer
  is dispatched.
- No guarantee best practices were followed → the code-reviewer checks them against an explicit checklist.
- No guarantee a recommendation was made on merit → architect-reminder forces a merit-only re-derivation.
- No guarantee a subagent is sandboxed → the worktree hooks and the agent's Step-0 self-check both verify
  it.
- No guarantee context was read → the precondition gate blocks edits until it was.
- No guarantee the harness itself stays correct → the Suggestion Collector proposes fixes from each
  session.

In every case the verifier sits between the step that produces a result and the step that would consume
it. That placement is the design.

## A worked example: the signature chain

Tickets routinely state how existing code behaves — "this step honors the flag," "that helper returns
`None`." Authors get these wrong often, because they reason from a grep instead of a trace, and a
developer who builds on a wrong claim writes correct-looking, wrong code.

When a ticket's correctness depends on existing behavior, grooming dispatches the **system-analyst**. It
traces the real execution path, cites `file:line` at each step, and ends its report with a signature:

```
⟦SYSTEM-ANALYST-VERIFIED⟧ topic="…" date="…" run="…" covers="the behaviors/files:lines verified"
```

That report goes into the ticket's **Current Behavior (verified)** section, and three later steps check for
the signature:

- the orchestrator's readiness gate won't dispatch a ticket whose behavioral claim lacks one;
- the developer won't build on an unsigned claim, and can dispatch the analyst itself;
- the code-reviewer fails any PR whose ticket carries an unsigned claim.

The signature is a token you can grep for, and three independent steps check it — so a guessed claim has no
path to merge.

## Why the checks are mechanical

A constellation of advice is still advice. The hand-offs hold because each runs through a mechanism:

- **Hooks block.** Precondition gates refuse edits until the required file was read; worktree guards refuse
  a subagent's write to the primary tree.
- **Signatures are grepped for.** `⟦SYSTEM-ANALYST-VERIFIED⟧` is a token, checkable by code.
- **Contracts must be filled.** The code-review checklist needs a verdict on every row.
- **Self-checks abort.** A subagent runs `git rev-parse --show-toplevel` and stops if it's outside its
  worktree.

When the answer to "what makes this happen?" is "the agent will remember to," there's no check yet.

## Applying it to your project

You don't need every role — you need the placement. For each thing your loop depends on but can't
guarantee:

1. Name the unguaranteed fact ("the migration is reversible," "the new endpoint is paginated").
2. Decide which *different* role verifies it — a reviewer, a dedicated analyst, a panel, a separate test
   gate.
3. Give the verification a visible result — a greppable marker, a blocking hook, a required checklist row.

Then put the check between the step that produces the result and the step that would use it unverified.

## What this doesn't give you

- **Not a security boundary.** Hooks fail open by design, so a script error or environment drift lets an
  action through. Treat them as strong defaults, not guarantees against an adversarial process.
- **Redundancy lowers the odds that every role misses a fact; it doesn't drive them to zero.** Mistakes get
  rarer and more visible.
- **It assumes a ticket-driven workflow** and, for the orchestration roles, an orchestrator → worktree
  setup. Adapt the specifics; keep the placement.

## Where each piece is documented

- [`harness_design.md`](harness_design.md) — the enforcement layer: hooks, gates, the session briefing,
  worktree safety, fail-open philosophy.
- [`development-loop.md`](development-loop.md) — the roles in motion, one ticket end to end.
- [`code-review.md`](code-review.md) — the most-customized check, and how to grow it.
- [`suggestion-collector.md`](suggestion-collector.md) — the loop that improves the harness itself.
