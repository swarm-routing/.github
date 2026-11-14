#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""The swarm-core pin of a protocol repository is one commit, and current.

A protocol's dual-licensed `core/` builds on swarm-core's `core/` at a pinned
commit, named in several places:

- `core/CMakeLists.txt`: `set(SWARM_CORE_REF "<sha>" ...)`, the reference;
- `Makefile`: `SWARM_CORE_REF ?= <sha>`;
- every workflow's `core-deps` entry for swarm-core
  (`swarm-routing/ns3-swarm-core@<sha>:core`): the licence check's, and the
  ns-3 CI's where `ns3/` exists;
- the ns-3 build's dependency (`swarm-core=swarm-routing/ns3-swarm-core@<ref>`),
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

Lock mode (swarm-routing/ns3-swarm-core#134), used when the repository has
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

Usage (the protocol repository's root as cwd; it reads no path from its arguments):
  check-swarm-core-pin.py [--swarm-core URL_OR_PATH] [--releases URL] [--bump]
  check-swarm-core-pin.py --self-test

`--releases` (default https://github.com) is where lock mode reads tags and
release assets; the self-test passes a `file://` tree.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script's dir
import release_lock  # noqa: E402

SWARM_CORE = "https://github.com/swarm-routing/ns3-swarm-core.git"
SWARM_CORE_REPO = "swarm-routing/ns3-swarm-core"
CMAKE = "core/CMakeLists.txt"
LOCK = "swarm-core.lock"
LOCK_PREFIX = "SWARM_CORE"
ASSET = "swarm-core-{version}.tar.gz"
KEY = re.compile(r"^\s*([A-Za-z0-9_-]+):")
# core/CMakeLists.txt reads the lock on a line that is not a comment
LOCK_READ = re.compile(r"^[^#\n]*file\(\s*(STRINGS|READ)\b[^#\n]*swarm-core\.lock", re.M)
HARD_RELEASE = re.compile(r"ns3-swarm-core/releases/download/v\d|swarm-core-\d+\.\d+\.\d+\.tar")
SHA = r"[0-9a-f]{40}"
CMAKE_PIN = re.compile(rf'^\s*set\(\s*SWARM_CORE_REF\s+"({SHA})"', re.M)
MAKE_PIN = re.compile(r"^\s*SWARM_CORE_REF\s*[?:]?=\s*(\S+)", re.M)
CORE_DEP = re.compile(r"swarm-routing/ns3-swarm-core@([^\s:'\"]+):")
NS3_DEP = re.compile(r"swarm-core=swarm-routing/ns3-swarm-core@([^\s:'\"]+)")


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
    """Errors when swarm-core main's core/ is not the pinned commit's (blobless clone)."""
    err, main, stat, _ = core_change(pin, url)
    if err:
        return [err], main
    if stat:
        return [
            f"swarm-core main ({main}) changed core/ since the pin ({pin}): bump "
            f"SWARM_CORE_REF in {CMAKE}, the Makefile and every core-deps to {main}",
            *stat,
        ], main
    return [], main


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
            line.replace(pin, main)
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


# --- lock mode (swarm-routing/ns3-swarm-core#134) -----------------------------------


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
    if prefix != LOCK_PREFIX or values[f"{prefix}_REPO"] != SWARM_CORE_REPO:
        errors.append(f"{LOCK}: want {LOCK_PREFIX}_REPO={SWARM_CORE_REPO}")
    tag, version = values[f"{prefix}_TAG"], values[f"{prefix}_VERSION"]
    asset = ASSET.format(version=version)
    if values.get(f"{prefix}_ASSET") != asset:
        errors.append(f"{LOCK}: want {LOCK_PREFIX}_ASSET={asset}")
    if f"{prefix}_SHA256" not in values:
        errors.append(f"{LOCK}: want {LOCK_PREFIX}_SHA256, the hash of {asset}")
    if not os.path.exists(CMAKE):
        errors.append(f"{CMAKE}: missing")
    else:
        with open(CMAKE, encoding="utf-8") as f:
            text = f.read()
        if not LOCK_READ.search(text):
            errors.append(f"{CMAKE}: does not read {LOCK} (file(STRINGS ...) or file(READ ...))")
        if HARD_RELEASE.search(text):
            errors.append(f"{CMAKE}: names a swarm-core release itself; take it from {LOCK}")
        if CMAKE_PIN.search(text):
            errors.append(f"{CMAKE}: still sets a commit SWARM_CORE_REF; the lock replaces it")
    if os.path.exists("Makefile"):
        for n, ref in lines_matching("Makefile", MAKE_PIN):
            if ref != tag and not ref.startswith("$("):
                errors.append(f"Makefile:{n}: SWARM_CORE_REF is {ref}, not {tag}")
    deps = 0
    for path in sorted(glob.glob(".github/workflows/*.y*ml")):
        rel = path.replace(os.sep, "/")
        for n, ref in lines_matching(path, CORE_DEP):
            deps += 1
            if ref != tag:
                errors.append(f"{rel}:{n}: core-deps names swarm-core {ref}, not {tag}")
        for n, ref, key in dep_lines(path):
            ok = (tag, "main") if key == "canary-dependencies" else (tag,)
            if ref not in ok:
                errors.append(f"{rel}:{n}: the ns-3 dependency names swarm-core {ref}, not {tag}")
    if not deps:
        errors.append(f".github/workflows: no core-deps entry for swarm-core (want @{tag}:core)")
    return prefix, values, errors


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


def run_lock(releases):
    prefix, values, errors = check_lock_files()
    newest = None
    if values:
        try:
            errors += release_lock.verify(prefix, values, releases)
            newest, _ = release_lock.latest(releases, values[f"{prefix}_REPO"])
        except release_lock.LockError as e:
            errors.append(str(e))
        tag = values[f"{prefix}_TAG"]
        if newest and release_lock.version_key(newest) > release_lock.version_key(tag):
            errors.append(
                f"swarm-core {newest} is released; {LOCK} names {tag}: bump the lock and "
                f"every pin place to {newest} (org-bot's swarm-core-pin task opens that PR)"
            )
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        print(f"swarm-core pin (lock): {len(errors)} problem(s)")
        return 1
    print(f"swarm-core pin (lock): ok, {LOCK} names {tag}, the newest swarm-core release")
    return 0


def bump_lock(releases):
    """--bump in lock mode: when a newer swarm-core release exists, write the lock
    for it (every value read from the release) and move the tag on the pin lines."""
    prefix, values, errors = check_lock_files()
    if values:
        try:
            errors += release_lock.verify(prefix, values, releases)
        except release_lock.LockError as e:
            errors.append(str(e))
    for e in errors:
        print(f"FAIL {e}")
    if not values or errors:
        print("swarm-core pin (lock): not bumped (fix the lock by hand first)")
        return 1
    repo, tag = values[f"{prefix}_REPO"], values[f"{prefix}_TAG"]
    try:
        newest, commit = release_lock.latest(releases, repo)
        if not newest or release_lock.version_key(newest) <= release_lock.version_key(tag):
            print(f"swarm-core pin (lock): current, {LOCK} names {tag}, the newest release")
            return 0
        with open(LOCK, encoding="utf-8") as f:
            header = "".join(line for line in f if line.lstrip().startswith("#"))
        text = release_lock.render(prefix, repo, newest, ASSET, releases, header)
    except release_lock.LockError as e:
        print(f"FAIL {e}")
        return 1
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(text)
    changed = [LOCK]
    for path, patterns in pin_places():
        with open(path, encoding="utf-8", newline="") as f:
            lines = f.readlines()
        new = [retag(line, patterns, tag, newest) for line in lines]
        if new != lines:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.writelines(new)
            changed.append(path)
    between = sorted(
        (
            t
            for t in release_lock.tags(releases, repo)
            if release_lock.version_key(t)
            and release_lock.version_key(tag)
            < release_lock.version_key(t)
            <= release_lock.version_key(newest)
        ),
        key=release_lock.version_key,
    )
    print(f"swarm-core pin (lock): bumped {tag} -> {newest} in {len(changed)} file(s)")
    print(f"pin-target: {commit}")
    for c in changed:
        print(f"  {c}")
    print("swarm-core releases since the lock (their notes: the release pages):")
    for t in between:
        print(f"  {t}: https://github.com/{repo}/releases/tag/{t}")
    return 0


def run(url):
    pin, errors = check_files()
    main = None
    if pin:
        more, main = check_main(pin, url)
        errors += more
    for e in errors:
        print(f"FAIL {e}")
    if errors:
        print(f"swarm-core pin: {len(errors)} problem(s)")
        return 1
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

        # lock mode (swarm-routing/ns3-swarm-core#134): the pin is a release
        rel = os.path.join(t, "rel")
        base = "file://" + rel
        env = dict(os.environ)
        new_commit = release_lock.fixture_repo(rel, SWARM_CORE_REPO, env)
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
            }
            for p_, body in files.items():
                os.makedirs(os.path.dirname(os.path.join(d, p_)) or d, exist_ok=True)
                with open(os.path.join(d, p_), "w", encoding="utf-8") as f:
                    f.write(body)
            return d

        def golock(repo, bump_mode=False):
            import contextlib
            import io

            out, here = io.StringIO(), os.getcwd()
            try:
                os.chdir(repo)
                with contextlib.redirect_stdout(out):
                    rc = main(["--releases", base] + (["--bump"] if bump_mode else []))
            finally:
                os.chdir(here)
            return rc, out.getvalue()

        current = locked("lock-ok", "v0.3.0")
        rc, out = golock(current)
        check("lock: newest release, every place on its tag: ok", rc == 0 and "lock): ok" in out)
        rc, out = golock(current, bump_mode=True)
        check("lock: --bump on the newest release changes nothing", rc == 0 and "current" in out)
        rc, out = golock(locked("lock-ns3", "v0.3.0", ns3_ref="main"))
        check(
            "lock: the ns-3 dependency on main is refused outside canary-dependencies",
            rc == 1 and "ns3.yml:5: the ns-3 dependency names swarm-core main" in out,
        )
        rc, out = golock(locked("lock-canary", "v0.3.0", canary="v0.2.9"))
        check("lock: a canary on another tag is refused", rc == 1 and "ns3.yml:7:" in out)
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
        release_lock.make_release(
            rel, SWARM_CORE_REPO, "v0.4.0", {"swarm-core-0.4.0.tar.gz": b"four"}, env
        )
        with open(os.path.join(current, "Makefile"), "w", encoding="utf-8") as f:
            f.write("SWARM_CORE_REF?=v0.3.0\n")  # no spaces: --bump must still move it
        rc, out = golock(current)
        check("lock: a newer release fails the check", rc == 1 and "v0.4.0 is released" in out)
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
            and open(os.path.join(current, "Makefile"), encoding="utf-8").read()
            == "SWARM_CORE_REF?=v0.4.0\n"
            and "@main\n" in ns3,
        )
        rc, out = golock(current)
        check("lock: …after which the check passes", rc == 0)
        new_commit("unreleased")  # main moves, no release: no finding in lock mode
        rc, out = golock(current)
        check("lock: swarm-core main moving is no finding", rc == 0)

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
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    if os.path.exists(LOCK):
        return bump_lock(a.releases) if a.bump else run_lock(a.releases)
    return bump(a.swarm_core) if a.bump else run(a.swarm_core)


if __name__ == "__main__":
    sys.exit(main())
