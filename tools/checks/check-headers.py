#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Licence-header gate for swarm-routing repos (AntHocNet's rules, ADR-0028).

Every swarm-routing repo is licensed per directory, as AntHocNet is:

- the simulator-free algorithm core (``core/``) and the standalone tooling
  (``tools/``, the Python CLI, CI and image scripts) are
  ``MIT OR GPL-2.0-only``, recipient's choice;
- everything else (ns-3 modules, the browser adapter, docs, data) is
  ``GPL-2.0-only``.

The MIT option is only real while three things hold, so this gate checks them:

1. every covered file carries ``SPDX-License-Identifier`` in its first lines;
2. every covered file under a dual root carries exactly
   ``MIT OR GPL-2.0-only`` (``--gpl-only`` lists files that stay GPL on
   purpose, with the reason in the caller);
3. a file whose header names more than one copyright holder (an outside
   contributor adds their own ``Copyright (c) <year> <Name>`` line beneath
   the org line, CONTRIBUTING "Outside contributions") keeps the org line
   first and the exact SPDX expression of its directory; those extra lines
   do not count against the five-line window;
4. a C++ file under a core root includes nothing from outside it: angle
   includes are C++ standard-library headers, quote includes resolve to a
   file under the same core root. A ``core/`` file that pulled in an ns-3
   header would bind the whole core to GPL. A core built on another
   repository's dual-licensed core (a protocol's ``core/`` on swarm-core's)
   names that checkout with ``--core-dep DIR``: a quote include may then also
   resolve to a file inside DIR, and only when that file itself carries
   ``MIT OR GPL-2.0-only``.

Usage (repo root as cwd):
    check-headers.py --dual core/ --dual tools/ --core core/ [.]
    check-headers.py --dual core/ --core core/ --core-dep .core-deps/ns3-swarm-core/core [.]
    check-headers.py --self-test
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

SPDX = "SPDX-License-Identifier"
DUAL_SPDX = f"{SPDX}: MIT OR GPL-2.0-only"
HEAD_LINES = 5
COPYRIGHT_RE = re.compile(r"^\s*(?://|#)\s*Copyright \(c\) \d{4}(?:-\d{4})? \S")
ORG_COPYRIGHT_RE = re.compile(
    r"^\s*(?://|#)\s*Copyright \(c\) \d{4}(?:-\d{4})? "
    r"Daniel Joppi \(https://github\.com/swarm-routing\)\s*$"
)
ORG_COPYRIGHT = "Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)"
EXTS = (".h", ".hpp", ".cc", ".cpp", ".py", ".sh")
CXX = (".h", ".hpp", ".cc", ".cpp")
STD_HEADERS = frozenset(
    """
algorithm any array atomic bit bitset cassert cctype cerrno cfloat charconv chrono
cinttypes climits clocale cmath compare complex concepts condition_variable csignal
cstdarg cstddef cstdint cstdio cstdlib cstring ctime cwchar deque exception expected
format forward_list fstream functional initializer_list iomanip ios iosfwd iostream
istream iterator limits list locale map memory mutex new numbers numeric optional
ostream queue random ranges ratio regex set shared_mutex source_location span sstream
stack stdexcept streambuf string string_view system_error thread tuple type_traits
typeindex typeinfo unordered_map unordered_set utility valarray variant vector version
""".split()
)


def head(text: str) -> list[str]:
    """The header window: the first HEAD_LINES lines, plus every copyright line
    after the first met on the way (a contributor's line never pushes the SPDX
    line out; a header with one copyright line keeps the plain window)."""
    out, counted, holders = [], 0, 0
    for line in text.split("\n"):
        if counted >= HEAD_LINES:
            break
        out.append(line)
        if COPYRIGHT_RE.match(line):
            holders += 1
            if holders == 1:
                counted += 1
        else:
            counted += 1
    return out


def head_has(text: str, needle: str) -> bool:
    return any(needle in line for line in head(text))


def copyright_findings(rel: str, text: str, expr: str) -> list[str]:
    """Extra copyright lines are fine beneath the org line, with the exact SPDX."""
    lines = head(text)
    holders = [line for line in lines if COPYRIGHT_RE.match(line)]
    if len(holders) < 2:
        return []
    out = []
    if not ORG_COPYRIGHT_RE.match(holders[0]):
        out.append(
            f"{rel}:1: a contributor's copyright line goes beneath the org line "
            f"'{ORG_COPYRIGHT}', which must come first"
        )
    spdx = [line for line in lines if SPDX in line]
    if not any(line.split(f"{SPDX}:", 1)[-1].strip() == expr for line in spdx):
        out.append(
            f"{rel}:1: with more than one copyright line the header must say exactly "
            f"'{SPDX}: {expr}'"
        )
    return out


