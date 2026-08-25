# Enforcement: from convention to a hard gate

[docs/AGENT_SETUP.md](AGENT_SETUP.md) gets an agent *told* to use tix. This gets it *unable to
skip it* — a turn that did real work with zero tix activity doesn't get to end quietly. Advice
is what you have until you can afford enforcement; this is the enforcement.

## Why this is split into two pieces

Every agent harness is different — some let you hook the end of a turn, some don't, and the
ones that do all speak a different contract. There's no single script that works everywhere.
So this splits into:

- **`tix guard check`** — the actual decision logic. Harness-agnostic: it takes a transcript
  (or plain text), figures out whether real work happened without tix activity since the last
  check, and prints `{"decision": "allow"|"block", "reason": ...}`. It has no idea what's
  calling it or what happens next.
- **A harness adapter** — a few lines translating your harness's own hook/callback contract to
  and from `guard check`. [adapters/claude-code-stop-hook.sh](../adapters/claude-code-stop-hook.sh)
  is the one shipped here, as a worked example.

Bringing tix to a new harness means writing a new adapter, not touching `guard check` at all.

## Using `tix guard check` directly

```
tix guard check --transcript /path/to/transcript.jsonl --session my-session-id
```

Or, for a harness with no Claude-Code-shaped transcript, feed it plain text instead — one
action per line, however your harness logs what just happened:

```
echo "git commit -m fix" | tix guard check --format lines --session my-session-id
```

Both print the same JSON. `--session` is only used to remember a checkpoint (under
`~/.tix/guard-checkpoints/`) so the same already-reviewed work isn't flagged again — pass
`--checkpoint /explicit/path` instead if you'd rather manage that yourself. See
`tix guard check --help` or [docs/COMMANDS.md](COMMANDS.md) for every flag.

## What counts as "real work"

By default, a generic set of patterns: `git commit`/`push`, `systemctl`, `docker run`/`build`,
`apt install`, `rm`/`mv`/`chmod`, plus (only for `--format claude-code`) Edit/Write tool calls.
That's a reasonable default for an agent that edits files and runs shell commands — and a
**wrong** one for an agent whose real work is sending email or driving a browser, which is
exactly the case [examples/role-confs/assistant.conf](../examples/role-confs/assistant.conf)
exists for.

Point `--conf` at your own file — one regex per line, `#` for comments — and it **extends** the
defaults for that role: your patterns plus the generic set, including the Edit/Write signal.
Write a conf as "the extra things my job does that the defaults miss," not as a full
replacement — a role-conf that doesn't mention file edits at all still gets them covered by
the defaults. Pass `--conf-only` if a role genuinely wants to declare its complete rule set
instead (the old, non-default behavior) — `guard check` prints which mode is active and how
many patterns to stderr either way, so it's never silent about it. Two examples are included:

- [examples/role-confs/developer.conf](../examples/role-confs/developer.conf) — close to the
  built-in defaults, a starting point for a code/infra agent.
- [examples/role-confs/assistant.conf](../examples/role-confs/assistant.conf) — illustrates a
  role with no filesystem footprint at all. The patterns in it are illustrative, not universal:
  they need to match whatever text *your* transcript actually records for those actions.

## Installing the Claude Code adapter

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "/path/to/adapters/claude-code-stop-hook.sh", "timeout": 15 }
      ] }
    ]
  }
}
```

Put that in `.claude/settings.json` (project-scoped) or `~/.claude/settings.json` (every
session). Optionally set `TIX_GUARD_CONF=/path/to/a/role-conf.conf` in the environment the
hook runs in to extend the generic defaults with role-specific patterns, and
`TIX_GUARD_CONF_ONLY=1` alongside it if that conf should fully replace the defaults instead.

## Writing an adapter for a different harness

The contract an adapter needs to satisfy is small:

1. Get your harness to run something after a turn ends (whatever hook/callback/plugin
   mechanism it offers).
2. Feed `tix guard check` either a transcript your harness produces (write your own `--format`
   parser if it's not Claude Code's, or just build a `lines`-format command log) and get back
   its JSON.
3. If `decision` is `"block"`, do whatever your harness does to stop the turn from ending
   cleanly and surface `reason` to the agent. If your harness has no such mechanism at all,
   there's nothing to enforce — fall back to [AGENT_SETUP.md](AGENT_SETUP.md)'s instructions-only
   version, which is the honest ceiling for a harness without hooks.
4. Handle your own harness's anti-loop concern, if it has an equivalent to Claude Code's
   `stop_hook_active` — a guard that can block the same attempt forever is worse than no guard.

`guard check` itself always exits 0 and always prints valid JSON (fails open internally on
anything unexpected) specifically so an adapter can be this thin without its own error handling.

## What this doesn't do

It won't catch a determined agent that decides to ignore a block and route around it, and it
won't tell you *when* an agent is repeatedly hitting blocks without ever filing — that's a
pattern worth surfacing to a human, not just re-litigating with the agent every time, and it
isn't built yet.
