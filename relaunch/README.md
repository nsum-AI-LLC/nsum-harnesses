# Session-continuity supervisor

Keeps long-running Claude Code work going across the two walls that end a session:
**context exhaustion** and **usage limits**. An external launchd tick watches for a
session that stopped, waits out whatever blocked it, and relaunches it in a real
terminal window.

## The one idea worth knowing

**First ask whether the session actually DIED. Then ask wound-down vs killed.**

| The session… | wrote a handoff? | mode |
|---|---|---|
| is stalled on a **model-scoped** limit (Opus/Sonnet/Fable/credits) — still alive, only refusing turns | n/a | **model_switch** — type `/model <tier>` into its own live window |
| wound down (context, or an anticipated usage wall) | yes | **pickup** — `claude "/pickup <id>"` |
| was killed mid-flight by a **shared** limit (session/weekly) | **no** | **resume** — `claude_resume <id> "<salvage prompt>"` |

A usage limit never kills the `claude` process — it only makes every request fail.
For a **shared** pool that distinction is academic: every tier is refused, so the
session has nothing left to do and goes quiet. For a **model-scoped** one it is
the whole story: another tier is open, the window and its shells and subagents are
all still there, and the client's own error message names the fix — *"switch
models with /model"*. Relaunching such a session kills a live process to resume it
onto the tier that is exhausted, where it re-dies in seconds. Switching it in
place costs it nothing.

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
| `claude_account` | stores several accounts and switches between them |
| `../hooks/session-pid-registry.py` | `SessionStart` hook: retire a surviving process |
| `install.sh` | installs the five, arms launchd, runs the self-test |
| `test_accounts.py` | pool scoping, burn attribution, account selection |

## Install

**This directory is the source of truth, and a consuming project keeps no copy.**
The supervisor is one launchd job watching every session on the machine, so it is
installed once rather than synced per project — `sync_tooling` does not touch it.
Edit here, then install.

A copy checked into a consumer repository reads as authoritative to whoever finds
it next, and a session searching only its own repository will find that copy, or a
stale snapshot of it, and conclude the running supervisor is untracked.

```bash
./install.sh              # installs, arms launchd, self-tests, dry-runs
./install.sh --no-arm     # installs the code, leaves launchd alone
```

Use `--no-arm` when the job is deliberately unloaded. Updating the code and
starting the job are two different intentions, and someone who stopped the
supervisor on purpose will still install a fix.

The installer refuses to arm anything if the self-test fails. It used to print
the failure and continue, which is how a self-test broken by a signature change
went unnoticed across every install for two days.

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

## Which Python this runs under

**The launchd job runs `/usr/bin/python3` — the system interpreter.** A background
job has no conda environment and no user `PATH`, so it cannot be assumed to reach
whatever `python3` means in a developer's shell. On current macOS the system
interpreter is 3.9, while a project environment is often several versions ahead,
and the same files here run under both: the tick under launchd, the CLI tools
under whatever the shebang resolves to.

**So everything in this directory must parse under the system interpreter.** A
3.10-or-later construct — `match`, `X | Y` annotations, `tomllib` — makes the
supervisor unimportable, and the failure is silent: launchd's tick dies at
startup and sessions simply stop being relaunched, with nothing announcing why.
`install.sh` refuses to install if any file fails to parse under
`/usr/bin/python3`.

The CLI tools carry `#!/usr/bin/env python3` so a person gets their own
interpreter, which is fine — they are invoked interactively and the supervisor
calls them as subprocesses rather than importing them.

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
- **The tier comes from settings, never from the supervisor's own opinion.** The
  order is `model` then `fallbackModel` out of `~/.claude/settings.json`, and a
  tier is used only after a probe says it is open. Hardcoding a preference here
  once pinned every relaunch to Opus, which is why the rule is "read the declared
  order", not "pick a good one". If every declared tier is spent, the supervisor
  says so and waits — it will not switch you onto a tier you never named.
- **…but it does have to apply that order itself, because the client won't.**
  `claude --help`: `--fallback-model` covers a primary that is *"overloaded or not
  available"*, and *"(only works with `--print`)"*. A usage limit is neither, and
  an interactive session is not `--print`. Measured 2026-09-05: three interactive
  sessions exhausted Fable and took five hard stops with **zero** Opus turns while
  `fallbackModel: ["opus"]` sat in settings. Do not re-derive "the client will
  fall back on its own" — it does not, and that assumption cost a live session.
- **The nudge is confirmed, not timed.** `write text` submits a short line but a
  long one arrives as a *paste*, whose newline is inserted as text instead of
  submitting — the prompt looks finished while the session stays stalled. A fixed
  delay then an Enter was worse: it landed mid-paste and the nudge was discarded
  entirely. So Enter is re-sent until the **transcript** shows the message
  actually arrived.

