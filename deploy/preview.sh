#!/bin/sh
# PR previews for the Shenan-Again Loop Timer.
#
# Runs on the droplet as the only thing GitHub's SSH key may do (a forced command in
# ~deploy/.ssh/authorized_keys). GitHub sends one of:
#   deploy <pr-number> <commit-sha>   build that commit and serve it at <pr>.preview.tinytabletops.com
#   remove <pr-number>                stop and delete that preview
#   list                              show running previews
# Anything else is refused. Previews keep no saved data and never touch the live site.
set -eu

REPO=https://github.com/bschulzke/timer-server.git
BASE=/srv/previews
NETWORK=timer-server_default        # the live compose project's network, which Caddy is on
DOMAIN=preview.tinytabletops.com
MAX_PREVIEWS=3

CMD=${SSH_ORIGINAL_COMMAND:-$*}
set -f            # no filename expansion of anything GitHub sends
set -- $CMD
ACTION=${1:-}; PR=${2:-}; SHA=${3:-}

fail() { echo "preview: $*" >&2; exit 1; }
case "$PR" in ''|*[!0-9]*) [ "$ACTION" = list ] || fail "PR number must be digits";; esac
[ ${#PR} -le 6 ] || fail "PR number too long"

NAME="timer-pr-$PR"
SRC="$BASE/src/pr-$PR"
HOST="$PR.$DOMAIN"

case "$ACTION" in
deploy)
  case "$SHA" in ''|*[!0-9a-f]*) fail "commit must be a hex SHA";; esac
  [ ${#SHA} -eq 40 ] || fail "commit must be a full 40-character SHA"

  running=$(docker ps --format '{{.Names}}' | grep -c '^timer-pr-' || true)
  if ! docker ps --format '{{.Names}}' | grep -qx "$NAME" && [ "$running" -ge "$MAX_PREVIEWS" ]; then
    fail "already running $running previews (limit $MAX_PREVIEWS). Close a PR to free a slot."
  fi

  mkdir -p "$BASE/src" "$BASE/allowed"
  [ -d "$SRC/.git" ] || git clone --quiet --filter=blob:none --no-checkout "$REPO" "$SRC"
  git -C "$SRC" fetch --quiet --depth 1 origin "pull/$PR/head"
  git -C "$SRC" checkout --quiet --force FETCH_HEAD
  HEAD=$(git -C "$SRC" rev-parse HEAD)
  [ "$HEAD" = "$SHA" ] || fail "PR $PR is now at ${HEAD%"${HEAD#???????}"}, not ${SHA%"${SHA#???????}"}; a newer push will deploy it"

  docker build --quiet -t "timer-preview:pr-$PR" "$SRC" >/dev/null
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --network "$NETWORK" --restart unless-stopped \
    --memory 128m --cpus 0.5 \
    --mount type=tmpfs,destination=/data,tmpfs-mode=1777 \
    -e MAX_AGE_HOURS=24 \
    "timer-preview:pr-$PR" >/dev/null
  touch "$BASE/allowed/$HOST"
  docker image prune -f >/dev/null 2>&1 || true
  echo "https://$HOST"
  ;;
remove)
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rmi "timer-preview:pr-$PR" >/dev/null 2>&1 || true
  rm -f "$BASE/allowed/$HOST"
  rm -rf "$SRC"
  echo "removed $HOST"
  ;;
list)
  docker ps --filter name='^timer-pr-' --format '{{.Names}}  {{.Status}}'
  ;;
*)
  fail "unknown command (use: deploy <pr> <sha> | remove <pr> | list)"
  ;;
esac
