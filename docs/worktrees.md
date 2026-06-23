# Worktrees — isolating parallel subagents

The orchestration roles in this repo assume an **orchestrator → worktree** topology: a primary session
that plans and delegates, and subagents (developer, code-reviewer, system-analyst, panel reviewers) that
each run in their own git worktree. This doc explains where worktrees are used, why the isolation matters,
and the guards and recovery tools that make it safe. The failure modes below are real ones from running a
fleet of agents on a production codebase — each guard exists because its absence cost a session.

## When worktrees are used

A git **worktree** is a second working directory backed by the same repository, checked out on its own
branch. The orchestrator dispatches each subagent into its own worktree under
`<project>/.claude/worktrees/<id>/`, on its own branch, via the platform's `isolation: "worktree"` (see
the agent frontmatter in `agents/`).

Why a worktree and not just a branch: a single checkout can only be on one branch at a time. Two subagents
sharing one checkout would overwrite each other's files and fight over `HEAD`. Worktrees give each agent an
isolated working directory while sharing the object store, so the orchestrator can run several developers
and reviewers at once.

The split between what's isolated and what's **shared** is what to keep straight:

- **Isolated per worktree:** the working directory and `HEAD` (which branch/commit is checked out).
- **Shared across all worktrees:** the object store and, critically, **branch refs**. A branch can be
  checked out in only one worktree at a time, and a `git checkout` in one place moves a ref everything else
  can see.

Most collisions come from acting on a *shared* thing as if it were isolated.

## Why isolation matters — the collisions it prevents

| Failure mode | What happens | Impact | Guard / tool |
|---|---|---|---|
| **Subagent writes into the primary tree** | A subagent builds a primary-rooted absolute path and writes there instead of its worktree | Corrupts the orchestrator's checkout mid-run | `subagent-block-primary-writes.sh` + Step-0 self-check |
| **Subagent reads the primary tree** | Same path slip on a Read: the harness serves the primary's stale, wrong-branch content | The agent reasons against content that contradicts its own diff, blames "tool caching," and burns a long wrong detour | `subagent-block-primary-reads.sh` + path discipline |
| **Orchestrator reads into a worktree** | The primary session reads `…/.claude/worktrees/X/...` when it meant its own copy | Decisions made on stale, cross-branch code | `cross-worktree-read-guard.sh` |
| **Stray branch switch in primary** | A misplaced subagent runs `git checkout` / `gh pr checkout` from the primary cwd | Moves the shared `HEAD`; can detach the orchestrator and lock the main branch in a dead worktree (manual recovery) | `guard-branch-switch.sh` |
| **Ad-hoc worktree removal** | `git worktree remove`/`prune` run by hand | Can delete a live worktree out from under an open editor and crash it | `guard-destructive-git.sh` + `prune_worktrees.sh` |
| **Planning write from a worktree** | A subagent writes a cross-cutting `planning/**` doc on its throwaway branch | The artifact is stranded on a branch that gets deleted; planning belongs on the shared primary tree | `protect-worktree-planning.sh` |
| **Misplacement** | The platform places a subagent in primary instead of its worktree | Everything the subagent does lands in the wrong tree | Step-0 self-check (`MISBINDING` abort) |
| **Reaped session strands work** | A session goes silent after a tool result and is killed; a commit never pushed, or a primary write never committed | Completed work looks like total failure; an orphaned artifact gets adopted blind | atomic `git commit && git push` + `harvest_unpushed_worktree_commits.sh` |
| **Worktree accumulation** | Finished worktrees pile up (a branch still checked out can't be auto-reaped) | Eventually a branch you need is "already checked out" elsewhere → checkout collision and stale materialization | `prune_worktrees.sh` (dry-run first) |
| **Silent commit loss** | A collision, branch-thrash, or merge mishap undoes a commit | Work that looked merged isn't on the main branch | `audit_session_commits.sh` |

## The guards (mechanical)

Two scopes. **Project-level** hooks (wired in `settings.json`) apply to the orchestrator and any session.
**Subagent-scoped** hooks (wired in an agent's YAML frontmatter) apply only to that subagent — never the
orchestrator, which must read and write the primary tree freely.

Project-level (`settings.json`):

- `cross-worktree-read-guard.sh` — PreToolUse on Read: block reading into a worktree the session doesn't own.
- `guard-branch-switch.sh` — PreToolUse on Bash: block `checkout`/`switch`/`gh pr checkout` from the primary cwd.
- `guard-destructive-git.sh` — PreToolUse on Bash: block `git worktree remove`/`prune` (route through the script).
- `protect-worktree-planning.sh` — PreToolUse on Write/Edit: block a worktree's `planning/**` writes. A subagent cannot write planning *anywhere* — this blocks the worktree copy, and the platform's shared-checkout guard blocks the primary copy — so planning is the orchestrator's to persist (a subagent hands it over in its report; see the note below the guard lists).
- `subagent-block-primary-writes.sh` — PreToolUse on Write/Edit: block writes that resolve into the primary tree. (Wired project-level for reliability; it no-ops for the orchestrator via its own scope check.)

Subagent-scoped (agent frontmatter):

- `subagent-block-primary-reads.sh` — PreToolUse on Read: block a subagent's read of the primary tree when a worktree twin exists, and return the corrected worktree path. Frontmatter-only by design — wired project-level it would block the orchestrator's constant primary reads. It also carries its own scope guard, so it's safe if mis-wired.

Every guard is **fail-open**: on any error it allows the call. They are strong defaults, not a security boundary.

**Planning docs are read-from-primary, written-by-orchestrator.** A subagent reads `planning/**` from the
primary tree (the read guards carve it out) but writes it *nowhere*: `protect-worktree-planning.sh` blocks
the worktree copy and the platform's shared-checkout guard blocks the primary copy. This is deliberate, not
a gap. Planning artifacts are cross-cutting and belong to the orchestrator, which runs in primary and
persists them — a subagent's status update reaches primary via its report, not its own write. Two corollaries
keep this from becoming a trap: a subagent that needs a planning write must hand the content to the
orchestrator (not retry either path — that just loops between the two guards), and the orchestrator must
never dispatch a docs-only / planning-only ticket to a worktree subagent (it would deadlock, with the
deliverable persistable nowhere) — the orchestrator writes those itself.

## The agent self-check

A hook can't catch a `gh pr checkout` from a mis-placed subagent (it would run in the wrong tree before any
guard fires). So every subagent's first action is a self-check — `pwd && git rev-parse --show-toplevel` —
and it aborts with `MISBINDING` if it's in the primary tree instead of a worktree (see the Step-0 block in
each file under `agents/`). The hook and the self-check together cover the realistic failure shapes;
either alone has gaps.

