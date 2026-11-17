#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Write golden.json from the Python check-headers.py (#531's byte-identical rule).

Builds every fixture of fixtures.json (files, raw bytes, symlinks, then the
git steps; a step starting with "!" may fail), runs the Python tool on each
case (as a program named check-headers, so its usage lines match the Go
command's) and records stdout, stderr and the exit code; a Python traceback
is recorded as a crash (exit 1, stdout), not byte for byte. Also records
check_file()'s findings for every self-test case. golden_test.go replays the
same fixtures and cases through the Go port.

    python3 -I internal/checkheaders/testdata/gen_golden.py tools/checks/check-headers.py
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_AUTHOR_DATE": "2026-11-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-11-01T00:00:00Z",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}
DEFAULT_STEPS = [["git", "init", "-q", "-b", "main", "."], ["git", "add", "-A"]]

# Each case: fixture, working directory inside it, arguments, and optionally
# extra environment variables. {dep} is the
# `dep` fixture's core/ directory, {depdir} the `dep` fixture itself.
CASES = [
    ("plain", ".", ["--dual", "core/", "--dual", "tools/", "--core", "core/", "."]),
    ("plain", ".", ["--dual", "core/", "--dual", "tools/", "--core", "core/"]),
    ("plain", ".", ["--dual", "", "."]),
    ("plain", ".", ["."]),
    ("plain", ".", []),
    ("plain", ".", ["--dual", "core/", "--core", "core"]),
    ("plain", ".", ["--dual", "core/", "--core", ""]),
    ("plain", ".", ["--dual", "core/", "--core", "", "--core", "core/"]),
    ("plain", ".", ["--dual", "core/", "--core", "core/", "--core", "core/src/"]),
    ("plain", ".", ["--dual", "core/", "--core", "core/", "--exclude", "^core/src/"]),
    ("plain", ".", ["--dual", "core/", "--core", "core/", "--exclude", "(a|r)\\.(cc|cpp)$"]),
    ("plain", ".", ["--dual", "tools/", "--gpl-only", "tools/run.py"]),
    ("plain", ".", ["--dual", "ns3/", "--gpl-only", "ns3/model/m.cc"]),
    ("plain", "core", ["--dual", "", "--core", ""]),
    ("plain", "core", ["--dual", "", "--core", "", "."]),
    ("plain", ".", ["--dual", "", "--core", "", "core"]),
    ("plain", ".", ["--dual", "", "--core", "", "core/src"]),
    ("plain", ".", ["--dual", "", "--core", "", "./core/../core"]),
    ("plain", ".", ["--dual", "core/", "--core", "core/", "--exclude", "[unclosed"]),
    ("plain", ".", ["--dual", "core/", "--exclude", "x", "--exclude", "", "."]),
    ("broken", ".", ["--dual", "core/", "--dual", "tools/", "--core", "core/", "."]),
    (
        "broken",
        ".",
        ["--dual", "core/", "--dual", "tools/", "--core", "core/", "--core-dep", "{dep}"],
    ),
    (
        "broken",
        ".",
        [
            "--dual",
            "core/",
            "--core",
            "core/",
            "--exclude",
            "^core/vendor/",
            "--gpl-only",
            "core/bad.cc",
        ],
    ),
    ("broken", ".", ["--dual", "", "."]),
    ("broken", ".", ["--core", "core/", "--core", "ns3/"]),
    ("broken", ".", []),
    ("dangling", ".", ["--dual", "core/"]),
    ("spaced", ".", ["--dual", "tools/"]),
    ("quoted", ".", ["--dual", "tools/"]),
    ("unmerged", ".", ["--dual", "tools/"]),
    ("index4", ".", ["--dual", "core/", "--core", "core/"]),
    ("index4", "core/very", ["--dual", "", "--core", "long/"]),
    ("index3", ".", ["--dual", "core/", "--core", "core/"]),
    ("ita", ".", ["--dual", "tools/"]),
    ("sha256", ".", ["--dual", "core/", "--core", "core/"]),
    ("skiphash", ".", ["--dual", "core/", "--core", "core/"]),
    ("worktree", "wt", ["--dual", "core/"]),
    ("worktree", "wt/core", ["--dual", ""]),
    ("empty", ".", ["--dual", "core/"]),
    ("sha256quoted", ".", ["--dual", "core/", "--core", "core/"]),
    ("altindex", ".", ["--dual", "tools/"]),
    ("altindex", ".", ["--dual", "tools/"], {"GIT_INDEX_FILE": ".git/alt"}),
    ("altindex", "tools", ["--dual", ""], {"GIT_INDEX_FILE": ".git/alt"}),
    ("altindex", ".", ["--dual", "tools/"], {"GIT_INDEX_FILE": ".git/missing"}),
    ("notgit", ".", ["--dual", "core/"]),
    ("plain", ".", ["--dual", "core/", "nonexistent-dir"]),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/"]),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/", "--core-dep", "{dep}"]),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/", "--core-dep", "{dep}/"]),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/", "--core-dep", "{depdir}"]),
    (
        "usesdep",
        ".",
        ["--dual", "core/", "--core", "core/", "--core-dep", "{dep}/sub", "--core-dep", "{dep}"],
    ),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/", "--core-dep", "{dep}/missing"]),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/", "--core-dep", "{dep}/up"]),
    ("usesdep", ".", ["--dual", "core/", "--core", "core/", "--core-dep", "../dep/core"]),
    # argparse: help, abbreviations, = forms, errors, positionals
    ("plain", ".", ["-h"]),
    ("plain", ".", ["--help"]),
    ("plain", ".", ["--he"]),
    ("plain", ".", ["--dual", "core/", "-h", "--bogus"]),
    ("plain", ".", ["--bogus", "-h"]),
    ("plain", ".", ["-hx"]),
    ("plain", ".", ["-h=x"]),
    ("plain", ".", ["-h="]),
    ("plain", ".", ["--help=x"]),
    ("plain", ".", ["--self-test"]),
    ("plain", ".", ["--self"]),
    ("plain", ".", ["--s"]),
    ("plain", ".", ["--self-test=x"]),
    ("plain", ".", ["--self-test=", "."]),
    ("plain", ".", ["--self-test", "--dual"]),
    ("plain", ".", ["--du", "core/"]),
    ("plain", ".", ["--du=core/", "--co=x"]),
    ("plain", ".", ["--c", "core/"]),
    ("plain", ".", ["--cor", "core/"]),
    ("plain", ".", ["--core-", "core/", "--dual=core/"]),
    ("plain", ".", ["--core=", "--dual=", "."]),
    ("plain", ".", ["--g", "x", "--e", "y", "--dual", "core/"]),
    ("plain", ".", ["--dual"]),
    ("plain", ".", ["--dual", "--core", "x"]),
    ("plain", ".", ["--dual", "-x"]),
    ("plain", ".", ["--dual", "-1", "."]),
    ("plain", ".", ["--dual", "- x"]),
    ("plain", ".", ["--dual", "-"]),
    ("plain", ".", ["--dual", "--", "x"]),
    ("plain", ".", [".", "--dual", "core/"]),
    ("plain", ".", [".", "--dual", "core/", "core"]),
    ("plain", ".", [".", "core"]),
    ("plain", ".", ["--", "."]),
    ("plain", ".", ["--", "--dual"]),
    ("plain", ".", ["--", "--", "x"]),
    ("plain", ".", ["--dual", "core/", "--"]),
    ("plain", ".", ["--dual", "core/", "--", ".", "x"]),
    ("plain", ".", ["-x"]),
    ("plain", ".", ["-"]),
    ("plain", ".", ["-1"]),
    ("plain", ".", ["-1", "-2"]),
    ("plain", ".", ["-x y"]),
    ("plain", ".", ["--x y"]),
    ("plain", ".", ["--nope=1", "x", "-d"]),
    ("plain", ".", ["--dual='q'", "--self-test=a'b", "."]),
    ("plain", ".", ["--self-test=a\"b'c\\\td"]),
    ("plain", ".", ["--self-test=é​\x7f"]),
    ("plain", ".", ["-h", "--dual"]),
    ("plain", ".", ["--dual", "core/", "--exclude"]),
]


