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
when swarm-core main changed `core/` since the pin, it rewrites every
occurrence of the pinned commit under the repository root (the places above,
and any other file naming it, such as a benchmark workflow's dependency) to
main's commit, and prints the files, a `pin-target: <sha>` line and the
swarm-core commits on `core/` since the pin. A pin the files disagree on is
left to a person (exit 1).

Usage (the protocol repository's root as cwd; it reads no path from its arguments):
  check-swarm-core-pin.py [--swarm-core URL_OR_PATH] [--bump]
  check-swarm-core-pin.py --self-test
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

SWARM_CORE = "https://github.com/swarm-routing/ns3-swarm-core.git"
CMAKE = "core/CMakeLists.txt"
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


def bump(url):
    """--bump (org-bot's swarm-core-pin task, #208): when swarm-core main changed
    core/ since the pin, rewrite every occurrence of the pinned commit under the
    cwd (the check's places and any other file that names it, such as a
    benchmark workflow's dependency) to main's commit. A pin the files disagree
    on is left to a person. 0: bumped or already current; 1: refused."""
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
    for root, dirs, files in os.walk("."):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "build"))
        for name in sorted(files):
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            if pin in text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text.replace(pin, main))
                changed.append(os.path.relpath(path).replace(os.sep, "/"))
    print(f"swarm-core pin: bumped {pin[:7]} -> {main[:7]} in {len(changed)} file(s)")
    print(f"pin-target: {main}")
    for c in changed:
        print(f"  {c}")
    print("swarm-core commits on core/ since the pin:")
    for line in log:
        print(f"  {line}")
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

        # --bump (#208): a stale pin is rewritten everywhere, extra files included
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
            "--bump rewrites the stale pin in every file, extra ones included",
            rc == 0
            and not names
            and f"pin-target: {c}" in out
            and "core/ changes" in out
            and "bench.yml" in out,
        )
        rc, out = go(stale, url)
        check("…after which the check passes", rc == 0)
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
        help="rewrite a stale pin to swarm-core main's commit everywhere it is named (#208)",
    )
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    return bump(a.swarm_core) if a.bump else run(a.swarm_core)


if __name__ == "__main__":
    sys.exit(main())
