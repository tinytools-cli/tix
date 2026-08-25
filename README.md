# tix

A minimal ticket tracker built for agents, not humans-with-a-web-browser-first. CLI-native
(the primary interface a human or an LLM agent uses), SQLite-backed, with an optional local
web UI for people who want a dashboard.

Why not Jira/Linear/GitHub Issues for agent work: those are built around a web UI with an API
bolted on. An agent shelling out to a CLI is cheaper and faster than round-tripping a REST API,
and `tix --help` is discoverable in-context the same way any other CLI is — no separate docs
site an agent has to have been trained on or go fetch.

See [CHANGELOG.md](CHANGELOG.md) for what's new in each release.

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

With that set, `--by`/`--author` default to it, so you don't have to pass `--by alice` on every
`add`/`update`/`note add`.

### `tix inbox` — what changed since you last looked

```
tix inbox            # defaults to $TIX_AGENT
tix inbox alice       # or name someone explicitly
```

Shows two kinds of things, both authored by someone other than you, since the last time you ran
`tix inbox` (reading it marks it seen — it doesn't delete anything, the ticket's own history is
untouched):

- **Field changes and notes on tickets assigned to you.**
- **Any note anywhere that `@mentions` you by name** — `tix note add NS-3 "@alice can you take a
  look at this"` — even on a ticket assigned to someone else. This is how you flag someone
  without reassigning the ticket to them.

Mentions only work in **notes**, not ticket descriptions — descriptions are a static current-state
summary, a mention there would just go stale. The match is a whole-word `@name`, case-insensitive,
with a word boundary on both sides, so `@alice` matches but doesn't false-fire on `@alicebot` or
vice versa. A note that mentions yourself doesn't add itself to your own inbox.

Every other `tix` command prints one line to stderr — `N ticket(s) changed — tix inbox` — when
your inbox is non-empty, silent otherwise. That's the whole notification mechanism: no polling,
no push, no daemon. It just rides on commands you're already running.

## Full command reference

Run `tix --help` or `tix <command> --help` for the authoritative, always-current spec — it's
generated straight from the code, not a doc that can drift out of sync. [docs/COMMANDS.md](docs/COMMANDS.md)
is a browsable version of the same thing, useful if you want to read it before installing
anything.

## Wiring this into your agents

Installing tix gives your agents a CLI. Getting them to actually *use* it consistently — file
a ticket before starting work, leave a real note before closing one — takes putting that
expectation in front of them, not just having the tool available. [docs/AGENT_SETUP.md](docs/AGENT_SETUP.md)
is a paste-ready instructions block for your agents' own system prompt/CLAUDE.md/AGENTS.md.

Instructions are advice — an agent can still just not follow them. `tix guard check` plus a
harness adapter turns that into a hard gate: a turn that did real work with zero tix activity
doesn't get to end quietly. See [docs/ENFORCEMENT.md](docs/ENFORCEMENT.md).

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