def build(spec: dict, d: pathlib.Path, env: dict) -> None:
    d.mkdir(parents=True)
    for rel, text in spec.get("files", {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    for rel, b64 in spec.get("raw", {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64decode(b64))
    for rel, target in spec.get("symlinks", {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, p)
    for step in spec.get("steps", DEFAULT_STEPS):
        may_fail = step[0].startswith("!")
        cmd = [step[0].lstrip("!")] + step[1:]
        r = subprocess.run(cmd, cwd=d, env=env, capture_output=True)
        if r.returncode and not may_fail:
            sys.exit(f"{cmd}: {r.stderr.decode()}")


def main() -> int:
    tool = pathlib.Path(sys.argv[1]).resolve()
    spec = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
    env = {**os.environ, **GIT_ENV}
    out = {"cases": [], "selftest": []}
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve() / "fx"
        prog = pathlib.Path(tmp) / "bin" / "check-headers"
        prog.parent.mkdir()
        prog.symlink_to(tool)
        for name, fx in spec.items():
            build(fx, root / name, env)
        for fixture, cwd, args, *rest in CASES:
            extra = rest[0] if rest else {}
            real = [
                a.replace("{depdir}", str(root / "dep")).replace(
                    "{dep}", str(root / "dep" / "core")
                )
                for a in args
            ]
            r = subprocess.run(
                [sys.executable, "-I", str(prog), *real],
                cwd=root / fixture / cwd,
                env={**{k: v for k, v in env.items() if k != "COLUMNS"}, **extra},
                capture_output=True,
            )
            stderr = r.stderr.decode("utf-8")
            crash = stderr.startswith("Traceback")
            out["cases"].append(
                {
                    "fixture": fixture,
                    "cwd": cwd,
                    "args": args,
                    "env": extra,
                    "rc": r.returncode,
                    "stdout": r.stdout.decode("utf-8"),
                    "stderr": "" if crash else stderr,
                    "crash": crash,
                }
            )
    mod_spec = importlib.util.spec_from_file_location("check_headers", tool)
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    dual, core, gpl = ("core/", "tools/"), ("core/",), {"tools/gpl_glue.py"}
    known = {"core/include/x/a.h", "core/src/b.h"}
    # the self-test's cases, read from its source: each tuple's findings
    import ast
    import inspect

    src = inspect.getsource(mod.self_test)
    tree = ast.parse(src)
    cases_node = next(
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "cases"
    )
    ns = {"ORG_COPYRIGHT": mod.ORG_COPYRIGHT, "H": "// Copyright (c) 2026 X\n"}
    for rel, text, fire, label in eval(compile(ast.Expression(cases_node), "cases", "eval"), ns):
        got = mod.check_file(rel, text, dual, core, gpl, known.__contains__)
        out["selftest"].append({"label": label, "fire": fire, "findings": got})
    (HERE / "golden.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"golden.json: {len(out['cases'])} cases, {len(out['selftest'])} self-test cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