The companion to the self-check is **path discipline**: the `/Users/.../<project>/...` paths in `CLAUDE.md`,
tickets, and the env header are the orchestrator's primary checkout. A subagent must translate them to its
own worktree root. Most read/write collisions are this slip, which is why the prompts repeat it and the
guards redirect it.

## Recovery and maintenance tools (`scripts/`)

- **`harvest_unpushed_worktree_commits.sh`** — read-only scan for "stream-death" strands: a worktree commit
  that was never pushed, or a primary `planning/**` write that was never committed. Run it before
  re-dispatching after a subagent dies, so you recover real work instead of rebuilding it. Mutates nothing.
- **`prune_worktrees.sh`** — the sanctioned way to remove worktrees (it `cd`s to the main dir first so it
  can't delete the directory you're in). `--list` and `--dry-run` first, always. Pushed work only — unpushed
  commits in a removed worktree are lost, so harvest first.
- **`audit_session_commits.sh`** — after a messy session, confirm every commit you made is actually on the
  main branch and the primary tree has no phantom (cross-subagent) changes.

The discipline that makes recovery rare: developers persist with an **atomic `git commit && git push`** (no
window between commit and push for a reap to strand work), and never create satellite `-fix` branches (a
commit on a branch the PR never sees survives merge as an orphan).

## Relationship to Claude Code's built-in worktree feature

Claude Code provides the isolation itself: `isolation: "worktree"` on an agent (and `--worktree`) places it
in its own worktree, and `WorktreeCreate` / `WorktreeRemove` hooks fire on the lifecycle. The official docs
document that feature but not the failure modes above. What this repo adds is the **safety net** (the guards
and the self-check, for when placement or path-translation goes wrong) and the **recovery tools** (for when
a session dies mid-flight). If you adopt the platform's worktree isolation for parallel agents, you want
this layer too.

## Adopting

1. Give each subagent `isolation: worktree` and the Step-0 self-check (the `agents/` files are the template).
2. Wire the project-level guards in `settings.json` (see `settings.example.json`).
3. Wire `subagent-block-primary-reads.sh` in each subagent's frontmatter (already done in `agents/`).
4. Put `scripts/` on your `PATH` so the recovery tools are one command away when a dispatch dies.
5. Add `.claude/worktrees/` to `.gitignore` — worktrees are local and disposable.
6. Prune on a cadence (`prune_worktrees.sh --sprint <N> --dry-run`, then for real) so accumulation never
   reaches the collision threshold.
