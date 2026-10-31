import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Resolution order: $TIX_DB_PATH override, else a per-user data dir (~/.tix/tix.db) so a
# pip-installed copy doesn't try to write into site-packages. Running the repo in place
# (dev mode) works the same way -- set TIX_DB_PATH if you want it colocated with the code.
_default_dir = Path.home() / ".tix"
_default_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("TIX_DB_PATH") or (_default_dir / "tix.db"))

TYPES = ("epic", "story", "task", "bug", "support")
# Release stages (TI-98): in_progress -> on_staging (built, live on staging) -> in_prod (live in
# production). `done` stays the general "finished" state for work that doesn't ship.
STATUSES = ("todo", "in_progress", "blocked", "on_staging", "in_prod", "done")
# Statuses that are no longer "open work": `list --open`, the web "unresolved" filter and the
# dashboard open counts exclude these. on_staging IS still open -- it is waiting for prod.
CLOSED_STATUSES = ("in_prod", "done")
PRIORITIES = ("low", "med", "high", "urgent")
# Seeded into the teams table on first migration — a starting point, not a hard limit.
DEFAULT_TEAMS = ("Engineering", "Sales", "Marketing", "Support", "Ops")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_key TEXT,
    type TEXT NOT NULL CHECK(type IN ('epic','story','task','bug','support')),
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','blocked','on_staging','in_prod','done')),
    priority TEXT NOT NULL DEFAULT 'med' CHECK(priority IN ('low','med','high','urgent')),
    parent_id INTEGER REFERENCES tickets(id),
    blocked_by INTEGER REFERENCES tickets(id),
    blocked_on TEXT DEFAULT '',
    project TEXT DEFAULT '',
    team TEXT DEFAULT '',
    assignee TEXT DEFAULT '',
    model TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    staging_sha TEXT DEFAULT '',
    prod_sha TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_type ON tickets(type);
