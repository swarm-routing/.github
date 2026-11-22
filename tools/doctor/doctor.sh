#!/usr/bin/env bash
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
#
# `make doctor` (#647): this machine's dev tools against the versions CI runs,
# so `make check` reproduces CI before a push (swarm-routing/.github#586).
# The versions are tools/versions.env next to this script (the org checkout
# every repository's Makefile keeps in ORG_DIR); Go is the repository's go.mod
# `toolchain` line, else `go`, as reusable-go-ci.yml reads it. A tool is
# checked only where the repository uses it: ruff and coverage when it tracks
# a .py file, Go, staticcheck and govulncheck when it has a go.mod. Then the
# hosts the network steps need, each named with the steps that skip offline.
#
#   tools/doctor/doctor.sh [REPO]       one line per tool: ok, MISMATCH or MISSING
#   tools/doctor/doctor.sh --self-test  fake tools on PATH, a fixture repository
#
# Exit 0 when every checked tool matches CI, 1 when one differs or is missing
# (the line says what to install); an unreachable host is reported, never a
# failure. DOCTOR_OFFLINE=1 skips the network probe.
set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
versions="${DOCTOR_VERSIONS:-$here/../versions.env}"

# want KEY: the value of KEY in versions.env
want() { sed -nE "s/^$1=([A-Za-z0-9._-]+)$/\1/p" "$versions"; }

bad=0
report() {  # tool want have install-hint
  if [ -z "$3" ]; then
    echo "MISSING  $1: CI runs $2 ($4)"; bad=1
  elif [ "$2" = "$3" ]; then
    echo "ok       $1 $3"
  else
    echo "MISMATCH $1: local $3, CI $2 ($4)"; bad=1
  fi
}

# first line of a version, or empty when the tool is not installed
ver() { command -v "$1" > /dev/null 2>&1 && "$@" 2>&1 | head -n 1; }

doctor() {
  local repo=$1 w have
  cd "$repo" || { echo "doctor: no directory $repo" >&2; return 2; }
  [ -r "$versions" ] || { echo "doctor: no $versions" >&2; return 2; }
  if git ls-files -- '*.py' 2> /dev/null | grep -q .; then
    w=$(want RUFF_VERSION)
    have=$(ver ruff --version | sed -nE 's/^ruff ([0-9.]+).*/\1/p')
    report ruff "$w" "$have" "pip install ruff==$w"
    w=$(want COVERAGE_VERSION)
    have=$(python3 -m coverage --version 2> /dev/null | sed -nE '1s/.*version ([0-9.]+).*/\1/p')
    report coverage "$w" "$have" "pip install coverage==$w"
  fi
  if [ -f go.mod ]; then
    w=$(sed -nE 's/^toolchain go([0-9][0-9.]*)[[:space:]]*$/\1/p' go.mod)
    [ -n "$w" ] || w=$(sed -nE 's/^go ([0-9][0-9.]*)[[:space:]]*$/\1/p' go.mod)
    have=$(GOTOOLCHAIN=local ver go env GOVERSION | sed -nE 's/^go([0-9.]+).*/\1/p')
    report go "$w" "$have" "go$w from https://go.dev/dl/, as GOTOOLCHAIN=local in CI"
    w=$(want STATICCHECK_VERSION)
    have=$(ver staticcheck -version | sed -nE 's/^staticcheck ([0-9.]+).*/\1/p')
    report staticcheck "$w" "$have" "go install honnef.co/go/tools/cmd/staticcheck@$w"
    w=$(want GOVULNCHECK_VERSION)
    have=$(command -v govulncheck > /dev/null 2>&1 && govulncheck -version 2>&1 | sed -nE 's/.*govulncheck@(v[0-9.]+).*/\1/p')
    report govulncheck "$w" "$have" "go install golang.org/x/vuln/cmd/govulncheck@$w"
  fi
  if [ "${DOCTOR_OFFLINE:-0}" != 1 ]; then
    probe github.com "make org-tools, headers and org-sync-check (the org checkout), reusable-python-ci's ruff.toml"
    probe ghcr.io "make headers with docker (the ci-tools image; without docker it builds with go), make shell and make test in an ns-3 repository (ns3-dev)"
    probe gitlab.com "sim-containers' test stage (ns-3's sources)"
  fi
  return "$bad"
}

