# Changelog

All notable changes to tix are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.2.11] - 2026-08-27

### Changed
- The update-available notice used to just print the same passive line every
  ~24h, forever, until someone upgraded. It now: (1) explicitly tells the
  agent to tell the human and ask if they want it upgraded, (2) fires once
  when a new version first appears, (3) reminds once more if ~2 days pass
  with no upgrade, then (4) goes quiet on that version for good. A genuinely
  newer release resets the cycle; upgrading clears it outright.

## [0.2.10] - 2026-08-27

### Changed
- The `--model` nudge added in 0.2.9 was scoped to `haiku` only, on the assumption
  that an expensive session doing cheap work was the only direction worth
  flagging. Guillermo's correction: it's for any model -- an under-powered
  session grinding through work that should have escalated is the same problem
  in the other direction, and `--model` is a dispatch instruction either way,
  not documentation. `tix add`/`show`/`update --status in_progress` now nudge
  for whatever model a ticket declares, naming it in the message.

## [0.2.9] - 2026-08-27

### Added
- A soft nudge on `--model haiku` tickets: `tix add`, `tix show`, and `tix update
  --status in_progress` now print a one-line stderr reminder to actually spawn a
  haiku sub-agent for the work rather than doing it in a more expensive session.
  `--model` records intent, not what actually ran the work, and tix has no way to
  detect the calling session's real model (no env var exposes it) -- so this can't
  catch a genuine mismatch, only remind at every point an agent touches a
  haiku-tagged ticket, including right before picking it up. Never blocks, same
  tone as every other tix nudge.

## [0.2.8] - 2026-08-27

### Changed
- The GitHub org moved: `tix-cli` -> `tinytools-cli` (Guillermo's call -- the org is
  becoming a small family of standalone tools, not just tix). Updated the
  update-check URL, README, and the enforcement adapter's doc pointer to match --
  the update-check nudge would have silently stopped working against the old,
  now-redirected org otherwise. Repo URLs under the old org continue to redirect.

## [0.2.7] - 2026-08-27

### Added
- `tix check <key>` — warns if a `--type story` ticket has no real Acceptance
  Criteria (missing section, or the unfilled `[context]`/`[action]`/`[outcome]`
  template left in place). Never blocks; a warning signal only. No-ops for any
  other ticket type.
- The `story` description template is now a real scrum-style template: "As a
  [role], I want [goal], so that [benefit]" plus a Given/When/Then Acceptance
  Criteria section, with inline guidance on why each part matters rather than
  just brackets to fill in.

## [0.2.6] - 2026-08-27

### Added
- Web dashboard: `?ticket=<key>` in the URL opens that ticket's modal on load --
  a deep link for other tools to point directly at a ticket instead of just
  linking to the dashboard's root.

## [0.2.5] - 2026-08-26

### Added
- tix now checks once a day whether a newer release is available and prints a
  one-line nudge (with a link to the release) if so -- same pattern as the
  existing "N ticket(s) changed" inbox notification. Silent when up to date,
  offline, or running from an uninstalled dev copy.

## [0.2.4] - 2026-08-26

### Added
- `tix search` now shows a preview of the description under each match, since the
  match may be in the description or a note rather than the title -- previously an
  agent had to open every candidate with `tix show` to tell if it was relevant.
  `--desc` help text and `docs/AGENT_SETUP.md` now nudge toward leading a
  description with a one-line purpose (like a commit message subject) so the
  preview is actually useful.

## [0.2.3] - 2026-08-25

### Reverted
- **The v0.3.0 "Telefleet" rename is reverted.** That release renamed the package/repo/CLI
  from `tix` to `telefleet`. Turned out to be a miscommunication: tix stays tix, standalone,
  as it was before. Telefleet is a separate, larger name for something tix will be *part of*
  later, not a replacement for it. v0.3.0 briefly existed as a real published release (repo
  rename, PyPI-style package rename, GitHub Release) — rather than rewrite that history, this
  is a forward-fixing revert back to the 0.2.2 state. If you installed v0.3.0, reinstall from
  this version.

## [0.2.2] - 2026-08-25

### Changed
- `tix guard check`'s block reason now tells you to pick the ticket type deliberately
  instead of just nudging you to file something. It previously enforced *that* you
  file, never *what* — which meant real bugs were landing as notes on task tickets,
  readable only to someone who already knew to open that ticket. The message now
  spells out `--type bug` (something was broken, even if fixed in the same breath)
  vs `task` (a unit of work) vs `story`/`epic` (larger scope).

## [0.2.1] - 2026-08-25

### Fixed
- `tix guard check --conf <role-conf>` now **extends** the built-in default work
  patterns instead of silently replacing them. A role-conf naturally reads as "the
  extra things my job does that the defaults miss" — replacing meant a role with a
  conf quietly stopped being checked for file edits, `rm`, `git commit`, etc. Found
  by an external adopter trying to migrate onto `guard check`. Added `--conf-only`
  (and `TIX_GUARD_CONF_ONLY=1` for the Claude Code adapter) to restore the old
  full-replace behavior for a role that wants to declare its complete rule set.
  `guard check` now also announces which patterns are active on stderr, so this
  isn't silent either way.

## [0.2.0] - 2026-08-25

### Added
- `tix guard check` — a harness-agnostic enforcement primitive that checks whether
  recent agent activity in a session transcript matches "did real work" patterns,
  with a role-conf system for custom pattern sets. Ships with a Claude Code Stop-hook
  adapter (`adapters/claude-code-stop-hook.sh`).
- Web dashboard: tree view for epics with an "unresolved" default filter (external
  contribution, #1).
- Web dashboard: stat cards are clickable and filter the ticket list by status.
- Web dashboard: assignee filter dropdown; clicking a leaderboard name filters by
  that person.
- Web dashboard: tix logo as favicon and inline header icon.
- `tix note add` (CLI and web) now requires an author — a note with no author is
  unreadable history. The web UI asks once per browser and remembers it.
- Web dashboard: type-aware description placeholders in the ticket modal, plus a
  `/` trigger that opens a menu to insert full template snippets per ticket type
  (bug/story/task/epic/support).
- Web dashboard: `@` autocomplete when writing a note, sourced from known assignees.

### Changed
- Web dashboard: epics get a small purple dot, bugs get a bug icon, the `key`
  column is renamed to `#`, and tickets nested under an epic are indented further.
- Web dashboard leaderboard: shows open/done ticket counts all-time per assignee;
  dropped the rolling 7-day column.

### Docs
- Documented `tix inbox` and `@mention` notifications, plus a full command
  reference (`docs/COMMANDS.md`).
- Added `docs/AGENT_SETUP.md` — a paste-ready instructions block for wiring tix
  into an agent's system context.

## [0.1.0] - 2026-08-24

Initial release: minimal, agent-native ticket tracker. CLI-first (`tix`), SQLite-backed,
with an optional web dashboard (`tix-web`).