CREATE INDEX IF NOT EXISTS idx_tickets_parent ON tickets(parent_id);
CREATE TABLE IF NOT EXISTS projects (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    next_seq INTEGER NOT NULL DEFAULT 1,
    folder TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author TEXT DEFAULT '',
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    decided_by TEXT DEFAULT '',
    channel TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_notes_ticket ON notes(ticket_id);
CREATE TABLE IF NOT EXISTS ticket_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    author TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket ON ticket_events(ticket_id);
CREATE TABLE IF NOT EXISTS inbox_watermarks (
    assignee TEXT PRIMARY KEY COLLATE NOCASE,
    last_event_id INTEGER NOT NULL DEFAULT 0,
    last_note_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watches (
    watcher TEXT NOT NULL COLLATE NOCASE,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    PRIMARY KEY (watcher, ticket_id)
);
"""


class TixError(ValueError):
    """Raised for user-facing validation failures (unregistered project/team, etc)."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_assignee(name):
    """Assignees are stored lowercase + trimmed and matched case-insensitively, so
    'Alice' and 'alice' are one person (TI-76)."""
    return (name or "").strip().lower()


def norm_blocked_on(value):
    """TI-101: who/what a ticket waits on. A ticket key (NS-3) is stored UPPERCASE; anything
    else is a person, stored lowercase like assignees. '' clears. Separate from blocked_by
    (the ticket FK)."""
    v = (value or "").strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*-\d+", v):
        return v.upper()
    return v.lower()


def norm_sha(value, label="sha"):
    """Commit ids are stored lowercase; 7-40 hex chars (abbreviated or full). '' clears."""
    v = (value or "").strip().lower()
    if v and not re.fullmatch(r"[0-9a-f]{7,40}", v):
        raise TixError(f"{label} must be a git commit id (7-40 hex characters), got '{value}'")
    return v


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_widen_type_check(conn):
    """Rebuild the table so the `type` CHECK allows 'support' and team/assignee exist.
    SQLite can't ALTER a CHECK constraint in place, so this rebuilds tickets into a
    new table with the current schema, copies rows, and swaps it in."""
    conn.execute("PRAGMA foreign_keys = OFF")
    create_new = SCHEMA.split(";")[0].replace("CREATE TABLE IF NOT EXISTS tickets", "CREATE TABLE tickets_new")
    conn.execute(create_new + ";")
    old_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    common = [c for c in ("id", "type", "title", "description", "status", "priority",
                           "parent_id", "project", "tags", "created_at", "updated_at") if c in old_cols]
    conn.execute(f"INSERT INTO tickets_new ({', '.join(common)}) SELECT {', '.join(common)} FROM tickets")
    conn.execute("DROP TABLE tickets")
    conn.execute("ALTER TABLE tickets_new RENAME TO tickets")
    conn.execute("PRAGMA foreign_keys = ON")


def _migrate_release_stages(conn):
    """TI-98: widen the status CHECK to allow on_staging/in_prod and add staging_sha/prod_sha.
    SQLite can't ALTER a CHECK, so (like the type-check migration) rebuild tickets: new table
    from the current SCHEMA, copy every column both have, swap, recreate indexes. Idempotent --
    skipped once the stored table definition already mentions on_staging. Runs in one
    transaction (BEGIN IMMEDIATE) so a crash leaves the old table intact."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tickets'").fetchone()
    if not sql or "on_staging" in sql["sql"]:
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        create_new = SCHEMA.split(";")[0].replace("CREATE TABLE IF NOT EXISTS tickets", "CREATE TABLE tickets_new")
        conn.execute("DROP TABLE IF EXISTS tickets_new")
        conn.execute(create_new)
        old_cols = [row["name"] for row in conn.execute("PRAGMA table_info(tickets)")]
        new_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tickets_new)")}
        common = ", ".join(c for c in old_cols if c in new_cols)
        conn.execute(f"INSERT INTO tickets_new ({common}) SELECT {common} FROM tickets")
        conn.execute("DROP TABLE tickets")
        conn.execute("ALTER TABLE tickets_new RENAME TO tickets")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_type ON tickets(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_parent ON tickets(parent_id)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _derive_key(name, taken):
    base = "".join(ch for ch in name.upper() if ch.isalnum())
    candidates = []
    if len(base) >= 2:
        candidates.append(base[:2])
    for i in range(2, len(base)):
        candidates.append(base[0] + base[i])
    i = 1
    while i <= 50:
        candidates.append(f"{base[:1] or 'X'}{i}")
        i += 1
    for c in candidates:
        if c and c not in taken:
            return c
    raise TixError(f"could not derive a project key for '{name}'")


def _backfill_registries_and_keys(conn):
    """Idempotent: registers any project/team names already sitting in tickets
    (from before the registry existed) and assigns ticket_key to any ticket that
    has a project but no key yet, in id order."""
    for team in DEFAULT_TEAMS:
        conn.execute("INSERT OR IGNORE INTO teams (name, created_at) VALUES (?, ?)", (team, now()))

    project_names = [r["project"] for r in conn.execute(
        "SELECT DISTINCT project FROM tickets WHERE project != '' ORDER BY id")]
    for name in project_names:
        exists = conn.execute("SELECT 1 FROM projects WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if not exists:
            taken = {r["key"] for r in conn.execute("SELECT key FROM projects")}
            key = _derive_key(name, taken)
            conn.execute("INSERT INTO projects (key, name, next_seq, created_at) VALUES (?, ?, 1, ?)",
                         (key, name, now()))

    team_names = [r["team"] for r in conn.execute("SELECT DISTINCT team FROM tickets WHERE team != ''")]
    for name in team_names:
        conn.execute("INSERT OR IGNORE INTO teams (name, created_at) VALUES (?, ?)", (name, now()))

    unkeyed = conn.execute(
        "SELECT id, project FROM tickets WHERE project != '' AND (ticket_key IS NULL OR ticket_key = '') ORDER BY id"
    ).fetchall()
    for row in unkeyed:
        proj = conn.execute("SELECT key, next_seq FROM projects WHERE name = ? COLLATE NOCASE", (row["project"],)).fetchone()
        if not proj:
            continue
        tkey = f"{proj['key']}-{proj['next_seq']}"
        conn.execute("UPDATE tickets SET ticket_key = ? WHERE id = ?", (tkey, row["id"]))
        conn.execute("UPDATE projects SET next_seq = next_seq + 1 WHERE key = ?", (proj["key"],))


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "project" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN project TEXT DEFAULT ''")
        cols.add("project")
    if "team" not in cols or "assignee" not in cols:
        _migrate_widen_type_check(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "ticket_key" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN ticket_key TEXT")
    if "model" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN model TEXT DEFAULT ''")
    if "blocked_by" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN blocked_by INTEGER REFERENCES tickets(id)")
    _migrate_release_stages(conn)
    # TI-101: blocked_on (person or ticket key). Checked AFTER the rebuild migrations above so
    # it survives them (SCHEMA also carries it for fresh/rebuilt tables); idempotent.
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "blocked_on" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN blocked_on TEXT DEFAULT ''")
    # TI-100: decision notes. Plain ADD COLUMN (existing rows get kind='note'); idempotent.
    note_cols = {row["name"] for row in conn.execute("PRAGMA table_info(notes)")}
    if "kind" not in note_cols:
        conn.execute("ALTER TABLE notes ADD COLUMN kind TEXT NOT NULL DEFAULT 'note'")
    if "decided_by" not in note_cols:
        conn.execute("ALTER TABLE notes ADD COLUMN decided_by TEXT DEFAULT ''")
    if "channel" not in note_cols:
        conn.execute("ALTER TABLE notes ADD COLUMN channel TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_kind ON notes(kind)")
    proj_cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "folder" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN folder TEXT DEFAULT ''")
    watermark_cols = {row["name"] for row in conn.execute("PRAGMA table_info(inbox_watermarks)")}
    if watermark_cols and "last_event_id" not in watermark_cols:
        # pre-release schema (timestamp-based, had a same-second tie bug) — watermarks are
        # disposable, so just rebuild; worst case someone re-sees their backlog once.
        conn.execute("DROP TABLE inbox_watermarks")
        conn.executescript(SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_project ON tickets(project)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_team ON tickets(team)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_blocked_by ON tickets(blocked_by)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_blocked_on ON tickets(blocked_on)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_ticket_key ON tickets(ticket_key) WHERE ticket_key IS NOT NULL")
    _backfill_registries_and_keys(conn)
    conn.commit()
    conn.close()


def resolve_project(conn, identifier):
    return conn.execute(
        "SELECT * FROM projects WHERE key = ? COLLATE NOCASE OR name = ? COLLATE NOCASE",
        (identifier, identifier),
    ).fetchone()


def resolve_team(conn, identifier):
    return conn.execute("SELECT * FROM teams WHERE name = ? COLLATE NOCASE", (identifier,)).fetchone()


def add_project(name, folder="", key=None):
    """Register a project, or fix up an existing one's folder.

    TI-88: re-running this on an existing name used to
    silently ignore a changed --folder and return the stale row -- CLI still
    printed "registered project ..." as if it had taken effect. `add` is now
    the same command you use to fix a moved folder, and always says which of
    the three things actually happened (created / updated / unchanged) via
    result["_state"], rather than reporting "registered" regardless."""
    if not folder:
        raise TixError(
            "folder is required — where does this project's context/files/downloads live? "
            "An absolute path, e.g. /home/you/Projects/my-project. Doesn't need to be a "
            "codebase; every project gets one, even non-code initiatives. Created if it "
            "for now this just reserves the location.)"
        )
    if not os.path.isabs(folder):
        raise TixError(f"folder must be an absolute path, got '{folder}'")
    conn = get_conn()
    existing = conn.execute("SELECT * FROM projects WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if existing:
        existing = dict(existing)
        if key and key.upper() != existing["key"]:
            conn.close()
            raise TixError(
                f"project '{name}' already exists with key '{existing['key']}' -- changing a "
                f"project's key would invalidate every ticket key already using it, so that's "
                f"not supported here. Pick a different name if you meant a separate project."
            )
        if existing.get("folder") == folder:
            existing["_state"] = "unchanged"
            conn.close()
            return existing
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            conn.close()
            raise TixError(f"couldn't create folder '{folder}': {e}")
        conn.execute("UPDATE projects SET folder = ? WHERE key = ?", (folder, existing["key"]))
        conn.commit()
        conn.close()
        existing["folder"] = folder
        existing["_state"] = "updated"
        return existing
    taken = {r["key"] for r in conn.execute("SELECT key FROM projects")}
    if key:
        key = key.upper()
        if key in taken:
            conn.close()
            raise TixError(f"key '{key}' is already used by another project")
    else:
        key = _derive_key(name, taken)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        conn.close()
        raise TixError(f"couldn't create folder '{folder}': {e}")
    conn.execute("INSERT INTO projects (key, name, next_seq, folder, created_at) VALUES (?, ?, 1, ?, ?)",
                 (key, name, folder, now()))
    conn.commit()
    conn.close()
    return {"key": key, "name": name, "next_seq": 1, "folder": folder, "_state": "created"}


def rename_project(identifier, new_name):
    """Change a project's display name. The key is never touched here — there's no
    parameter for it — so a rename can't accidentally invalidate ticket keys that are
    already referenced elsewhere (docs, commit messages, other tickets)."""
    conn = get_conn()
    proj = resolve_project(conn, identifier)
    if not proj:
        conn.close()
        raise TixError(f"no such project '{identifier}'")
    clash = conn.execute(
        "SELECT 1 FROM projects WHERE name = ? COLLATE NOCASE AND key != ?", (new_name, proj["key"])
    ).fetchone()
    if clash:
        conn.close()
        raise TixError(f"a project named '{new_name}' already exists")
    conn.execute("UPDATE projects SET name = ? WHERE key = ?", (new_name, proj["key"]))
    conn.execute("UPDATE tickets SET project = ? WHERE project = ? COLLATE NOCASE", (new_name, proj["name"]))
    conn.commit()
    conn.close()
    return {"key": proj["key"], "name": new_name}


def set_project_folder(identifier, folder, create=True):
    """Point an existing project at a new folder (TI-90). Looks the project up by key or
    name, so unlike `project add` you don't have to re-type its full name. Key and
    tickets are untouched. Creates the folder unless create=False."""
    if not folder or not os.path.isabs(folder):
        raise TixError(f"folder must be an absolute path, got '{folder}'")
    conn = get_conn()
    proj = resolve_project(conn, identifier)
    if not proj:
        conn.close()
        raise TixError(f"no such project '{identifier}'")
    if create:
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            conn.close()
            raise TixError(f"couldn't create folder '{folder}': {e}")
    conn.execute("UPDATE projects SET folder = ? WHERE key = ?", (folder, proj["key"]))
    conn.commit()
    conn.close()
    return {"key": proj["key"], "name": proj["name"], "old_folder": proj["folder"], "folder": folder}


def list_projects_registry():
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.key, p.name, p.folder, COUNT(t.id) AS ticket_count FROM projects p "
        "LEFT JOIN tickets t ON t.project = p.name COLLATE NOCASE "
        "GROUP BY p.key ORDER BY p.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_team(name):
    conn = get_conn()
    existing = conn.execute("SELECT * FROM teams WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if existing:
        conn.close()
        return dict(existing)
    conn.execute("INSERT INTO teams (name, created_at) VALUES (?, ?)", (name, now()))
    conn.commit()
    conn.close()
    return {"name": name}


def list_teams_registry():
    conn = get_conn()
    rows = conn.execute(
        "SELECT te.name, COUNT(t.id) AS ticket_count FROM teams te "
        "LEFT JOIN tickets t ON t.team = te.name COLLATE NOCASE "
        "GROUP BY te.name ORDER BY te.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_ticket_id(identifier):
    """Accept either an internal integer id or a ticket_key like 'NS-1'."""
    s = str(identifier)
    if s.isdigit():
        return int(s)
    conn = get_conn()
    row = conn.execute("SELECT id FROM tickets WHERE ticket_key = ? COLLATE NOCASE", (s,)).fetchone()
    conn.close()
    return row["id"] if row else None


def add_ticket(type_, title, description="", status="todo", priority="med", parent_id=None,
               project="", team="", assignee="", model="", tags="", blocked_by=None, created_at=None, by="", blocked_on=""):
    if not project:
        raise TixError(
            "project is required. Pick an existing one (tix project list) or register a "
            "new one (tix project add \"name\")."
        )
    if not model:
        raise TixError(
            "model is required — which model is doing this work? (haiku/sonnet/opus, or the "
            "full model id). Pick it up front and use that model for the task."
        )
    assignee = norm_assignee(assignee)
    blocked_on = norm_blocked_on(blocked_on)
    conn = get_conn()
    ticket_key = None
    if project:
        proj = resolve_project(conn, project)
        if not proj:
            conn.close()
            raise TixError(f"no such project '{project}'. Register it first: tix project add \"{project}\"")
        project = proj["name"]
        ticket_key = f"{proj['key']}-{proj['next_seq']}"
        conn.execute("UPDATE projects SET next_seq = next_seq + 1 WHERE key = ?", (proj["key"],))
    if team:
        te = resolve_team(conn, team)
        if not te:
            conn.close()
            raise TixError(f"no such team '{team}'. Register it first: tix team add \"{team}\"")
        team = te["name"]
    ts = created_at or now()
    cur = conn.execute(
        "INSERT INTO tickets (ticket_key, type, title, description, status, priority, parent_id, blocked_by, blocked_on, project, team, assignee, model, tags, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket_key, type_, title, description, status, priority, parent_id, blocked_by, blocked_on, project, team, assignee, model, tags, ts, ts),
    )
    tid = cur.lastrowid
    if assignee or parent_id:  # parent_id: so watchers of the parent (TI-99) see new children
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, field, old_value, new_value, author, created_at) "
            "VALUES (?, 'created', NULL, ?, ?, ?)",
            (tid, title, by, ts),
        )
    conn.commit()
    conn.close()
    return tid


def list_tickets(status=None, type_=None, priority=None, parent_id=None, project=None, team=None, assignee=None, model=None, blocked_by=None, blocked_on=None):
    conn = get_conn()
    q = ("SELECT t.*, p.ticket_key AS parent_key, b.ticket_key AS blocked_by_key FROM tickets t "
         "LEFT JOIN tickets p ON p.id = t.parent_id "
         "LEFT JOIN tickets b ON b.id = t.blocked_by WHERE 1=1")
    params = []
    if status:
        q += " AND t.status = ?"
        params.append(status)
    if type_:
        q += " AND t.type = ?"
        params.append(type_)
    if priority:
        q += " AND t.priority = ?"
        params.append(priority)
    if parent_id is not None:
        q += " AND t.parent_id = ?"
        params.append(parent_id)
    if project:
        proj = resolve_project(conn, project)
        q += " AND t.project = ?"
        params.append(proj["name"] if proj else project)
    if team:
        te = resolve_team(conn, team)
        q += " AND t.team = ?"
        params.append(te["name"] if te else team)
    if assignee:
        q += " AND LOWER(t.assignee) = ?"
        params.append(norm_assignee(assignee))
    if model:
        q += " AND t.model = ?"
        params.append(model)
    if blocked_by is not None:
        q += " AND t.blocked_by = ?"
        params.append(blocked_by)
    if blocked_on:
        q += " AND LOWER(t.blocked_on) = LOWER(?)"
        params.append(norm_blocked_on(blocked_on))
    q += " ORDER BY t.priority DESC, t.id ASC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ticket(tid):
    conn = get_conn()
    row = conn.execute(
        "SELECT t.*, p.ticket_key AS parent_key, b.ticket_key AS blocked_by_key FROM tickets t "
        "LEFT JOIN tickets p ON p.id = t.parent_id "
        "LEFT JOIN tickets b ON b.id = t.blocked_by WHERE t.id = ?",
        (tid,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_ticket(tid, by="", **fields):
    if not fields:
        return get_ticket(tid)
    if "assignee" in fields:
        fields["assignee"] = norm_assignee(fields["assignee"])
    if "blocked_on" in fields:
        fields["blocked_on"] = norm_blocked_on(fields["blocked_on"])
    conn = get_conn()
    # project/model are required-going-forward fields, but plenty of tickets predate them
    # and already sit at ''. Only block an actual CLEAR (had a value, now doesn't) — an
    # already-empty field staying empty in a full-object PATCH (the web UI's save()) is a
    # no-op, not a clear, so just drop it rather than erroring on every legacy-ticket edit.
    for sticky in ("project", "model"):
        if sticky in fields and not fields[sticky]:
            current = conn.execute(f"SELECT {sticky} FROM tickets WHERE id = ?", (tid,)).fetchone()
            if current and current[sticky]:
                conn.close()
                raise TixError(f"{sticky} can't be cleared — change it to a different {sticky} instead.")
            del fields[sticky]
    if not fields:
        conn.close()
        return get_ticket(tid)
    for sha_field in ("staging_sha", "prod_sha"):
        if sha_field in fields:
            fields[sha_field] = norm_sha(fields[sha_field], sha_field)
    if fields.get("project"):
        proj = resolve_project(conn, fields["project"])
        if not proj:
            conn.close()
            raise TixError(f"no such project '{fields['project']}'. Register it first: tix project add \"{fields['project']}\"")
        fields["project"] = proj["name"]
        current = conn.execute("SELECT ticket_key FROM tickets WHERE id = ?", (tid,)).fetchone()
        if current and not current["ticket_key"]:
            fields["ticket_key"] = f"{proj['key']}-{proj['next_seq']}"
            conn.execute("UPDATE projects SET next_seq = next_seq + 1 WHERE key = ?", (proj["key"],))
    if fields.get("team"):
        te = resolve_team(conn, fields["team"])
        if not te:
            conn.close()
            raise TixError(f"no such team '{fields['team']}'. Register it first: tix team add \"{fields['team']}\"")
        fields["team"] = te["name"]
    before = conn.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
    changed = {k: v for k, v in fields.items() if before and before[k] != v}
    fields["updated_at"] = now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [tid]
    conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", params)
    ts = fields["updated_at"]
    for field, new_value in changed.items():
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, field, old_value, new_value, author, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tid, field, before[field], new_value, by, ts),
        )
    conn.commit()
    conn.close()
    return get_ticket(tid)


def delete_ticket(tid):
    conn = get_conn()
    conn.execute("DELETE FROM tickets WHERE id = ?", (tid,))
    conn.commit()
    conn.close()


def search_tickets(text):
    conn = get_conn()
    like = f"%{text}%"
    rows = conn.execute(
        "SELECT t.*, p.ticket_key AS parent_key, b.ticket_key AS blocked_by_key FROM tickets t "
        "LEFT JOIN tickets p ON p.id = t.parent_id "
        "LEFT JOIN tickets b ON b.id = t.blocked_by "
        "WHERE t.title LIKE ? OR t.description LIKE ? OR t.tags LIKE ? OR t.project LIKE ? "
        "OR t.team LIKE ? OR t.assignee LIKE ? OR t.ticket_key LIKE ? OR t.model LIKE ? "
        "OR EXISTS (SELECT 1 FROM notes n WHERE n.ticket_id = t.id AND n.text LIKE ?) "
        "ORDER BY t.priority DESC, t.id ASC",
        (like, like, like, like, like, like, like, like, like),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_note(ticket_id, text, author="", created_at=None, kind="note", decided_by="", channel=""):
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not exists:
        conn.close()
        raise TixError(f"no such ticket 'id={ticket_id}'")
    ts = created_at or now()
    cur = conn.execute(
        "INSERT INTO notes (ticket_id, author, text, created_at, kind, decided_by, channel) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, author, text, ts, kind, decided_by, channel),
    )
    conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now(), ticket_id))
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return nid


def list_notes(ticket_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notes WHERE ticket_id = ? ORDER BY id ASC", (ticket_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_decisions(project=None, search=None):
    """TI-100: decision notes (kind='decision'), newest first. project filters on the ticket's
    project (name or key); search is a case-insensitive substring match on the verbatim text."""
    conn = get_conn()
    q = ("SELECT n.id, n.created_at, n.author, n.text, n.decided_by, n.channel, "
         "t.ticket_key, t.title, t.project FROM notes n JOIN tickets t ON t.id = n.ticket_id "
         "WHERE n.kind = 'decision'")
    params = []
    if project:
        proj = resolve_project(conn, project)
        q += " AND t.project = ?"
        params.append(proj["name"] if proj else project)
    q += " ORDER BY n.created_at DESC, n.id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    if search:
        needle = search.casefold()
        rows = [r for r in rows if needle in r["text"].casefold()]
    return rows


def recent_activity(limit=20, project=None, team=None, status=None, type_=None, priority=None, assignee=None, model=None):
    """Recent history across all tickets: new tickets and notes, newest first.
    Filters combine with AND, same as list_tickets. Doesn't (yet) track field-level
    changes like status flips — just creation + notes."""
    conn = get_conn()
    ticket_filter = ""
    params = []
    if project:
        proj = resolve_project(conn, project)
        ticket_filter += " AND t.project = ?"
        params.append(proj["name"] if proj else project)
    if team:
        te = resolve_team(conn, team)
        ticket_filter += " AND t.team = ?"
        params.append(te["name"] if te else team)
    if status:
        ticket_filter += " AND t.status = ?"
        params.append(status)
    if type_:
        ticket_filter += " AND t.type = ?"
        params.append(type_)
    if priority:
        ticket_filter += " AND t.priority = ?"
        params.append(priority)
    if assignee:
        ticket_filter += " AND LOWER(t.assignee) = ?"
        params.append(norm_assignee(assignee))
    if model:
        ticket_filter += " AND t.model = ?"
        params.append(model)
    rows = conn.execute(
        "SELECT 'created' AS kind, t.created_at AS ts, t.assignee AS author, "
        "t.ticket_key, t.title, t.title AS text "
        "FROM tickets t WHERE 1=1" + ticket_filter +
        " UNION ALL "
        "SELECT 'note' AS kind, n.created_at AS ts, n.author, "
        "t.ticket_key, t.title, n.text "
        "FROM notes n JOIN tickets t ON t.id = n.ticket_id WHERE 1=1" + ticket_filter +
        " ORDER BY ts DESC LIMIT ?",
        params + params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _watermark(conn, assignee):
    row = conn.execute(
        "SELECT last_event_id, last_note_id FROM inbox_watermarks WHERE assignee = ? COLLATE NOCASE",
        (assignee,),
    ).fetchone()
    return (row["last_event_id"], row["last_note_id"]) if row else (0, 0)


def _mentions(text, name):
    """True if `text` contains an @name mention of `name` as a whole token (not a
    substring of a longer handle) — e.g. '@ben' matches, '@bencool' doesn't."""
    if not text or not name:
        return False
    return re.search(rf"(?<!\w)@{re.escape(name)}(?!\w)", text, re.IGNORECASE) is not None


def get_inbox(assignee):
    """Unseen items for `assignee` since their watermark, excluding entries they
    authored themselves: field updates on tickets assigned to them, plus notes that
    are either on a ticket assigned to them OR @mention them by name anywhere (own
    ticket or not — a mention is a direct flag, independent of assignment). Watermark
    is an id cursor, not a timestamp — avoids missing same-second events. Does not
    consume the watermark — call mark_inbox_seen() for that."""
    conn = get_conn()
    last_event_id, last_note_id = _watermark(conn, assignee)
    rows = conn.execute(
        "SELECT 'event' AS kind, e.id AS row_id, e.created_at AS ts, e.author, t.ticket_key, t.title, "
        "e.field, e.old_value, e.new_value, NULL AS text, t.assignee AS ticket_assignee, "
        "(SELECT p.ticket_key FROM tickets p WHERE p.id = t.parent_id) AS parent_key "
        "FROM ticket_events e JOIN tickets t ON t.id = e.ticket_id "
        "WHERE (t.assignee = ? COLLATE NOCASE OR (e.field = 'created' AND t.parent_id IN "
        "(SELECT w.ticket_id FROM watches w WHERE w.watcher = ?))) AND e.id > ? "
        "UNION ALL "
        "SELECT 'note' AS kind, n.id AS row_id, n.created_at AS ts, n.author, t.ticket_key, t.title, "
        "NULL AS field, NULL AS old_value, NULL AS new_value, n.text, t.assignee AS ticket_assignee, NULL AS parent_key "
        "FROM notes n JOIN tickets t ON t.id = n.ticket_id "
        "WHERE n.id > ? "
        "ORDER BY ts ASC",
        (assignee, assignee, last_event_id, last_note_id),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d["author"] and d["author"].strip().lower() == assignee.strip().lower():
            continue
        if d["kind"] == "event":
            result.append(d)
            continue
        own_ticket = d["ticket_assignee"] and d["ticket_assignee"].strip().lower() == assignee.strip().lower()
        mentioned = _mentions(d["text"], assignee)
        if not (own_ticket or mentioned):
            continue
        d["mentioned"] = mentioned and not own_ticket
        result.append(d)
    return result


def watch_ticket(watcher, tid):
    """Subscribe `watcher` to new children of ticket `tid` (they show up in their inbox)."""
    watcher = norm_assignee(watcher)
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM tickets WHERE id = ?", (tid,)).fetchone():
        conn.close()
        raise TixError(f"no such ticket 'id={tid}'")
    conn.execute("INSERT OR IGNORE INTO watches (watcher, ticket_id) VALUES (?, ?)", (watcher, tid))
    conn.commit()
    conn.close()


def unwatch_ticket(watcher, tid):
    conn = get_conn()
    cur = conn.execute("DELETE FROM watches WHERE watcher = ? AND ticket_id = ?", (norm_assignee(watcher), tid))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def list_watches(watcher):
    conn = get_conn()
    rows = conn.execute(
        "SELECT t.ticket_key, t.title FROM watches w JOIN tickets t ON t.id = w.ticket_id "
        "WHERE w.watcher = ? ORDER BY t.id", (norm_assignee(watcher),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_inbox(assignee):
    if not assignee:
        return 0
    return len(get_inbox(assignee))


def mark_inbox_seen(assignee):
    conn = get_conn()
    max_event = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM ticket_events").fetchone()["m"]
    max_note = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM notes").fetchone()["m"]
    conn.execute(
        "INSERT INTO inbox_watermarks (assignee, last_event_id, last_note_id) VALUES (?, ?, ?) "
        "ON CONFLICT(assignee) DO UPDATE SET last_event_id = excluded.last_event_id, "
        "last_note_id = excluded.last_note_id",
        (assignee, max_event, max_note),
    )
    conn.commit()
    conn.close()


def dashboard_stats():
    """Counts and a per-assignee leaderboard for the web dashboard. Leaderboard is
    keyed off each ticket's current status (open vs done) and assignee -- simple
    current-state read, not an event-history reconstruction, so a ticket that
    bounced done -> reopened -> done again is counted once, at its current state,
    not per transition."""
    conn = get_conn()
    status_counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM tickets GROUP BY status")}
    total = sum(status_counts.values())
    open_count = sum(n for st, n in status_counts.items() if st not in CLOSED_STATUSES)
    done_count = status_counts.get("done", 0)
    blocked_count = status_counts.get("blocked", 0)
    staging_count = status_counts.get("on_staging", 0)

    by_project = [dict(r) for r in conn.execute(
        "SELECT COALESCE(NULLIF(project, ''), '(none)') AS project, COUNT(*) AS n "
        "FROM tickets WHERE status NOT IN ('in_prod','done') GROUP BY project ORDER BY n DESC, project ASC"
    )]

    leaderboard = [dict(r) for r in conn.execute(
        "SELECT assignee, "
        "SUM(CASE WHEN status NOT IN ('in_prod','done') THEN 1 ELSE 0 END) AS open_all, "
        "SUM(CASE WHEN status IN ('in_prod','done') THEN 1 ELSE 0 END) AS done_all "
        "FROM tickets WHERE assignee != '' "
        "GROUP BY assignee COLLATE NOCASE ORDER BY done_all DESC, assignee ASC"
    )]

    by_model = [dict(r) for r in conn.execute(
        "SELECT COALESCE(NULLIF(model, ''), '(none)') AS model, COUNT(*) AS n "
        "FROM tickets GROUP BY model ORDER BY n DESC, model ASC"
    )]

    conn.close()
    return {
        "total": total, "open": open_count, "done": done_count, "blocked": blocked_count, "on_staging": staging_count,
        "by_project": by_project, "leaderboard": leaderboard, "by_model": by_model,
    }
