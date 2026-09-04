# Session continuity — surviving the two walls

Long autonomous runs end for two reasons that have nothing to do with the work:
the **context window** fills, or a **usage limit** hits. The first is well handled by
a wind-down convention (write a handoff, start a fresh session, pick it up). The
second is not — and treating it like the first loses work in a way that is hard to
notice afterwards.

This is the machinery that closes the gap.

## The distinction everything turns on

**The axis is WOUND-DOWN vs KILLED — not context vs usage.**

| The session… | wrote a handoff? | correct relaunch |
|---|---|---|
| wound down (context, or an anticipated usage wall) | yes | **pickup** — fresh session, reads the handoff |
| was killed mid-flight by a usage limit | **no** | **resume** — same session id, plus a salvage prompt |

A killed session never reached its wind-down, so there is no handoff to pick up.
If you point a `/pickup` at it anyway, the handoff-extraction step greps its
transcript and returns the *last* handoff block in the file — which for a killed
session is **the one its predecessor handed it**. The relaunch then silently
re-runs a stale mission.

That is not hypothetical. Measured 2026-09-04: a session was relaunched into its
predecessor's handoff, whose stated goal ("nine PRs open, not one merged") was five
merges out of date. Four interrupted agents' work — including 711 uncommitted lines
in one worktree — sat unharvested until a human noticed.

So a killed session is **resumed**, keeping the context that knows what was in
flight, and handed a prompt telling it to salvage its own interrupted work.

## A usage limit does not kill the process

This is the part that surprises people, and it is what makes the resume path
dangerous if you stop at the previous section.

A usage limit only makes every *request* fail. The process, its terminal window and
its child processes all survive, appending nothing to the transcript. That silence
is exactly what a watchdog reads as "dead." So when the limit resets, the original
process is usually **still sitting there** — measured: the same live pid 4h12m after
it hit the wall.

Under `pickup` that is merely untidy (two processes, two session ids). Under
`resume` it is a correctness bug: `claude --resume <id>` against a session whose
process is alive starts a **copy**, giving two owners of one session id and one
transcript.

`hooks/session-pid-registry.py` closes it. On `SessionStart` it maps session id →
pid and **retires** any other live process registered under the same id.

### Why retire rather than revive

Waking the surviving window in place is elegant — it preserves the running process
and its in-flight background work. It also fails exactly when the wait is longest: a
weekly limit resets in *days*, by which time the window is almost certainly gone.
Launching fresh is robust in both directions, so the pid map is spent retiring the
survivor rather than reviving it.

### Finding the pid is harder than it looks

There is no cheap session-id → pid link. All three obvious candidates were measured
and rejected:

- **argv** — a client's own session id is *not* in its command line. It names the
  session it was told to pick up, if any.
- **lsof** — no persistent handle; transcript writes are append-and-close.
- **environment** — carries no session id.

What works is the **process tree**: a hook runs as a descendant of the client, so
walking up `ppid` finds it.

### Every kill is gated

Signals are not sent on a guess. A process is retired only when **all** hold: it is
not this process, not an ancestor of it, still alive, its command is still `claude`,
and its **recorded start time still matches** — the real pid-reuse guard, since a
recycled pid gets a new start instant. Anything ambiguous is left alone and logged.
SIGTERM, a 3-second grace, then SIGKILL.

**Accepted consequence:** single ownership is unconditional. Resuming a session that
is genuinely alive retires it — there is no "is it busy?" exemption. Two writers on
one transcript is the worse outcome, and the transcript survives either way; the
cost is that an accidental resume terminates in-flight agents rather than forking.

## Waiting out the wall

- A **shared pool** (session / weekly) gates every model, so it must be waited out.
- A **model-scoped pool** (Opus / Sonnet / Fable / credits) does not gate the other
  tiers — relaunch immediately and let the client's own `fallbackModel` chain land
  on one that is open. Waiting days for one tier while another sits available is the
  dormancy this exists to prevent.
- A death whose reset time cannot be determined is **never dropped**. It becomes a
  polled spec and launches when the pool answers. (The predecessor logged "no reset
  time" and did nothing — 1,643 times across three days, for one weekly kill it had
  detected correctly on the very first tick.)
- Even a known reset is an **upper bound**; resets happen off-cycle, so a waiting
  spec is probed and launches the moment the pool reopens.

**No model is named on relaunch.** Your settings already carry the tier policy
(`model` + `fallbackModel`) and the client applies it per request. Pinning a model
in the supervisor overrides that policy for the life of the session. Probing still
names one, because a canary has to ask about a specific pool.

## Why this is not redundant with the client's own auto-continue

Claude Code will not auto-continue past a 24-hour horizon ("the usage limit now
resets more than 24 hours out, so this task will not resume on its own"). A weekly
reset is days out — so the weekly case is precisely the one the product does not
cover.

## Parts

| File | Role |
|---|---|
| `relaunch/claude_relaunch_supervisor` | the launchd tick: watchdog, wait/probe, relaunch |
| `relaunch/claude_write_relaunch_spec` | called at wind-down to arm the next session |
| `relaunch/relaunch_common.py` | limit wording, reset parsing, availability probe, path resolution |
| `relaunch/claude_usage_meter` | burn estimate against a calibrated window ceiling |
| `relaunch/install.sh` | installs, arms launchd, self-tests, dry-runs |
| `hooks/session-pid-registry.py` | `SessionStart`: retire a surviving process |
| `scripts/claude_resume` | resume a session by id, optionally with a first prompt |

## Install

```bash
cd relaunch && ./install.sh
```

Then wire the hook per project (it needs an entry in that project's settings):

```bash
cp hooks/session-pid-registry.py <project>/.claude/hooks/
```
```json
{ "hooks": { "SessionStart": [
  { "matcher": "", "hooks": [
    { "type": "command",
      "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session-pid-registry.py",
      "timeout": 15 } ] } ] } }
```

**macOS only** — it uses `launchd` for the tick and AppleScript to open a terminal
window. The decision logic is portable; the two platform seams are the launchd plist
and the `osascript` call in `launch()`.

## Safety rails

- **Kill switch:** `touch <root>/pause` stops everything; `rm` resumes.
- **Crash-loop cap:** more than 3 relaunches in a rolling hour stops and notifies.
- **Every action and refusal** is logged to `<root>/log.jsonl` with its trigger.
- **A relaunch happens only from a spec**, and a consumed spec is retired, so one
  death cannot double-launch. The "already handled?" check is **death-aware**,
  because a resumed session keeps its id — otherwise the first usage-kill would be
  the last one the supervisor ever acted on for that session.
- **Ambiguity refuses.** Two distinct limit-dead sessions in one tick notifies and
  relaunches nothing.
