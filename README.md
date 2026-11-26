# miniworlds-editor-backend

Optional classroom storage for [miniworlds-editor](https://github.com/asbl/miniworlds-editor).
The editor works as a static application without cloning, installing or running this repository.
The [miniworlds engine](https://github.com/asbl/miniworlds) is released independently on PyPI.

This repository owns project codes, optional passwords, courses, tasks, submissions,
media, server-side Git history, publication, backups and teacher/admin dashboards.
All pupil editing and execution use **https://editor.opencoding.de**.
There is no Python engine source, wheel build, pupil editor or Pyodide runtime here.

## Local development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pytest
# Configure a persistent SECRET_KEY and optional ADMIN_EMAIL / ADMIN_PASSWORD in the environment.
EDITOR_URL=http://localhost:5173 FRONTEND_ORIGINS=http://localhost:5173 \
  uvicorn app.main:create_app --factory --port 8000
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

`SECRET_KEY` is required and must be kept with the backups. No credentials are tracked.
Teacher/admin pages remain on the backend origin. Pupil Bearer tokens remain in the editor tab;
the editor never sends teacher cookies. `/play` redirects to the configured `EDITOR_URL`.
Old tab-local unsaved drafts can be exported at `/recover` (linked from the editor code dialog); they are never deleted or sent with access tokens.
The API names `/api/claim` and `/api/play/*` stay unchanged, as do the database and storage formats.

Teacher, submitted-version and public previews embed the real editor with `?embed=1`.
Only a checked snapshot of project files is sent by `postMessage`, to the exact editor origin.
The frontend must declare `read-only-preview` before receiving files. Teacher cookies and tokens
are never transferred. Configure the backend origin in the editor's `embedOrigins` and CSP
`frame-ancestors`; configure `EDITOR_URL` and `FRONTEND_ORIGINS` on the backend.

## Rate limits and passwords

A whole school often shares one IP address. Only failed attempts are limited per IP (300 unknown
codes per minute), a valid code is never refused because of the IP, and wrong project passwords
are counted per code. The compose file trusts `X-Forwarded-For` from private networks only
(`FORWARDED_ALLOW_IPS`). With rootless Docker the proxy may still see one address for everybody;
the limits are chosen so that this does not block lessons.

Teachers and admins change their password on their dashboard. For a forgotten teacher password,
the admin creates a one-time code (valid 24 hours) which is redeemed at `/teacher/reset`.

Git remotes (push/pull) have been removed. Starting this release drops the stored remote tokens;
the backup taken by the rollout still contains them.

## Compatibility and updates

`GET /api/compatibility` reports API ranges, required frontend capabilities and the built revision.
The frontend publishes `/compatibility.json` and sends `X-Miniworlds-API: 1` with requests.
Unsupported versions receive HTTP 426 before any database write. Compatible updates can be
released independently. A breaking protocol change must change the declared ranges and provide
an overlap/migration period; a newer commit alone does not imply a required counterpart update.

```sh
python scripts/check_compatibility.py \
  --frontend https://editor.opencoding.de/compatibility.json \
  --backend https://backend.editor.opencoding.de/api/compatibility
```

The checker exits nonzero and names the component requiring an update. Both repositories run
real cross-origin editor/backend tests on pushes/PRs and daily against the other repository's
`main`. Workflow dispatch accepts a tag or exact commit to test a planned release pair.
No cross-repository write token or mandatory backend clone is needed for normal editor use.

## Deployment and migration

```sh
docker build -t miniworlds-backend:tested .
DEPLOY_TARGET=user@host:/existing/backend/path scripts/deploy.sh
```

The Docker build needs only this checkout and does not download/build miniworlds. Runtime
execution and engine version selection belong to the frontend. The image runs as UID 10001.
`deploy/compose.yml` keeps the existing `miniworlds-backend` container and volume names
`miniworlds-backend-data` / `miniworlds-backend-backups`. Keep `backend.env`, `SECRET_KEY`,
database/media/Git storage, backup timer location, domain, CORS origins and TLS settings.
Do not create new volumes or reset credentials for the repository migration.

The deployment helper checks frontend compatibility, requires a committed release, builds a
revision-labelled image, and invokes `scripts/rollout.sh` on the existing host. The rollout first
creates and verifies a backup with the old image, retains the previous Compose configuration and
image reference, then starts the new image and checks its API. A failure restores the old
configuration. `BACKEND_RUNTIME` in the existing release environment remains supported.
For a coordinated first rollout, `FRONTEND_MANIFEST=/path/to/tested/frontend/compatibility.json`
checks the planned frontend artifact; deploy the backend first and the frontend immediately after,
then check both live manifests. Older preview frontends are refused rather than shown editable.

Rollback: restore `release.previous.env` and `compose.previous.yml` and run Compose again.
Backups: `docker compose --env-file release.env -f compose.yml run --rm backup`.
The existing systemd timer in `deploy/` continues to use `~/projects/miniworlds-backend`.

## Origin

Extracted with `git subtree split --prefix=backend` from `asbl/miniworlds`, source commit
`32ec5c0d983c463f1bfe3be7be40451aebd06928`. The six original backend commits and their authors
are retained in this repository. No existing repository history was rewritten.
