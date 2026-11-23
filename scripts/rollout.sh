#!/usr/bin/env bash
# Run on the existing backend host: scripts/rollout.sh /path/to/deployment new-image.tar new-compose.yml new-release.env
set -euo pipefail
cd "$1"
image_archive="$2"
new_compose="$3"
new_release="$4"
test -f backend.env
test -f release.env
test -f compose.yml
# Backup and recovery verification use the currently running release and existing volumes.
docker compose --env-file release.env -f compose.yml run --rm backup
cp release.env release.previous.env
cp compose.yml compose.previous.yml
rollback() {
  cp release.previous.env release.env
  cp compose.previous.yml compose.yml
  docker compose --env-file release.env -f compose.yml up -d backend
}
trap rollback ERR
docker load -i "$image_archive"
cp "$new_compose" compose.yml
python3 - "$new_release" <<'PYENV'
from pathlib import Path
import sys
new = Path(sys.argv[1]).read_text().strip()
p = Path("release.env")
lines = [line for line in p.read_text().splitlines() if not line.startswith("BACKEND_IMAGE=")]
p.write_text("\n".join([*lines, new]) + "\n")
PYENV
docker compose --env-file release.env -f compose.yml up -d --wait backend
docker exec miniworlds-backend python -c 'import json,urllib.request; m=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/compatibility",timeout=10)); assert m["api"]["min"] <= 1 <= m["api"]["max"]'
trap - ERR
printf '%s\n' 'Backend updated; previous release retained in release.previous.env and compose.previous.yml.'
