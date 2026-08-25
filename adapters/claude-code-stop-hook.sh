#!/usr/bin/env bash
# Claude Code Stop-hook adapter for `tix guard check`.
#
# This is deliberately thin -- all the actual logic (checkpointing, role-conf
# matching, deciding block vs allow) lives in `tix guard check` itself, which
# knows nothing about Claude Code specifically. This script's only job is
# translating Claude Code's hook JSON contract to and from that command.
# Writing an adapter for a different harness means replacing this file, not
# touching tix at all -- see docs/ENFORCEMENT.md in the repo (github.com/tix-cli/telefleet).
#
# INSTALL: wire this into a Stop hook in your settings.json, e.g.:
#   { "hooks": { "Stop": [ { "hooks": [
#       { "type": "command", "command": "/path/to/claude-code-stop-hook.sh", "timeout": 15 }
#   ] } ] } }
#
# CONFIGURE (optional): set TIX_GUARD_CONF to a role-conf file path (one regex
# per line, '#' comments allowed) to EXTEND the generic default patterns
# `tix guard check` ships with -- useful if "real work" looks different for
# your agent too (e.g. sending email/driving a browser, not just editing
# files). Set TIX_GUARD_CONF_ONLY=1 as well if the conf should fully REPLACE
# the defaults instead -- only do this if you're sure your conf covers file
# edits too, since the defaults are what catch those.
set -uo pipefail
payload="$(cat 2>/dev/null || true)"
[ -n "$payload" ] || exit 0

jqp() {
    printf '%s' "$payload" | python3 -c "
import json, sys
try:
    v = json.load(sys.stdin).get('$1')
    print('' if v is None else v)
except Exception:
    print('')
" 2>/dev/null
}

# Anti-loop: Claude Code sets this true when this Stop hook already blocked
# once for this same stop attempt. Always allow then, or the hook re-blocks
# its own block and the agent can never finish the turn.
[ "$(jqp stop_hook_active)" = "True" ] && exit 0

transcript="$(jqp transcript_path)"
session="$(jqp session_id)"
[ -n "$transcript" ] || exit 0

conf_args=()
[ -n "${TIX_GUARD_CONF:-}" ] && conf_args=(--conf "$TIX_GUARD_CONF")
[ -n "${TIX_GUARD_CONF_ONLY:-}" ] && conf_args+=(--conf-only)

result="$(tix guard check --transcript "$transcript" --format claude-code --session "${session:-unknown}" "${conf_args[@]}" 2>/dev/null)"
[ -n "$result" ] || exit 0

decision="$(printf '%s' "$result" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('decision', 'allow'))
except Exception:
    print('allow')
" 2>/dev/null)"

[ "$decision" = "block" ] && printf '%s\n' "$result"
exit 0
