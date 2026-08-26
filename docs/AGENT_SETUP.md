# Wiring tix into your agents

Installing tix gets your agents a CLI. It doesn't get them a *habit* — an agent that knows
`tix add` exists will still just... not use it consistently unless something in its own
instructions tells it to. This is a paste-ready block for that: drop it into whatever your
agents actually read at the start of a session (`CLAUDE.md`, `AGENTS.md`, a system prompt,
whatever your setup calls it). Edit the bracketed bits, drop what doesn't apply.

It's written the way it is on purpose — as instructions *to* an agent, not documentation
*about* tix. An agent reads it as a set of rules to follow, not background to summarize.

---

```markdown
## Ticket discipline (tix)

This project tracks work in `tix`, a CLI ticket tracker (`tix --help` for the full command
reference). Follow this, don't just know it exists:

- **File a ticket before starting any real unit of work** — not every command, not reads or
  quick lookups, but anything with a start and a finish someone might reasonably ask about
  later: `tix add "<what you're doing>" --project <name> --model <tier> --status in_progress`.
  **Lead the description with the one-line purpose**, like a commit message subject —
  `tix search` shows a preview of the description under each match, so a vague opener means
  the next agent can't tell if a result is relevant without opening it.
- **Finishing means leaving a note, not flipping a status.** Before `tix update <key> --status
  done`, always `tix note add <key> "..."` covering, in order: (1) what you actually did, (2)
  where the output is — file paths, commit hashes, service names, (3) what you found — the
  finding, the constraint, the dead end, this is the part most worth writing and most often
  skipped, (4) what you did NOT do and why, (5) any open questions you couldn't decide alone.
  Write it for someone with none of your context, because that's exactly who reads it —
  including you, next session, with no memory of this one. Say plainly if something failed or
  is unverified; a note that reads as success when the work was partial is worse than no note.
- **A ticket is history, not a current-state doc.** It records a decision and what it cost —
  don't edit a closed ticket to keep it "current" as reality moves on. What's true *right now*
  belongs in a real doc; the ticket links to it, never the reverse.
- [If you run agents on more than one model tier] **`--model` records a real decision, made
  before starting, not paperwork after.** Match the model to the task — cheap for
  triage/extraction/classification, mid-tier for ordinary implementation, top-tier for design
  or consequential judgement — and use what you declared.
- [If more than one agent shares this tix database] **Set `$TIX_AGENT` to your own name** in
  your shell/session startup. Then `tix inbox` shows you what changed on tickets assigned to
  you, or where someone `@mentioned` you in a note, since you last checked. Every other `tix`
  command prints a one-line nudge when it's non-empty — check it when you see that.
```

---

## Why this is instructions, not a description

`docs/COMMANDS.md` tells an agent (or a person) *what tix can do*. This tells an agent *what
to actually do, unprompted, every time*. Those are different jobs — a tool's command reference
doesn't create a habit, and an agent that has to be reminded per-task isn't any better off than
one with no tracker at all. Put this where your agents' instructions already live, not in a
`docs/` folder they'd have to think to go read.
