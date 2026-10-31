#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

import click

from . import db as tixdb

tixdb.init_db()

UPDATE_CACHE = Path.home() / ".tix" / "update-check.json"


def _version_tuple(v):
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        return (0,)


def _check_for_update():
    """Return (latest, installed) when it's time to NOTIFY about a pending update,
    None otherwise. Two separate throttles, easy to conflate:

    1. THE NETWORK CHECK -- at most once every 24h (cache["last_checked"]),
       purely to avoid hammering GitHub's API. Independent of whether we've
       already told anyone about the result.
    2. THE NOTIFICATION -- fires once when a new version first appears, once
       more ~2 days later if still not upgraded, then goes quiet on that
       version forever (tell the human, ask if they
       want it, remind once, then stop nagging). A genuinely newer release
       resets the two-strike count; upgrading clears it outright.

    Never raises: a broken update check must never break the command someone's
    actually trying to run."""
    try:
        installed = pkg_version("tix")
    except PackageNotFoundError:
        return None

    now = datetime.now(timezone.utc)
    cache = {}
    if UPDATE_CACHE.exists():
        try:
            cache = json.loads(UPDATE_CACHE.read_text())
        except Exception:
            cache = {}

    latest = cache.get("latest")
    last_checked = cache.get("last_checked")
    stale = True
    if last_checked:
        try:
            stale = now - datetime.fromisoformat(last_checked) >= timedelta(hours=24)
        except Exception:
            stale = True

    if stale:
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/tinytools-cli/tix/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                fetched = json.loads(resp.read()).get("tag_name", "").lstrip("v")
            if fetched:
                latest = fetched
                cache["last_checked"] = now.isoformat()
                cache["latest"] = latest
        except Exception:
            pass  # keep whatever `latest` the cache already had, if any

    notify = cache.get("notify") or {}
    fire = False
    if not latest or _version_tuple(latest) <= _version_tuple(installed):
        # up to date (or the human already upgraded) -- clear so the next
        # real release starts its own fresh two-strike cycle
        if notify:
            cache["notify"] = {}
    elif notify.get("version") != latest:
        # first time this specific version has been seen
        cache["notify"] = {"version": latest, "first_notified_at": now.isoformat(), "reminders_sent": 1}
        fire = True
    elif notify.get("reminders_sent", 0) < 2:
        try:
            due = now - datetime.fromisoformat(notify["first_notified_at"]) >= timedelta(days=2)
        except Exception:
            due = False
        if due:
            cache["notify"] = {**notify, "reminders_sent": 2}
            fire = True
    # else: already reminded twice about this version -- stay quiet

    try:
        UPDATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CACHE.write_text(json.dumps(cache))
    except Exception:
        pass

    return (latest, installed) if fire else None


def _model_nudge(model):
    """Soft nudge only -- same tone as the inbox/update-available nudges.

    --model records intent, not what actually ran the work: nothing stops an agent
    from filing --model X and then doing the work itself in whatever session it
    already has open. tix has no way to detect what model is actually calling it
    (no env var exposes that), so this can't catch a real mismatch in either
    direction -- cheap ticket done in an expensive session, or an expensive
    ticket done on the cheap by a session that should have escalated. It can
    only remind, on every touch of the ticket, that the declared model is a
    dispatch instruction, not documentation -- covers every --model value, not
    just haiku."""
    if model:
        click.echo(f"[tix nudge] declared model: {model} -- if you're not already running as "
                    f"{model}, spawn a sub-agent on it for this rather than doing it in place.",
                    err=True)


INBOX_NUDGE_STATE = Path.home() / ".tix" / "inbox-nudge.json"
INBOX_NUDGE_EVERY = timedelta(minutes=5)


def _inbox_nudge_due(agent, n):
    """TI-102a: the 'N ticket(s) changed' line used to print on EVERY command. Now:
    TIX_INBOX_NUDGE=1 forces it every time (agents that rely on it), =0 silences it;
    otherwise it is shown only on an interactive terminal (stdout is a TTY), and then only
    when the count changed since last shown or 5 minutes have passed. Never raises."""
    mode = os.environ.get("TIX_INBOX_NUDGE", "")
    if mode == "1":
        return True
    if mode == "0" or not sys.stdout.isatty():
        return False
    now = datetime.now(timezone.utc)
    try:
        state = json.loads(INBOX_NUDGE_STATE.read_text())
    except Exception:
        state = {}
    last = state.get(agent) or {}
    try:
        recent = now - datetime.fromisoformat(last["at"]) < INBOX_NUDGE_EVERY
    except Exception:
        recent = False
    if recent and last.get("count") == n:
        return False
    state[agent] = {"count": n, "at": now.isoformat()}
    try:
        INBOX_NUDGE_STATE.parent.mkdir(parents=True, exist_ok=True)
        INBOX_NUDGE_STATE.write_text(json.dumps(state))
    except Exception:
        pass
    return True


def resolve_by(by):
    """--by defaults to $TIX_AGENT (the identity tix inbox also nudges) so agents whose
    shell exports it don't have to repeat themselves on every add/update."""
    return by if by is not None else os.environ.get("TIX_AGENT", "")


