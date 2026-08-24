# tix

A minimal ticket tracker built for agents, not humans-with-a-web-browser-first. CLI-native
(the primary interface a human or an LLM agent uses), SQLite-backed, with an optional local
web UI for people who want a dashboard.

Why not Jira/Linear/GitHub Issues for agent work: those are built around a web UI with an API
bolted on. An agent shelling out to a CLI is cheaper and faster than round-tripping a REST API,
and `tix --help` is discoverable in-context the same way any other CLI is — no separate docs
site an agent has to have been trained on or go fetch.

## Install

```
pip install .
```

This gives you two commands: `tix` (the CLI) and `tix-web` (the optional dashboard, on
`http://127.0.0.1:8791` by default).

For local development, install it editable instead so code changes take effect immediately:

```
pip install -e .
```

Data lives in `~/.tix/tix.db` (SQLite) by default. Override with `TIX_DB_PATH=/some/path.db`
if you want it somewhere else, or colocated with a specific project's own data.

## Quickstart

Register a project and a ticket:

```
tix project add "My Project" --folder ~/projects/my-project
tix add "Fix the login bug" --project "My Project" --model sonnet
```

`--model` is required on every ticket — see "Why `--model` is required" below.

List, inspect, update:

```
tix list
tix show MY-1
tix update MY-1 --status in_progress
tix note add MY-1 "Found the root cause, it's a stale cache key."
tix update MY-1 --status done
```

Search and activity feed:

```
tix search "login"
tix activity --limit 20
```

## Multi-agent / multi-user setup

If several agents or people share one `tix.db`, set `TIX_AGENT` in each shell/session to your
own name:

```
export TIX_AGENT=alice
```

With that set:
- `--by`/`--author` default to it, so you don't have to pass `--by alice` on every command.
- `tix inbox` shows you what changed on your tickets (or where you were `@mentioned` in a note)
  since you last checked — reading it marks it seen, doesn't delete anything.
- Every other command prints a one-line nudge to stderr when your inbox is non-empty, so you
  find out without having to remember to check.

## Full command reference

Run `tix --help` or `tix <command> --help` — it's the actual spec, kept in sync with the code,
not a separate doc that drifts. Commands: `add`, `list`, `show`, `update`, `rm`, `search`,
`activity`, `inbox`, `note add`/`note list`, `project add`/`list`/`rename`, `projects`,
`team add`/`list`, `teams`.

## Design notes

**A ticket is history, not a current-state doc.** It records a decision and what it cost — why
X was set to Y, on what date, what dead ends came first. Don't edit a closed ticket to keep it
"current" as reality moves on — that destroys the record. What's true *right now* belongs in a
doc; the ticket links to it, never the reverse.

**Finishing means leaving a note, not flipping a status.** `tix note add <key> "..."` before
`tix update <key> --status done`, covering: what you actually did, where the output is, what
you found (the highest-value part, most often skipped), what you did *not* do and why, and any
open questions. Write it for someone with none of your context — because that's exactly who
reads it, including you next week.

**Why `--model` is required.** If agents of varying cost/capability are doing the work, deciding
which model fits a given ticket *before* starting is a real judgement call worth recording, not
paperwork after the fact. `haiku`-tier = triage/classification/extraction. `sonnet`-tier =
ordinary implementation. `opus`-tier = design, hard debugging, consequential judgement. Doesn't
apply if you're not running multiple model tiers — set it to whatever's true for you.

**Scale roughly:** project = multi-month or permanent initiative. epic = weeks to a month.
story/task/bug/support = an hour to a couple of days. If something will take more than a couple
of days, it's not a task — make it an epic and break it into tasks under it (`--parent`).

## License

MIT — see [LICENSE](LICENSE).
