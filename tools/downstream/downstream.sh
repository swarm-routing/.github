#!/usr/bin/env bash
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
#
# Downstream check: build and test org ns-3 contrib modules (a consumer list)
# on one ns3-dev image, each in its own fresh container. One code path for
# two callers (swarm-routing/.github#482):
#
# - sim-containers' image canary (its test/downstream.sh, sim-containers#44):
#   every org module on the candidate image before `latest-*` moves;
# - reusable-release.yml's `downstream-consumers` (a library's release dry
#   run): the library's main consumers built against the candidate, the
#   library's own checkout standing in for its release (DOWNSTREAM_LOCAL).
#
#   downstream.sh <image-ref> [LIST]   run the check
#   downstream.sh --check [LIST]       validate the list (no docker, no network)
#   downstream.sh --self-test          the parser, ranges and overrides on fixtures
#
# Only `debug` images on the Ubuntu base are checked: that is the image every
# consumer's automatic CI builds against (latest-debug), asserts on. Any other
# image prints SKIP and passes. Each consumer is cloned on the host (public
# repositories, no credential), or copied from DOWNSTREAM_LOCAL, then staged,
# built with ns3-build-contrib and tested in its own fresh container under a
# wall-clock budget (DOWNSTREAM_BUDGET seconds, default 3600): a consumer that
# does not finish is a hang and fails.
#
# The list: one consumer per line, columns separated by `|`:
#
#   name | owner/repo@ref | ns-3 | modules | suites | stage | run
#
# name     the consumer; its checkout is /w/<name> in the container
# ref      a branch, a tag or a 40-char commit
# ns-3     releases it supports: `3.42+` (that one and newer) or `3.36-3.48`
# modules  ns3-build-contrib specs `name=path`, path relative to /w, so a
#          dependency is another line's checkout; dependencies first
# suites   test.py suites (empty: every module's own suite)
# stage    bash, in the checkout, before the build
# run      bash, in the checkout, after the build: the consumer's own checks
# A field cannot contain `|`; a pipeline belongs in a consumer's script.
#
# LIST              the consumer list (else DOWNSTREAM_FILE)
# DOWNSTREAM_LOCAL  space-separated `name=dir`: that line's checkout is a copy
#                   of dir (the candidate under test) instead of a clone
# DOWNSTREAM_TITLE  the step summary's heading (default "Downstream check")
# DOWNSTREAM_FAILED if set, a file that receives one line per failing
#                   consumer: <name> <repo>@<commit> <reason>
set -euo pipefail

self=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
local_dirs=${DOWNSTREAM_LOCAL:-}
title=${DOWNSTREAM_TITLE:-Downstream check}
budget=${DOWNSTREAM_BUDGET:-3600}
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
failed_file=${DOWNSTREAM_FAILED:-/dev/null}