## Known behaviour to accept

**Single ownership is unconditional.** Resuming a session that is genuinely alive
retires it — there is no "is it busy?" exemption. Two writers on one transcript is
the worse outcome, and the transcript survives either way; the cost is that an
accidental resume terminates in-flight agents rather than forking.

## Multiple accounts

One account has one set of limits. When a session hits the 5-hour, weekly or
monthly-spend wall there is no tier left to move to, and until now the only
answer was to wait for the reset. With a second account registered, the
supervisor switches to it and carries on.

```bash
claude_account setup      # says what is saved and what to do next
```

Registering an account requires being logged into it, and only one can be logged
in at a time, so setup is a loop: `/login` as an account, run `setup`, repeat.
`setup` cannot drive `/login` — that is an interactive browser flow inside the
client — so it reports state and names the next action rather than claiming a
completion it cannot deliver.

An account's stored state is its OAuth tokens, read from and written to the
login Keychain under service `Claude Code-credentials`, together with the
identity block under `oauthAccount` in `~/.claude.json`. **Both move together or
neither does** — swapping one leaves the client holding one account's tokens and
another's profile. The write to `~/.claude.json` is verified and retried, because
a running client rewrites that file on its own schedule.

Stored accounts live in `<root>/accounts/`, mode 0600 inside a 0700 directory.
Nothing prints a token.

### What the supervisor decides

Tier first, then account. A model-scoped limit (Opus, Sonnet, Fable) is answered
by `/model`, because another tier on the same account still has quota. Only when
no declared tier is open does the account change.

The pools are not equivalent, and treating them as one list gets it wrong twice
over:

- **Shared pools** — 5-hour, weekly, monthly spend — gate every model on the
  account. An account spent on any of them is closed for every need, and a
  session dying on one has already stopped every other session on that account,
  so switching costs them nothing.
- **Model pools** — Opus, Sonnet, Fable — are independent of each other and of
  the shared pools. A session stalled on Opus says nothing about one running
  Fable, so a switch that would break those is deferred and the stalled session
  waits for its reset instead.

The exhausted account's limit is recorded before the switch, so the next
escalation does not walk back into it and the return trip waits for a known
reset rather than polling.

Preference order is by plan size unless `<root>/account-preference.json` names
an explicit list of emails.

### Model policy per account

A larger plan can afford a cheaper model by default and hold the expensive one
as headroom; a smaller plan is better spent going straight to the model the work
needs. Both accounts share one `settings.json`, so the order is stored per
account and written into that file on every switch.

```bash
claude_account set-policy big@example.com   fable opus
claude_account set-policy small@example.com opus
```

The supervisor reads the order back out of `settings.json`, so there is one
source of truth. An account with no declared policy leaves the file alone.

### Two things that will bite you

**A switch is not private to the session that makes it.** The account is machine
state and a running client re-reads it: a switch held for eight seconds killed
two subagents in an unrelated session, which authenticated as the incoming
account and died on its limits. `claude_account switch` refuses while other
sessions are running and names them; `--force` overrides. A session that picked
up the wrong account mid-flight has to be restarted — reverting the switch does
not reach a credential it has already cached.

**Refresh tokens rotate.** They last about a month, and a session refreshing its
own tokens invalidates the copy you stored. The supervisor re-captures the
active account every tick, and a switch captures the outgoing account before
swapping away. A switch onto an expired credential is refused rather than
attempted: it produces a session sitting at a login prompt, which looks like a
successful relaunch until someone checks. Recovering a stale account needs a
real `/login` followed by `claude_account capture`.

### The meter is account-scoped too

Burn is attributed to the account that was live when it was spent, from the
switch log — summing the whole trailing window bills a freshly-switched account
for its predecessor's usage. And the window ceiling is a property of the plan,
so each account learns its own from the server's published percentage: burn
divided by percentage, taken live rather than by waiting to hit a limit. Each
server reading calibrates at most once, since burn grows between readings while
the percentage stands still.

## Testing

`install.sh` runs a self-test covering: the real death record, the quoted-429
false-positive control, usage-death→resume, context-wind-down→pickup, the no-model
rule, and slug resolution. `claude_relaunch_supervisor --dry-run` prints decisions
without launching, moving, or spending a probe.

`test_accounts.py` covers multi-account rotation — pool scoping, credential
expiry, the disruption rule, burn attribution across a switch, and the
per-account ceiling. It touches no network, no Keychain and no real account.

```bash
/usr/bin/python3 relaunch/test_accounts.py
```
