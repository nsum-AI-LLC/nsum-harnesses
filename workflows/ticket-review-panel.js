export const meta = {
  name: 'ticket-review-panel',
  description: 'Adversarial accountability panel: spawn N independent reviewers (diverse lenses) against a groomed ticket BEFORE a developer is dispatched; collect structured findings. See docs/development-loop.md.',
  whenToUse: 'Before dispatching a developer on a high-sensitivity ticket (irreversible operations, wide blast radius, a contested design fork). Pass {ticketPath (ABSOLUTE path), fork} as args — relative paths are rejected (they can resolve against a stale worktree CWD and review the wrong file).',
  phases: [
    { title: 'Panel', detail: 'three independent reviewers, diverse lenses' },
  ],
}

// args: { ticketPath: string (ABSOLUTE), fork?: string }  (tolerant of a JSON-string-encoded args)
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (e) { A = {} } }
const ticketPath = (A && A.ticketPath) || ''
const fork = (A && A.fork) || "(see the ticket's Design Decisions section)"
if (!ticketPath) throw new Error('ticket-review-panel requires args.ticketPath')

// ENFORCED (not a remembered practice): ticketPath MUST be absolute. A relative path resolves against the
// reviewer agent's CWD, which can silently be a stale git worktree left by a prior background agent — the
// panel would then review an OUT-OF-DATE ticket and re-derive findings already fixed. Fail loud instead.
if (!ticketPath.startsWith('/')) {
  throw new Error(
    `ticket-review-panel requires an ABSOLUTE ticketPath (got '${ticketPath}'). A relative path can ` +
    `resolve against a stale worktree CWD and review the wrong file. Pass the full /Users/.../... path.`
  )
}

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'findings', 'steelman'],
  properties: {
    verdict: { type: 'string', enum: ['READY', 'REVISE', 'BLOCK'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'challenge', 'failure_mode', 'suggested_resolution'],
        properties: {
          severity: { type: 'string', enum: ['blocking', 'should-address', 'consider'] },
          challenge: { type: 'string' },
          failure_mode: { type: 'string', description: 'the concrete failure this finding guards against' },
          suggested_resolution: { type: 'string' },
        },
      },
    },
    steelman: { type: 'string', description: "the single strongest alternative to the ticket's chosen path, and why it does or does not win on merit" },
  },
}

const COMMON = `You are an INDEPENDENT adversarial reviewer of a GROOMED TICKET, reviewing it BEFORE any developer is dispatched. You did NOT write it. Review on merit as though you had unlimited time and resources — never weigh token/effort/timeline cost as a reason for or against a recommendation, and flag it if the TICKET does ("decide on merit, not on cost of change").

Read first, so your challenge is grounded, not generic:
- The ticket: ${ticketPath}
- The project's strategy / product-vision doc, if it has one (core objectives the ticket should serve)
- The project's quality bar and decision-hygiene rules (often in the root CLAUDE.md)
- Any spec or proposal the ticket cites
- The actual code files the ticket's Approach/Files name — read them and verify the approach is real, not just plausible

The design fork this ticket resolves: ${fork}

Every challenge must be SUBSTANTIVE: name a concrete failure mode, a violated principle, or a specific better alternative. Vague "have you considered" is noise. Do NOT rubber-stamp by silence: if you find little wrong, still produce your steelman of the strongest alternative and explain why it loses. You are read-only; do not write files. Return ONLY the structured object.

Be EXHAUSTIVE — review as deeply and as widely as the ticket warrants: the cited specs/files, the call sites of every function it changes, the jobs/commands that invoke the affected code, and anything a literal implementation could break. Depth is the point of this review; do NOT trade thoroughness for speed. If the platform drops your connection, the run is retried — never cut a review short to avoid it.`

const LENSES = [
  { key: 'fork-merit', prompt: `${COMMON}

YOUR LENS — FORK CORRECTNESS ON MERIT: Is the chosen path genuinely the best option, decided on merit? Steelman each dismissed alternative under the "unlimited resources" test — would it win if effort and time were free? Scan the ticket's own reasoning for cost-gating red flags ("ship now", "defer", "the win is small", "non-trivial work", "pragmatic compromise"). Is the evidence cited actually sufficient to support the decision, or is it thin?` },
  { key: 'safety-blast-radius', prompt: `${COMMON}

YOUR LENS — HIDDEN ASSUMPTIONS & BLAST RADIUS: What must be true for this to work that the ticket never verifies? Could it mutate more than intended, run wider than intended, over-write or destroy hard-won data, or act destructively without a recoverable backup or dry-run? Is it idempotent, reversible, observable? What is the worst case if the developer implements it literally as written?` },
  { key: 'strategy-groom', prompt: `${COMMON}

YOUR LENS — STRATEGIC FIT & GROOM COMPLETENESS: Does this serve the product strategy, or optimize a local metric against the global goal? Is it self-contained enough for a zero-context developer (concrete file paths, class/method names — not "implement X")? Are the acceptance criteria specific and testable, split into what-ships-with-the-change vs. what-runs-after, and do they include "PR merged"? Is the Files list complete? Does every current-behavior claim it relies on carry a system-analyst signature? If it touches an external service, is the integration provider-agnostic?` },
]

phase('Panel')

// Retry each lens until it genuinely completes. A stalled reviewer is silence, not approval (intermittent
// platform API drops) — so we re-spawn it rather than accept a partial panel. This is the "retry through
// failures, never degrade the review" posture.
async function reviewWithRetry(lens, maxAttempts) {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const label = `review:${lens.key}` + (attempt > 1 ? `#${attempt}` : '')
    let r = null
    try {
      r = await agent(lens.prompt, { label, phase: 'Panel', schema: FINDINGS_SCHEMA })
    } catch (e) {
      r = null
    }
    if (r) return { lens: lens.key, attempts: attempt, ...r }
    log(`reviewer ${lens.key} did not complete (attempt ${attempt}/${maxAttempts}) — re-spawning`)
  }
  return null // exhausted all attempts
}

const reports = await parallel(LENSES.map(lens => () => reviewWithRetry(lens, 5)))
const valid = reports.filter(Boolean)
const incomplete = LENSES.map(l => l.key).filter(k => !valid.find(v => v.lens === k))
const blocking = valid.flatMap(r => (r.findings || []).filter(f => f.severity === 'blocking').map(f => ({ lens: r.lens, ...f })))

return {
  ticketPath,
  reviewers: valid.length,
  complete: incomplete.length === 0, // true only if all lenses genuinely returned
  incomplete,                         // lenses that never completed — the panel is NOT trustworthy if non-empty
  verdicts: valid.map(r => ({ lens: r.lens, verdict: r.verdict })),
  blocking_findings: blocking,
  all: valid,
}
