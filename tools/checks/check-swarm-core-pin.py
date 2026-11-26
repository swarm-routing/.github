#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""The swarm-core pin of a protocol repository is one commit, and current.

A protocol's dual-licensed `core/` builds on swarm-core's `core/` at a pinned
commit, named in several places:

- `core/CMakeLists.txt`: `set(SWARM_CORE_REF "<sha>" ...)`, the reference;
- `Makefile`: `SWARM_CORE_REF ?= <sha>`;
- every workflow's `core-deps` entry for swarm-core
  (`swarm-routing/swarm-adapter-ns3@<sha>:core`): the licence check's, and the
  ns-3 CI's where `ns3/` exists;
- the ns-3 build's dependency (`swarm-core=swarm-routing/swarm-adapter-ns3@<ref>`),
  which follows swarm-core `main` (swarm-core golden rule 12): it must name
  `main` or the pinned commit.

The check fails, naming the file and line, when any of them names another
commit, when the Makefile or every workflow lacks the pin, and when swarm-core
`main`'s `core/` differs from the pinned commit's `core/`: then the ns-3 build
(on `main`) and the pinned `core/` are different code, and the pin needs a bump
PR. It clones swarm-core (`--swarm-core`, default its GitHub URL) without
blobs into a temporary directory. Output is one line per finding and a summary
line (AntHocNet ADR-0014). Stdlib only.

