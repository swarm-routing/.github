#!/usr/bin/env bash
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
#
# Runs cmd/check-headers, the licence-header gate (Go, #531, #578), on this
# machine as reusable-licence-check.yml runs it in CI. Every repository's
# `make headers` calls it from its ORG_DIR checkout of swarm-routing/.github.
#
# With docker: the ci-tools image at the digest reusable-licence-check.yml
# pins, so the same image CI runs (ADR-0002; whatever moves that digest moves
# this one), pulled with the org's retry when it is not local (#645). The tool runs as your user, with the current directory mounted
# read-only at its own path, each --core-dep directory read-only at
# /core-deps/<n>, and, in a worktree or a submodule (`.git` is a file), the git
# directories at their own paths, so a relative `gitdir:` resolves as on the
# host. The image has no git: the tool reads the git index itself.
# Without docker (or with its daemon down): `go build` of cmd/check-headers
# from this checkout, run here.
#
# Run it from the repository root; the arguments are check-headers' own:
#   tools/checks/check-headers.sh --dual core/ --core core/ --core-dep ../ns3-swarm-core/core .
#   tools/checks/check-headers.sh --self-test
set -euo pipefail

org=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)

if command -v docker > /dev/null 2>&1 && docker info > /dev/null 2>&1; then
  wf="$org/.github/workflows/reusable-licence-check.yml"
  img=$(sed -nE 's/^[[:space:]]*IMG: (ghcr\.io\/swarm-routing\/ci-tools@sha256:[0-9a-f]{64})[[:space:]]*$/\1/p' "$wf")
  [ -n "$img" ] || { echo "check-headers.sh: no ci-tools digest (IMG:) in $wf" >&2; exit 2; }
  here=$(pwd -P)
  run=(docker run --rm --user "$(id -u):$(id -g)" -v "$here:$here:ro" -w "$here")
  if [ -f .git ]; then  # a worktree or a submodule: its index lives in a git directory elsewhere
    for d in "$(git rev-parse --path-format=absolute --git-common-dir)" "$(git rev-parse --path-format=absolute --git-dir)"; do
      run+=(-v "$d:$d:ro")
    done
  fi
  args=()
  n=0
  while [ $# -gt 0 ]; do
    case $1 in
      --core-dep=*) dep=${1#*=}; shift ;;
      --core-dep) [ $# -ge 2 ] || { args+=("$1"); shift; continue; }; dep=$2; shift 2 ;;
      *) args+=("$1"); shift; continue ;;
    esac
    abs=$(cd "$dep" 2> /dev/null && pwd -P) || { echo "check-headers.sh: --core-dep $dep is not a directory" >&2; exit 2; }
    n=$((n + 1))
    run+=(-v "$abs:/core-deps/$n:ro")
    args+=(--core-dep "/core-deps/$n")
  done
  # the image once, with the org's retry (#645); a local copy is used as it is
  docker image inspect "$img" > /dev/null 2>&1 || "$org/.github/actions/pull-ci-tools/docker-retry.sh" pull "$img"
  exec "${run[@]}" "$img" check-headers "${args[@]}"
fi

command -v go > /dev/null 2>&1 || {
  echo "check-headers.sh: needs docker (the ci-tools image) or go (to build cmd/check-headers)" >&2
  exit 127
}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
go build -C "$org" -o "$tmp/check-headers" ./cmd/check-headers
"$tmp/check-headers" "$@"
