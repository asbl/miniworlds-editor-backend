"""Server-seitige git-Repositories pro Schülerprojekt.

Jedes Projekt erhält unter ``settings.git_root`` ein eigenes git-Repository
(Arbeitsbaum mit ``main.py``, ``save.db`` und ``media/``). Jeder Speichervorgang
im Player erzeugt einen Commit — das ist die git-Integration für Schüler:
Verlauf ansehen, alten Stand ansehen und wiederherstellen.

Das Modul hängt nur von der Config ab und kapselt alle subprocess-Aufrufe.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import fcntl
from functools import wraps
from pathlib import Path

from .config import Settings

AUTHOR = "miniworlds server"
EMAIL = "server@miniworlds.local"

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


class GitError(Exception):
    """git-Vorgang fehlgeschlagen; die Message ist deutsch und für Schüler geeignet."""


def git_available() -> bool:
    return shutil.which("git") is not None


def repo_dir(settings: Settings, project_id: int) -> Path:
    return Path(settings.git_root) / f"project-{project_id}"


def locked_project(function):
    @wraps(function)
    def run(settings, project_id, *args, **kwargs):
        root = Path(settings.git_root)
        root.mkdir(parents=True, exist_ok=True)
        # Außerhalb des Repos, damit Löschen den Lock nicht ungültig macht.
        with (root / f".project-{project_id}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return function(settings, project_id, *args, **kwargs)
    return run


def history_bytes(settings: Settings, project_id: int) -> int:
    directory = repo_dir(settings, project_id) / ".git"
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            pass  # eine parallele git gc kann lose Objekte gerade ersetzen
    return total


def history_paused(settings: Settings, project_id: int) -> bool:
    return (repo_dir(settings, project_id) / ".history-full").exists()


@locked_project
def history_bundle(settings: Settings, project_id: int) -> bytes:
    repo = _require_repo(settings, project_id)
    with tempfile.TemporaryDirectory(prefix="mw-history-") as directory:
        target = Path(directory) / "history.bundle"
        _checked(repo, "bundle", "create", str(target), "HEAD")
        return target.read_bytes()


@locked_project
def delete_repo(settings: Settings, project_id: int) -> None:
    path = repo_dir(settings, project_id)
    if path.exists():
        shutil.rmtree(path)


def _git(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    if not repo.is_dir():
        raise GitError("Repository existiert noch nicht")
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise GitError("git ist auf dem Server nicht installiert") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"git {' '.join(args[:2])} wurde nach {timeout}s abgebrochen") from None


def _checked(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    result = _git(repo, *args, timeout=timeout)
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "replace").strip()
        raise GitError(err[:300] if err else f"git {args[0]} ist fehlgeschlagen")
    return result


def _out(result: subprocess.CompletedProcess) -> str:
    return result.stdout.decode("utf-8", "replace")


def _ensure_identity(repo: Path) -> None:
    if not _out(_git(repo, "config", "user.email")).strip():
        _checked(repo, "config", "user.name", AUTHOR)
        _checked(repo, "config", "user.email", EMAIL)


def ensure_repo(settings: Settings, project_id: int) -> Path:
    repo = repo_dir(settings, project_id)
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        _checked(repo, "init")
        _ensure_identity(repo)
    return repo


def _sync_media(repo: Path, media_src: Path) -> None:
    dst = repo / "media"
    names = {f.name for f in media_src.iterdir() if f.is_file()} if media_src.is_dir() else set()
    if names:
        dst.mkdir(exist_ok=True)
        for name in names:
            shutil.copy2(media_src / name, dst / name)
    if dst.is_dir():
        for f in dst.iterdir():
            if f.is_file() and f.name not in names:
                f.unlink()


def _check_worktree(repo: Path) -> None:
    # Ältere Versionen konnten Remotes laden, die main.py, save.db oder media als
    # Link auschecken. Kein anschließender Schreib-/Kopiervorgang darf solchen Links folgen.
    if repo.is_symlink() or any(path.is_symlink() for path in repo.rglob("*")):
        raise GitError("Symbolische Links sind in Projekt-Repositories nicht erlaubt.")


def _commit_if_dirty(repo: Path, message: str, settings: Settings, project_id: int) -> str | None:
    if history_paused(settings, project_id):
        raise GitError("Der Versionsverlauf ist voll und pausiert. Dein aktuelles Projekt ist gespeichert. Lade den Verlauf herunter oder lösche ihn, um neue Versionen anzulegen.")
    old_head = _git(repo, "rev-parse", "--verify", "HEAD")
    _checked(repo, "add", "-A")
    if _git(repo, "diff", "--cached", "--quiet").returncode == 0:
        return None  # keine Änderungen seit dem letzten Commit
    _checked(repo, "commit", "-m", message)
    if history_bytes(settings, project_id) > settings.history_max_bytes:
        # Verdichten, bevor das Budget als voll gilt. Einen zu großen neuen
        # Commit wieder entfernen; der aktuelle Arbeitsstand bleibt in der DB.
        _checked(repo, "gc", "--prune=now")
        if history_bytes(settings, project_id) > settings.history_max_bytes:
            if old_head.returncode == 0:
                _checked(repo, "reset", "--mixed", _out(old_head).strip())
            else:
                ref = _out(_checked(repo, "symbolic-ref", "HEAD")).strip()
                _checked(repo, "update-ref", "-d", ref)
                _checked(repo, "read-tree", "--empty")
            _checked(repo, "reflog", "expire", "--expire=now", "--all")
            _checked(repo, "gc", "--prune=now")
            (repo / ".history-full").touch()
            raise GitError("Der Versionsverlauf ist voll und pausiert. Dein aktuelles Projekt ist gespeichert. Vorhandene Versionen kannst du weiterhin herunterladen.")
    return _out(_checked(repo, "rev-parse", "--short", "HEAD")).strip()


@locked_project
def commit_save(
    settings: Settings,
    project_id: int,
    source: str,
    db_bytes: bytes | None,
    message: str,
    files: dict[str, str] | None = None,
) -> str | None:
    """Schreibt main.py/save.db/media ins Repo und committet. None bei leerem Commit."""
    if not git_available():
        return None
    repo = ensure_repo(settings, project_id)
    _check_worktree(repo)
    if files is not None:
        from .editor_files import MANIFEST, validate_files
        validate_files(files)
        (repo / MANIFEST).write_text(json.dumps(files), encoding="utf-8")
    (repo / "main.py").write_text(source, encoding="utf-8")
    db_file = repo / "save.db"
    if db_bytes is None:
        db_file.unlink(missing_ok=True)
    else:
        db_file.write_bytes(db_bytes)
    _sync_media(repo, Path(settings.media_root) / str(project_id))
    return _commit_if_dirty(repo, message.strip() or "Speichern", settings, project_id)


@locked_project
def commit_media(settings: Settings, project_id: int, message: str) -> str | None:
    """Nur die Medien ins Repo übernehmen und committen (Upload/Löschen)."""
    if not git_available():
        return None
    repo = ensure_repo(settings, project_id)
    _check_worktree(repo)
    _sync_media(repo, Path(settings.media_root) / str(project_id))
    return _commit_if_dirty(repo, message.strip() or "Medien aktualisiert", settings, project_id)


def _require_repo(settings: Settings, project_id: int) -> Path:
    repo = repo_dir(settings, project_id)
    if not (repo / ".git").exists():
        raise GitError("Für dieses Projekt gibt es noch keinen Versionsverlauf")
    return repo


def history(settings: Settings, project_id: int, limit: int = 50) -> list[dict]:
    """Commits, neueste zuerst: [{hash, short, date, message}]."""
    repo = repo_dir(settings, project_id)
    if not (repo / ".git").exists():
        return []
    result = _git(repo, "log", f"--max-count={int(limit)}", "--pretty=format:%H%x00%h%x00%ad%x00%s", "--date=iso-strict")
    if result.returncode != 0:
        return []
    commits = []
    for line in _out(result).splitlines():
        parts = line.split("\0")
        if len(parts) == 4:
            commits.append({"hash": parts[0], "short": parts[1], "date": parts[2], "message": parts[3]})
    return commits


def _check_commit(commit: str) -> str:
    commit = (commit or "").strip().lower()
    if commit == "head":
        return "HEAD"
    if not _COMMIT_RE.match(commit):
        raise GitError(f"Ungültiger Commit-Bezeichner: {commit!r}")
    return commit


def read_save_at(settings: Settings, project_id: int, commit: str) -> bytes:
    """Save-Payload (JSON: source + base64-db) aus einem Commit rekonstruieren."""
    repo = _require_repo(settings, project_id)
    commit = _check_commit(commit)
    source = _out(_checked(repo, "show", f"{commit}:main.py"))
    db_result = _git(repo, "show", f"{commit}:save.db")
    db_b64 = base64.b64encode(db_result.stdout).decode() if db_result.returncode == 0 and db_result.stdout else None
    from .editor_files import MANIFEST, save_payload
    manifest = _git(repo, "show", f"{commit}:{MANIFEST}")
    try:
        files = json.loads(manifest.stdout) if manifest.returncode == 0 else None
        return json.dumps(save_payload(source, db_b64, files)).encode()
    except Exception as error:
        raise GitError("Ungültige Editor-Projektdateien im Versionsverlauf") from error


