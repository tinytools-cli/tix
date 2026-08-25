# Changelog

All notable changes to Telefleet (formerly `tix`) are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.3.0] - 2026-08-25

### Changed
- **Renamed the project to Telefleet.** Cosmetic, not breaking: the package installs as
  `telefleet`, and both `telefleet`/`tix` (CLI) and `telefleet-web`/`tix-web` (dashboard)
  commands work identically going forward. No change to the DB path, env var names
  (`TIX_AGENT`, `TIX_DB_PATH`, `TIX_GUARD_CONF`, etc.), or the ticket-key prefix — those
  are internal plumbing and existing data references, not branding, and changing them
  would break every current install and cross-reference for no real benefit.
- Web dashboard: new Telefleet logo and branding, tagline "Agents. Sessions. Tickets.
  Connected." in the header.
- `tix guard check`'s activity detection now also recognizes `telefleet add`/`update`/
  `note`, not just `tix ...`.

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