def check_file(
    rel: str,
    text: str,
    dual: tuple,
    core: tuple,
    gpl_only: set,
    exists=lambda p: False,
    dep_ok=lambda name: False,
) -> list[str]:
    out = []
    expr = "MIT OR GPL-2.0-only" if rel.startswith(dual) and rel not in gpl_only else "GPL-2.0-only"
    if not head_has(text, SPDX):
        out.append(
            f"{rel}:1: no {SPDX} in the first {HEAD_LINES} lines — add\n"
            f"    // Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)\n"
            f"    // {SPDX}: {expr}\n  ('#' comments for Python/shell, after any shebang)"
        )
        return out
    if rel.startswith(dual) and rel not in gpl_only and not head_has(text, DUAL_SPDX):
        out.append(
            f"{rel}:1: this root is dual-licensed — the header must say "
            f"exactly '{DUAL_SPDX}' (or list the file with --gpl-only)"
        )
    out += copyright_findings(rel, text, expr)
    root = next((c for c in core if rel.startswith(c)), None)
    if root and rel.endswith(CXX):
        out += include_findings(rel, text, root, exists, dep_ok)
    return out


def include_findings(
    rel: str, text: str, root: str, exists, dep_ok=lambda name: False
) -> list[str]:
    out = []
    here = str(pathlib.PurePosixPath(rel).parent)
    for n, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s.startswith("#include"):
            continue
        target = s[len("#include") :].strip()
        if target.startswith("<"):
            name = target[1 : target.find(">")] if ">" in target else target[1:]
            if name not in STD_HEADERS:
                out.append(
                    f"{rel}:{n}: {root} may include only the C++ standard library "
                    f"with <...>, not <{name}>"
                )
        elif target.startswith('"'):
            name = target[1 : target.find('"', 1)]
            cands = [norm(f"{here}/{name}")] + [
                norm(f"{d}/{name}") for d in (f"{root}include", root.rstrip("/"))
            ]
            if not any(c.startswith(root) and exists(c) for c in cands) and not dep_ok(name):
                out.append(
                    f'{rel}:{n}: "{name}" does not resolve to a file under {root} '
                    f"or to a dual-licensed file of a --core-dep "
                    f"— {root} includes nothing from outside it"
                )
    return out


def norm(rel: str) -> str:
    parts = []
    for p in pathlib.PurePosixPath(rel).parts:
        if p == "..":
            if parts:
                parts.pop()
        elif p != ".":
            parts.append(p)
    return "/".join(parts)


def dep_resolver(deps):
    """dep_ok(name) for check_file: `name` is a file inside one of the --core-dep
    directories (never above it) whose first lines carry the dual SPDX."""
    dirs = [pathlib.Path(d).resolve() for d in deps]

    def dep_ok(name: str) -> bool:
        for d in dirs:
            p = (d / name).resolve()
            if p.is_relative_to(d) and p.is_file():
                if head_has(p.read_text(encoding="utf-8", errors="replace"), DUAL_SPDX):
                    return True
        return False

    return dep_ok


def scan(root: pathlib.Path, dual, core, gpl_only, exclude, deps=()) -> int:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    files = sorted(
        f for f in tracked if f.endswith(EXTS) and not (exclude and re.search(exclude, f))
    )
    dep_ok = dep_resolver(deps)
    problems = []
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        problems += check_file(
            rel, text, dual, core, gpl_only, lambda p: (root / p).is_file(), dep_ok
        )
    for p in problems:
        print(f"FAIL: {p}")
    print(f"checked {len(files)} tracked source file(s); {len(problems)} problem(s)")
    return 1 if problems else 0