probe() {  # host what-needs-it
  if curl -s -o /dev/null --max-time 5 "https://$1/"; then
    echo "ok       network $1"
  else
    echo "offline  $1: skipped or failing here: $2"
  fi
}

self_test() {
  local tmp out rc fail=0
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin" "$tmp/repo"
  printf 'RUFF_VERSION=0.17.1\nCOVERAGE_VERSION=7.16.2\nSTATICCHECK_VERSION=2026.2.2\nGOVULNCHECK_VERSION=v1.9.0\nBAD LINE\n' > "$tmp/versions.env"
  fake() { printf '#!/bin/sh\n%s\n' "$2" > "$tmp/bin/$1"; chmod +x "$tmp/bin/$1"; }
  fake ruff 'echo "ruff 0.16.9"'
  fake python3 'echo "Coverage.py, version 7.16.2 with C extension"'
  fake go 'echo go1.27.4'
  fake staticcheck 'echo "staticcheck 2026.2.2 (0.8.2)"'
  git -C "$tmp/repo" init -q && touch "$tmp/repo/a.py" && git -C "$tmp/repo" add a.py
  printf 'module x\n\ngo 1.27\n\ntoolchain go1.27.4\n' > "$tmp/repo/go.mod"
  check() {  # name want-rc pattern...
    local name=$1 wrc=$2; shift 2
    [ "$rc" = "$wrc" ] || { echo "self-test: FAIL $name: exit $rc, want $wrc"; echo "$out"; fail=1; }
    for p in "$@"; do
      grep -qxF -- "$p" <<< "$out" || { echo "self-test: FAIL $name: no line '$p'"; echo "$out"; fail=1; }
    done
  }
  run() { rc=0; out=$(PATH="$tmp/bin:/usr/bin:/bin" DOCTOR_OFFLINE=1 DOCTOR_VERSIONS="$tmp/versions.env" bash "${BASH_SOURCE[0]}" "$@") || rc=$?; }
  run "$tmp/repo"
  check "a mismatch, a missing tool, matches" 1 \
    "MISMATCH ruff: local 0.16.9, CI 0.17.1 (pip install ruff==0.17.1)" \
    "ok       coverage 7.16.2" "ok       go 1.27.4" "ok       staticcheck 2026.2.2" \
    "MISSING  govulncheck: CI runs v1.9.0 (go install golang.org/x/vuln/cmd/govulncheck@v1.9.0)"
  fake ruff 'echo "ruff 0.17.1"'
  fake govulncheck 'printf "Go: go1.27.4\nScanner: govulncheck@v1.9.0\n"'
  run "$tmp/repo"
  check "every tool as CI" 0 "ok       ruff 0.17.1" "ok       govulncheck v1.9.0"
  printf 'module x\n\ngo 1.28\n' > "$tmp/repo/go.mod"
  run "$tmp/repo"
  check "go from the go line when there is no toolchain line" 1 "MISMATCH go: local 1.27.4, CI 1.28 (go1.28 from https://go.dev/dl/, as GOTOOLCHAIN=local in CI)"
  rm "$tmp/repo/go.mod"; git -C "$tmp/repo" rm -q --cached a.py
  run "$tmp/repo"
  check "a repository with neither Python nor Go checks nothing" 0
  [ -z "$out" ] || { echo "self-test: FAIL nothing to check printed: $out"; fail=1; }
  [ "$fail" = 0 ] && echo "self-test: PASS"
  return "$fail"
}

case ${1:-} in
  --self-test) self_test ;;
  -h | --help) sed -n '4,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) doctor "${1:-.}" ;;
esac
