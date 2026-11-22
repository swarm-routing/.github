#!/usr/bin/env bash
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
#
# The org's one retry for a registry call (#645): `docker-retry.sh pull IMG`
# or `docker-retry.sh push REF` runs `docker pull --quiet` / `docker push
# --quiet` and, when it fails, tries three more times, 15, 30 and 45 s apart.
# GHCR answered `denied` and then `not found` for a public ci-tools digest for
# a few minutes on 2026-11-17 (#623, #578), and `unknown blob` on a push
# (#618): each cleared on its own. The pull-ci-tools action (action.yml here)
# runs it in every workflow that runs the ci-tools image;
# tools/checks/check-headers.sh runs it before its local `docker run`.
#
#   docker-retry.sh pull ghcr.io/swarm-routing/ci-tools@sha256:<digest>
#   docker-retry.sh push ghcr.io/swarm-routing/ci-tools-dev:pr-1-abc1234
#   docker-retry.sh --self-test     # a fake docker: first try, a recovery, giving up
#
# DOCKER_RETRY_DELAYS overrides the waits (space-separated seconds, the
# self-test sets it to zeros); DOCKER names the docker binary.
set -euo pipefail

retry() {
  local op=$1 ref=$2 delay n=0
  for delay in ${DOCKER_RETRY_DELAYS:-15 30 45} last; do
    n=$((n + 1))
    if "${DOCKER:-docker}" "$op" --quiet "$ref" > /dev/null; then
      [ "$n" -eq 1 ] || echo "docker-retry: $op $ref succeeded on try $n" >&2
      return 0
    fi
    if [ "$delay" = last ]; then
      echo "::error::could not $op $ref after $n tries"
      return 1
    fi
    echo "docker-retry: $op $ref failed (try $n); retrying in $delay s" >&2
    sleep "$delay"
  done
}

self_test() {
  local tmp rc
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN
  # a fake docker that fails the first $FAILS calls, counting them in a file
  cat > "$tmp/docker" <<'SH'
#!/usr/bin/env bash
n=$(( $(cat "$COUNT" 2> /dev/null || echo 0) + 1 )); echo "$n" > "$COUNT"
echo "$*" >> "$COUNT.args"
[ "$n" -gt "$FAILS" ]
SH
  chmod +x "$tmp/docker"
  export DOCKER="$tmp/docker" DOCKER_RETRY_DELAYS="0 0 0"
  check() {  # name fails want-rc want-calls op
    rm -f "$tmp/c" "$tmp/c.args"
    rc=0; COUNT="$tmp/c" FAILS=$2 retry "$5" img@sha256:x > "$tmp/out" 2>&1 || rc=$?
    if ! { [ "$rc" = "$3" ] && [ "$(cat "$tmp/c")" = "$4" ] && grep -qx "$5 --quiet img@sha256:x" "$tmp/c.args"; }; then
      echo "self-test: FAIL $1 (rc $rc, calls $(cat "$tmp/c"))"; cat "$tmp/out"; exit 1
    fi
  }
  check "first try" 0 0 1 pull
  check "recovers on the third try" 2 0 3 pull
  check "push recovers too" 1 0 2 push
  check "gives up after four tries" 9 1 4 pull
  grep -q '::error::could not pull img@sha256:x after 4 tries' "$tmp/out" \
    || { echo "self-test: FAIL no ::error:: line"; exit 1; }
  echo "self-test: PASS"
}

case ${1:-} in
  --self-test) self_test ;;
  pull | push) [ $# -eq 2 ] || { echo "usage: docker-retry.sh pull|push REF" >&2; exit 2; }; retry "$1" "$2" ;;
  *) echo "usage: docker-retry.sh pull|push REF | --self-test" >&2; exit 2 ;;
esac
