from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.retention import maybe_retention

from .conftest import auth, create_project, student_token


# ---------- Separate frontend ----------


def test_player_config_points_to_editor(client, settings):
    assert client.get("/api/player/config").json() == {"editor_url": settings.editor_url, "api_version": 1}
    assert client.get("/wheel/miniworlds.whl").status_code == 404


def test_player_without_snapshot_redirects_to_editor(client, settings):
    r = client.get("/player", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == settings.editor_url


# ---------- Retention ----------


def _db(app):
    return app.state.SessionLocal()


def test_retention_read_only_then_delete(app, client, teacher_csrf, settings):
    p = create_project(client, teacher_csrf)[0]
    token = student_token(client, p["code"])
    client.put("/api/play/save", json={"source": "x"}, headers=auth(token))
    db = _db(app)
    try:
        from app.models import Project

        now = datetime(2026, 11, 22, tzinfo=timezone.utc)
        # frisches Projekt: nichts passiert
        res = maybe_retention(db, settings, now=now)
        assert res["set_read_only"] == 0 and res["deleted"] == 0
        # gleicher Tag: übersprungen
        res = maybe_retention(db, settings, now=now)
        assert res.get("skipped") is True
        # last_save vor 25 Monaten → read-only
        old = now - timedelta(days=25 * 31)
        db.query(Project).update({"last_save_at": old})
        db.commit()
        res = maybe_retention(db, settings, now=now + timedelta(days=1))
        assert res["set_read_only"] == 1
        assert db.get(Project, p["id"]).read_only is True
        # 37 Monate alt → gelöscht
        older = now - timedelta(days=37 * 31)
        db.query(Project).update({"last_save_at": older, "read_only": False})
        db.commit()
        res = maybe_retention(db, settings, now=now + timedelta(days=2))
        assert res["deleted"] == 1
        assert db.get(Project, p["id"]) is None
        # Schüler-Token danach ungültig
        assert client.get("/api/play/project", headers=auth(token)).status_code == 401
    finally:
        db.close()


# ---------- DSGVO-Export ----------


def test_teacher_export(client, teacher_csrf):
    p = create_project(client, teacher_csrf)[0]
    token = student_token(client, p["code"])
    client.put("/api/play/save", json={"source": "print(1)"}, headers=auth(token))
    r = client.get("/api/teacher/export", headers={"X-CSRF-Token": teacher_csrf})
    assert r.status_code == 200
    d = r.json()
    assert d["user"]["email"] == "lehrer@schule.de"
    assert d["projects"][0]["id"] == p["id"]
    assert d["projects"][0]["save_size_bytes"] > 0
    # keine Schüler-Namen serverseitig — Export enthält keine Namensfelder
    assert "name" not in str(d).lower().replace("orig_name", "").replace("filename", "")


# ---------- Öffentliche Aufgaben-Seite ----------


def test_public_task_page(client, teacher_csrf):
    r = client.post("/api/teacher/tasks", json={"title": "Öff. Aufgabe", "description": "d"}, headers={"X-CSRF-Token": teacher_csrf})
    tid = r.json()["task"]["id"]
    client.post(f"/api/teacher/tasks/{tid}/items", json={"kind": "checkbox", "prompt": "Check mich"}, headers={"X-CSRF-Token": teacher_csrf})
    pt = client.post(f"/api/teacher/tasks/{tid}/publish", json={"author_alias": "A"}, headers={"X-CSRF-Token": teacher_csrf}).json()["public_task"]
    r = client.get(f"/t/{pt['slug']}")
    assert r.status_code == 200 and "Öff. Aufgabe" in r.text and "Check mich" in r.text
    assert client.get("/t/gibts-nicht").status_code == 404
    # hidden → 404
    client.post(f"/api/teacher/public-tasks/{pt['id']}/unpublish", json={}, headers={"X-CSRF-Token": teacher_csrf})
    assert client.get(f"/t/{pt['slug']}").status_code == 404