def self_test() -> int:
    dual, core, gpl = ("core/", "tools/"), ("core/",), {"tools/gpl_glue.py"}
    known = {"core/include/x/a.h", "core/src/b.h"}
    ex = known.__contains__
    H = "// Copyright (c) 2026 X\n"
    cases = [  # (rel, text, should_fire, label)
        ("ns3/model/a.cc", "#include <map>\n", True, "no header"),
        (
            "ns3/model/a.cc",
            "\n" * 5 + "// SPDX-License-Identifier: GPL-2.0-only\n",
            True,
            "header too low",
        ),
        ("ns3/model/a.cc", H + "// SPDX-License-Identifier: GPL-2.0-only\n", False, "GPL module"),
        (
            "tools/x.py",
            "#!/usr/bin/env python3\n# SPDX-License-Identifier: GPL-2.0-only\n",
            True,
            "GPL in dual root",
        ),
        (
            "tools/x.py",
            "#!/usr/bin/env python3\n# SPDX-License-Identifier: MIT\n",
            True,
            "MIT-only in dual root",
        ),
        (
            "tools/x.sh",
            "#!/bin/sh\n# SPDX-License-Identifier: MIT OR GPL-2.0-only\n",
            False,
            "dual tool",
        ),
        (
            "tools/gpl_glue.py",
            "# SPDX-License-Identifier: GPL-2.0-only\n",
            False,
            "listed gpl-only",
        ),
        (
            "core/src/b.cc",
            H + "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n"
            '#include "x/a.h"\n#include "b.h"\n#include <span>\n',
            False,
            "clean core",
        ),
        (
            "core/src/b.cc",
            H + "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include <ns3/node.h>\n",
            True,
            "ns-3 angle include",
        ),
        (
            "core/src/b.cc",
            H + '// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include "ns3/node.h"\n',
            True,
            "ns-3 quote include",
        ),
        (
            "core/src/b.cc",
            H + '// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include "../../ns3/model/a.h"\n',
            True,
            "escape by ..",
        ),
        (
            "core/src/b.cc",
            "// " + ORG_COPYRIGHT + "\n// Copyright (c) 2027 Ada Lovelace\n"
            "// Copyright (c) 2027 Alan Turing\n// Copyright (c) 2027 Grace Hopper\n"
            "// Copyright (c) 2027 Edsger Dijkstra\n"
            "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n",
            False,
            "contributors beneath the org line",
        ),
        (
            "tools/x.py",
            "#!/usr/bin/env python3\n# " + ORG_COPYRIGHT + "\n# Copyright (c) 2027 Ada Lovelace\n"
            "# SPDX-License-Identifier: MIT OR GPL-2.0-only\n",
            False,
            "contributor in a script",
        ),
        (
            "ns3/model/a.cc",
            "// Copyright (c) 2027 Ada Lovelace\n// SPDX-License-Identifier: GPL-2.0-only\n"
            "// Copyright (c) 2027 Alan Turing\n",
            True,
            "contributors without the org line",
        ),
        (
            "ns3/model/a.cc",
            "// Copyright (c) 2027 Ada Lovelace\n// " + ORG_COPYRIGHT + "\n"
            "// SPDX-License-Identifier: GPL-2.0-only\n",
            True,
            "contributor above the org line",
        ),
        (
            "ns3/model/a.cc",
            "// " + ORG_COPYRIGHT + "\n// Copyright (c) 2027 Ada Lovelace\n"
            "// SPDX-License-Identifier: GPL-2.0-or-later\n",
            True,
            "contributor with an inexact SPDX",
        ),
        (
            "ns3/model/a.cc",
            "\n" * 4
            + "// Copyright (c) 2027 Ada Lovelace\n// SPDX-License-Identifier: GPL-2.0-only\n",
            True,
            "one copyright line keeps the five-line window",
        ),
    ]
    fails = 0
    for rel, text, fire, label in cases:
        got = check_file(rel, text, dual, core, gpl, ex)
        if bool(got) != fire:
            fails += 1
            print(
                f"SELF-TEST FAIL ({label}): expected {'a finding' if fire else 'silence'}, got {got}"
            )
    fails += self_test_core_dep()
    print("self-test:", "PASS" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


def self_test_core_dep() -> int:
    """--core-dep: a dual-licensed header of the dependency resolves; a GPL one,
    a missing one and an escape above the directory do not."""
    import tempfile

    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        dep = pathlib.Path(tmp, "dep", "core")
        dep.mkdir(parents=True)
        dep.joinpath("dual.h").write_text("// x\n// SPDX-License-Identifier: MIT OR GPL-2.0-only\n")
        dep.joinpath("gpl.h").write_text("// x\n// SPDX-License-Identifier: GPL-2.0-only\n")
        pathlib.Path(tmp, "dep", "above.h").write_text(
            "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n"
        )
        dep_ok = dep_resolver([str(dep)])
        head = "// x\n// SPDX-License-Identifier: MIT OR GPL-2.0-only\n"
        for name, fire in (
            ("dual.h", False),
            ("gpl.h", True),
            ("nope.h", True),
            ("../above.h", True),
        ):
            text = head + f'#include "{name}"\n'
            got = check_file("core/a.cc", text, ("core/",), ("core/",), set(), dep_ok=dep_ok)
            without = check_file("core/a.cc", text, ("core/",), ("core/",), set())
            if bool(got) != fire or not without:
                fails += 1
                print(f"SELF-TEST FAIL (--core-dep {name}): got {got}")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--dual", action="append", default=[], help="dual-licensed root (repeatable)")
    ap.add_argument(
        "--core", action="append", default=[], help="simulator-free core root (repeatable)"
    )
    ap.add_argument(
        "--gpl-only", action="append", default=[], help="file under a dual root that stays GPL"
    )
    ap.add_argument(
        "--core-dep",
        action="append",
        default=[],
        help="a dependency's dual-licensed core directory a core may include from (repeatable)",
    )
    ap.add_argument("--exclude", default="", help="regex of tracked paths to skip (vendored code)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return scan(
        pathlib.Path(a.root),
        tuple(a.dual),
        tuple(a.core),
        set(a.gpl_only),
        a.exclude,
        tuple(a.core_dep),
    )


if __name__ == "__main__":
    sys.exit(main())