def parse_created_at(value):
    """Accept a date or datetime string and normalize to the same format db.now() uses."""
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise click.BadParameter(
            f"'{value}' is not a valid date/time — use ISO format, e.g. 2026-08-15 or 2026-08-15T09:30:00"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


DEFAULT_DISPLAY_TZ = "UTC"


def display_tz():
    """Timezone timestamps are DISPLAYED in (TI-102d). Storage stays UTC. Order: $TIX_TZ,
    then $TZ, then UTC. An unknown name falls back to the
    default rather than breaking the command. TIX_TZ=UTC shows the stored values as-is."""
    from zoneinfo import ZoneInfo
    for name in (os.environ.get("TIX_TZ"), os.environ.get("TZ"), DEFAULT_DISPLAY_TZ):
        if name:
            try:
                return ZoneInfo(name)
            except Exception:
                continue
    return timezone.utc


def fmt_ts(value):
    """Stored UTC ISO timestamp -> same ISO format in the display timezone (offset included,
    so it stays unambiguous and machine-parseable). Anything unparseable is returned as-is."""
    if not value or not isinstance(value, str):
        return value
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(display_tz()).isoformat(timespec="seconds")


def fmt_row(t):
    key = t.get("ticket_key") or f"#{t['id']}"
    parent = f" ^{t.get('parent_key') or t['parent_id']}" if t["parent_id"] else ""
    blocked = f" !{t.get('blocked_by_key') or t['blocked_by']}" if t.get("blocked_by") else ""
    if t.get("blocked_on"):
        blocked += f" ⏳{t['blocked_on']}"
    tags = f" [{t['tags']}]" if t["tags"] else ""
    project = f"{t['project']:<12} " if t.get("project") else f"{'':<12} "
    team = f"{t['team']:<11} " if t.get("team") else f"{'':<11} "
    model = f" ({t['model']})" if t.get("model") else ""
    assignee = f" @{t['assignee']}" if t.get("assignee") else ""
    shas = "".join(f" {lbl}:{t[col][:7]}" for lbl, col in (("stg", "staging_sha"), ("prod", "prod_sha")) if t.get(col))
    return f"{key:<8} {project}{team}{t['type']:<7} {t['status']:<11} {t['priority']:<5} {t['title']}{parent}{blocked}{assignee}{model}{tags}{shas}"


def fmt_snippet(desc, width=120):
    """A one-line preview of a ticket's description, for search results that would
    otherwise be title-only even though the match may be in the description or a
    note. Collapses whitespace so a multi-paragraph description doesn't break the
    one-line-per-result output."""
    text = " ".join((desc or "").split())
    if not text:
        return None
    return text[:width] + ("..." if len(text) > width else "")


def resolve_tid(identifier):
    tid = tixdb.resolve_ticket_id(identifier)
    if tid is None:
        click.echo(f"no such ticket '{identifier}'", err=True)
        raise SystemExit(1)
    return tid


def die_on_tix_error(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except tixdb.TixError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@click.group()
@click.pass_context
def cli(ctx):
    """tix — minimal ticket tracker for humans and agents.

    First time using a project or team? Register it first:

      tix project add "North Star" --key NS
      tix team add "Exco"

    Then reference either by name or key everywhere else.

    Scale, roughly  — get the ticket at the right
    altitude before you create it:

      project = multi-month or permanent initiative (e.g. North Star, tix itself)
      epic    = weeks to a month of work — the biggest thing that goes IN a project
      story/task/bug/support = an hour to a couple of days

    If something will take more than a couple of days, it's not a task — make it an epic
    and break it into tasks under it (--parent).

    Every ticket also requires --model. Recommended convention: choose
    the model to fit the task, to minimize cost AND maximize fit — decide BEFORE you start,
    don't inherit a default. This field is where that judgement gets declared, not paperwork
    after the fact.

      haiku  = triage, classification, extraction, checks against a clear rule
      sonnet = ordinary implementation, day-to-day work
      opus   = design, hard debugging, consequential judgement

    Recurring work is where an oversized default actually costs you: a one-off on the wrong
    model costs once, but a job that wakes every few hours is a standing bill, not a single
    charge. Cheap is not careless, though — where being wrong is expensive (deletion,
    credentials, anything outward-facing), pay for the better model.

    Once you set it, use that model for the task — the field records a commitment, not just
    a label after the fact. If a piece of work has parts that genuinely need different
    models by complexity, split it into separate tickets rather than picking one model for
    the whole thing.

    A ticket is history, not a current-state doc  It records a decision and
    what it cost — why X was set to Y, on what date, what dead ends came first. Don't edit a
    closed ticket to keep it "current" as reality moves on; that destroys the record and gives
    you no way to tell which of several edits is the live answer. What's true RIGHT NOW belongs
    in a doc (INFRASTRUCTURE.md, a project's own docs, whatever's canonical for that thing) —
    the ticket links to it, never the reverse. A later change to something already-closed is a
    new ticket, not a reopened or edited old one.
    """
    agent = os.environ.get("TIX_AGENT", "")
    if agent and ctx.invoked_subcommand != "inbox":
        n = tixdb.count_inbox(agent)
        if n and _inbox_nudge_due(agent, n):
            click.echo(f"{n} ticket(s) changed — tix inbox", err=True)

    update = _check_for_update()
    if update:
        latest, installed = update
        click.echo(f"tix v{latest} is available (you have v{installed}) -- tell your human and ask "
                    "if they want it upgraded: https://github.com/tinytools-cli/tix/releases", err=True)


@cli.command()
@click.argument("title")
@click.option("--type", "type_", default="task", type=click.Choice(tixdb.TYPES),
              help="epic = weeks-to-a-month of work. story/task/bug/support = hours to a couple of days.")
@click.option("--desc", default="", help="lead with the one-line purpose, like a commit message subject -- "
                                          "'tix search' shows the first ~120 characters of this as a preview, "
                                          "so a vague opener means an agent can't tell relevance without opening it.")
@click.option("--status", default="todo", type=click.Choice(tixdb.STATUSES))
@click.option("--priority", default="med", type=click.Choice(tixdb.PRIORITIES))
@click.option("--parent", "parent", default=None, help="parent ticket key or id (must be an epic)")
@click.option("--blocked-by", "blocked_by", default=None, help="ticket key or id this is stuck behind — a reference only, not enforced")
@click.option("--blocked-on", "blocked_on", default="", help="who/what this waits on: a person (alice) or a ticket key (NS-3). Structured, filterable via `tix list --blocked-on`.")
@click.option("--project", required=True, help="required — project name or key, must already be registered (tix project add)")
@click.option("--team", default="", help="team name — must already be registered (tix team add)")
@click.option("--assignee", default="")
@click.option("--model", required=True, help="required — haiku (triage/extraction) / sonnet (implementation) / opus (design/hard debugging), or a full model id. Decide before starting, use it for the task.")
@click.option("--tags", default="")
@click.option("--created-at", default=None, help="backdate the ticket's created/updated time (ISO date or datetime, e.g. 2026-08-15) — for importing history, not normal use")
@click.option("--by", default=None, help="who's creating this — defaults to $TIX_AGENT if set. Used to skip your own entries in your inbox, nothing else.")
def add(title, type_, desc, status, priority, parent, blocked_by, blocked_on, project, team, assignee, model, tags, created_at, by):
    """Add a new ticket."""
    parent_id = resolve_tid(parent) if parent else None
    blocked_by_id = resolve_tid(blocked_by) if blocked_by else None
    created_at = parse_created_at(created_at)
    by = resolve_by(by)
    tid = die_on_tix_error(tixdb.add_ticket, type_, title, desc, status, priority, parent_id, project, team, assignee, model, tags, blocked_by_id, created_at, by, blocked_on)
    t = tixdb.get_ticket(tid)
    click.echo(f"created {t['ticket_key'] or ('#' + str(tid))}")
    _model_nudge(t["model"])


@cli.command("list")
@click.option("--status", default=None, type=click.Choice(tixdb.STATUSES))
@click.option("--type", "type_", default=None, type=click.Choice(tixdb.TYPES))
@click.option("--priority", default=None, type=click.Choice(tixdb.PRIORITIES))
@click.option("--parent", default=None, help="parent ticket key or id")
@click.option("--blocked-by", "blocked_by", default=None, help="ticket key or id")
@click.option("--blocked-on", "blocked_on", default=None, help="person or ticket key the ticket waits on (case-insensitive), e.g. alice")
@click.option("--project", default=None)
@click.option("--team", default=None)
@click.option("--assignee", default=None)
@click.option("--model", default=None)
@click.option("--tree", is_flag=True, help="nest children under their parent (indented). A child whose parent is filtered out of this listing shows at top level.")
@click.option("--open", "open_", is_flag=True, help="only open tickets (everything but done and in_prod; on_staging counts as open, it is waiting for prod). Shortcut for the common view; ignored if --status is given.")
def list_cmd(status, type_, priority, parent, blocked_by, blocked_on, project, team, assignee, model, tree, open_):
    """List tickets, optionally filtered."""
    parent_id = resolve_tid(parent) if parent else None
    blocked_by_id = resolve_tid(blocked_by) if blocked_by else None
    rows = tixdb.list_tickets(status, type_, priority, parent_id, project, team, assignee, model, blocked_by_id, blocked_on)
    if open_ and not status:
        rows = [t for t in rows if t["status"] not in tixdb.CLOSED_STATUSES]
    if not rows:
        click.echo("no tickets")
        return
    if not tree:
        for t in rows:
            click.echo(fmt_row(t))
        return
    in_listing = {t["id"] for t in rows}
    children: dict = {}
    roots = []
    for t in rows:
        if t["parent_id"] in in_listing:
            children.setdefault(t["parent_id"], []).append(t)
        else:
            roots.append(t)

    def emit(t, depth):
        indent = "    " * (depth - 1) + "  └─ " if depth else ""
        click.echo(indent + fmt_row(t))
        for c in children.get(t["id"], []):
            emit(c, depth + 1)

    for r in roots:
        emit(r, 0)


@cli.group()
def project():
    """Register and list projects. A project must be registered before tickets can use it.

    A project is a multi-month or permanent initiative (a product line, a major buildout, tix itself) —
    not a single piece of work. If it'll be done in weeks, that's an epic inside a project,
    not a project of its own.
    """


@project.command("add")
@click.argument("name")
@click.option("--key", default=None, help="2-letter code for ticket numbers, e.g. NS. Auto-derived if omitted.")
@click.option("--folder", required=True,
              help="required — absolute path where this project's context/files/downloads live. "
                   "Created if missing. Not just for codebases — every project gets one. "
                   "Standard structure inside it is still being defined (IS-13); for now this "
                   "just reserves the location.")
def project_add(name, key, folder):
    row = die_on_tix_error(tixdb.add_project, name, folder, key)
    verb = {"created": "registered", "updated": "updated", "unchanged": "already registered"}[row.get("_state", "created")]
    click.echo(f"{verb} project '{row['name']}' — key {row['key']} (tickets will be {row['key']}-1, {row['key']}-2, ...), folder {row.get('folder', folder)}")


@project.command("list")
def project_list():
    rows = tixdb.list_projects_registry()
    if not rows:
        click.echo("no projects registered yet — tix project add \"name\" --folder /path")
        return
    for r in rows:
        folder = f" -> {r['folder']}" if r.get("folder") else ""
        if r.get("folder") and not os.path.isdir(r["folder"]):
            folder += "  (MISSING -- tix project set-folder)"
        click.echo(f"{r['key']:<4} {r['name']:<24} {r['ticket_count']} ticket(s){folder}")


@project.command("rename")
@click.argument("identifier")
@click.argument("new_name")
def project_rename(identifier, new_name):
    """Rename a project's display name (by its current key or name). The key never
    changes — ticket ids like AG-6 stay valid everywhere they're already referenced."""
    row = die_on_tix_error(tixdb.rename_project, identifier, new_name)
    click.echo(f"renamed {row['key']} to '{row['name']}' — key unchanged, existing tickets updated")


@project.command("set-folder")
@click.argument("identifier")
@click.argument("folder")
@click.option("--no-create", is_flag=True, help="don't create the folder if it doesn't exist")
def project_set_folder(identifier, folder, no_create):
    """Point a project at a new folder (by key or name) -- for when its directory moved or
    was renamed. Key and tickets are untouched. FOLDER must be an absolute path; it is
    created if missing unless --no-create."""
    row = die_on_tix_error(tixdb.set_project_folder, identifier, folder, not no_create)
    click.echo(f"project {row['key']} ('{row['name']}') folder: {row['old_folder'] or '(none)'} -> {row['folder']}")


@cli.command()
def projects():
    """Shortcut for `tix project list`."""
    project_list.callback()


@cli.group()
def team():
    """Register and list teams. A team must be registered before tickets can use it."""


@team.command("add")
@click.argument("name")
def team_add(name):
    row = die_on_tix_error(tixdb.add_team, name)
    click.echo(f"registered team '{row['name']}'")


@team.command("list")
def team_list():
    rows = tixdb.list_teams_registry()
    if not rows:
        click.echo("no teams registered yet — tix team add \"name\"")
        return
    for r in rows:
        click.echo(f"{r['name']:<16} {r['ticket_count']} ticket(s)")


@cli.command()
def teams():
    """Shortcut for `tix team list`."""
    team_list.callback()


@cli.command()
@click.argument("tid")
def show(tid):
    """Show full detail for one ticket (by ticket key or id), including its notes."""
    real_id = resolve_tid(tid)
    t = tixdb.get_ticket(real_id)
    for k, v in t.items():
        if k in ("created_at", "updated_at"):
            v = fmt_ts(v)
        click.echo(f"{k}: {v}")
    notes = tixdb.list_notes(real_id)
    if notes:
        click.echo("\nnotes:")
        for n in notes:
            who = f" ({n['author']})" if n["author"] else ""
            mark = _decision_tag(n) + " " if n.get("kind") == "decision" else ""
            click.echo(f"  [{fmt_ts(n['created_at'])}]{who} {mark}{n['text']}")
    _model_nudge(t["model"])


def _decision_tag(n):
    bits = ["DECISION"]
    if n.get("decided_by"):
        bits.append(f"by {n['decided_by']}")
    if n.get("channel"):
        bits.append(f"via {n['channel']}")
    return "[" + " ".join(bits) + "]"


@cli.group()
def note():
    """Append-only work-log entries on a ticket. Description stays the current summary;
    notes are the running history of what actually happened."""


# ignore_unknown_options: a note body that merely CONTAINS or STARTS with "--flag" text (quoted
# CLI options, say) must be taken as the positional TEXT, not rejected as an unknown option
# (TI-91). A lone mistyped option (one token, no whitespace) is still caught below.
@note.command("add", context_settings={"ignore_unknown_options": True})
@click.argument("tid")
@click.argument("text")
@click.option("--author", default=None, help="defaults to $TIX_AGENT if set")
@click.option("--created-at", default=None, help="backdate the note's timestamp (ISO date or datetime, e.g. 2026-08-15) — for importing history, not normal use")
@click.option("--decision", "decision", is_flag=True, help="record this note as a DECISION: the verbatim words someone decided with (needs --by). Listed by `tix decisions`.")
@click.option("--by", "decided_by", default=None, help="with --decision: who decided (e.g. Alice)")
@click.option("--channel", default=None, help="with --decision: where it was said, e.g. chat:12345 (channel:message-id)")
def note_add(tid, text, author, created_at, decision, decided_by, channel):
    """Add a note. This is how you FINISH a ticket — a status flip alone tells the next
    reader nothing (). Before `tix update
    <KEY> --status done`, always `tix note add <KEY> "..."` covering, in order:

    \b
    1. What you actually did — not just what the ticket asked for.
    2. Where the output is — file paths, commit hashes, ticket keys, service names. Absolute paths.
    3. What you found — the finding, the constraint, the dead end. Highest-value part, most-skipped.
    4. What you did NOT do — scope you left, and why.
    5. Open questions for whoever owns this — anything you couldn't decide alone.

    Write it for someone with none of your context — that's exactly who reads it,
    including you next week with the session gone. Say plainly if something failed,
    was skipped, or is unverified — a note that reads as success when the work was
    partial is worse than no note, because it's trusted.

    Shell-safe for long or code-heavy notes: pass TEXT as '-' and the note is read from
    stdin. With a QUOTED heredoc delimiter the shell expands nothing, so backticks, $VARS,
    $(...) and quotes arrive exactly as typed:

    \b
      tix note add TI-1 - <<'EOF'
      Ran `git log`, cost $5, see "quoted" bits -- all stored verbatim.
      EOF

    (In double quotes the shell would run `git log` and expand $5 before tix saw them.)

    Decisions (so they don't get buried in long notes and re-asked): add --decision with
    --by and optionally --channel; TEXT is the decider's VERBATIM words.

    \b
      tix note add TI-1 "1 Same rule" --decision --by Alice --channel chat:4821

    List them with `tix decisions`."""
    if text == "-":
        text = sys.stdin.read().rstrip("\n")
    if text.startswith("-") and not any(c.isspace() for c in text):
        click.echo(f"'{text}' looks like a mistyped option, not a note -- nothing added. "
                    "A real note is a sentence; put the text in quotes.", err=True)
        raise SystemExit(2)
    if not text.strip():
        click.echo("note text is empty -- nothing added", err=True)
        raise SystemExit(1)
    real_id = resolve_tid(tid)
    author = resolve_by(author)
    if not author:
        click.echo("--author is required (or set $TIX_AGENT) -- a note with no author is unreadable history", err=True)
        raise SystemExit(1)
    created_at = parse_created_at(created_at)
    if (decided_by or channel) and not decision:
        click.echo("--by/--channel only apply with --decision -- nothing added", err=True)
        raise SystemExit(1)
    if decision and not (decided_by or "").strip():
        click.echo("--decision needs --by NAME (who decided) -- nothing added", err=True)
        raise SystemExit(1)
    if decision:
        die_on_tix_error(tixdb.add_note, real_id, text, author, created_at,
                         "decision", decided_by.strip(), (channel or "").strip())
        click.echo("decision added")
        return
    die_on_tix_error(tixdb.add_note, real_id, text, author, created_at)
    click.echo("note added")


@note.command("list")
@click.argument("tid")
def note_list(tid):
    real_id = resolve_tid(tid)
    notes = tixdb.list_notes(real_id)
    if not notes:
        click.echo("no notes")
        return
    for n in notes:
        who = f" ({n['author']})" if n["author"] else ""
        mark = _decision_tag(n) + " " if n.get("kind") == "decision" else ""
        click.echo(f"[{fmt_ts(n['created_at'])}]{who} {mark}{n['text']}")


@cli.command()
@click.option("--project", default=None, help="only decisions on tickets in this project (name or key)")
@click.option("--search", default=None, help="case-insensitive substring match on the verbatim text")
def decisions(project, search):
    """List recorded decisions (notes added with `tix note add --decision`), newest first:
    date, ticket, who decided, channel, and the verbatim words. Check here before asking
    the owner something they may already have answered."""
    rows = tixdb.list_decisions(project=project, search=search)
    if not rows:
        click.echo("no decisions")
        return
    for r in rows:
        click.echo(f"[{fmt_ts(r['created_at'])}] {r['ticket_key']:<8} {r['decided_by'] or '-'} "
                   f"({r['channel'] or '-'}): {r['text']}")


@cli.command()
@click.argument("tid")
@click.option("--title", default=None)
@click.option("--desc", default=None, help="REPLACES the whole description (use --append-desc to add to it).")
@click.option("--append-desc", "append_desc", default=None, help="append to the existing description (blank line between), instead of replacing it. Pass '-' to read the text from stdin.")
@click.option("--status", default=None, type=click.Choice(tixdb.STATUSES))
@click.option("--priority", default=None, type=click.Choice(tixdb.PRIORITIES))
@click.option("--type", "type_", default=None, type=click.Choice(tixdb.TYPES))
@click.option("--parent", default=None, help="parent ticket key or id")
@click.option("--blocked-by", "blocked_by", default=None, help="ticket key or id this is stuck behind. Pass \"\" to clear.")
@click.option("--blocked-on", "blocked_on", default=None, help="person (alice) or ticket key (NS-3) this waits on. Pass \"\" to clear.")
@click.option("--project", default=None)
@click.option("--team", default=None)
@click.option("--assignee", default=None)
@click.option("--model", default=None)
@click.option("--tags", default=None)
@click.option("--staging-sha", "staging_sha", default=None, help="commit id (7-40 hex) live on staging. Pass \"\" to clear.")
@click.option("--prod-sha", "prod_sha", default=None, help="commit id (7-40 hex) live in production. Pass \"\" to clear.")
@click.option("--by", default=None, help="who's making this change — defaults to $TIX_AGENT if set. Used to skip your own entries in your inbox, nothing else.")
def update(tid, title, desc, append_desc, status, priority, type_, parent, blocked_by, blocked_on, project, team, assignee, model, tags, staging_sha, prod_sha, by):
    """Update fields on a ticket (by ticket key or id)."""
    real_id = resolve_tid(tid)
    fields = {}
    if title is not None:
        fields["title"] = title
    if desc is not None and append_desc is not None:
        click.echo("--desc and --append-desc are mutually exclusive", err=True)
        raise SystemExit(1)
    if desc is not None:
        fields["description"] = desc
    if append_desc is not None:
        if append_desc == "-":
            append_desc = sys.stdin.read().rstrip("\n")
        if not append_desc.strip():
            click.echo("--append-desc text is empty -- nothing changed", err=True)
            raise SystemExit(1)
        current = tixdb.get_ticket(real_id).get("description") or ""
        fields["description"] = f"{current}\n\n{append_desc}" if current else append_desc
    if status is not None:
        fields["status"] = status
    if priority is not None:
        fields["priority"] = priority
    if type_ is not None:
        fields["type"] = type_
    if parent is not None:
        fields["parent_id"] = resolve_tid(parent)
    if blocked_by is not None:
        fields["blocked_by"] = resolve_tid(blocked_by) if blocked_by else None
    if blocked_on is not None:
        fields["blocked_on"] = blocked_on
    if project is not None:
        fields["project"] = project
    if team is not None:
        fields["team"] = team
    if assignee is not None:
        fields["assignee"] = assignee
    if model is not None:
        fields["model"] = model
    if tags is not None:
        fields["tags"] = tags
    if staging_sha is not None:
        fields["staging_sha"] = staging_sha
    if prod_sha is not None:
        fields["prod_sha"] = prod_sha
    if not fields:
        click.echo("nothing to update", err=True)
        raise SystemExit(1)
    t = die_on_tix_error(tixdb.update_ticket, real_id, resolve_by(by), **fields)
    click.echo(f"updated {t['ticket_key'] or ('#' + str(real_id))}")
    if fields.get("status") == "in_progress":
        _model_nudge(t["model"])



@cli.command()
@click.argument("tid")
def rm(tid):
    """Delete a ticket (by ticket key or id)."""
    real_id = resolve_tid(tid)
    tixdb.delete_ticket(real_id)
    click.echo(f"deleted #{real_id}")


@cli.command()
@click.argument("text")
def search(text):
    """Full-text search across title, description, tags, project, team, assignee, key, and notes.
    Prints a short description preview under each match, since the match may be in the
    description or a note rather than the title -- run `tix show <key>` to read the rest."""
    rows = tixdb.search_tickets(text)
    if not rows:
        click.echo("no matches")
        return
    for t in rows:
        click.echo(fmt_row(t))
        snippet = fmt_snippet(t.get("description"))
        if snippet:
            click.echo(f"         {snippet}")


def _story_check(desc):
    """A story's description is 'incomplete' if it has no Acceptance Criteria
    section, or that section is still the unfilled Given/[context]/[action]/
    [outcome] placeholder from the template -- a warning signal only, never a
    reason to refuse anything. Scoped to --type story specifically, not every
    ticket -- a task or bug was never asked to look like a user story."""
    problems = []
    m = re.search(r"^##\s+Acceptance Criteria\s*$", desc or "", re.MULTILINE)
    if not m:
        problems.append("no 'Acceptance Criteria' section")
        return problems
    rest = desc[m.end():]
    next_header = re.search(r"^##\s+", rest, re.MULTILINE)
    content = (rest[:next_header.start()] if next_header else rest).strip()
    if not content or "[context]" in content or "[action]" in content or "[outcome]" in content:
        problems.append("Acceptance Criteria section is still the unfilled template")
    return problems


@cli.command()
@click.argument("tid")
def check(tid):
    """Warn if a --type story ticket is missing real Acceptance Criteria.
    Never blocks -- a warning signal, same as tix guard check's philosophy.
    No-op (prints nothing, exits 0) for any type other than story."""
    real_id = resolve_tid(tid)
    t = tixdb.get_ticket(real_id)
    if t["type"] != "story":
        click.echo(f"'{t['type']}' tickets aren't checked -- this only applies to --type story")
        return
    problems = _story_check(t.get("description"))
    if not problems:
        click.echo("looks complete -- has real Acceptance Criteria")
        return
    click.echo(f"{len(problems)} issue(s):")
    for p in problems:
        click.echo(f"  - {p}")


@cli.command()
@click.option("--limit", default=20, help="how many entries to show")
@click.option("--project", default=None)
@click.option("--team", default=None)
@click.option("--status", default=None, type=click.Choice(tixdb.STATUSES))
@click.option("--type", "type_", default=None, type=click.Choice(tixdb.TYPES))
@click.option("--priority", default=None, type=click.Choice(tixdb.PRIORITIES))
@click.option("--assignee", default=None)
@click.option("--model", default=None)
def activity(limit, project, team, status, type_, priority, assignee, model):
    """Recent history across all tickets — new tickets and notes, newest first.
    Filters combine like a WHERE clause, same as `list`: tix activity --project tix --status in_progress"""
    rows = tixdb.recent_activity(limit, project, team, status, type_, priority, assignee, model)
    if not rows:
        click.echo("no activity yet")
        return
    for r in rows:
        tag = "created" if r["kind"] == "created" else "note"
        who = f" ({r['author']})" if r["author"] else ""
        click.echo(f"[{fmt_ts(r['ts'])}] {r['ticket_key']:<8} {tag:<7}{who} {r['text']}")


@cli.command()
@click.argument("assignee", required=False, default=None)
def inbox(assignee):
    """What changed on your tickets since you last checked — field updates and notes on
    tickets assigned to you, plus any note anywhere that @mentions you by name (e.g.
    "@ben check this"), all authored by someone else. Reading this marks it seen
    (doesn't delete anything; the ticket's own history is unaffected).

    ASSIGNEE defaults to $TIX_AGENT if omitted. Other tix commands print a one-line
    nudge to stderr when your inbox is non-empty (set $TIX_AGENT for that to work) -- only on an
    interactive terminal, and only when the count changed or 5 minutes passed. Piped/captured
    output stays quiet; TIX_INBOX_NUDGE=1 forces it on every command, =0 turns it off."""
    who = assignee or os.environ.get("TIX_AGENT", "")
    if not who:
        click.echo("no assignee given and $TIX_AGENT is not set — tix inbox <assignee>", err=True)
        raise SystemExit(1)
    items = tixdb.get_inbox(who)
    if not items:
        click.echo("inbox empty")
        tixdb.mark_inbox_seen(who)
        return
    for it in items:
        who_did = f" ({it['author']})" if it["author"] else ""
        if it["kind"] == "event" and it["field"] == "created" and (it["ticket_assignee"] or "").lower() != who.strip().lower():
            click.echo(f"[{fmt_ts(it['ts'])}] {it['ticket_key']:<8} new child of {it['parent_key']}{who_did} (watched) — {it['title']}")
        elif it["kind"] == "event" and it["field"] == "created":
            click.echo(f"[{fmt_ts(it['ts'])}] {it['ticket_key']:<8} created, assigned to you{who_did} — {it['title']}")
        elif it["kind"] == "event" and it["field"] == "assignee" and (it["new_value"] or "").lower() == who.strip().lower():
            click.echo(f"[{fmt_ts(it['ts'])}] {it['ticket_key']:<8} assigned to you{who_did} — {it['title']}")
        elif it["kind"] == "event":
            click.echo(f"[{fmt_ts(it['ts'])}] {it['ticket_key']:<8} {it['field']} changed{who_did}: {it['old_value']} -> {it['new_value']}")
        elif it.get("mentioned"):
            click.echo(f"[{fmt_ts(it['ts'])}] {it['ticket_key']:<8} @mention{who_did}: {it['text']}")
        else:
            click.echo(f"[{fmt_ts(it['ts'])}] {it['ticket_key']:<8} note{who_did}: {it['text']}")
    tixdb.mark_inbox_seen(who)


@cli.command()
@click.option("--parent", "parent", default=None, help="ticket (usually an epic) whose new children you want in your inbox")
@click.option("--stop", is_flag=True, help="with --parent: stop watching it")
@click.option("--as", "who", default=None, help="watcher name -- defaults to $TIX_AGENT")
def watch(parent, stop, who):
    """Watch an epic: new tickets created under it show up in `tix inbox` (and the
    'N ticket(s) changed' nudge). With no --parent, lists what you are watching.
    Children created since your last `tix inbox` are included on the first read."""
    who = who or os.environ.get("TIX_AGENT", "")
    if not who:
        click.echo("no watcher given and $TIX_AGENT is not set -- tix watch --as <name>", err=True)
        raise SystemExit(1)
    if not parent:
        rows = tixdb.list_watches(who)
        if not rows:
            click.echo("not watching anything")
        for r in rows:
            click.echo(f"{r['ticket_key']:<8} {r['title']}")
        return
    real_id = resolve_tid(parent)
    if stop:
        click.echo("unwatched" if tixdb.unwatch_ticket(who, real_id) else "was not watching that ticket")
        return
    tixdb.watch_ticket(who, real_id)
    click.echo(f"watching {parent} -- new children will appear in tix inbox")


# Generic "did real work happen" heuristics, in case no role-conf is given or
# readable. Shell-command oriented so they work against either transcript format.
DEFAULT_WORK_PATTERNS = [
    r"\bgit\s+(commit|push|merge|reset|checkout)\b",
    r"\bsystemctl\s+(?!.*(status|is-active|list|show|cat))",
    r"\bdocker\s+(run|rm|stop|start|restart|exec|build|compose)\b",
    r"\bapt(-get)?\s+(install|remove|purge)\b",
    r"\b(rm|mv|chmod|chown|tee|crontab)\s",
]
# Claude Code transcripts also record Edit/Write tool calls as structured JSON,
# not shell commands -- only relevant for that one transcript format.
CLAUDE_CODE_EXTRA_PATTERNS = [r'"name":"(Edit|Write)"']
# Claude Code transcripts are raw JSONL, so a newline inside a Bash command is the two
# characters backslash-n, and the 'n' looked like a letter to [^a-zA-Z] -- `tix` at the start
# of a line (after a heredoc, say) was invisible and the guard falsely blocked (TI-95).
TIX_ACTIVITY_PATTERN = r'(^|[^a-zA-Z]|\\[nrt])tix\s+(add|update|note)(\s|"|$)'


def _guard_checkpoint_path(session):
    if not session:
        return None
    d = Path.home() / ".tix" / "guard-checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{session}.offset")


def _guard_load_patterns(conf_path, fmt, conf_only=False):
    """A role-conf EXTENDS the generic defaults by default -- a conf naturally reads as
    "the extra things my job does that the defaults miss" (that's how the examples in
    examples/role-confs/ are written), so silently dropping the defaults the moment a
    conf is supplied means a role stops being checked for file edits, rm, git commit
    etc. without any signal that happened. Pass --conf-only for the old full-override
    behaviour, for a role that genuinely wants to declare its own complete rule set.
    Prints what's active to stderr either way, since silence is what made this a bug
    report the first time (found by Ben, TI-59, 2026-08-25)."""
    patterns = list(DEFAULT_WORK_PATTERNS)
    if fmt == "claude-code":
        patterns = patterns + CLAUDE_CODE_EXTRA_PATTERNS

    if not conf_path:
        return patterns

    try:
        lines = Path(conf_path).read_text().splitlines()
        custom = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        custom = []

    if not custom:
        return patterns

    if conf_only:
        click.echo(f"guard check: using {len(custom)} pattern(s) from {conf_path}; "
                    "built-in defaults NOT active (--conf-only)", err=True)
        return custom

    click.echo(f"guard check: using {len(custom)} pattern(s) from {conf_path} "
                f"plus {len(patterns)} built-in default(s)", err=True)
    return patterns + custom


def _guard_check_impl(transcript, fmt, conf, checkpoint, session, conf_only=False):
    ckpt_path = checkpoint or _guard_checkpoint_path(session)
    offset = 0
    if ckpt_path and os.path.exists(ckpt_path):
        try:
            offset = int((Path(ckpt_path).read_text() or "0").strip())
        except Exception:
            offset = 0

    if fmt == "claude-code":
        if not transcript or not os.path.exists(transcript):
            return {"decision": "allow", "reason": None}
        raw = Path(transcript).read_text(errors="ignore")
    else:
        raw = sys.stdin.read()

    if offset > len(raw):
        offset = 0
    window, new_offset = raw[offset:], len(raw)

    def mark_seen():
        if ckpt_path:
            try:
                Path(ckpt_path).write_text(str(new_offset))
            except Exception:
                pass

    patterns = _guard_load_patterns(conf, fmt, conf_only)
    did_work = any(re.search(p, window) for p in patterns)
    if not did_work:
        mark_seen()
        return {"decision": "allow", "reason": None}

    if re.search(TIX_ACTIVITY_PATTERN, window):
        mark_seen()
        return {"decision": "allow", "reason": None}

    return {
        "decision": "block",
        "reason": (
            "Real work happened without any tix activity (no 'tix add' / 'tix update' / "
            "'tix note' run) since the last check. File it if this was a real unit of work, "
            "or proceed if it genuinely didn't need one. If you do file it, pick the type "
            "deliberately: --type bug if something was broken or behaved differently from "
            "what it claims (even if you fixed it in the same breath), task for a unit of "
            "work, story/epic for larger scope -- a bug filed as a note on a task ticket is "
            "invisible to anyone who didn't already know to open it. This checks the window "
            "since the last time it allowed a turn through, not the whole session, so it "
            "won't re-flag the same thing forever once you've either filed it or moved past it."
        ),
    }


@cli.group()
def guard():
    """Enforcement primitives for wiring tix into an agent harness as a hard gate,
    not just a written convention. `guard check` is harness-agnostic on purpose --
    see docs/ENFORCEMENT.md in the repo (github.com/tinytools-cli/tix) for how to wire it
    into your own harness's hook or callback mechanism (a Claude Code Stop-hook
    adapter is included as a worked example)."""


@guard.command("check")
@click.option("--transcript", default=None, help="path to a transcript file. Required when --format is claude-code.")
@click.option("--format", "fmt", default="claude-code", type=click.Choice(["claude-code", "lines"]),
              help="'claude-code' parses a Claude Code session transcript (JSONL) at --transcript. "
                   "'lines' reads plain text from stdin instead -- one action/command per line, for "
                   "any other harness's adapter to produce however it logs its own actions.")
@click.option("--conf", default=None, help="path to a role-conf file, one regex per line ('#' comments allowed). "
                                            "EXTENDS the built-in generic defaults by default -- write a conf as "
                                            "'the extra things my job does that the defaults miss'. Falls back to "
                                            "just the built-in defaults if omitted or unreadable.")
@click.option("--conf-only", is_flag=True, default=False, help="with --conf, use ONLY the conf's patterns -- the "
                                                                 "built-in defaults (including file-edit detection) "
                                                                 "are not active. For a role that wants to declare "
                                                                 "its complete rule set, not just extras.")
@click.option("--checkpoint", default=None, help="checkpoint file path, tracking what's already been reviewed so "
                                                   "the same work isn't re-flagged forever. Auto-derived from "
                                                   "--session under ~/.tix/guard-checkpoints/ if omitted.")
@click.option("--session", default=None, help="session identifier -- only used to derive a default --checkpoint path.")
def guard_check(transcript, fmt, conf, conf_only, checkpoint, session):
    """Decide whether real work happened (per the active generic defaults, extended by
    a role-conf if given) without any tix activity since the last check for this session.

    Prints {"decision": "allow"|"block", "reason": ...} as JSON on stdout and
    always exits 0 -- callers read the JSON, not the exit code, so a caller that
    mishandles this can't get stuck. This command doesn't know or care what's
    calling it or what happens on a block -- that's your harness adapter's job."""
    try:
        result = _guard_check_impl(transcript, fmt, conf, checkpoint, session, conf_only)
    except Exception:
        # Fails open: a broken guard must never be able to wedge a session.
        result = {"decision": "allow", "reason": None}
    click.echo(json.dumps(result))


if __name__ == "__main__":
    cli()
