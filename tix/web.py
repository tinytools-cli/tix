from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db as tixdb

tixdb.init_db()

app = FastAPI(title="tix")


class TicketIn(BaseModel):
    type: str = "task"
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "med"
    parent_id: Optional[str] = None
    blocked_by: Optional[str] = None
    project: str  # required — every ticket needs one, see db.add_ticket
    team: str = ""
    assignee: str = ""
    model: str  # required — which model is doing the work, see db.add_ticket
    tags: str = ""


class TicketPatch(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    parent_id: Optional[str] = None
    blocked_by: Optional[str] = None
    project: Optional[str] = None
    team: Optional[str] = None
    assignee: Optional[str] = None
    model: Optional[str] = None
    tags: Optional[str] = None


class ProjectIn(BaseModel):
    name: str
    folder: str  # required — where this project's context/files live, see db.add_project
    key: Optional[str] = None


class TeamIn(BaseModel):
    name: str


def _resolve_or_404(tid: str) -> int:
    real = tixdb.resolve_ticket_id(tid)
    if real is None:
        raise HTTPException(404, f"no such ticket '{tid}'")
    return real


@app.get("/api/tickets")
def api_list(status: Optional[str] = None, type: Optional[str] = None,
             priority: Optional[str] = None, parent_id: Optional[str] = None,
             blocked_by: Optional[str] = None, project: Optional[str] = None, team: Optional[str] = None,
             assignee: Optional[str] = None, model: Optional[str] = None, q: Optional[str] = None):
    if q:
        return tixdb.search_tickets(q)
    pid = _resolve_or_404(parent_id) if parent_id else None
    bid = _resolve_or_404(blocked_by) if blocked_by else None
    return tixdb.list_tickets(status, type, priority, pid, project, team, assignee, model, bid)


@app.post("/api/tickets")
def api_add(t: TicketIn):
    pid = _resolve_or_404(t.parent_id) if t.parent_id else None
    bid = _resolve_or_404(t.blocked_by) if t.blocked_by else None
    try:
        tid = tixdb.add_ticket(t.type, t.title, t.description, t.status, t.priority, pid,
                                t.project, t.team, t.assignee, t.model, t.tags, bid)
    except tixdb.TixError as e:
        raise HTTPException(400, str(e))
    return tixdb.get_ticket(tid)


@app.get("/api/tickets/{tid}")
def api_get(tid: str):
    t = tixdb.get_ticket(_resolve_or_404(tid))
    return t


@app.patch("/api/tickets/{tid}")
def api_patch(tid: str, patch: TicketPatch):
    real_id = _resolve_or_404(tid)
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "parent_id" in fields:
        fields["parent_id"] = _resolve_or_404(fields["parent_id"]) if fields["parent_id"] else None
    if "blocked_by" in fields:
        fields["blocked_by"] = _resolve_or_404(fields["blocked_by"]) if fields["blocked_by"] else None
    try:
        t = tixdb.update_ticket(real_id, **fields)
    except tixdb.TixError as e:
        raise HTTPException(400, str(e))
    return t


@app.delete("/api/tickets/{tid}")
def api_delete(tid: str):
    tixdb.delete_ticket(_resolve_or_404(tid))
    return {"ok": True}


class NoteIn(BaseModel):
    text: str
    author: str = ""


@app.get("/api/tickets/{tid}/notes")
def api_notes_list(tid: str):
    return tixdb.list_notes(_resolve_or_404(tid))


@app.post("/api/tickets/{tid}/notes")
def api_notes_add(tid: str, n: NoteIn):
    if not n.author.strip():
        raise HTTPException(400, "author is required -- a note with no author is unreadable history")
    real_id = _resolve_or_404(tid)
    tixdb.add_note(real_id, n.text, n.author)
    return tixdb.list_notes(real_id)


@app.get("/api/activity")
def api_activity(limit: int = 20, project: Optional[str] = None, team: Optional[str] = None,
                  status: Optional[str] = None, type: Optional[str] = None,
                  priority: Optional[str] = None, assignee: Optional[str] = None,
                  model: Optional[str] = None):
    return tixdb.recent_activity(limit, project, team, status, type, priority, assignee, model)


@app.get("/api/projects")
def api_projects():
    return tixdb.list_projects_registry()


@app.post("/api/projects")
def api_project_add(p: ProjectIn):
    try:
        return tixdb.add_project(p.name, p.folder, p.key)
    except tixdb.TixError as e:
        raise HTTPException(400, str(e))


class ProjectRename(BaseModel):
    name: str


@app.patch("/api/projects/{identifier}")
def api_project_rename(identifier: str, p: ProjectRename):
    try:
        return tixdb.rename_project(identifier, p.name)
    except tixdb.TixError as e:
        raise HTTPException(400, str(e))


@app.get("/api/teams")
def api_teams():
    return tixdb.list_teams_registry()


@app.post("/api/teams")
def api_team_add(t: TeamIn):
    return tixdb.add_team(t.name)


@app.get("/api/stats")
def api_stats():
    return tixdb.dashboard_stats()


@app.get("/api/meta")
def api_meta():
    return {
        "types": tixdb.TYPES,
        "statuses": tixdb.STATUSES,
        "priorities": tixdb.PRIORITIES,
        "projects": [p["name"] for p in tixdb.list_projects_registry()],
        "teams": [t["name"] for t in tixdb.list_teams_registry()],
    }


static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def main():
    """Entry point for the `tix-web` console script -- `uvicorn web:app` works too,
    this just saves remembering the module:app spelling."""
    import os
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("TIX_WEB_PORT", "8791")))


@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")
