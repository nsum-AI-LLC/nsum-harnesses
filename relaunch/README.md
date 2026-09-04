# Session-continuity supervisor

Keeps long-running Claude Code work going across the two walls that end a session:
**context exhaustion** and **usage limits**. An external launchd tick watches for a
session that stopped, waits out whatever blocked it, and relaunches it in a real
terminal window.

## The one idea worth knowing

**The axis is WOUND-DOWN vs KILLED — not context vs usage.**

| The session… | wrote a handoff? | relaunch mode |
|---|---|---|
| wound down (context, or an anticipated usage wall) | yes | **pickup** — `claude "/pickup <id>"` |
| was killed mid-flight by a usage limit | **no** | **resume** — `claude_resume <id> "<salvage prompt>"` |

A killed session never wrote a handoff, so there is nothing for a fresh session to
pick up. `claude_handoff` greps the transcript and returns the *last* handoff block
in it — which for a killed session is the one its **predecessor** handed it. The
fresh session then silently re-runs a stale mission while the dead session's real
state (live agents, dirty worktrees, unpushed branches) is orphaned.

Measured 2026-09-04: a session was relaunched into its predecessor's handoff, whose
stated goal ("nine PRs open, not one merged") was five merges out of date, and four
interrupted agents' work sat unharvested until a human noticed.

## A usage limit does not kill the process

It only makes every request fail. The process, its window and its children survive,
appending nothing — and that quiet transcript is exactly what the watchdog reads as
a death. So when the limit resets, the original process is usually *still there*.
Measured: a session was still the same live pid **4h12m** after hitting its limit.

Harmless under `pickup` (two processes, two session ids). A correctness bug under
`resume`: `claude --resume <id>` against a live process starts a **copy**, giving
two owners of one session id and one transcript.

The fix is `hooks/session-pid-registry.py` — a `SessionStart` hook that maps
session id → pid and **retires** the survivor. Note it retires rather than revives:
waking the old window in place is elegant when the wait is short and fails exactly
when it is long (a weekly limit resets in days, by which time the window is gone).

There is no cheap session→pid link, so the hook walks the process tree. All three
obvious candidates were measured and rejected: **argv** does not carry a client's
own session id (it names the session it picked up), **lsof** shows no persistent
handle (append-and-close writes), and the **environment** has no session id.

## Parts

| File | Role |
|---|---|
| `claude_relaunch_supervisor` | the launchd tick: watchdog, wait/probe, relaunch |
| `claude_write_relaunch_spec` | called at wind-down to arm the next session |
| `relaunch_common.py` | limit wording, reset parsing, availability probe, path resolution |
| `claude_usage_meter` | burn estimate against a calibrated window ceiling |
| `../hooks/session-pid-registry.py` | `SessionStart` hook: retire a surviving process |
| `install.sh` | installs the four, arms launchd, runs the self-test |

## Install

```bash
./install.sh          # installs, arms launchd, self-tests, dry-runs
```

Then wire the hook per project — it is not installed globally, because it needs an
entry in that project's `.claude/settings.json`:

```bash
cp ../hooks/session-pid-registry.py <project>/.claude/hooks/
```
```json
{ "hooks": { "SessionStart": [
  { "matcher": "", "hooks": [
    { "type": "command",
      "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session-pid-registry.py",
      "timeout": 15 } ] } ] } }
```

**Root resolution** (`$CLAUDE_RELAUNCH_ROOT` → an existing `~/.claude/willcall-relaunch`
→ `~/.claude/claude-relaunch`) means an in-place upgrade keeps a running job's specs,
log and history exactly where they are. `install.sh` reuses an existing launchd label
for the same reason — a second label would leave two supervisors racing one spec dir.

## Safety rails

- **Kill switch:** `touch <root>/pause` stops everything; `rm` resumes.
- **Crash-loop cap:** more than 3 relaunches in a rolling hour stops and notifies.
- **Every action and refusal** is appended to `<root>/log.jsonl` with its trigger.
- **A relaunch happens only from a spec**, and a consumed spec moves to `done/`, so
  one death cannot double-launch. `already_handled` is death-aware, because a
  resumed session keeps its id — otherwise the first usage-kill would be the last
  one the supervisor ever acted on for that session.
- **Every process kill** is gated on: not self · not an ancestor · still alive ·
  `comm` is still `claude` · **recorded start time still matches** (the pid-reuse
  guard). Anything ambiguous is left alone and logged. SIGTERM, 3s, then SIGKILL.
- **No model is named.** `~/.claude/settings.json` already carries the tier policy
  (e.g. `model: fable`, `fallbackModel: [opus]`) and the client applies it per
  request. Pinning a model here overrode that. Probing still names one, because a
  canary must ask about a specific pool.

## Known behaviour to accept

**Single ownership is unconditional.** Resuming a session that is genuinely alive
retires it — there is no "is it busy?" exemption. Two writers on one transcript is
the worse outcome, and the transcript survives either way; the cost is that an
accidental resume terminates in-flight agents rather than forking.

## Testing

`install.sh` runs a self-test covering: the real death record, the quoted-429
false-positive control, usage-death→resume, context-wind-down→pickup, the no-model
rule, and slug resolution. `claude_relaunch_supervisor --dry-run` prints decisions
without launching, moving, or spending a probe.