`--bump` (org-bot's swarm-core-pin task, #208) does what the check asks for:
when swarm-core main changed `core/` since the pin, it rewrites the pinned
commit to main's in the places above only, on the lines the check reads (the
`SWARM_CORE_REF` lines, and every workflow's `core-deps` and ns-3 dependency
lines, a benchmark workflow's included), and prints the files, a
`pin-target: <sha>` line and the swarm-core commits on `core/` since the pin.
No other file or line changes: a recorded cell's `##PROV##`, a doc or a
campaign plan naming the old commit records what a run used, and recorded
data is never rewritten (#407). A pin the files disagree on is left to a
person (exit 1).

Lock mode (swarm-routing/swarm-adapter-ns3#134), used when the repository has
`swarm-core.lock` (a release lock, `release_lock.py` beside this file): the
pin is a swarm-core **release**, not a commit. The check fails when the lock
does not verify against the release (the tag names the commit, the hash is
`swarm-core-<ver>.tar.gz`'s in the release's `SHA256SUMS`), when
`core/CMakeLists.txt` does not read the lock or still sets a commit
`SWARM_CORE_REF`, when the Makefile's `SWARM_CORE_REF` or a workflow's
`core-deps` or ns-3 dependency names another ref than the lock's tag (a
`canary-dependencies:` block may name `main`, swarm-routing/.github#411), and
when a **newer swarm-core release** exists; swarm-core `main` moving is not a
finding. `--bump` then writes the lock for the newest release (every value
read from it) and moves the tag on the same pin lines, nothing else. A
repository without a lock keeps the commit mode above.

The ns-3 adapter's layout (swarm-routing/swarm-adapter-ns3#258), lock mode
without `core/`: the root `CMakeLists.txt` reads the lock and there is no
`core-deps`, Makefile or ns-3 dependency pin. The check reads the root
`CMakeLists.txt` in place of `core/CMakeLists.txt`, wants no `core-deps`, and
`--bump` writes the lock alone.

The root vcpkg layout (swarm-routing/swarm-routingd, #958), vcpkg mode without
`core/`: the root `CMakeLists.txt` finds swarm-core with
`find_package(swarm-core CONFIG ...)`, and the root `vcpkg.json` and
`vcpkg-configuration.json` pin it; no `core-deps`, Makefile or ns-3 dependency
pin. Everything vcpkg mode checks below holds, on the root `CMakeLists.txt`,
and `--bump` moves the lock, the override and the baseline.

vcpkg mode (#489), a lock mode for a repository whose `core/` takes swarm-core
through vcpkg in manifest mode: `vcpkg.json` at the root depends on
`swarm-core`. The lock stays the record of the release the ns-3 build uses
(its tag) and everything above holds, except that `core/CMakeLists.txt` must
not read the lock but `find_package(swarm-core CONFIG ...)`. Also checked:
`vcpkg.json`'s `overrides` pin swarm-core at the lock's version (with a
`port-version`), and `vcpkg-configuration.json`'s swarm-routing/vcpkg-registry
entry (`--registry`, default its GitHub URL, cloned without blobs) names as
`baseline` a commit on the registry's `main` whose `versions/baseline.json`
holds exactly that version and port-version. So vcpkg, the ns-3 tag and
`core-deps` name one swarm-core release. `--bump` moves the lock and the pin
lines as above, the override, and the baseline to the registry's `main`, but
only once the registry's `main` holds the new release (its port PR merged):
until then it bumps nothing and says it waits (exit 0).

Stale pin (#586): a pin that is consistent but out of date (a newer release
in lock mode, swarm-core main's core/ moved in commit mode) is a finding the
repository's own change did not cause, so `--stale` says how to report it:
`fail` (the default, and a local run), `warn` (a `::warning::` line, exit 0:
reusable-swarm-core-pin.yml passes it on pull_request and merge_group, so a
release never turns an unrelated PR red), or `bump-pr` (a push to main, a
schedule: red only while org-bot's bump branch `org-bot/swarm-core-pin` exists
in GITHUB_REPOSITORY, read with GH_TOKEN; before org-bot proposes it, or if
the lookup fails, a warning). Every other finding, a pin the files disagree
on or a lock that does not verify, is the repository's own and fails in every
mode.

swarm-core's `core/` lives in swarm-routing/swarm-adapter-ns3, named
swarm-routing/ns3-swarm-core until 2026-11-22 (swarm-routing/.github#672): the
old name still counts on every pin line and in the lock, and a bump writes the
new name on the lines it moves. Its releases after v1.0.0 come from
swarm-routing/swarm-core (#691): a lock on swarm-adapter-ns3 counts swarm-core's
first release as newer whatever its version (`release_lock.MOVED`), and the bump
moves the lock, `core-deps` and the Makefile's fetch of `$(SWARM_CORE_REF)` to
swarm-routing/swarm-core. The ns-3 dependency keeps naming swarm-adapter-ns3:
once the lock is on swarm-core, it names the newest published swarm-adapter-ns3
release whose own `swarm-core.lock` names the lock's swarm-core release (the
ns-3 CI its tag, a benchmark cell its commit), read from the adapter's tags,
never typed. A line on another ref is a stale finding while such a release
exists, and `--bump` moves it there, with the lock or alone (the lock already
current); while none ships it, the line stays and only `main` outside
`canary-dependencies:` is refused. The bump also moves a `main` line, the
canary's, still on the old name to `swarm-adapter-ns3@main`, its ref kept.

Usage (the protocol repository's root as cwd; it reads no path from its arguments):
  check-swarm-core-pin.py [--swarm-core URL_OR_PATH] [--releases URL] [--registry URL_OR_PATH]
                          [--stale fail|warn|bump-pr] [--bump]
  check-swarm-core-pin.py --self-test

`--releases` (default https://github.com) is where lock mode reads tags and
release assets; the self-test passes a `file://` tree.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script's dir
import release_lock  # noqa: E402

SWARM_CORE = "https://github.com/swarm-routing/swarm-adapter-ns3.git"
SWARM_CORE_REPO = "swarm-routing/swarm-adapter-ns3"
LEGACY_REPO = "swarm-routing/ns3-swarm-core"  # its name until 2026-11-22 (#672)
# swarm-core's own repository, where its releases come from after v1.0.0 (#691)
CORE_REPO = release_lock.MOVED[("SWARM_CORE", SWARM_CORE_REPO)]
SLUG = r"swarm-routing/(?:swarm-adapter-ns3|ns3-swarm-core)"
CORE_SLUG = r"swarm-routing/(?:swarm-core|swarm-adapter-ns3|ns3-swarm-core)"
CMAKE = "core/CMakeLists.txt"
# the ns-3 adapter's layout (swarm-routing/swarm-adapter-ns3#258): no core/, the
# root CMakeLists.txt reads the lock and links swarm-core's core/ itself
ROOT_CMAKE = "CMakeLists.txt"
LOCK = "swarm-core.lock"
LOCK_PREFIX = "SWARM_CORE"
ASSET = "swarm-core-{version}.tar.gz"
KEY = re.compile(r"^\s*([A-Za-z0-9_-]+):")
# core/CMakeLists.txt reads the lock on a line that is not a comment
LOCK_READ = re.compile(r"^[^#\n]*file\(\s*(STRINGS|READ)\b[^#\n]*swarm-core\.lock", re.M)
HARD_RELEASE = re.compile(
    r"swarm-routing/(?:swarm-core|swarm-adapter-ns3|ns3-swarm-core)/releases/download/v\d"
    r"|swarm-core-\d+\.\d+\.\d+\.tar"
)
SHA = r"[0-9a-f]{40}"
CMAKE_PIN = re.compile(rf'^\s*set\(\s*SWARM_CORE_REF\s+"({SHA})"', re.M)
MAKE_PIN = re.compile(r"^\s*SWARM_CORE_REF\s*[?:]?=\s*(\S+)", re.M)
CORE_DEP = re.compile(CORE_SLUG + r"@([^\s:'\"]+):")
CORE_DEP_REPO = re.compile(r"(" + CORE_SLUG + r")@[^\s:'\"]+:")
NS3_DEP = re.compile(r"swarm-core=" + SLUG + r"@([^\s:'\"]+)")
# the Makefile's fetch of swarm-core's core/ at the lock's tag (`make headers`)
MAKE_FETCH = re.compile(r"github\.com/(" + SLUG + r")(?:\.git)?(?=\s+\$\(SWARM_CORE_REF\))")
# vcpkg mode (#489)
REGISTRY = "https://github.com/swarm-routing/vcpkg-registry"
VCPKG_MANIFEST = "vcpkg.json"
VCPKG_CONFIG = "vcpkg-configuration.json"
PORT = "swarm-core"
FIND_PACKAGE = re.compile(r"^[^#\n]*find_package\(\s*swarm-core\b[^#\n)]*\bCONFIG\b", re.M)
BUMP_BRANCH = "org-bot/swarm-core-pin"  # org_bot.py's FIXED_BRANCH for the task (#208)
STALE_MODES = ("fail", "warn", "bump-pr")


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def lines_matching(path, pattern):
    """(line number, captured ref) for each match of `pattern` in `path`."""
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            out += [(n, m.group(1)) for m in pattern.finditer(line)]
    return out


def check_files():
    """(pin, errors): the pinned commit and the files that disagree with it, in the cwd."""
    cmake = CMAKE
    if not os.path.exists(cmake):
        return None, [f"{CMAKE}: missing (no swarm-core pin to check)"]
    with open(cmake, encoding="utf-8") as f:
        m = CMAKE_PIN.search(f.read())
    if not m:
        return None, [f'{CMAKE}: no set(SWARM_CORE_REF "<40-char commit>" ...)']
    pin, errors = m.group(1), []
    make = "Makefile"
    found = lines_matching(make, MAKE_PIN) if os.path.exists(make) else []
    if not found:
        errors.append(f"Makefile: no SWARM_CORE_REF (want {pin})")
    errors += [
        f"Makefile:{n}: SWARM_CORE_REF is {ref}, not {pin}" for n, ref in found if ref != pin
    ]
    deps = 0
    for path in sorted(glob.glob(".github/workflows/*.y*ml")):
        rel = path.replace(os.sep, "/")
        for n, ref in lines_matching(path, CORE_DEP):
            deps += 1
            if ref != pin:
                errors.append(f"{rel}:{n}: core-deps names swarm-core {ref}, not {pin}")
        for n, ref in lines_matching(path, NS3_DEP):
            if ref not in ("main", pin):
                errors.append(f"{rel}:{n}: the ns-3 dependency names swarm-core {ref}, not main")
    if not deps:
        errors.append(f".github/workflows: no core-deps entry for swarm-core (want @{pin}:core)")
    return pin, errors


def core_change(pin, url):
    """(error, main, diff --stat lines, commits on core/ since the pin): swarm-core
    main against the pin, from a blobless clone. error is None when both resolve."""
    with tempfile.TemporaryDirectory() as d:
        rc, _, err = git("clone", "-q", "--filter=blob:none", "--no-checkout", url, d)
        if rc:
            return f"cannot clone swarm-core ({url}): {err}", None, [], []
        _, main, _ = git("rev-parse", "origin/main", cwd=d)
        if git("cat-file", "-e", f"{pin}^{{commit}}", cwd=d)[0]:
            return f"{CMAKE}: SWARM_CORE_REF {pin} is not a swarm-core commit", main, [], []
        rc, stat, err = git("diff", "--stat", pin, main, "--", "core/", cwd=d)
        if rc:
            return f"git diff {pin} {main}: {err}", main, [], []
        _, log, _ = git("log", "--format=%h %s", f"{pin}..{main}", "--", "core/", cwd=d)
        return None, main, stat.splitlines() if stat else [], log.splitlines() if log else []


def check_main(pin, url):
    """(errors, stale, main): errors when swarm-core cannot be read, stale when
    swarm-core main's core/ is not the pinned commit's (blobless clone)."""
    err, main, stat, _ = core_change(pin, url)
    if err:
        return [err], [], main
    if stat:
        return (
            [],
            [
                f"swarm-core main ({main}) changed core/ since the pin ({pin}): bump "
                f"SWARM_CORE_REF in {CMAKE}, the Makefile and every core-deps to {main}",
                *stat,
            ],
            main,
        )
    return [], [], main


def bump_pr_open():
    """True when org-bot's bump branch exists in GITHUB_REPOSITORY (its PR is
    open: the branch goes when the PR merges or is superseded), None when
    that cannot be read."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        return None
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(f"{api}/repos/{repo}/branches/{BUMP_BRANCH}")
    req.add_header("Accept", "application/vnd.github+json")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except (urllib.error.URLError, OSError):
        return None


def judge_stale(stale, mode):
    """The stale findings that fail under `mode`; the rest are printed as
    warnings (#586)."""
    if not stale or mode == "fail":
        return stale
    if mode == "bump-pr":
        found = bump_pr_open()
        if found:
            return [*stale[:1], f"org-bot's bump PR ({BUMP_BRANCH}) is open: merge it", *stale[1:]]
        why = "not yet proposed" if found is False else "cannot be read"
    else:
        why = "the change under test did not cause it"
    print(
        f"::warning title=swarm-core pin::{stale[0]} ({why}; org-bot's swarm-core-pin task bumps it)"
    )
    for line in stale[1:]:
        print(f"note {line}")
    return []


def pin_places():
    """(path, the patterns whose lines hold the pin): the places the check reads.
    core/CMakeLists.txt is handled whole by bump(), as CMAKE_PIN may span lines."""
    places = [("Makefile", [MAKE_PIN])]
    places += [
        (p.replace(os.sep, "/"), [CORE_DEP, NS3_DEP])
        for p in sorted(glob.glob(".github/workflows/*.y*ml"))
    ]
    return [(p, pats) for p, pats in places if os.path.exists(p)]


def bump(url):
    """--bump (org-bot's swarm-core-pin task, #208): when swarm-core main changed
    core/ since the pin, rewrite the pinned commit to main's on the pin lines of
    the check's places only (pin_places), never in any other file or line:
    recorded cells, docs and campaign plans name the commit a run used (#407).
    A pin the files disagree on is left to a person. 0: bumped or already
    current; 1: refused."""
    pin, errors = check_files()
    for e in errors:
        print(f"FAIL {e}")
    if not pin or errors:
        print("swarm-core pin: not bumped (fix the pin by hand first)")
        return 1
    err, main, stat, log = core_change(pin, url)
    if err:
        print(f"FAIL {err}")
        return 1
    if not stat:
        print(f"swarm-core pin: current, core/ at {pin[:7]} is swarm-core main's")
        return 0
    changed = []
    with open(CMAKE, encoding="utf-8", newline="") as f:
        text = f.read()
    m = CMAKE_PIN.search(text)  # the one the check read; it may span lines
    with open(CMAKE, "w", encoding="utf-8", newline="") as f:
        f.write(text[: m.start(1)] + main + text[m.end(1) :])
    changed.append(CMAKE)
    for path, patterns in pin_places():
        with open(path, encoding="utf-8", newline="") as f:
            lines = f.readlines()
        new = [
            reslug(line, line.replace(pin, main))
            if any(m.group(1) == pin for pat in patterns for m in pat.finditer(line))
            else line
            for line in lines
        ]
        if new != lines:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.writelines(new)
            changed.append(path)
    print(f"swarm-core pin: bumped {pin[:7]} -> {main[:7]} in {len(changed)} file(s)")
    print(f"pin-target: {main}")
    for c in changed:
        print(f"  {c}")
    print("swarm-core commits on core/ since the pin:")
    for line in log:
        print(f"  {line}")
    return 0


# --- lock mode (swarm-routing/swarm-adapter-ns3#134) --------------------------------


def dep_lines(path):
    """(line number, ref, YAML key the line sits under) for each ns-3 dependency line."""
    out, key = [], None
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            m = KEY.match(line)
            if m:
                key = m.group(1)
            out += [(n, d.group(1), key) for d in NS3_DEP.finditer(line)]
    return out


def check_lock_files():
    """(prefix, values, errors): the lock and the pin places that disagree with it."""
    try:
        prefix, values = release_lock.parse(LOCK)
    except (release_lock.LockError, OSError) as e:
        return None, None, [str(e)]
    errors = []
    repo = release_lock.canonical(values[f"{prefix}_REPO"])
    if prefix != LOCK_PREFIX or repo not in (SWARM_CORE_REPO, CORE_REPO):
        errors.append(f"{LOCK}: want {LOCK_PREFIX}_REPO={CORE_REPO}")
    # past the move (#691) the ns-3 dependency names swarm-adapter-ns3's own
    # releases, no longer the lock's tag
    moved = repo == CORE_REPO
    tag, version = values[f"{prefix}_TAG"], values[f"{prefix}_VERSION"]
    commit = values[f"{prefix}_COMMIT"]
    asset = ASSET.format(version=version)
    if values.get(f"{prefix}_ASSET") != asset:
        errors.append(f"{LOCK}: want {LOCK_PREFIX}_ASSET={asset}")
    if f"{prefix}_SHA256" not in values:
        errors.append(f"{LOCK}: want {LOCK_PREFIX}_SHA256, the hash of {asset}")
    root = root_layout()
    cmake = ROOT_CMAKE if root else CMAKE
    if not os.path.exists(cmake):
        errors.append(f"{cmake}: missing")
    else:
        with open(cmake, encoding="utf-8") as f:
            text = f.read()
        if vcpkg_mode():
            if not FIND_PACKAGE.search(text):
                errors.append(
                    f"{cmake}: no find_package(swarm-core CONFIG ...): with {VCPKG_MANIFEST}, "
                    "the build takes swarm-core from its vcpkg port"
                )
            if LOCK_READ.search(text):
                errors.append(
                    f"{cmake}: reads {LOCK}; with {VCPKG_MANIFEST} swarm-core comes from vcpkg"
                )
        elif not LOCK_READ.search(text):
            errors.append(f"{cmake}: does not read {LOCK} (file(STRINGS ...) or file(READ ...))")
        if HARD_RELEASE.search(text):
            errors.append(f"{cmake}: names a swarm-core release itself; take it from {LOCK}")
        if CMAKE_PIN.search(text):
            errors.append(f"{cmake}: still sets a commit SWARM_CORE_REF; the lock replaces it")
    if os.path.exists("Makefile"):
        for n, ref in lines_matching("Makefile", MAKE_PIN):
            if ref != tag and not ref.startswith("$("):
                errors.append(f"Makefile:{n}: SWARM_CORE_REF is {ref}, not {tag}")
        if moved:
            for n, slug in lines_matching("Makefile", MAKE_FETCH):
                errors.append(f"Makefile:{n}: fetches SWARM_CORE_REF from {slug}, not {repo}")
    deps = 0
    for path in sorted(glob.glob(".github/workflows/*.y*ml")):
        rel = path.replace(os.sep, "/")
        for n, ref in lines_matching(path, CORE_DEP):
            deps += 1
            if ref not in (tag, commit):
                errors.append(f"{rel}:{n}: core-deps names swarm-core {ref}, not {tag}")
        for n, slug in lines_matching(path, CORE_DEP_REPO):
            if release_lock.canonical(slug) != repo:
                errors.append(f"{rel}:{n}: core-deps names {slug}, {LOCK} {repo}")
        with open(path, encoding="utf-8") as f:
            # a benchmark cell's build mode checks out a 40-hex commit (#409), so
            # it takes the commit the tag names; reusable-ns3-ci.yml clones with
            # `git clone --branch`, which takes the tag and not a commit
            bench = "reusable-benchmark-cell.yml" in f.read()
        for n, ref, key in dep_lines(path):
            ok = (commit,) if bench else (tag,)
            if key == "canary-dependencies":
                ok += ("main",)
            if moved and (ref != "main" or key == "canary-dependencies"):
                continue  # swarm-adapter-ns3's release, not swarm-core's (#691)
            if ref not in ok:
                errors.append(f"{rel}:{n}: the ns-3 dependency names swarm-core {ref}, not {tag}")
    if not deps and not root:
        errors.append(f".github/workflows: no core-deps entry for swarm-core (want @{tag}:core)")
    return prefix, values, errors


# --- the ns-3 dependency past the move (#691) ---------------------------------


def ns3_pins():
    """(path, line number, ref, bench) for each ns-3 dependency line that pins a
    release: not `main`, not under `canary-dependencies:`. `bench`: a benchmark
    cell's line, which takes the commit (#409), the ns-3 CI's the tag."""
    out = []
    for path in sorted(glob.glob(".github/workflows/*.y*ml")):
        with open(path, encoding="utf-8") as f:
            bench = "reusable-benchmark-cell.yml" in f.read()
        for n, ref, key in dep_lines(path):
            if ref != "main" and key != "canary-dependencies":
                out.append((path.replace(os.sep, "/"), n, ref, bench))
    return out


def lock_at(base, repo, tag):
    """The text of `repo`'s swarm-core.lock at `tag`, or None when the tag has
    none: the tag fetched shallow into a scratch repository, no token."""
    with tempfile.TemporaryDirectory() as d:
        git("init", "-q", d)
        rc, _, err = git(
            "-C", d, "fetch", "-q", "--depth", "1", "--",
            release_lock.git_url(base, repo), f"refs/tags/{tag}",
        )  # fmt: skip
        if rc:
            raise release_lock.LockError(f"git fetch {repo} {tag}: {err}")
        rc, text, _ = git("-C", d, "show", f"FETCH_HEAD:{LOCK}")
        return text + "\n" if rc == 0 else None


def adapter_for(base, core_tag):
    """(tag, commit) of the newest published swarm-adapter-ns3 release whose own
    swarm-core.lock names swarm-routing/swarm-core `core_tag`: the ns-3 module
    built on that swarm-core release; (None, None) when none ships it. Read from
    the adapter's tags newest first, never typed; a published release without
    the lock ends the search (the adapter has one from swarm-adapter-ns3#258 on)."""
    found = release_lock.tags(base, SWARM_CORE_REPO)
    for tag in sorted(
        (t for t in found if release_lock.version_key(t)),
        key=release_lock.version_key,
        reverse=True,
    ):
        if release_lock.sha256sums(base, SWARM_CORE_REPO, tag) is None:
            continue  # a tag, not a published release
        text = lock_at(base, SWARM_CORE_REPO, tag)
        if text is None:
            break
        try:
            prefix, values = release_lock.parse_text(text, f"{SWARM_CORE_REPO}@{tag}:{LOCK}")
        except release_lock.LockError:
            continue
        if (
            release_lock.canonical(values[f"{prefix}_REPO"]) == CORE_REPO
            and values[f"{prefix}_TAG"] == core_tag
        ):
            return tag, found[tag]
    return None, None


def adapter_stale(base, core_tag):
    """Stale findings for the ns-3 dependency lines not on the adapter release
    that ships swarm-core `core_tag` (none while no release ships it)."""
    pins = ns3_pins()
    if not pins:
        return []
    a_tag, a_commit = adapter_for(base, core_tag)
    if not a_tag:
        return []
    return [
        f"{path}:{n}: the ns-3 dependency names {ref}; {SWARM_CORE_REPO} {a_tag} ships "
        f"swarm-core {core_tag}: bump it to {a_commit if bench else a_tag} (org-bot's "
        "swarm-core-pin task opens that PR)"
        for path, n, ref, bench in pins
        if ref != (a_commit if bench else a_tag)
    ]


def move_adapter(a_tag, a_commit, rename=True):
    """Rewrite each release-pinning ns-3 dependency line (ns3_pins) to
    swarm-adapter-ns3 at `a_tag`, a benchmark cell's at `a_commit` (none while
    `a_tag` is None), and, with `rename` (the lock past the move, #691), each
    `@main` line, a canary's, still on the old name swarm-routing/ns3-swarm-core
    (#672) to swarm-adapter-ns3@main; the files changed."""
    changed = []

    def dep(d, want):
        if d.group(1) == "main":
            return f"swarm-core={SWARM_CORE_REPO}@main" if rename else d.group(0)
        return f"swarm-core={SWARM_CORE_REPO}@{want}" if want else d.group(0)

    for path in sorted(glob.glob(".github/workflows/*.y*ml")):
        with open(path, encoding="utf-8", newline="") as f:
            lines = f.readlines()
        want = a_commit if any("reusable-benchmark-cell.yml" in x for x in lines) else a_tag
        key, new = None, []
        for line in lines:
            m = KEY.match(line)
            if m:
                key = m.group(1)
            # a canary keeps its ref; only its `main` line changes, by name
            pin = None if key == "canary-dependencies" or not a_tag else want
            new.append(NS3_DEP.sub(lambda d: dep(d, pin), line))
        if new != lines:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.writelines(new)
            changed.append(path.replace(os.sep, "/"))
    return changed


def root_layout():
    """True when the pin lives at the root, with no core/CMakeLists.txt: the ns-3
    adapter's layout, whose root CMakeLists.txt reads the lock
    (swarm-routing/swarm-adapter-ns3#258), or a root vcpkg consumer
    (swarm-routing/swarm-routingd, #958), whose root vcpkg.json depends on
    swarm-core. Its pin is the lock (and the vcpkg files) alone: no core-deps (no
    dual-licensed core/ of its own), no Makefile or ns-3 dependency pin."""
    if os.path.exists(CMAKE) or not os.path.exists(ROOT_CMAKE):
        return False
    if vcpkg_mode():
        return True
    with open(ROOT_CMAKE, encoding="utf-8") as f:
        return LOCK_READ.search(f.read()) is not None


def vcpkg_mode():
    """True when vcpkg.json at the root depends on swarm-core (#489)."""
    try:
        with open(VCPKG_MANIFEST, encoding="utf-8") as f:
            deps = json.load(f).get("dependencies") or []
    except (OSError, ValueError, AttributeError):
        return os.path.exists(VCPKG_MANIFEST)  # unreadable: let check_vcpkg say why
    return any((d.get("name") if isinstance(d, dict) else d) == PORT for d in deps)


def load_json(path, errors):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        errors.append(f"{path}: unreadable ({e})")
        return None
    if not isinstance(data, dict):
        errors.append(f"{path}: not a JSON object")
        return None
    return data


def same_repo(url):
    return url.rstrip("/").removesuffix(".git") == REGISTRY


def vcpkg_pins():
    """(override, port-version, baseline, manifest, config, errors) from the two vcpkg files."""
    errors = []
    manifest, config = load_json(VCPKG_MANIFEST, errors), load_json(VCPKG_CONFIG, errors)
    version = port_version = baseline = None
    if manifest is not None:
        deps = manifest.get("dependencies") or []
        if not any((d.get("name") if isinstance(d, dict) else d) == PORT for d in deps):
            errors.append(f"{VCPKG_MANIFEST}: no {PORT} in dependencies")
        over = [o for o in manifest.get("overrides") or [] if o.get("name") == PORT]
        if len(over) != 1:
            errors.append(
                f"{VCPKG_MANIFEST}: want one overrides entry for {PORT} "
                f"(its version and port-version, so the version is explicit)"
            )
        else:
            o = over[0]
            version = o.get("version") or o.get("version-semver")
            port_version = o.get("port-version", 0)
            if not version:
                errors.append(f"{VCPKG_MANIFEST}: the {PORT} override names no version")
    if config is not None:
        regs = [
            r
            for r in config.get("registries") or []
            if same_repo(str(r.get("repository", ""))) and PORT in (r.get("packages") or [])
        ]
        if len(regs) != 1 or regs[0].get("kind") != "git":
            errors.append(
                f"{VCPKG_CONFIG}: want one git registry {REGISTRY} with {PORT} in its packages"
            )
        else:
            baseline = regs[0].get("baseline", "")
            if not re.fullmatch(SHA, baseline):
                errors.append(f"{VCPKG_CONFIG}: the registry's baseline is not a 40-hex commit")
                baseline = None
    return version, port_version, baseline, manifest, config, errors


def registry_clone(url, d):
    """A blobless clone of the registry in `d`; the error, or None."""
    rc, _, err = git("clone", "-q", "--filter=blob:none", "--no-checkout", url, d)
    return f"cannot clone the vcpkg registry ({url}): {err}" if rc else None


def registry_port(d, commit):
    """(version, port-version) of swarm-core in the registry's versions/baseline.json
    at `commit`, or None."""
    rc, text, _ = git("show", f"{commit}:versions/baseline.json", cwd=d)
    if rc:
        return None
    try:
        entry = json.loads(text)["default"][PORT]
        return entry["baseline"], entry.get("port-version", 0)
    except (ValueError, KeyError, TypeError):
        return None


def check_vcpkg(version, registry):
    """Errors when the vcpkg pins disagree with the lock's version or the registry."""
    want, pv, baseline, _, _, errors = vcpkg_pins()
    if want and want != version:
        errors.append(
            f"{VCPKG_MANIFEST}: the override pins {PORT} {want}, {LOCK} names {version} "
            "(the ns-3 build's tag): one repository builds one swarm-core"
        )
    if not baseline:
        return errors
    with tempfile.TemporaryDirectory() as d:
        err = registry_clone(registry, d)
        if err:
            return errors + [err]
        if git("cat-file", "-e", f"{baseline}^{{commit}}", cwd=d)[0]:
            return errors + [f"{VCPKG_CONFIG}: baseline {baseline} is not a registry commit"]
        if git("merge-base", "--is-ancestor", baseline, "origin/main", cwd=d)[0]:
            errors.append(f"{VCPKG_CONFIG}: baseline {baseline} is not on the registry's main")
        got = registry_port(d, baseline)
        if not got:
            errors.append(f"{VCPKG_CONFIG}: the registry at {baseline[:7]} has no {PORT} port")
        elif want and got != (want, pv):
            errors.append(
                f"{VCPKG_CONFIG}: the registry at {baseline[:7]} has {PORT} "
                f"{got[0]}#{got[1]}, {VCPKG_MANIFEST} overrides {want}#{pv}"
            )
    return errors


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def retag(line, patterns, old, new):
    """The line with every pin match naming `old` rewritten to `new`, on the
    matched span only, whatever the spacing around it."""
    spans = sorted(
        {m.span(1) for pat in patterns for m in pat.finditer(line) if m.group(1) == old},
        reverse=True,
    )
    for a, b in spans:
        line = line[:a] + new + line[b:]
    return line


def reslug(old_line, new_line, to=SWARM_CORE_REPO, force=False):
    """A pin line the bump moved, with swarm-core's old repository name (#672)
    replaced by its new one, `to` (swarm-core's own repository once its releases
    moved there, #691); a line the bump left is returned as it is, unless
    `force`."""
    if new_line == old_line and not force:
        return new_line
    for old in (LEGACY_REPO, SWARM_CORE_REPO):
        new_line = new_line.replace(old + "@", to + "@")
    return new_line


def run_lock(releases, registry=REGISTRY, stale_mode="fail"):
    prefix, values, errors = check_lock_files()
    stale = []
    newest = None
    vcpkg = vcpkg_mode()
    if values and vcpkg:
        errors += check_vcpkg(values[f"{prefix}_VERSION"], registry)
    if values:
        try:
            errors += release_lock.verify(prefix, values, releases)
            repo = values[f"{prefix}_REPO"]
            new_repo, newest, _ = release_lock.next_release(releases, prefix, repo)
        except release_lock.LockError as e:
            errors.append(str(e))
        tag = values[f"{prefix}_TAG"]
        if newest and release_lock.is_newer(repo, tag, new_repo, newest):
            where = "" if new_repo == release_lock.canonical(repo) else f" from {new_repo}"
            stale.append(
                f"swarm-core {newest} is released{where}; {LOCK} names {tag}: bump the lock and "
                f"every pin place to {newest} (org-bot's swarm-core-pin task opens that PR)"
            )
    if values and release_lock.canonical(values[f"{prefix}_REPO"]) == CORE_REPO:
        try:
            stale += adapter_stale(releases, values[f"{prefix}_TAG"])
        except release_lock.LockError as e:
            errors.append(str(e))
    stale_failed = judge_stale(stale, stale_mode)
    errors += stale_failed
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        print(f"swarm-core pin (lock): {len(errors)} problem(s)")
        return 1
    also = f", {VCPKG_MANIFEST} and the registry baseline agree" if vcpkg else ""
    newest_note = (
        " (a newer release is out: a warning above)" if stale else ", the newest swarm-core release"
    )
    print(f"swarm-core pin (lock): ok, {LOCK} names {tag}{newest_note}{also}")
    return 0


def bump_lock(releases, registry=REGISTRY):
    """--bump in lock mode: when a newer swarm-core release exists, write the lock
    for it (every value read from the release) and move the tag on the pin lines;
    in vcpkg mode also the override and the registry baseline, once the registry's
    main holds the release."""
    prefix, values, errors = check_lock_files()
    vcpkg = vcpkg_mode()
    if values:
        try:
            errors += release_lock.verify(prefix, values, releases)
        except release_lock.LockError as e:
            errors.append(str(e))
        if vcpkg:
            errors += check_vcpkg(values[f"{prefix}_VERSION"], registry)
    for e in errors:
        print(f"FAIL {e}")
    if not values or errors:
        print("swarm-core pin (lock): not bumped (fix the lock by hand first)")
        return 1
    repo, tag = release_lock.canonical(values[f"{prefix}_REPO"]), values[f"{prefix}_TAG"]
    try:
        new_repo, newest, commit = release_lock.next_release(releases, prefix, repo)
        lock_moves = bool(newest) and release_lock.is_newer(repo, tag, new_repo, newest)
        core_repo, core_tag = (new_repo, newest) if lock_moves else (repo, tag)
        # the ns-3 dependency follows the adapter release that ships the
        # lock's swarm-core release (#691)
        a_tag, a_commit = (
            adapter_for(releases, core_tag)
            if core_repo == CORE_REPO and ns3_pins()
            else (None, None)
        )
        if lock_moves:
            with open(LOCK, encoding="utf-8") as f:
                header = "".join(line for line in f if line.lstrip().startswith("#"))
            text = release_lock.render(prefix, new_repo, newest, ASSET, releases, header)
    except release_lock.LockError as e:
        print(f"FAIL {e}")
        return 1
    if not lock_moves:
        changed = move_adapter(a_tag, a_commit, core_repo == CORE_REPO)
        if not changed:
            print(f"swarm-core pin (lock): current, {LOCK} names {tag}, the newest release")
            return 0
        if not a_tag:
            print(
                f"swarm-core pin (lock): the ns-3 canary moves to {SWARM_CORE_REPO}@main, "
                f"its name since 2026-11-22, in {len(changed)} file(s)"
            )
            for c in changed:
                print(f"  {c}")
            return 0
        print(
            f"swarm-core pin (lock): the ns-3 dependency moves to {SWARM_CORE_REPO} {a_tag}, "
            f"the release that ships swarm-core {tag}, in {len(changed)} file(s)"
        )
        print(f"pin-target: {a_commit}")
        for c in changed:
            print(f"  {c}")
        return 0
    if vcpkg:
        # the registry's main must hold the release (its port PR merged) first
        new_version = release_lock.parse_text(text)[1][f"{prefix}_VERSION"]
        with tempfile.TemporaryDirectory() as d:
            err = registry_clone(registry, d)
            if err:
                print(f"FAIL {err}")
                return 1
            head = git("rev-parse", "origin/main", cwd=d)[1]
            got = registry_port(d, head)
        if not got or got[0] != new_version:
            have = f"{got[0]}#{got[1]}" if got else "no port"
            print(
                f"swarm-core pin (vcpkg): swarm-core {newest} is released, the registry's "
                f"main ({head[:7]}) has {PORT} {have}: waiting for its port PR, nothing bumped"
            )
            return 0
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(text)
    changed = [LOCK]
    if vcpkg:
        _, _, _, manifest, config, _ = vcpkg_pins()
        for o in manifest["overrides"]:
            if o.get("name") == PORT:
                o.pop("version-semver", None)
                o["version"], o["port-version"] = got
        for r in config["registries"]:
            if same_repo(str(r.get("repository", ""))) and PORT in (r.get("packages") or []):
                r["baseline"] = head
        write_json(VCPKG_MANIFEST, manifest)
        write_json(VCPKG_CONFIG, config)
        changed += [VCPKG_MANIFEST, VCPKG_CONFIG]
    moving = new_repo != repo  # to swarm-core's own repository (#691)
    for path, patterns in pin_places():
        if new_repo == CORE_REPO and path != "Makefile":
            # core-deps follow swarm-core; the ns-3 dependency names
            # swarm-adapter-ns3, which has no such release, on every bump
            # from the move on
            patterns = [CORE_DEP]
        with open(path, encoding="utf-8", newline="") as f:
            lines = f.readlines()
        old_commit = values[f"{prefix}_COMMIT"]
        new = [
            reslug(
                line,
                retag(retag(line, patterns, tag, newest), patterns, old_commit, commit),
                new_repo,
                # moving: every core-deps line changes repository, even one
                # whose tag or commit the successor's release shares
                force=moving and CORE_DEP.search(line) is not None,
            )
            for line in lines
        ]
        if moving and path == "Makefile":
            new = [MAKE_FETCH.sub(f"github.com/{new_repo}", line) for line in new]
        if new != lines:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.writelines(new)
            changed.append(path)
    on_adapter = move_adapter(a_tag, a_commit, core_repo == CORE_REPO)
    changed += [p for p in on_adapter if p not in changed]
    low = None if moving else release_lock.version_key(tag)
    between = sorted(
        (
            t
            for t in release_lock.tags(releases, new_repo)
            if release_lock.version_key(t)
            and (low is None or low < release_lock.version_key(t))
            and release_lock.version_key(t) <= release_lock.version_key(newest)
        ),
        key=release_lock.version_key,
    )
    where = f" (from {repo} to {new_repo})" if moving else ""
    print(f"swarm-core pin (lock): bumped {tag} -> {newest}{where} in {len(changed)} file(s)")
    print(f"pin-target: {commit}")
    if a_tag:
        print(f"the ns-3 dependency: {SWARM_CORE_REPO} {a_tag}, which ships swarm-core {newest}")
        print(f"pin-target: {a_commit}")
    for c in changed:
        print(f"  {c}")
    print("swarm-core releases since the lock (their notes: the release pages):")
    for t in between:
        print(f"  {t}: https://github.com/{new_repo}/releases/tag/{t}")
    return 0


def run(url, stale_mode="fail"):
    pin, errors = check_files()
    main, stale = None, []
    if pin:
        more, stale, main = check_main(pin, url)
        errors += more + judge_stale(stale, stale_mode)
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        print(f"swarm-core pin: {len(errors)} problem(s)")
        return 1
    if stale:
        print(f"swarm-core pin: ok, the pin is one commit ({pin}); main moved: a warning above")
        return 0
    print(f"swarm-core pin: ok, core/ at {pin} is swarm-core main's ({main})")
    return 0


# --- self-test: a local swarm-core and fixture protocol repositories -----------


def self_test():
    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    for k in ("GIT_AUTHOR", "GIT_COMMITTER"):  # the fixture commits' identity
        os.environ[f"{k}_NAME"], os.environ[f"{k}_EMAIL"] = "t", "t@t"

    def commit(d, files, msg):
        for p, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)), exist_ok=True)
            with open(os.path.join(d, p), "w", encoding="utf-8") as f:
                f.write(text)
        git("add", "-A", cwd=d)
        git("commit", "-q", "-m", msg, cwd=d)
        return git("rev-parse", "HEAD", cwd=d)[1]

    # the fixtures name swarm-core by its old repository name on purpose: it
    # still counts (#672); a bump moves it to the new one
    def protocol(d, cmake, make, licence, ns3=None):
        files = {
            CMAKE: f'set(SWARM_CORE_REF "{cmake}" CACHE STRING "swarm-core commit")\n',
            "Makefile": f"SWARM_CORE_REF ?= {make}\n",
            ".github/workflows/licence.yml": "jobs:\n  headers:\n    with:\n"
            f"      core-deps: swarm-routing/ns3-swarm-core@{licence}:core\n",
        }
        if ns3:
            files[".github/workflows/ns3.yml"] = (
                "jobs:\n  ci:\n    with:\n      dependencies: |\n"
                f"        swarm-core=swarm-routing/ns3-swarm-core@{ns3[0]}\n"
                f"      core-deps: swarm-routing/ns3-swarm-core@{ns3[1]}:core\n"
            )
        os.makedirs(d)
        for p, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)), exist_ok=True)
            with open(os.path.join(d, p), "w", encoding="utf-8") as f:
                f.write(text)
        return d

    def go(repo, url, bump_mode=False):
        import contextlib
        import io

        out, here = io.StringIO(), os.getcwd()
        try:
            os.chdir(repo)
            with contextlib.redirect_stdout(out):
                rc = bump(url) if bump_mode else run(url)
        finally:
            os.chdir(here)
        return rc, out.getvalue()

    with tempfile.TemporaryDirectory() as t:
        sc = os.path.join(t, "swarm-core")
        os.makedirs(sc)
        git("init", "-q", "-b", "main", cwd=sc)
        a = commit(sc, {"core/a.h": "int a;\n", "README.md": "x\n"}, "a")
        b = commit(sc, {"README.md": "y\n", "model/m.cc": "int m;\n"}, "outside core/")
        url = sc

        rc, out = go(protocol(os.path.join(t, "ok"), a, a, a, ("main", a)), url)
        check("one pin, core/ unchanged since: ok", rc == 0 and f"core/ at {a}" in out)
        check("a change outside core/ needs no bump", b in out)

        rc, out = go(protocol(os.path.join(t, "make"), a, b, a), url)
        check("Makefile disagrees", rc == 1 and f"Makefile:1: SWARM_CORE_REF is {b}" in out)

        rc, out = go(protocol(os.path.join(t, "lic"), a, a, b, ("main", a)), url)
        check(
            "licence core-deps disagrees, named by file and line",
            rc == 1
            and f".github/workflows/licence.yml:4: core-deps names swarm-core {b}" in out
            and "ns3.yml" not in out,
        )
        rc, out = go(protocol(os.path.join(t, "ns3"), a, a, a, ("main", b)), url)
        check("ns-3 core-deps disagrees", rc == 1 and ".github/workflows/ns3.yml:6:" in out)
        rc, out = go(protocol(os.path.join(t, "dep"), a, a, a, ("v1", a)), url)
        check("ns-3 dependency neither main nor the pin", rc == 1 and "ns3.yml:5:" in out)

        c = commit(sc, {"core/a.h": "int a, b;\n"}, "core/ changes")
        rc, out = go(protocol(os.path.join(t, "stale"), a, a, a), url)
        check(
            "swarm-core main changed core/: bump",
            rc == 1
            and f"swarm-core main ({c}) changed core/ since the pin ({a})" in out
            and "core/a.h" in out,
        )
        # #586: on a PR the stale pin is a warning, but a pin the files disagree
        # on still fails
        here = os.getcwd()
        os.chdir(os.path.join(t, "stale"))
        try:
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_warn = run(url, "warn")
        finally:
            os.chdir(here)
        check(
            "swarm-core main changed core/, --stale warn: a warning, exit 0",
            rc_warn == 0 and "::warning title=swarm-core pin::swarm-core main" in buf.getvalue(),
        )
        disagree = protocol(os.path.join(t, "stale-disagree"), a, c, a)
        os.chdir(disagree)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc_dis = run(url, "warn")
        finally:
            os.chdir(here)
        check("--stale warn still fails a pin the files disagree on", rc_dis == 1)
        rc, out = go(protocol(os.path.join(t, "new"), c, c, c), url)
        check("bumped pin: ok", rc == 0)

        # --bump (#208): a stale pin is rewritten in every pin place, extra workflows included
        stale = protocol(os.path.join(t, "bump"), a, a, a, ("main", a))
        with open(os.path.join(stale, ".github", "workflows", "bench.yml"), "w") as f:
            f.write(f"        swarm-core=swarm-routing/ns3-swarm-core@{a}\n")
        rc, out = go(stale, url, bump_mode=True)
        names = []
        for root, _, files in os.walk(stale):
            for name in files:
                with open(os.path.join(root, name)) as f:
                    names += [name] if a in f.read() else []
        check(
            "--bump rewrites the stale pin in every pin place, a benchmark workflow included",
            rc == 0
            and not names
            and f"pin-target: {c}" in out
            and "core/ changes" in out
            and "bench.yml" in out,
        )
        with open(os.path.join(stale, ".github", "workflows", "licence.yml")) as f:
            licence_text = f.read()
        check(
            "--bump writes swarm-core's new repository name on the lines it moves (#672)",
            f"swarm-routing/swarm-adapter-ns3@{c}:core" in licence_text
            and "ns3-swarm-core" not in licence_text,
        )
        rc, out = go(stale, url)
        check("…after which the check passes", rc == 0)

        # #407: recorded data naming the old pin is never rewritten, only the pin places
        rec = protocol(os.path.join(t, "recorded"), a, a, a, ("main", a))
        kept = {
            "results/cells/anchor/cell-1.txt": f"##PROV## base=sha256:x modules=swarm-core@{a}\n",
            "docs/benchmarks/anchor.md": f"Ran on swarm-core `{a}`.\n",
            "tools/bench/campaigns/anchor.yaml": f"pins:\n  swarm-core: {a}\n",
            "README.md": f"Pinned at {a}.\n",
            ".github/workflows/notes.yml": f"# recorded with swarm-core {a}\n",
        }
        for p, text in kept.items():
            os.makedirs(os.path.dirname(os.path.join(rec, p)), exist_ok=True)
            with open(os.path.join(rec, p), "w", encoding="utf-8") as f:
                f.write(text)
        rc, out = go(rec, url, bump_mode=True)
        same = []
        for p, text in kept.items():
            with open(os.path.join(rec, p), encoding="utf-8") as f:
                same += [p] if f.read() == text else []
        check(
            "--bump leaves recorded cells, docs, plans and other files byte-identical (#407)",
            rc == 0 and same == list(kept) and not any(p in out for p in kept),
        )
        rc, out = go(rec, url)
        check("…and still moves every pin place, so the check passes", rc == 0)

        split = protocol(os.path.join(t, "split-cmake"), a, a, a)
        with open(os.path.join(split, CMAKE), "w", encoding="utf-8") as f:
            f.write(f'set(SWARM_CORE_REF\n    "{a}"\n    CACHE STRING "swarm-core commit")\n')
        rc, out = go(split, url, bump_mode=True)
        with open(os.path.join(split, CMAKE), encoding="utf-8") as f:
            moved = c in f.read()
        rc2, _ = go(split, url)
        check("--bump rewrites a CMake pin split over lines", rc == 0 and moved and rc2 == 0)
        rc, out = go(stale, url, bump_mode=True)
        check("--bump on a current pin changes nothing", rc == 0 and "current" in out)
        rc, out = go(protocol(os.path.join(t, "split"), a, b, a), url, bump_mode=True)
        check("--bump refuses a pin the files disagree on", rc == 1 and "not bumped" in out)

        rc, out = go(protocol(os.path.join(t, "ghost"), "f" * 40, "f" * 40, "f" * 40), url)
        check(
            "a pin that is not a swarm-core commit", rc == 1 and "is not a swarm-core commit" in out
        )

        bare = os.path.join(t, "bare")
        os.makedirs(os.path.join(bare, "core"))
        with open(os.path.join(bare, CMAKE), "w") as f:
            f.write("project(x)\n")
        rc, out = go(bare, url)
        check("no SWARM_CORE_REF", rc == 1 and "no set(SWARM_CORE_REF" in out)
        nomake = protocol(os.path.join(t, "nomake"), c, c, c)
        os.remove(os.path.join(nomake, "Makefile"))
        os.remove(os.path.join(nomake, ".github", "workflows", "licence.yml"))
        rc, out = go(nomake, url)
        check(
            "no Makefile pin, no core-deps",
            rc == 1 and "Makefile: no SWARM_CORE_REF" in out and "no core-deps entry" in out,
        )

        # lock mode (swarm-routing/swarm-adapter-ns3#134): the pin is a release
        rel = os.path.join(t, "rel")
        base = "file://" + rel
        env = dict(os.environ)
        new_commit = release_lock.fixture_repo(rel, SWARM_CORE_REPO, env)
        core_commit = release_lock.fixture_repo(rel, CORE_REPO, env)  # no release yet (#691)
        release_lock.make_release(
            rel, SWARM_CORE_REPO, "v0.3.0", {"swarm-core-0.3.0.tar.gz": b"three"}, env
        )

        def locked(name, tag, cmake_reads=True, ns3_ref=None, canary=None, make=None):
            d = os.path.join(t, name)
            text = release_lock.render(LOCK_PREFIX, SWARM_CORE_REPO, tag, ASSET, base, "# lock\n")
            files = {
                LOCK: text,
                CMAKE: f"file(STRINGS ${{CMAKE_CURRENT_LIST_DIR}}/../{LOCK} x)\n"
                if cmake_reads
                else "project(x)\n",
                "Makefile": f"SWARM_CORE_REF ?= {make or tag}\n",
                ".github/workflows/licence.yml": "jobs:\n  headers:\n    with:\n"
                f"      core-deps: swarm-routing/ns3-swarm-core@{tag}:core\n",
                ".github/workflows/ns3.yml": "jobs:\n  ci:\n    with:\n      dependencies: |\n"
                f"        swarm-core=swarm-routing/ns3-swarm-core@{ns3_ref or tag}\n"
                "      canary-dependencies: |\n"
                f"        swarm-core=swarm-routing/ns3-swarm-core@{canary or 'main'}\n"
                f"      core-deps: swarm-routing/ns3-swarm-core@{tag}:core\n",
                "results/cell.txt": f"##PROV## swarm-core@{tag}\n",
                ".github/workflows/bench.yml": "    uses: swarm-routing/.github/.github/workflows/"
                "reusable-benchmark-cell.yml@main\n      dependencies: |\n"
                "        swarm-core=swarm-routing/ns3-swarm-core@"
                + release_lock.parse_text(text)[1][f"{LOCK_PREFIX}_COMMIT"]
                + "\n",
            }
            for p_, body in files.items():
                os.makedirs(os.path.dirname(os.path.join(d, p_)) or d, exist_ok=True)
                with open(os.path.join(d, p_), "w", encoding="utf-8") as f:
                    f.write(body)
            return d

        def golock(repo, bump_mode=False, stale=None):
            import contextlib
            import io

            out, here = io.StringIO(), os.getcwd()
            try:
                os.chdir(repo)
                with contextlib.redirect_stdout(out):
                    rc = main(
                        ["--releases", base]
                        + (["--bump"] if bump_mode else [])
                        + (["--stale", stale] if stale else [])
                    )
            finally:
                os.chdir(here)
            return rc, out.getvalue()

        current = locked("lock-ok", "v0.3.0")
        rc, out = golock(current)
        check("lock: newest release, every place on its tag: ok", rc == 0 and "lock): ok" in out)
        rc, out = golock(current, bump_mode=True)
        check("lock: --bump on the newest release changes nothing", rc == 0 and "current" in out)
        legacy = locked("lock-legacy", "v0.3.0")
        with open(os.path.join(legacy, LOCK), encoding="utf-8") as f:
            text = f.read().replace(SWARM_CORE_REPO, LEGACY_REPO)
        with open(os.path.join(legacy, LOCK), "w", encoding="utf-8") as f:
            f.write(text)
        rc, out = golock(legacy)
        check("lock: swarm-core's name before 2026-11-22 still verifies (#672)", rc == 0)
        rc, out = golock(locked("lock-ns3", "v0.3.0", ns3_ref="main"))
        check(
            "lock: the ns-3 dependency on main is refused outside canary-dependencies",
            rc == 1 and "ns3.yml:5: the ns-3 dependency names swarm-core main" in out,
        )
        rc, out = golock(locked("lock-canary", "v0.3.0", canary="v0.2.9"))
        check("lock: a canary on another tag is refused", rc == 1 and "ns3.yml:7:" in out)
        incommit = locked("lock-ns3commit", "v0.3.0")
        with open(os.path.join(incommit, LOCK), encoding="utf-8") as f:
            pinned = release_lock.parse_text(f.read())[1][f"{LOCK_PREFIX}_COMMIT"]
        ns3p = os.path.join(incommit, ".github", "workflows", "ns3.yml")
        with open(ns3p, encoding="utf-8") as f:
            body = f.read()
        with open(ns3p, "w", encoding="utf-8") as f:
            f.write(body.replace("ns3-swarm-core@v0.3.0\n", f"ns3-swarm-core@{pinned}\n", 1))
        rc, out = golock(incommit)
        check(
            "lock: the ns-3 CI's dependency takes the tag, not the commit (git clone --branch)",
            rc == 1 and "ns3.yml:5:" in out,
        )
        rc, out = golock(locked("lock-make", "v0.3.0", make="v0.2.0"))
        check("lock: the Makefile on another tag", rc == 1 and "Makefile:1:" in out)
        rc, out = golock(locked("lock-cmake", "v0.3.0", cmake_reads=False))
        check("lock: core/CMakeLists.txt must read the lock", rc == 1 and "does not read" in out)
        mention = locked("lock-comment", "v0.3.0")
        with open(os.path.join(mention, CMAKE), "w", encoding="utf-8") as f:
            f.write(f"# reads {LOCK} (not really)\nset(URL swarm-core-0.3.0.tar.gz)\n")
        rc, out = golock(mention)
        check(
            "lock: a comment naming the lock is no read, a release in CMake is refused",
            rc == 1 and "does not read" in out and "names a swarm-core release" in out,
        )
        nohash = locked("lock-nohash", "v0.3.0")
        with open(os.path.join(nohash, LOCK), encoding="utf-8") as f:
            body = f.read()
        with open(os.path.join(nohash, LOCK), "w", encoding="utf-8") as f:
            f.write(body.replace("SWARM_CORE_SHA256=", "SWARM_CORE_OTHER_SHA256="))
        rc, out = golock(nohash)
        check(
            "lock: SWARM_CORE_SHA256 is required, another asset's hash is not enough",
            rc == 1 and "SWARM_CORE_SHA256" in out and "needs" in out,
        )
        bad = locked("lock-hash", "v0.3.0")
        with open(os.path.join(bad, LOCK), encoding="utf-8") as f:
            body = f.read()
        with open(os.path.join(bad, LOCK), "w", encoding="utf-8") as f:
            f.write(re.sub(r"SHA256=\w+", "SHA256=" + "0" * 64, body))
        rc, out = golock(bad)
        check("lock: a hash that is not the release's", rc == 1 and "SHA256SUMS" in out)

        # a new release: the check fails, --bump writes the lock for it and moves the tag
        new_commit("four")
        release_lock.make_release(
            rel, SWARM_CORE_REPO, "v0.4.0", {"swarm-core-0.4.0.tar.gz": b"four"}, env
        )
        with open(os.path.join(current, "Makefile"), "w", encoding="utf-8") as f:
            f.write("SWARM_CORE_REF?=v0.3.0\n")  # no spaces: --bump must still move it
        rc, out = golock(current)
        check("lock: a newer release fails the check", rc == 1 and "v0.4.0 is released" in out)
        # #586: on a PR or a merge group a newer release is a warning; on main it
        # fails only while org-bot's bump branch exists
        rc, out = golock(current, stale="warn")
        check(
            "lock: --stale warn passes a newer release with a warning",
            rc == 0 and "::warning title=swarm-core pin::swarm-core v0.4.0 is released" in out,
        )
        real_bump_pr_open = globals()["bump_pr_open"]
        try:
            for found, want_rc in ((True, 1), (False, 0), (None, 0)):
                globals()["bump_pr_open"] = lambda found=found: found
                rc, out = golock(current, stale="bump-pr")
                check(
                    f"lock: --stale bump-pr with the bump branch {found}: exit {want_rc}",
                    rc == want_rc
                    and ("bump PR (org-bot/swarm-core-pin) is open" in out) == (want_rc == 1),
                )
        finally:
            globals()["bump_pr_open"] = real_bump_pr_open
        rc, out = golock(current, bump_mode=True)
        with open(os.path.join(current, LOCK), encoding="utf-8") as f:
            lock_text = f.read()
        with open(os.path.join(current, "results", "cell.txt"), encoding="utf-8") as f:
            cell = f.read()
        with open(os.path.join(current, ".github", "workflows", "ns3.yml"), encoding="utf-8") as f:
            ns3 = f.read()
        check(
            "lock: --bump writes the new release's lock and tag, recorded data untouched",
            rc == 0
            and "SWARM_CORE_TAG=v0.4.0" in lock_text
            and lock_text.startswith("# lock\n")
            and "pin-target:" in out
            and "v0.4.0:" in out
            and cell == "##PROV## swarm-core@v0.3.0\n"
            and "@v0.4.0\n" in ns3
            and "swarm-core=swarm-routing/swarm-adapter-ns3@v0.4.0\n" in ns3
            and open(os.path.join(current, "Makefile"), encoding="utf-8").read()
            == "SWARM_CORE_REF?=v0.4.0\n"
            and "@main\n" in ns3
            and release_lock.parse_text(lock_text)[1]["SWARM_CORE_COMMIT"]
            in open(os.path.join(current, ".github", "workflows", "bench.yml")).read(),
        )
        rc, out = golock(current)
        check("lock: …after which the check passes", rc == 0)
        new_commit("unreleased")  # main moves, no release: no finding in lock mode
        rc, out = golock(current)
        check("lock: swarm-core main moving is no finding", rc == 0)

        # vcpkg mode (#489): the lock records the ns-3 tag, vcpkg pins the port
        reg = os.path.join(t, "registry")
        os.makedirs(reg)
        git("init", "-q", "-b", "main", cwd=reg)

        def port(v, pv):
            body = {"default": {PORT: {"baseline": v, "port-version": pv}}}
            return {"versions/baseline.json": json.dumps(body)}

        commit(reg, port("0.3.0", 0), "0.3.0")
        r4 = commit(reg, port("0.4.0", 1), "0.4.0#1")
        git("checkout", "-q", "-b", "pr", cwd=reg)
        side = commit(reg, port("0.4.0", 2), "an unmerged port PR")
        git("checkout", "-q", "main", cwd=reg)

        def vcpkged(name, version="0.4.0", pv=1, baseline=r4, cmake=None):
            d = locked(name, "v0.4.0")
            with open(os.path.join(d, CMAKE), "w", encoding="utf-8") as f:
                f.write(cmake or "find_package(swarm-core CONFIG REQUIRED)\n")
            manifest = {
                "dependencies": [PORT],
                "overrides": [{"name": PORT, "version": version, "port-version": pv}],
            }
            config = {
                "default-registry": {"kind": "builtin", "baseline": "a" * 40},
                "registries": [
                    {
                        "kind": "git",
                        "repository": REGISTRY,
                        "baseline": baseline,
                        "packages": [PORT],
                    }
                ],
            }
            write_json(os.path.join(d, VCPKG_MANIFEST), manifest)
            write_json(os.path.join(d, VCPKG_CONFIG), config)
            return d

        def govcpkg(repo, bump_mode=False):
            import contextlib
            import io

            out, here = io.StringIO(), os.getcwd()
            try:
                os.chdir(repo)
                with contextlib.redirect_stdout(out):
                    args = ["--releases", base, "--registry", reg]
                    rc = main(args + (["--bump"] if bump_mode else []))
            finally:
                os.chdir(here)
            return rc, out.getvalue()

        ok = vcpkged("vcpkg-ok")
        rc, out = govcpkg(ok)
        check("vcpkg: override, registry baseline and lock agree: ok", rc == 0 and "agree" in out)
        rc, out = govcpkg(vcpkged("vcpkg-version", "0.3.0", 0))
        check(
            "vcpkg: an override on another version than the lock (the ns-3 tag)",
            rc == 1 and "the override pins swarm-core 0.3.0, swarm-core.lock names 0.4.0" in out,
        )
        rc, out = govcpkg(vcpkged("vcpkg-pv", pv=0))
        check(
            "vcpkg: the baseline's port-version differs from the override's",
            rc == 1 and "has swarm-core 0.4.0#1, vcpkg.json overrides 0.4.0#0" in out,
        )
        rc, out = govcpkg(vcpkged("vcpkg-side", pv=2, baseline=side))
        check(
            "vcpkg: a baseline off the registry's main",
            rc == 1 and "not on the registry's main" in out,
        )
        rc, out = govcpkg(vcpkged("vcpkg-ghost", baseline="f" * 40))
        check(
            "vcpkg: a baseline that is no registry commit",
            rc == 1 and "not a registry commit" in out,
        )
        rc, out = govcpkg(vcpkged("vcpkg-lock", cmake=f"file(STRINGS ../{LOCK} x)\n"))
        check(
            "vcpkg: core/ must find_package swarm-core, not read the lock",
            rc == 1
            and "no find_package(swarm-core CONFIG" in out
            and "reads swarm-core.lock" in out,
        )
        noover = vcpkged("vcpkg-noover")
        write_json(os.path.join(noover, VCPKG_MANIFEST), {"dependencies": [PORT]})
        rc, out = govcpkg(noover)
        check(
            "vcpkg: the version must be explicit (an override)",
            rc == 1 and "overrides entry" in out,
        )

        # a new release: no bump until the registry's main holds its port
        new_commit("five")
        release_lock.make_release(
            rel, SWARM_CORE_REPO, "v0.5.0", {"swarm-core-0.5.0.tar.gz": b"five"}, env
        )
        before = {
            p_: open(os.path.join(ok, p_)).read() for p_ in (LOCK, VCPKG_MANIFEST, VCPKG_CONFIG)
        }
        rc, out = govcpkg(ok, bump_mode=True)
        after = {p_: open(os.path.join(ok, p_)).read() for p_ in before}
        check(
            "vcpkg: --bump waits for the registry's port, changing nothing",
            rc == 0 and "waiting for its port PR" in out and before == after,
        )
        r5 = commit(reg, port("0.5.0", 0), "0.5.0")
        rc, out = govcpkg(ok, bump_mode=True)
        with open(os.path.join(ok, VCPKG_MANIFEST), encoding="utf-8") as f:
            manifest = json.load(f)
        with open(os.path.join(ok, VCPKG_CONFIG), encoding="utf-8") as f:
            config = json.load(f)
        check(
            "vcpkg: --bump moves the lock, the override and the registry baseline together",
            rc == 0
            and "SWARM_CORE_TAG=v0.5.0" in open(os.path.join(ok, LOCK)).read()
            and manifest["overrides"] == [{"name": PORT, "version": "0.5.0", "port-version": 0}]
            and config["registries"][0]["baseline"] == r5
            and config["default-registry"]["baseline"] == "a" * 40
            and VCPKG_CONFIG in out,
        )
        rc, out = govcpkg(ok)
        check("vcpkg: …after which the check passes", rc == 0)

        # swarm-core releases from its own repository (#691): its first release
        # counts as newer than swarm-adapter-ns3's last whatever its version; the
        # bump moves the lock, core-deps and the Makefile's fetch there, and
        # leaves the ns-3 dependency, which names swarm-adapter-ns3's module
        moved = locked("moved", "v0.5.0")
        mk = os.path.join(moved, "Makefile")
        with open(mk, "a", encoding="utf-8") as f:
            f.write(
                "\tgit fetch -q --depth 1 https://github.com/swarm-routing/ns3-swarm-core "
                "$(SWARM_CORE_REF)\n"
            )
        rc, out = golock(moved)
        check("moved: no swarm-core release yet, the adapter's lock is current", rc == 0)
        core_commit("two")
        release_lock.make_release(
            rel, CORE_REPO, "v0.1.0", {"swarm-core-0.1.0.tar.gz": b"own"}, env
        )
        rc, out = golock(moved)
        check(
            "moved: the first swarm-core release is newer than swarm-adapter-ns3's last",
            rc == 1 and f"swarm-core v0.1.0 is released from {CORE_REPO}" in out,
        )
        ns3_path = os.path.join(moved, ".github", "workflows", "ns3.yml")
        bench_path = os.path.join(moved, ".github", "workflows", "bench.yml")
        ns3_before = open(ns3_path, encoding="utf-8").read()
        bench_before = open(bench_path, encoding="utf-8").read()
        rc, out = golock(moved, bump_mode=True)
        lock_text = open(os.path.join(moved, LOCK), encoding="utf-8").read()
        ns3 = open(ns3_path, encoding="utf-8").read()
        licence = open(
            os.path.join(moved, ".github", "workflows", "licence.yml"), encoding="utf-8"
        ).read()
        make = open(mk, encoding="utf-8").read()
        check(
            "moved: --bump writes swarm-core's lock, core-deps and Makefile, not the ns-3 dep",
            rc == 0
            and f"from {SWARM_CORE_REPO} to {CORE_REPO}" in out
            and f"SWARM_CORE_REPO={CORE_REPO}\n" in lock_text
            and "SWARM_CORE_TAG=v0.1.0\n" in lock_text
            and f"core-deps: {CORE_REPO}@v0.1.0:core\n" in licence
            and f"core-deps: {CORE_REPO}@v0.1.0:core\n" in ns3
            and "swarm-core=swarm-routing/ns3-swarm-core@v0.5.0\n" in ns3
            and "swarm-core=swarm-routing/swarm-adapter-ns3@main\n" in ns3
            and "ns3-swarm-core@main" not in ns3
            and open(bench_path, encoding="utf-8").read() == bench_before
            and "SWARM_CORE_REF ?= v0.1.0\n" in make
            and f"https://github.com/{CORE_REPO} $(SWARM_CORE_REF)" in make
            and f"v0.1.0: https://github.com/{CORE_REPO}/releases/tag/v0.1.0" in out
            and ns3_before != ns3,
        )
        rc, out = golock(moved)
        check("moved: …after which the check passes", rc == 0)
        with open(ns3_path, "w", encoding="utf-8") as f:
            f.write(
                ns3.replace(
                    f"{CORE_REPO}@v0.1.0:core", "swarm-routing/swarm-adapter-ns3@v0.1.0:core"
                )
            )
        with open(mk, "w", encoding="utf-8") as f:
            f.write(make.replace(CORE_REPO, SWARM_CORE_REPO))
        rc, out = golock(moved)
        check(
            "moved: core-deps or the Makefile's fetch on swarm-adapter-ns3 are refused",
            rc == 1
            and f"core-deps names swarm-routing/swarm-adapter-ns3, {LOCK} {CORE_REPO}" in out
            and f"Makefile:2: fetches SWARM_CORE_REF from {SWARM_CORE_REPO}" in out,
        )
        # the successor's release on the lock's own tag: core-deps on that tag
        # change repository all the same
        same = locked("moved-same", "v0.5.0")
        core_commit("three")
        release_lock.make_release(
            rel, CORE_REPO, "v0.5.0", {"swarm-core-0.5.0.tar.gz": b"own five"}, env
        )
        rc, out = golock(same, bump_mode=True)
        ns3_path = os.path.join(same, ".github", "workflows", "ns3.yml")
        ns3 = open(ns3_path, encoding="utf-8").read()
        check(
            "moved: a successor release on the same tag still moves core-deps",
            rc == 0
            and f"core-deps: {CORE_REPO}@v0.5.0:core\n" in ns3
            and "swarm-core=swarm-routing/ns3-swarm-core@v0.5.0\n" in ns3
            and golock(same)[0] == 0,
        )
        # a later bump, swarm-core to swarm-core: the ns-3 dependency naming the
        # adapter at the old swarm-core tag stays on the adapter
        core_commit("four")
        release_lock.make_release(
            rel, CORE_REPO, "v0.6.0", {"swarm-core-0.6.0.tar.gz": b"own six"}, env
        )
        rc, out = golock(same, bump_mode=True)
        ns3 = open(ns3_path, encoding="utf-8").read()
        check(
            "moved: a later bump leaves the adapter's ns-3 dependency on the same tag",
            rc == 0
            and f"core-deps: {CORE_REPO}@v0.6.0:core\n" in ns3
            and "swarm-core=swarm-routing/ns3-swarm-core@v0.5.0\n" in ns3
            and golock(same)[0] == 0,
        )

        # the ns-3 adapter's layout (swarm-routing/swarm-adapter-ns3#258): the root
        # CMakeLists.txt reads the lock, no core/, no core-deps; the lock is the pin
        adapter = os.path.join(t, "adapter")
        lock5 = release_lock.render(LOCK_PREFIX, CORE_REPO, "v0.5.0", ASSET, base, "# lock\n")
        ci = "jobs:\n  ci:\n    with:\n      modules: swarm-core=.\n"
        for p_, body in (
            (LOCK, lock5),
            (ROOT_CMAKE, f"file(STRINGS ${{CMAKE_CURRENT_SOURCE_DIR}}/{LOCK} x)\n"),
            (".github/workflows/ci.yml", ci),
        ):
            os.makedirs(os.path.dirname(os.path.join(adapter, p_)) or adapter, exist_ok=True)
            with open(os.path.join(adapter, p_), "w", encoding="utf-8") as f:
                f.write(body)
        rc, out = golock(adapter)
        check(
            "adapter: a consistent lock behind the newest release is only stale",
            rc == 1
            and "v0.6.0 is released" in out
            and "no core-deps" not in out
            and "core/CMakeLists.txt" not in out,
        )
        rc, out = golock(adapter, bump_mode=True)
        check(
            "adapter: --bump writes the lock alone",
            rc == 0
            and "in 1 file(s)" in out
            and "SWARM_CORE_TAG=v0.6.0\n" in open(os.path.join(adapter, LOCK)).read()
            and open(os.path.join(adapter, ".github", "workflows", "ci.yml")).read() == ci
            and golock(adapter)[0] == 0,
        )
        with open(os.path.join(adapter, ROOT_CMAKE), "w", encoding="utf-8") as f:
            f.write("project(x)\n")
        rc, out = golock(adapter)
        check(
            "adapter: a root CMakeLists.txt that does not read the lock is no adapter layout",
            rc == 1 and "core/CMakeLists.txt: missing" in out,
        )

        # past the move the ns-3 dependency follows the swarm-adapter-ns3 release
        # whose own swarm-core.lock names the protocol's swarm-core release (#691),
        # read from the adapter's tag, never typed
        adapter_git = os.path.join(rel, SWARM_CORE_REPO + ".git")

        def adapter_release(tag, core_tag, msg):
            with open(os.path.join(adapter_git, LOCK), "w", encoding="utf-8") as f:
                f.write(release_lock.render(LOCK_PREFIX, CORE_REPO, core_tag, ASSET, base))
            new_commit(msg)
            v = tag[1:]
            return release_lock.make_release(
                rel, SWARM_CORE_REPO, tag, {f"swarm-adapter-ns3-{v}.cdx.json": msg.encode()}, env
            )[0]

        bench_path = os.path.join(same, ".github", "workflows", "bench.yml")
        bench_before = open(bench_path, encoding="utf-8").read()
        adapter_release("v0.8.0", "v0.5.0", "adapter on swarm-core v0.5.0")
        rc, out = golock(same)
        rc_b, out_b = golock(same, bump_mode=True)
        check(
            "adapter dep: no adapter release ships the lock's swarm-core, the line stays",
            rc == 0 and rc_b == 0 and "current" in out_b and open(ns3_path).read() == ns3,
        )
        a9 = adapter_release("v0.9.0", "v0.6.0", "adapter on swarm-core v0.6.0")
        subprocess.run(["git", "-C", adapter_git, "tag", "v0.10.0"], check=True, env=env)
        rc, out = golock(same)
        rc_w, _ = golock(same, stale="warn")
        check(
            "adapter dep: an adapter release shipping the lock's swarm-core makes the line stale",
            rc == 1
            and rc_w == 0
            and f"{SWARM_CORE_REPO} v0.9.0 ships swarm-core v0.6.0" in out
            and "ns3.yml:5:" in out
            and "bench.yml:" in out
            and "v0.10.0" not in out,  # a tag without a published release
        )
        rc, out = golock(same, bump_mode=True)
        ns3_moved = open(ns3_path, encoding="utf-8").read()
        bench = open(bench_path, encoding="utf-8").read()
        check(
            "adapter dep: --bump moves the ns-3 dependency alone (tag, a cell's commit)",
            rc == 0
            and f"pin-target: {a9}" in out
            and "swarm-core=swarm-routing/swarm-adapter-ns3@v0.9.0\n" in ns3_moved
            and "swarm-core=swarm-routing/swarm-adapter-ns3@main\n" in ns3_moved
            and f"core-deps: {CORE_REPO}@v0.6.0:core\n" in ns3_moved
            and f"swarm-core=swarm-routing/swarm-adapter-ns3@{a9}\n" in bench
            and bench_before != bench
            and "SWARM_CORE_TAG=v0.6.0\n" in open(os.path.join(same, LOCK)).read()
            and golock(same)[0] == 0
            and "current" in golock(same, bump_mode=True)[1],
        )
        # swarm-core and the adapter on it both released: one bump moves both
        core_commit("five")
        release_lock.make_release(
            rel, CORE_REPO, "v0.7.0", {"swarm-core-0.7.0.tar.gz": b"own seven"}, env
        )
        a11 = adapter_release("v0.11.0", "v0.7.0", "adapter on swarm-core v0.7.0")
        rc, out = golock(same, bump_mode=True)
        ns3_moved = open(ns3_path, encoding="utf-8").read()
        check(
            "adapter dep: a swarm-core bump takes the adapter release that ships it",
            rc == 0
            and "SWARM_CORE_TAG=v0.7.0\n" in open(os.path.join(same, LOCK)).read()
            and f"core-deps: {CORE_REPO}@v0.7.0:core\n" in ns3_moved
            and "swarm-core=swarm-routing/swarm-adapter-ns3@v0.11.0\n" in ns3_moved
            and f"swarm-core=swarm-routing/swarm-adapter-ns3@{a11}\n" in open(bench_path).read()
            and f"pin-target: {a11}" in out
            and golock(same)[0] == 0,
        )
        # the canary on swarm-core's old repository name (#672), every release
        # line current: --bump moves the slug alone, `main` kept
        with open(ns3_path, "w", encoding="utf-8") as f:
            f.write(
                ns3_moved.replace(
                    "swarm-core=swarm-routing/swarm-adapter-ns3@main\n",
                    "swarm-core=swarm-routing/ns3-swarm-core@main\n",
                )
            )
        rc, out = golock(same, bump_mode=True)
        check(
            "adapter dep: --bump moves a canary on the old name to swarm-adapter-ns3@main",
            rc == 0
            and open(ns3_path, encoding="utf-8").read() == ns3_moved
            and ".github/workflows/ns3.yml" in out
            and "None" not in out
            and "current" in golock(same, bump_mode=True)[1],
        )

        # the root vcpkg layout (swarm-routing/swarm-routingd, #958): no core/, the
        # root CMakeLists.txt finds the vcpkg port, no core-deps, no ns-3 build
        r7 = commit(reg, port("0.7.0", 0), "0.7.0")

        def rooted(name, version="0.7.0", baseline=r7, tag="v0.7.0"):
            d = os.path.join(t, name)
            lock = release_lock.render(LOCK_PREFIX, CORE_REPO, tag, ASSET, base, "# lock\n")
            for p_, body in (
                (LOCK, lock),
                (ROOT_CMAKE, "project(d)\nfind_package(swarm-core CONFIG REQUIRED)\n"),
                ("Makefile", "build:\n\tcmake --build build\n"),
                (".github/workflows/build.yml", "jobs:\n  build:\n    steps: []\n"),
            ):
                os.makedirs(os.path.dirname(os.path.join(d, p_)) or d, exist_ok=True)
                with open(os.path.join(d, p_), "w", encoding="utf-8") as f:
                    f.write(body)
            write_json(
                os.path.join(d, VCPKG_MANIFEST),
                {
                    "dependencies": [PORT],
                    "overrides": [{"name": PORT, "version": version, "port-version": 0}],
                },
            )
            write_json(
                os.path.join(d, VCPKG_CONFIG),
                {
                    "registries": [
                        {
                            "kind": "git",
                            "repository": REGISTRY,
                            "baseline": baseline,
                            "packages": [PORT],
                        }
                    ]
                },
            )
            return d

        root_ok = rooted("root-ok")
        rc, out = govcpkg(root_ok)
        check(
            "root vcpkg: lock, override and baseline agree, no core/ or core-deps wanted: ok",
            rc == 0 and "agree" in out and "core/" not in out and "core-deps" not in out,
        )
        rc, out = govcpkg(rooted("root-version", version="0.5.0"))
        check(
            "root vcpkg: an override on another version than the lock",
            rc == 1 and "the override pins swarm-core 0.5.0, swarm-core.lock names 0.7.0" in out,
        )
        rc, out = govcpkg(rooted("root-baseline", baseline=r5))
        check(
            "root vcpkg: a baseline holding another version",
            rc == 1 and "has swarm-core 0.5.0#0, vcpkg.json overrides 0.7.0#0" in out,
        )
        nofind = rooted("root-nofind")
        with open(os.path.join(nofind, ROOT_CMAKE), "w", encoding="utf-8") as f:
            f.write("project(d)\n")
        rc, out = govcpkg(nofind)
        check(
            "root vcpkg: the root CMakeLists.txt must find_package swarm-core",
            rc == 1 and "CMakeLists.txt: no find_package(swarm-core CONFIG" in out,
        )
        core_commit("eight")
        release_lock.make_release(
            rel, CORE_REPO, "v0.8.0", {"swarm-core-0.8.0.tar.gz": b"own eight"}, env
        )
        rc, out = govcpkg(root_ok)
        check(
            "root vcpkg: a newer release makes the lock stale",
            rc == 1 and "swarm-core v0.8.0 is released" in out,
        )
        before = {
            p_: open(os.path.join(root_ok, p_)).read()
            for p_ in (LOCK, VCPKG_MANIFEST, VCPKG_CONFIG)
        }
        rc, out = govcpkg(root_ok, bump_mode=True)
        after = {p_: open(os.path.join(root_ok, p_)).read() for p_ in before}
        check(
            "root vcpkg: --bump waits for the registry's port, changing nothing",
            rc == 0 and "waiting for its port PR" in out and before == after,
        )
        r8 = commit(reg, port("0.8.0", 0), "0.8.0")
        build = open(os.path.join(root_ok, ".github", "workflows", "build.yml")).read()
        rc, out = govcpkg(root_ok, bump_mode=True)
        with open(os.path.join(root_ok, VCPKG_MANIFEST), encoding="utf-8") as f:
            manifest = json.load(f)
        with open(os.path.join(root_ok, VCPKG_CONFIG), encoding="utf-8") as f:
            config = json.load(f)
        check(
            "root vcpkg: --bump writes the lock, the override and the baseline, nothing else",
            rc == 0
            and "in 3 file(s)" in out
            and "SWARM_CORE_TAG=v0.8.0\n" in open(os.path.join(root_ok, LOCK)).read()
            and manifest["overrides"] == [{"name": PORT, "version": "0.8.0", "port-version": 0}]
            and config["registries"][0]["baseline"] == r8
            and open(os.path.join(root_ok, ".github", "workflows", "build.yml")).read() == build
            and govcpkg(root_ok)[0] == 0,
        )

    for f in failures:
        print(f"FAIL: {f}")
    print(
        f"check-swarm-core-pin.py self-test: {'ok' if not failures else f'{len(failures)} failed'}"
    )
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--swarm-core", default=SWARM_CORE, help="swarm-core's git URL or a local path")
    p.add_argument(
        "--bump",
        action="store_true",
        help="rewrite a stale pin to swarm-core main's commit in the pin places only (#208, #407)",
    )
    p.add_argument(
        "--releases",
        default=release_lock.GITHUB,
        help="lock mode: where swarm-core's tags and release assets are read",
    )
    p.add_argument(
        "--registry",
        default=REGISTRY + ".git",
        help="vcpkg mode: swarm-routing/vcpkg-registry's git URL or a local path",
    )
    p.add_argument(
        "--stale",
        choices=STALE_MODES,
        default="fail",
        help="how an out-of-date but consistent pin is reported: fail, warn (a PR or merge "
        "group), bump-pr (fail only while org-bot's bump branch exists, #586)",
    )
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    if os.path.exists(LOCK):
        if a.bump:
            return bump_lock(a.releases, a.registry)
        return run_lock(a.releases, a.registry, a.stale)
    return bump(a.swarm_core) if a.bump else run(a.swarm_core, a.stale)


if __name__ == "__main__":
    sys.exit(main())
