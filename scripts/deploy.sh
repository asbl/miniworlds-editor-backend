#!/usr/bin/env bash
# DEPLOY_TARGET=user@host:/existing/backend/path [DEPLOY_SSH_PORT=22] scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DEPLOY_TARGET:?set DEPLOY_TARGET=user@host:/existing/backend/path}"
port="${DEPLOY_SSH_PORT:-22}"
host="${DEPLOY_TARGET%%:*}"
remote_dir="${DEPLOY_TARGET#*:}"
test "$host" != "$remote_dir"
python3 scripts/check_compatibility.py --frontend "${FRONTEND_MANIFEST:-https://editor.opencoding.de/compatibility.json}" --backend app/compatibility.json
revision="$(git rev-parse HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
  printf '%s\n' 'Commit the tested backend release before deployment.' >&2
  exit 1
fi
image="miniworlds-backend:$revision"
docker build --build-arg "BACKEND_REVISION=$revision" -t "$image" .
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
docker save -o "$stage/image.tar" "$image"
printf 'BACKEND_IMAGE=%s\n' "$image" > "$stage/release.next.env"
cp deploy/compose.yml "$stage/compose.next.yml"
cp scripts/rollout.sh "$stage/rollout.sh"
# Quote the server directory once for the remote shell, including spaces and quotes.
printf -v remote_quoted '%q' "$remote_dir"
ssh -p "$port" "$host" "test -d $remote_quoted && mkdir -p $remote_quoted/incoming"
scp -P "$port" "$stage/image.tar" "$stage/release.next.env" "$stage/compose.next.yml" "$stage/rollout.sh" "$host:$remote_dir/incoming/"
ssh -p "$port" "$host" "bash $remote_quoted/incoming/rollout.sh $remote_quoted incoming/image.tar incoming/compose.next.yml incoming/release.next.env"
