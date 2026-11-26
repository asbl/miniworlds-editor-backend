from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..config import Settings
from ..deps import get_current_user, get_db, get_settings, require_csrf
from ..models import Session as DbSession
from ..models import PasswordReset, TeacherInvite, User, aware, utcnow
from ..security import (
    csrf_token,
    gen_code,
    hash_code,
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/session")
def current_session(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "Nicht angemeldet")
    return {"role": user.role, "csrf": csrf_token(request.app.state.settings.secret_key, request.cookies["session"])}


def _issue_session(response: Response, db: Session, settings: Settings, user: User) -> dict:
    token = new_session_token()
    db.add(
        DbSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=settings.session_hours),
        )
    )
    db.commit()
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return {"ok": True, "role": user.role, "csrf": csrf_token(settings.secret_key, token)}


class LoginIn(BaseModel):
    email: str
    password: str
    role: str  # admin | teacher


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    ip = request.client.host if request.client else "?"
    email = body.email.strip().lower()
    rl = request.app.state.rate_limiter
    # Fehlversuche pro IP und pro Account begrenzen (Password-Spraying erschweren).
    # Die IP-Grenze ist großzügig, weil sich eine Schule eine IP teilen kann.
    if not rl.allow(f"login-ip:{ip}", 100, 900) or not rl.allow(f"login-acct:{email}", 10, 900):
        raise HTTPException(429, "Zu viele Versuche — bitte später erneut versuchen")
    # abgelaufene Sessions opportunistisch aufräumen
    db.query(DbSession).filter(DbSession.expires_at < utcnow()).delete(synchronize_session=False)
    user = db.query(User).filter_by(email=email).first()
    if (
        not user
        or not verify_password(body.password, user.pw_hash)
        or user.role != body.role
        or user.disabled
    ):
        raise HTTPException(401, "Ungültige Zugangsdaten")
    rl.forgive(f"login-ip:{ip}")
    rl.forgive(f"login-acct:{email}")
    log_audit(db, user.role, f"user:{user.id}", "login", target=user.role)
    return _issue_session(response, db, settings, user)


class ClaimIn(BaseModel):
    invite_code: str
    email: str
    password: str


@router.post("/claim")
def claim(body: ClaimIn, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Lehrer-Account per Invite-Code anlegen (kein Name, nur E-Mail + Passwort; Schule kommt aus dem Invite)."""
    ip = request.client.host if request.client else "?"
    if not request.app.state.rate_limiter.allow(f"claim:{ip}", 100, 900):
        raise HTTPException(429, "Zu viele Versuche — bitte später erneut versuchen")
    ch = hash_code(body.invite_code)
    if not request.app.state.rate_limiter.allow(f"claim-code:{ch[:16]}", 10, 60):
        raise HTTPException(429, "Zu viele Versuche für diesen Code")
    inv = db.query(TeacherInvite).filter_by(code_hash=ch).first()
    if not inv or inv.claimed_at or (inv.expires_at and aware(inv.expires_at) < utcnow()):
        raise HTTPException(401, "Lehrercode ungültig, bereits eingelöst oder abgelaufen")
    email = body.email.strip().lower()
    if inv.email and inv.email.lower() != email:
        raise HTTPException(400, "Diese E-Mail-Adresse passt nicht zum Lehrercode")
    if len(body.password) < 8:
        raise HTTPException(400, "Passwort muss mindestens 8 Zeichen haben")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "Für diese E-Mail existiert bereits ein Account")
    user = User(role="teacher", email=email, pw_hash=hash_password(body.password), school=inv.school)
    db.add(user)
    db.flush()
    inv.claimed_at = utcnow()
    inv.claimed_by = user.id
    request.app.state.rate_limiter.forgive(f"claim:{ip}")
    log_audit(db, "teacher", f"user:{user.id}", "claim", target=f"invite:{inv.id}", meta={"school": inv.school})
    return _issue_session(response, db, settings, user)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("session")
    if token:
        sess = db.query(DbSession).filter_by(token_hash=hash_token(token)).first()
        if sess:
            db.delete(sess)
            db.commit()
    response.delete_cookie("session", path="/")
    return {"ok": True}


@router.post("/invite-code-check")
def invite_code_check(body: ClaimIn, request: Request, db: Session = Depends(get_db)):
    """Prüft ohne Einzulösen, ob ein Lehrercode gültig ist (für das Claim-Formular)."""
    ip = request.client.host if request.client else "?"
    rl = request.app.state.rate_limiter
    ch = hash_code(body.invite_code)
    if not rl.allow(f"invite-ip:{ip}", 100, 60) or not rl.allow(f"invite-code:{ch[:16]}", 10, 60):
        raise HTTPException(429, "Zu viele Versuche")
    inv = db.query(TeacherInvite).filter_by(code_hash=ch).first()
    if not inv or inv.claimed_at or (inv.expires_at and aware(inv.expires_at) < utcnow()):
        raise HTTPException(401, "Ungültiger Code")
    rl.forgive(f"invite-ip:{ip}")
    return {"school": inv.school, "email": inv.email}


MIN_PASSWORD = 8


def _set_password(db: Session, user: User, password: str) -> None:
    """Neues Passwort; alle Sitzungen und offenen Rücksetzcodes verfallen."""
    user.pw_hash = hash_password(password)
    db.query(DbSession).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(PasswordReset).filter_by(user_id=user.id).delete(synchronize_session=False)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=256)


@router.post("/password", dependencies=[Depends(require_csrf)])
def change_password(body: PasswordChangeIn, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "Nicht angemeldet")
    rl = request.app.state.rate_limiter
    if not rl.allow(f"password-change:{user.id}", 10, 900):
        raise HTTPException(429, "Zu viele Versuche — bitte später erneut versuchen")
    if not verify_password(body.current_password, user.pw_hash):
        raise HTTPException(400, "Das aktuelle Passwort ist falsch")
    rl.forgive(f"password-change:{user.id}")
    _set_password(db, user, body.new_password)
    log_audit(db, user.role, f"user:{user.id}", "password_changed")
    # Die eigene Sitzung wird neu ausgestellt (Cookie und CSRF-Token ändern sich).
    return _issue_session(response, db, settings, user)


class PasswordResetIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    email: str = Field(max_length=255)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=256)


@router.post("/reset")
def reset_password(body: PasswordResetIn, request: Request, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    ip = request.client.host if request.client else "?"
    rl = request.app.state.rate_limiter
    if not rl.allow(f"reset:{ip}", 50, 900):
        raise HTTPException(429, "Zu viele Versuche — bitte später erneut versuchen")
    email = body.email.strip().lower()
    row = db.query(PasswordReset).filter_by(code_hash=hash_code(body.code)).first()
    user = db.get(User, row.user_id) if row else None
    if not user or user.email != email or user.role != "teacher" or user.disabled or aware(row.expires_at) < utcnow():
        raise HTTPException(401, "Code oder E-Mail ungültig, oder der Code ist abgelaufen")
    # Atomar verbrauchen: zwei gleichzeitige Anfragen dürfen den Code nicht doppelt nutzen.
    if db.query(PasswordReset).filter_by(user_id=user.id, code_hash=row.code_hash).delete(synchronize_session=False) != 1:
        raise HTTPException(401, "Code bereits eingelöst")
    rl.forgive(f"reset:{ip}")
    rl.reset(f"login-acct:{email}")
    _set_password(db, user, body.new_password)
    log_audit(db, "teacher", f"user:{user.id}", "password_reset")
    return _issue_session(response, db, settings, user)


__all__ = ["router", "gen_code"]
