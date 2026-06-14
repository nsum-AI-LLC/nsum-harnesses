---
name: architect-reminder
description: Force a re-derivation of an architectural recommendation when cost, timeline, sunk-cost, or schedule-state factors appear to have gated the decision rather than merit. Use any time the model has produced (or is about to produce) a recommendation between architectural options — especially when a "Path A vs Path B" framing appears, or phrases like "ship now / iterate later," "file as follow-up," "defer to next cycle," "the win is small," "non-trivial work," or "risk of disruption" surface in the draft.
---

# Architect Reminder Skill

You were invoked because someone — the user, or you yourself — detected (or wants to preempt) a
cost-gated or sunk-cost-driven architectural recommendation. The job of this skill is to re-derive that
recommendation **on merit alone**, with non-merit factors explicitly stripped out.

This is a mandatory-process skill: walk through every step and produce the structured output. Do not
summarize or skip steps.

## Why this skill exists

Two failure patterns recur in long-running agentic work:

1. When new evidence invalidates a plan that's already in motion, you tend to fold the evidence into the
   existing plan as a "follow-up" rather than restart from the new evidence.
2. You tend to weigh "this would take work" as a strike against the architecturally-correct option.

Both substitute *cost of change* for *correctness*. This skill catches them by forcing the decision
through a rubric where non-merit factors are removed before the recommendation is written.

> **Decide on merit, as if resources were unlimited.** Effort, token budget, timeline, and how far along
> the current plan is are *planning* concerns — they inform how the work gets sequenced **after** you pick
> the right answer, never which answer is right. If your project has a written decision-hygiene rubric,
> this skill is its enforcement procedure; if not, the principle above is the rubric.

## Process — execute every step

### Step 1: Name the recommendation under review

State the options being weighed. If you've already drafted a recommendation, quote it verbatim (your
exact words, including any "Path A vs Path B" framing). If you're about to draft one, name the options
before going further.

### Step 2: Enumerate every factor you weighed

Be exhaustive. Split into two columns:

| Merit factors (correctness + fit) | Non-merit factors (cost / timeline / state) |
|---|---|
| Accuracy, correctness, behavior on real inputs | Effort estimate / "that's a big change" |
| Architectural fit with existing design | Schedule / "the PR is already in review" |
| Operational properties (determinism, observability, reversibility) | Sunk cost in the current plan |
| Long-term maintainability | "Risk of disruption" with no quantified risk |
| Performance/scaling characteristics | Prior momentum / "we're partway through X" |
| … | … |

The non-merit column is what must be EXCLUDED from the decision. List everything you actually weighed;
don't sanitize.

### Step 3: Cross out the non-merit factors

Strike them. They are planning considerations that *follow* the recommendation, not decision criteria.

### Step 4: Apply the unlimited-resources test

Ask, out loud: "If the work happened by magic — zero effort, zero time, zero disruption — would my
recommendation change?"

- **If yes:** non-merit factors gated the decision. The merit-based answer is the right answer. Continue.
- **If no:** the recommendation was already on merit. Continue anyway to verify the red flags are absent.

### Step 5: Re-state the recommendation on merit only

Write a single recommendation. Not "Path A vs Path B." One path, on merit, with the reasoning that
supports it. Then, in a **separate, clearly-labeled** section ("Work involved" / "Planning notes"),
surface the effort, sequencing, and risk the user needs to commission the work. That section is for the
user's planning — it does not gate which option you recommended.

### Step 6: Self-check against the red-flag phrases

Scan your revised recommendation. If any of these appear *in the recommendation itself* (not in the
separate planning-notes section), you have not fully re-derived — loop back to Step 4:

- "Ship now, iterate later" / "File as follow-up"
- "Defer to next cycle/sprint" (as a recommendation, not a user-requested option)
- "Already in review" / "too far along to change"
- "The win is small" (especially small on one axis but large on another — small accuracy gain at large
  cost is *not* small)
- "Path B captures most of the value" (the framing itself is suspect)
- "Non-trivial work" used as a reason NOT to do the work
- "Risk of disruption" without a quantified risk
- "Pragmatic/practical compromise"
- "Smaller change is safer" (without quantifying both)

**Budget / turn-length manifestation** (the recurring "ration the budget" reflex — flag these even
outside a formal recommendation, in *any* work product):

- "I can't do everything in one session" / "realistically this session" / "as far as I get"
- "to keep this short" / "to save tokens / context" — as a reason to abbreviate an artifact or do less
- Any framing where token count, context-window pressure, or session length influences *what* you do,
  *how much*, or *how completely* you write something. These are never decision inputs. The harness
  summarizes context and continues across windows, so "the session is long" is an imaginary boundary.
  Depth follows the artifact's job, never its length.

### Step 7: Brief self-diagnosis

In 2–3 sentences, name the specific non-merit factors that crept into the original draft and what
triggered the slip. Honest record-keeping makes the pattern visible and helps calibrate when to re-invoke
this skill.

## Output structure

Four clearly-labeled sections:

1. **Original (cost-gated) draft** — quote it if you had one; else "none — applying preemptively."
2. **Merit-only recommendation** — one path, with correctness and architectural reasoning.
3. **Work involved (planning notes, not decision criteria)** — effort, sequencing, risks, follow-ups.
4. **Self-diagnosis** — 2–3 honest sentences on what gated the original draft.

## When to invoke this skill

- The user invokes `/architect-reminder` directly.
- Before writing any architectural recommendation between options (framework choice, schema design with
  trade-offs, build-vs-reuse, provider choice).
- After writing a draft that contains any red-flag phrase from Step 6.