trim() { local s=$1; s=${s#"${s%%[![:space:]]*}"}; printf '%s' "${s%"${s##*[![:space:]]}"}"; }

# Consumers, one per element, fields separated by a unit separator.
entries=()
parse() {
    local n=0 line name src range modules suites stage run
    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        case "$(trim "$line")" in ''|'#'*) continue ;; esac
        IFS='|' read -r name src range modules suites stage run <<<"$line"
        name=$(trim "$name"); src=$(trim "$src"); range=$(trim "$range")
        modules=$(trim "$modules"); suites=$(trim "$suites")
        stage=$(trim "$stage"); run=$(trim "${run:-}")
        [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "$list:$n: bad name '$name'" >&2; return 1; }
        [[ "$src" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+@[A-Za-z0-9._/-]+$ ]] \
            || { echo "$list:$n: '$src' is not owner/repo@ref" >&2; return 1; }
        [[ "$range" =~ ^[0-9]+\.[0-9]+(\+|-[0-9]+\.[0-9]+)$ ]] \
            || { echo "$list:$n: ns-3 range '$range' is not 3.42+ or 3.36-3.48" >&2; return 1; }
        [ -n "$modules" ] || { echo "$list:$n: no modules" >&2; return 1; }
        for spec in $modules; do
            [[ "$spec" =~ ^[A-Za-z0-9_-]+=[A-Za-z0-9._/-]+$ ]] \
                || { echo "$list:$n: module '$spec' is not name=path" >&2; return 1; }
        done
        entries+=("$name"$'\x1f'"$src"$'\x1f'"$range"$'\x1f'"$modules"$'\x1f'"$suites"$'\x1f'"$stage"$'\x1f'"$run")
    done < "$list"
    [ ${#entries[@]} -gt 0 ] || { echo "$list: no consumer listed" >&2; return 1; }
}

# 0 when ns-3 version $1 is inside range $2 (3.42+ or 3.36-3.48), by minor.
in_range() {
    local v lo hi
    v=$(cut -d. -f1,2 <<<"$1")
    if [[ "$2" == *+ ]]; then lo=${2%+}; hi=$v; else lo=${2%-*}; hi=${2#*-}; fi
    [ "$(printf '%s\n%s\n' "$lo" "$v" | sort -V | head -1)" = "$lo" ] &&
        [ "$(printf '%s\n%s\n' "$v" "$hi" | sort -V | head -1)" = "$v" ]
}

# 0 and the directory when consumer $1 is overridden by DOWNSTREAM_LOCAL.
local_dir() {
    local spec
    for spec in $local_dirs; do
        [ "${spec%%=*}" = "$1" ] && { printf '%s' "${spec#*=}"; return 0; }
    done
    return 1
}

# Every DOWNSTREAM_LOCAL entry names a listed consumer and an existing directory.
check_local() {
    local spec name dir e found
    for spec in $local_dirs; do
        [[ "$spec" =~ ^[A-Za-z0-9._-]+=.+$ ]] || { echo "DOWNSTREAM_LOCAL: '$spec' is not name=dir" >&2; return 1; }
        name=${spec%%=*}; dir=${spec#*=}; found=n
        for e in "${entries[@]}"; do [ "${e%%$'\x1f'*}" = "$name" ] && found=y; done
        [ "$found" = y ] || { echo "DOWNSTREAM_LOCAL: '$name' is not a consumer in $list" >&2; return 1; }
        [ -d "$dir" ] || { echo "DOWNSTREAM_LOCAL: $dir (for $name) is not a directory" >&2; return 1; }
    done
}

self_test() {
    local t fails=0 bad v a b
    t=$(mktemp -d)
    expect() { if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; fails=$((fails + 1)); fi; }
    # 0 or 1: whether the command succeeds (set -e stays off its failure)
    ok() { if "$@"; then echo 0; else echo 1; fi; }
    # the exit code of this script run with leading VAR=value words as its environment
    code() {
        local envs=()
        while [ $# -gt 0 ] && [[ "$1" == [A-Z]*=* ]]; do envs+=("$1"); shift; done
        if env "${envs[@]}" bash "$self" "$@" > "$t/out" 2>&1; then echo 0; else echo $?; fi
    }
    printf '%s\n' '# fixture' '' \
        'lib | o/lib@main | 3.42+ | lib=lib | | |' \
        'app | o/app@v1.0.0 | 3.36-3.48 | lib=lib app=app/ns3 | app | make stage | ./run' > "$t/ok.txt"
    expect "a valid list" "$(code --check "$t/ok.txt")"
    expect "--check names each consumer" "$(ok grep -q '^ok    app (o/app@v1.0.0, ns-3 3.36-3.48)$' "$t/out")"
    mkdir "$t/cand"
    expect "a local override" "$(code DOWNSTREAM_LOCAL="lib=$t/cand" --check "$t/ok.txt")"
    expect "--check says the override" "$(ok grep -q "^ok    lib (local: $t/cand" "$t/out")"
    expect "an override of an unlisted consumer is refused" \
        "$(ok test "$(code DOWNSTREAM_LOCAL="nope=$t/cand" --check "$t/ok.txt")" != 0)"
    expect "an override of a missing directory is refused" \
        "$(ok test "$(code DOWNSTREAM_LOCAL="lib=$t/missing" --check "$t/ok.txt")" != 0)"
    for bad in 'b@d | o/x@main | 3.42+ | x=x | | |' 'x | o/x | 3.42+ | x=x | | |' \
               'x | o/x@main | 3.4 | x=x | | |' 'x | o/x@main | 3.42+ | | | |' \
               'x | o/x@main | 3.42+ | x=x;rm | | |'; do
        printf '%s\n' "$bad" > "$t/bad.txt"
        expect "refused: $bad" "$(ok test "$(code --check "$t/bad.txt")" != 0)"
    done
    : > "$t/empty.txt"
    expect "an empty list is refused" "$(ok test "$(code --check "$t/empty.txt")" != 0)"
    expect "no list: usage, exit 2" "$(ok test "$(code DOWNSTREAM_FILE=)" = 2)"
    expect "DOWNSTREAM_FILE names the list" "$(code DOWNSTREAM_FILE="$t/ok.txt" --check)"
    for v in 3.36 3.42 3.48 3.49; do
        if in_range "$v" 3.42+; then a=y; else a=n; fi
        if in_range "$v" 3.36-3.48; then b=y; else b=n; fi
        case "$v:$a$b" in 3.36:ny|3.42:yy|3.48:yy|3.49:yn) expect "in_range $v" 0 ;; *) expect "in_range $v" 1 ;; esac
    done
    rm -rf "$t"
    echo "downstream.sh self-test: $([ $fails -eq 0 ] && echo ok || echo "$fails failed")"
    [ $fails -eq 0 ]
}

if [ "${1:-}" = --self-test ]; then
    self_test
    exit $?
fi

list=${2:-${DOWNSTREAM_FILE:-}}
[ -n "$list" ] || { echo "usage: $0 <image-ref> [LIST] | --check [LIST] | --self-test (or DOWNSTREAM_FILE=LIST)" >&2; exit 2; }
[ -f "$list" ] || { echo "$list: no such consumer list" >&2; exit 2; }

if [ "${1:-}" = --check ]; then
    parse
    check_local
    for e in "${entries[@]}"; do
        IFS=$'\x1f' read -r name src range _ <<<"$e"
        if dir=$(local_dir "$name"); then
            echo "ok    $name (local: $dir, in place of $src; ns-3 $range)"
        else
            echo "ok    $name ($src, ns-3 $range)"
        fi
    done
    for v in 3.36 3.42 3.48 3.49; do
        in_range "$v" 3.42+ && ok=y || ok=n
        case "$v:$ok" in 3.36:n|3.42:y|3.48:y|3.49:y) ;; *) echo "in_range broken for $v" >&2; exit 1 ;; esac
        in_range "$v" 3.36-3.48 && ok=y || ok=n
        case "$v:$ok" in 3.36:y|3.42:y|3.48:y|3.49:n) ;; *) echo "in_range broken for $v" >&2; exit 1 ;; esac
    done
    echo "$(basename "$list"): ${#entries[@]} consumers"
    exit 0
fi

image=$1
parse
check_local

label() { docker image inspect --format "{{ index .Config.Labels \"$1\" }}" "$image"; }
version=$(label org.opencontainers.image.version)
profile=$(label io.github.swarm-routing.ns3.profile)
os=$(label io.github.swarm-routing.ns3.base)

{
    echo "### $title on \`$image\`"
    echo
} >> "$summary"
if [ "$profile" != debug ] || [ "$os" != ubuntu ]; then
    echo "  SKIP  downstream: runs on the ubuntu debug image (this is $os $profile)" | tee -a "$summary"
    exit 0
fi
echo "ns-3 $version ($os $profile)"
{
    echo "ns-3 $version ($os $profile); consumer list: \`$(basename "$list")\`${local_dirs:+; local: \`$local_dirs\`}"
    echo
    echo "| Consumer | Commit | Result | Time |"
    echo "|---|---|---|---|"
} >> "$summary"

work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/downstream.XXXXXX")
cleanup() {
    # Builds run as root in the container: remove what they wrote from there.
    docker run --rm -v "$work:/w" "$image" find /w -mindepth 1 -delete >/dev/null 2>&1 || true
    rm -rf "$work" 2>/dev/null || true
}
trap cleanup EXIT

# Clone every consumer first: a module's dependency is another line's checkout.
declare -A commit
for e in "${entries[@]}"; do
    IFS=$'\x1f' read -r name src _ <<<"$e"
    slug=${src%@*}; ref=${src#*@}
    dest="$work/$name"
    if dir=$(local_dir "$name"); then
        mkdir -p "$dest"
        cp -a "$dir/." "$dest/"
        commit[$name]=$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo local)
        continue
    elif [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
        git init -q "$dest"
        git -C "$dest" fetch -q --depth 1 "https://github.com/$slug.git" "$ref"
        git -C "$dest" checkout -q FETCH_HEAD
    else
        git clone -q --depth 1 --branch "$ref" "https://github.com/$slug.git" "$dest"
    fi
    commit[$name]=$(git -C "$dest" rev-parse HEAD)
done

# Runs in the image, in /w/<name>. Exit 77: nothing to build yet (skip).
inner=$(cat <<'EOF'
if [ -f ci/canary.sh ]; then
    echo "canary: the consumer's own ci/canary.sh"
    exec bash ci/canary.sh
fi
if [ -n "$C_STAGE" ]; then echo "canary: stage: $C_STAGE"; bash -euo pipefail -c "$C_STAGE"; fi
args=()
for spec in $C_MODULES; do
    d=/w/${spec#*=}
    if [ ! -d "$d" ]; then echo "  SKIP  $C_NAME: no ns-3 module yet (${spec#*=} does not exist)"; exit 77; fi
    args+=("${spec%%=*}=$d")
done
tests=(--test)
for s in $C_SUITES; do tests+=(--suite "$s"); done
ns3-build-contrib "${tests[@]}" "${args[@]}"
if [ -n "$C_RUN" ]; then echo "canary: run: $C_RUN"; bash -euo pipefail -c "$C_RUN"; fi
EOF
)

fails=0
for e in "${entries[@]}"; do
    IFS=$'\x1f' read -r name src range modules suites stage run <<<"$e"
    sha=${commit[$name]}
    short="[\`${sha::7}\`](https://github.com/${src%@*}/commit/$sha)"
    local_dir "$name" > /dev/null && short="$short (local)"
    if ! in_range "$version" "$range"; then
        echo "  SKIP  $name: supports ns-3 $range, this is $version"
        echo "| $name | $short | SKIP (supports ns-3 $range) | |" >> "$summary"
        continue
    fi
    echo "::group::downstream: $name ($src at ${sha::7})"
    start=$(date +%s)
    cname="downstream-$name-$$"
    set +e
    # TERM reaches the docker client, which passes it to the container's bash
    # (PID 1, which ignores it): KILL follows 60 s later, and the container
    # is removed whatever ended the client (#485).
    timeout -k 60 "$budget" docker run --rm --name "$cname" -v "$work:/w" -w "/w/$name" \
        -e C_NAME="$name" -e C_MODULES="$modules" -e C_SUITES="$suites" \
        -e C_STAGE="$stage" -e C_RUN="$run" "$image" bash -euo pipefail -c "$inner"
    rc=$?
    docker rm -f "$cname" >/dev/null 2>&1 || true
    set -e
    echo "::endgroup::"
    took=$(( $(date +%s) - start ))
    # KILL after the budget (137) is the hang too; a 137 before it (OOM) is not
    if [ "$rc" = 137 ] && [ "$took" -ge "$budget" ]; then rc=124; fi
    case "$rc" in
        0)  echo "downstream: $name passed (${took} s)"
            echo "| $name | $short | pass | ${took} s |" >> "$summary" ;;
        77) echo "  SKIP  $name: no ns-3 module yet"
            echo "| $name | $short | SKIP (no ns-3 module yet) | |" >> "$summary" ;;
        124)
            echo "downstream: $name did not finish within ${budget} s (hang)" >&2
            echo "| $name | $short | **FAIL** (no result within ${budget} s: hang) | ${took} s |" >> "$summary"
            echo "$name ${src%@*}@$sha hang (no result within ${budget} s)" >> "$failed_file"
            fails=$((fails + 1)) ;;
        *)  echo "downstream: $name FAILED (exit $rc)" >&2
            echo "| $name | $short | **FAIL** (exit $rc) | ${took} s |" >> "$summary"
            echo "$name ${src%@*}@$sha exit $rc" >> "$failed_file"
            fails=$((fails + 1)) ;;
    esac
done

[ "$fails" -eq 0 ] || { echo "downstream: $fails consumer(s) failed on $image" >&2; exit 1; }
echo "downstream: every consumer passed or was skipped on $image"
