# Command reference

This is a browsable copy of what `tix --help` / `tix <command> --help` prints — generated
from the actual CLI, not written by hand separately, so it's worth re-checking against
`--help` if you suspect drift after an update. `ASSIGNEE`/`TID` etc. in a `Usage:` line are
positional arguments; everything else is a flag.

## `tix add TITLE`

Add a new ticket.

| Flag | Notes |
|---|---|
| `--type [epic\|story\|task\|bug\|support]` | epic = weeks-to-a-month of work. story/task/bug/support = hours to a couple of days. |
| `--desc TEXT` | |
| `--status [todo\|in_progress\|blocked\|done]` | |
| `--priority [low\|med\|high\|urgent]` | |
| `--parent TEXT` | parent ticket key or id (must be an epic) |
| `--blocked-by TEXT` | ticket key or id this is stuck behind — a reference only, not enforced |
| `--project TEXT` | **required** — project name or key, must already be registered (`tix project add`) |
| `--team TEXT` | team name — must already be registered (`tix team add`) |
| `--assignee TEXT` | |
| `--model TEXT` | **required** — haiku (triage/extraction) / sonnet (implementation) / opus (design/hard debugging), or a full model id. Decide before starting, use it for the task. |
| `--tags TEXT` | |
| `--created-at TEXT` | backdate the ticket's created/updated time (ISO date or datetime, e.g. `2026-08-15`) — for importing history, not normal use |
| `--by TEXT` | who's creating this — defaults to `$TIX_AGENT` if set. Used to skip your own entries in your inbox, nothing else. |

## `tix list`

List tickets, optionally filtered.

Flags: `--status`, `--type`, `--priority`, `--parent`, `--blocked-by`, `--project`, `--team`,
`--assignee`, `--model` — same choices as `add`, all optional, combine as an AND filter.

## `tix show TID`

Show full detail for one ticket (by ticket key or id), including its notes.

## `tix update TID`

Update fields on a ticket (by ticket key or id).

Same flags as `add` (`--title`, `--desc`, `--status`, `--priority`, `--type`, `--parent`,
`--project`, `--team`, `--assignee`, `--model`, `--tags`, `--by`), plus:

| Flag | Notes |
|---|---|
| `--blocked-by TEXT` | ticket key or id this is stuck behind. Pass `""` to clear. |

## `tix rm TID`

Delete a ticket (by ticket key or id).

## `tix search TEXT`

Full-text search across title, description, tags, project, team, assignee, key, and notes.

## `tix activity`

Recent history across all tickets — new tickets and notes, newest first. Filters combine like
a `WHERE` clause, same as `list`: `tix activity --project tix --status in_progress`.

Flags: `--limit INTEGER` (how many entries to show), plus `--project`, `--team`, `--status`,
`--type`, `--priority`, `--assignee`, `--model`.

## `tix inbox [ASSIGNEE]`

What changed on your tickets since you last checked — field updates and notes on tickets
assigned to you, plus any note anywhere that `@mentions` you by name (e.g. `"@ben check
this"`), all authored by someone else. Reading this marks it seen (doesn't delete anything;
the ticket's own history is unaffected).

`ASSIGNEE` defaults to `$TIX_AGENT` if omitted. Any other `tix` command prints a one-line
nudge to stderr when your inbox is non-empty (set `$TIX_AGENT` for that to work). See the
README's "Multi-agent / multi-user setup" section for the full mechanics.

## `tix note add TID TEXT`

Add a note. This is how you FINISH a ticket — a status flip alone tells the next reader
nothing. Before `tix update <KEY> --status done`, always `tix note add <KEY> "..."` covering,
in order:

1. What you actually did — not just what the ticket asked for.
2. Where the output is — file paths, commit hashes, ticket keys, service names. Absolute paths.
3. What you found — the finding, the constraint, the dead end. Highest-value part, most-skipped.
4. What you did NOT do — scope you left, and why.
5. Open questions for whoever owns this — anything you couldn't decide alone.

Write it for someone with none of your context — that's exactly who reads it, including you
next week with the session gone. Say plainly if something failed, was skipped, or is
unverified — a note that reads as success when the work was partial is worse than no note,
because it's trusted.

| Flag | Notes |
|---|---|
| `--author TEXT` | defaults to `$TIX_AGENT` if set |
| `--created-at TEXT` | backdate the note's timestamp (ISO date or datetime, e.g. `2026-08-15`) — for importing history, not normal use |

## `tix note list TID`

List notes on a ticket.

## `tix project add NAME`

| Flag | Notes |
|---|---|
| `--key TEXT` | 2-letter code for ticket numbers, e.g. `NS`. Auto-derived if omitted. |
| `--folder TEXT` | **required** — absolute path where this project's context/files/downloads live. Created if missing. Not just for codebases — every project gets one. |

## `tix project list` / `tix projects`

List registered projects. `tix projects` is a shortcut for `tix project list`.

## `tix project rename IDENTIFIER NEW_NAME`

Rename a project's display name (by its current key or name). The key never changes — ticket
ids like `NS-6` stay valid everywhere they're already referenced.

## `tix team add NAME` / `tix team list` / `tix teams`

Register and list teams. `tix teams` is a shortcut for `tix team list`.
