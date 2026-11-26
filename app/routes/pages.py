from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, get_settings
from ..config import Settings
from ..models import PublicTask

router = APIRouter(tags=["pages"])

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/play")


@router.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
def admin_login(request: Request):
    return TEMPLATES.TemplateResponse(request, "login.html", {"role": "admin", "page": "login"})


@router.get("/teacher/login", response_class=HTMLResponse, include_in_schema=False)
def teacher_login(request: Request):
    return TEMPLATES.TemplateResponse(request, "login.html", {"role": "teacher", "page": "login"})


@router.get("/teacher/claim", response_class=HTMLResponse, include_in_schema=False)
def teacher_claim(request: Request):
    return TEMPLATES.TemplateResponse(request, "claim.html", {"page": "claim"})


@router.get("/teacher/reset", response_class=HTMLResponse, include_in_schema=False)
def teacher_reset(request: Request):
    return TEMPLATES.TemplateResponse(request, "reset.html", {"page": "reset"})


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/admin/login", status_code=302)
    return TEMPLATES.TemplateResponse(request, "admin.html", {"user": user, "page": "admin"})


@router.get("/teacher", response_class=HTMLResponse, include_in_schema=False)
def teacher_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "teacher":
        return RedirectResponse("/teacher/login", status_code=302)
    return TEMPLATES.TemplateResponse(request, "teacher.html", {"user": user, "page": "teacher"})


@router.get("/play", include_in_schema=False)
def play_page(settings: Settings = Depends(get_settings)):
    # No project codes or credentials in a redirect URL.
    return RedirectResponse(settings.editor_url.rstrip("/") + "/?project-code=1", status_code=307)


@router.get("/recover", response_class=HTMLResponse, include_in_schema=False)
def recover_drafts(request: Request, settings: Settings = Depends(get_settings)):
    return TEMPLATES.TemplateResponse(request, "recover.html", {"page": "recovery", "editor_url": settings.editor_url})


@router.get("/player", include_in_schema=False)
def player_page(request: Request, settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    from urllib.parse import urlencode
    params = request.query_params
    endpoint = None
    if params.get("teacher"):
        from .teacher_api import preview_project
        from ..deps import require_teacher
        teacher = require_teacher(request, db)
        pid = _positive_id(params["teacher"])
        preview_project(pid, teacher, db, settings)  # ownership before rendering
        endpoint = f"/api/teacher/projects/{pid}/snapshot"
    elif params.get("submission"):
        from .teacher_api import submission_snapshot
        from ..deps import require_teacher
        teacher = require_teacher(request, db)
        sid, version = _positive_id(params["submission"]), _positive_id(params.get("version", "1"))
        submission_snapshot(sid, version, teacher, db)
        endpoint = f"/api/teacher/submissions/{sid}/versions/{version}"
    elif params.get("public"):
        from .share_api import public_payload
        from urllib.parse import quote
        slug = params["public"]
        public_payload(slug, db)
        endpoint = f"/api/public/{quote(slug, safe='')}"
    if endpoint is None:
        return RedirectResponse(settings.editor_url, status_code=307)
    editor = settings.editor_url.rstrip("/") + "/?" + urlencode({"embed": "1"})
    return TEMPLATES.TemplateResponse(request, "preview.html", {
        "page": "preview", "editor_url": editor, "endpoint": endpoint,
    })


def _positive_id(value):
    try:
        result = int(value)
        if result < 1:
            raise ValueError
        return result
    except ValueError:
        raise HTTPException(422, "Ungültige Vorschau-ID") from None


@router.get("/t/{slug}", response_class=HTMLResponse, include_in_schema=False)
def public_task_page(slug: str, request: Request, db: Session = Depends(get_db)):
    pt = db.query(PublicTask).filter_by(slug=slug, status="published").first()
    if not pt:
        raise HTTPException(404, "Aufgabe nicht öffentlich verfügbar")
    return TEMPLATES.TemplateResponse(
        request,
        "public_task.html",
        {
            "page": "public_task",
            "slug": pt.slug,
            "title": pt.title,
            "description": pt.description,
            "items": json.loads(pt.items),
            "author_alias": pt.author_alias,
            "school": pt.school,
            "license": pt.license,
            "version": pt.version,
            "published_at": pt.published_at.isoformat() if pt.published_at else None,
        },
    )
