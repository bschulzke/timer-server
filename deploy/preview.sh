#!/bin/sh
# PR previews for the Shenan-Again Loop Timer.
#
# GitHub builds each PR into an image on its own machines and pushes it to
# ghcr.io/bschulzke/timer-server. This script only pulls that exact image (by digest) and runs it,
# locked down, at <pr>.preview.tinytabletops.com. Nothing from the PR is cloned, built or mounted here.
#
# It runs as root through one sudo rule, and is the only thing GitHub's SSH key may run (a forced
# command for the deploy user). GitHub sends one of:
#   deploy <pr-number> <commit-sha> <image-digest>
#   remove <pr-number>
#   list
# Anything else is refused.
set -eu
umask 022

IMAGE_REPO=ghcr.io/bschulzke/timer-server    # fixed: callers can't point at any other image
NETWORK=timer-previews                       # previews' own network; only Caddy is also on it
ALLOWED=/srv/previews/allowed                # names Caddy may get certificates for
DOMAIN=preview.tinytabletops.com
MAX_PREVIEWS=3

CMD=${SSH_ORIGINAL_COMMAND:-$*}
set -f            # no filename expansion of anything GitHub sends
set -- $CMD
ACTION=${1:-}; PR=${2:-}; SHA=${3:-}; DIGEST=${4:-}
[ $# -le 4 ] || { echo "preview: too many arguments" >&2; exit 1; }

fail() { echo "preview: $*" >&2; exit 1; }
short() { printf '%.7s' "$1"; }
if [ "$ACTION" != list ]; then
  case "$PR" in ''|*[!0-9]*) fail "PR number must be digits";; esac
  [ ${#PR} -le 6 ] || fail "PR number too long"
fi

NAME="timer-pr-$PR"
HOST="$PR.$DOMAIN"

case "$ACTION" in
deploy)
  case "$SHA" in ''|*[!0-9a-f]*) fail "commit must be a hex SHA";; esac
  [ ${#SHA} -eq 40 ] || fail "commit must be a full 40-character SHA"
  case "$DIGEST" in sha256:*) ;; *) fail "image must be a sha256 digest";; esac
  HEX=${DIGEST#sha256:}
  case "$HEX" in ''|*[!0-9a-f]*) fail "image digest must be hex";; esac
  [ ${#HEX} -eq 64 ] || fail "image digest must be 64 hex characters"

  running=$(docker ps --format '{{.Names}}' | grep -c '^timer-pr-' || true)
  if ! docker ps --format '{{.Names}}' | grep -qx "$NAME" && [ "$running" -ge "$MAX_PREVIEWS" ]; then
    fail "already running $running previews (limit $MAX_PREVIEWS). Close a PR to free a slot."
  fi

  IMAGE="$IMAGE_REPO@$DIGEST"
  docker pull --quiet "$IMAGE" >/dev/null || fail "couldn't pull the image (is the ghcr package public?)"
  # The image must say it was built from this commit, as a preview.
  REV=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE")
  KIND=$(docker image inspect --format '{{ index .Config.Labels "timer-preview" }}' "$IMAGE")
  [ "$REV" = "$SHA" ] || fail "image was built from $(short "$REV"), not $(short "$SHA")"
  [ "$KIND" = 1 ] || fail "image isn't a preview build"

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
list)
  docker ps --filter label=timer-preview=1 --format '{{.Names}}  {{.Status}}'
  ;;
*)
  fail "unknown command (use: deploy <pr> <sha> <digest> | remove <pr> | list)"
  ;;
esac
