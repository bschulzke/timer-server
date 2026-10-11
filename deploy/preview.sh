#!/bin/sh
# PR previews for the Shenan-Again Loop Timer.
#
# GitHub builds each PR into an image on its own machines and pushes it to
# ghcr.io/bschulzke/timer-server. This script only pulls that exact image (by digest) and runs it,
# locked down, at <pr>.preview.tinytabletops.com. Nothing from the PR is cloned, built or mounted here.
#
# The same file is installed twice, and what it accepts depends on the name it runs under:
#   timer-preview   deploy <pr-number> <commit-sha> <image-digest>   start or update a PR preview
#                   remove <pr-number>                                 delete a PR preview
#                   list                                               show running previews
#   timer-live      live <commit-sha> <image-digest>                   update the live site to a commit on main
# Each runs as root through its own sudo rule, and each is the forced command of its own SSH key: the
# preview key (usable from any branch's workflow) can never update the live site, and the live key is
# kept in a GitHub environment that only main can use. Anything else is refused.
set -eu
umask 022

IMAGE_REPO=ghcr.io/bschulzke/timer-server    # fixed: callers can't point at any other image
NETWORK=timer-previews                       # previews' own network; only Caddy is also on it
ALLOWED=/srv/previews/allowed                # names Caddy may get certificates for
DOMAIN=preview.tinytabletops.com
MAX_PREVIEWS=3
LIVE_DIR=/root/timer-server                  # the live site's checkout (compose file, Caddyfile, .env)

CMD=${SSH_ORIGINAL_COMMAND:-$*}
set -f            # no filename expansion of anything GitHub sends
set -- $CMD
ACTION=${1:-}; PR=${2:-}; SHA=${3:-}; DIGEST=${4:-}
[ $# -le 4 ] || { echo "preview: too many arguments" >&2; exit 1; }

fail() { echo "preview: $*" >&2; exit 1; }
short() { printf '%.7s' "$1"; }
case "${0##*/}" in
  timer-live)    [ "$ACTION" = live ] || fail "this key can only update the live site";;
  timer-preview) [ "$ACTION" != live ] || fail "this key can't update the live site";;
  *)             fail "install this script as timer-preview or timer-live";;
esac
if [ "$ACTION" = live ]; then
  SHA=${2:-}; DIGEST=${3:-}; PR=0
  [ $# -le 3 ] || fail "too many arguments"
elif [ "$ACTION" != list ]; then
  case "$PR" in ''|*[!0-9]*) fail "PR number must be digits";; esac
  [ ${#PR} -le 6 ] || fail "PR number too long"
fi

check_sha_digest() {
  case "$SHA" in ''|*[!0-9a-f]*) fail "commit must be a hex SHA";; esac
  [ ${#SHA} -eq 40 ] || fail "commit must be a full 40-character SHA"
  case "$DIGEST" in sha256:*) ;; *) fail "image must be a sha256 digest";; esac
  HEX=${DIGEST#sha256:}
  case "$HEX" in ''|*[!0-9a-f]*) fail "image digest must be hex";; esac
  [ ${#HEX} -eq 64 ] || fail "image digest must be 64 hex characters"
}
# Pull $IMAGE and require labels saying it's this kind of build (timer-preview / timer-live) from $SHA.
pull_checked() {
  docker pull --quiet "$IMAGE" >/dev/null || fail "couldn't pull the image (is the ghcr package public?)"
  REV=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE")
  KIND=$(docker image inspect --format "{{ index .Config.Labels \"$1\" }}" "$IMAGE")
  [ "$REV" = "$SHA" ] || fail "image was built from $(short "$REV"), not $(short "$SHA")"
  [ "$KIND" = 1 ] || fail "image isn't a $1 build"
}

NAME="timer-pr-$PR"
HOST="$PR.$DOMAIN"

case "$ACTION" in
deploy)
  check_sha_digest

  running=$(docker ps --format '{{.Names}}' | grep -c '^timer-pr-' || true)
  if ! docker ps --format '{{.Names}}' | grep -qx "$NAME" && [ "$running" -ge "$MAX_PREVIEWS" ]; then
    fail "already running $running previews (limit $MAX_PREVIEWS). Close a PR to free a slot."
  fi

  IMAGE="$IMAGE_REPO@$DIGEST"
  pull_checked timer-preview

  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --network "$NETWORK" --restart unless-stopped \
    --label timer-preview=1 \
    --user 1000:1000 \
    --cap-drop ALL --security-opt no-new-privileges \
    --read-only \
    --mount type=tmpfs,destination=/data,tmpfs-mode=1777,tmpfs-size=8m \
    --mount type=tmpfs,destination=/tmp,tmpfs-mode=1777,tmpfs-size=8m \
    --memory 128m --memory-swap 128m --cpus 0.5 --pids-limit 64 \
    -e MAX_AGE_HOURS=24 \
    "$IMAGE" >/dev/null
  mkdir -p "$ALLOWED"
  touch "$ALLOWED/$HOST"
  docker image prune -af --filter label=timer-preview=1 >/dev/null 2>&1 || true
  echo "https://$HOST"
  ;;
remove)
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -f "$ALLOWED/$HOST"
  docker image prune -af --filter label=timer-preview=1 >/dev/null 2>&1 || true
  echo "removed $HOST"
  ;;
live)
  check_sha_digest
  IMAGE="$IMAGE_REPO@$DIGEST"
  cd "$LIVE_DIR"
  # Only commits that are on main. Re-running an older deploy rolls back to it.
  git fetch --quiet origin main
  git merge-base --is-ancestor "$SHA" FETCH_HEAD 2>/dev/null || fail "$(short "$SHA") isn't on main"
  pull_checked timer-live
  OLD=$(git rev-parse HEAD)
  git checkout --quiet --force -B main "$SHA"     # compose file and Caddyfile from that commit
  export TIMER_IMAGE="$IMAGE"
  docker compose up -d --no-build --remove-orphans >/dev/null 2>&1 || fail "docker compose up failed"
  # Caddy reads its config from a mounted file; restart it only when that file changed.
  if ! git diff --quiet "$OLD" "$SHA" -- Caddyfile; then docker compose up -d --no-build --force-recreate caddy >/dev/null 2>&1; fi
  # Wait for the new server to answer before calling it done.
  CID=$(docker compose ps -q timer)
  i=0
  until docker exec "$CID" wget -qO- http://localhost:3000/healthz >/dev/null 2>&1; do
    i=$((i + 1)); [ $i -lt 30 ] || fail "the new version didn't come up; re-run the previous deploy to roll back"
    sleep 1
  done
  # Remember this image in .env, so a plain `docker compose up -d` later keeps this version
  # instead of falling back to an old local build.
  touch .env
  { grep -v '^TIMER_IMAGE=' .env || true; echo "TIMER_IMAGE=$IMAGE"; } > .env.new
  chmod 600 .env.new && mv .env.new .env
  docker image prune -af --filter label=timer-live=1 >/dev/null 2>&1 || true
  echo "live: $(short "$SHA")"
  ;;
list)
  docker ps --filter label=timer-preview=1 --format '{{.Names}}  {{.Status}}'
  ;;
*)
  fail "unknown command (use: deploy <pr> <sha> <digest> | remove <pr> | live <sha> <digest> | list)"
  ;;
esac
