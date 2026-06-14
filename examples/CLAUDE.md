# Example root `CLAUDE.md` — the Context Cascade pattern

> This is a **template**. Copy it to your repo root as `CLAUDE.md`, trim it to
> your project's real global rules, and add a per-area `CLAUDE.md` to each major
> code directory.
>
> Claude Code loads every `CLAUDE.md` along the path from the file being edited
> up to the repo root, so rules live next to the code they govern. Keep the root
> file **short** — global rules plus a pointer table — and push area-specific
> gotchas down to the leaves. A root file that grows to hundreds of lines is the
> anti-pattern this avoids.

## Role & quality bar

State your project's non-negotiables here, concretely. The rules an engineer
(human or agent) must not violate — not a style guide. Examples:

- Read before you write. Never edit a file you haven't read in full.
- No mechanical transforms (sed/regex) on production code — every line by hand.
- Trace at least the happy path, one error path, and one edge case after a change.

## Context cascade — read the local `CLAUDE.md` for the area you're editing

| Path | Covers |
|---|---|
| `api/CLAUDE.md` | API contract; keep serializer and client types in sync |
| `worker/CLAUDE.md` | background jobs: idempotency, retries, no work in a loop |
| `web/CLAUDE.md` | frontend conventions; build & test commands |

Replace these rows with your real areas. Each leaf `CLAUDE.md` should:

- lead with its **critical gotchas** (the things that have broken before),
- stay short (a couple hundred lines at most), and
- link out to deeper specs for detail rather than inlining them.

## Where to find things

- **Architecture / specs:** point to your docs directory.
- **Process / how work is dispatched:** point to your process doc.
- **Per-area rules:** the table above — local rules supersede these global ones.
