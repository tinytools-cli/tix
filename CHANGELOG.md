# Changelog

All notable changes to tix are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
