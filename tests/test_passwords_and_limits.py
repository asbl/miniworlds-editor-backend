from __future__ import annotations

from sqlalchemy import inspect, text

from app.main import create_app

from .conftest import auth, create_project, login, make_teacher, student_token

TEACHER = "lehrer@schule.de"


def _teacher_login(client, password):
    return client.post("/api/auth/login", json={"email": TEACHER, "password": password, "role": "teacher"})


def test_successful_logins_are_never_rate_limited(client, teacher_csrf):
    code = create_project(client, teacher_csrf)[0]["code"]
    assert all(_teacher_login(client, "lehrerpw123").status_code == 200 for _ in range(15))
    assert all(client.post("/api/claim", json={"code": code}).status_code == 200 for _ in range(40))


def test_teacher_changes_password_and_other_sessions_end(client, client2, teacher_csrf):
    assert _teacher_login(client2, "lehrerpw123").status_code == 200
    headers = {"X-CSRF-Token": teacher_csrf}
    wrong = client.post("/api/auth/password", json={"current_password": "falsch", "new_password": "neues-passwort"}, headers=headers)
    assert wrong.status_code == 400
    assert client.post("/api/auth/password", json={"current_password": "lehrerpw123", "new_password": "neues-passwort"}).status_code == 403
    changed = client.post("/api/auth/password", json={"current_password": "lehrerpw123", "new_password": "neues-passwort"}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert client.get("/api/teacher/me").status_code == 200
    assert client2.get("/api/teacher/me").status_code == 401
    assert _teacher_login(client2, "lehrerpw123").status_code == 401
    assert _teacher_login(client2, "neues-passwort").status_code == 200


def test_admin_reset_code_works_once_and_only_for_that_teacher(client, client2):
    make_teacher(client2)
    csrf = login(client, "admin@schule.de", "adminpw123", "admin")
    teacher = client.get("/api/admin/teachers").json()["teachers"][0]
    url = f"/api/admin/teachers/{teacher['id']}/reset-code"
    old = client.post(url, headers={"X-CSRF-Token": csrf}).json()["code"]
    code = client.post(url, headers={"X-CSRF-Token": csrf}).json()["code"]
    body = {"email": TEACHER, "new_password": "vergessen-neu"}
    assert client.post("/api/auth/reset", json={**body, "code": old}).status_code == 401
    assert client.post("/api/auth/reset", json={**body, "email": "x@schule.de", "code": code}).status_code == 401
    assert client2.get("/api/teacher/me").status_code == 200
    assert client.post("/api/auth/reset", json={**body, "code": code}).status_code == 200
    assert client2.get("/api/teacher/me").status_code == 401
    assert client.post("/api/auth/reset", json={**body, "code": code}).status_code == 401
    assert _teacher_login(client2, "vergessen-neu").status_code == 200


def test_expired_reset_code_is_refused(client, client2, app):
    from datetime import timedelta

    from app.models import PasswordReset, utcnow

    make_teacher(client2)
    csrf = login(client, "admin@schule.de", "adminpw123", "admin")
    teacher = client.get("/api/admin/teachers").json()["teachers"][0]
    code = client.post(f"/api/admin/teachers/{teacher['id']}/reset-code", headers={"X-CSRF-Token": csrf}).json()["code"]
    with app.state.SessionLocal() as db:
        db.get(PasswordReset, teacher["id"]).expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.post("/api/auth/reset", json={"email": TEACHER, "code": code, "new_password": "vergessen-neu"}).status_code == 401
    assert client.get("/teacher/reset").status_code == 200


def test_pupil_can_request_publication(client, teacher_csrf):
    token = student_token(client, create_project(client, teacher_csrf)[0]["code"])
    response = client.post("/api/play/share-request", json={"declaration_accepted": True}, headers=auth(token))
    assert response.status_code == 200, response.text
    assert client.get("/api/play/share-status", headers=auth(token)).json()["status"] == "pending"


def test_stored_git_remote_tokens_are_removed_on_upgrade(app, settings):
    with app.state.engine.begin() as conn:
        conn.execute(text("CREATE TABLE project_remotes (project_id INTEGER PRIMARY KEY, token_enc VARCHAR)"))
    upgraded = create_app(settings, enable_yearly_task=False)
    assert "project_remotes" not in inspect(upgraded.state.engine).get_table_names()
