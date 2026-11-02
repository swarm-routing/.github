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
3. a C++ file under a core root includes nothing from outside it: angle
   includes are C++ standard-library headers, quote includes resolve to a
   file under the same core root. A ``core/`` file that pulled in an ns-3
   header would bind the whole core to GPL.

Usage (repo root as cwd):
    check-headers.py --dual core/ --dual tools/ --core core/ [.]
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


def head_has(text: str, needle: str) -> bool:
    return any(needle in line for line in text.split("\n")[:HEAD_LINES])


def check_file(
    rel: str, text: str, dual: tuple, core: tuple, gpl_only: set, exists=lambda p: False
) -> list[str]:
    out = []
    if not head_has(text, SPDX):
        expr = (
            "MIT OR GPL-2.0-only"
            if rel.startswith(dual) and rel not in gpl_only
            else "GPL-2.0-only"
        )
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
    root = next((c for c in core if rel.startswith(c)), None)
    if root and rel.endswith(CXX):
        out += include_findings(rel, text, root, exists)
    return out


def include_findings(rel: str, text: str, root: str, exists) -> list[str]:
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
            if not any(c.startswith(root) and exists(c) for c in cands):
                out.append(
                    f'{rel}:{n}: "{name}" does not resolve to a file under {root} '
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


def scan(root: pathlib.Path, dual, core, gpl_only, exclude) -> int:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    files = sorted(
        f for f in tracked if f.endswith(EXTS) and not (exclude and re.search(exclude, f))
    )
    problems = []
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        problems += check_file(rel, text, dual, core, gpl_only, lambda p: (root / p).is_file())
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
    ]
    fails = 0
    for rel, text, fire, label in cases:
        got = check_file(rel, text, dual, core, gpl, ex)
        if bool(got) != fire:
            fails += 1
            print(
                f"SELF-TEST FAIL ({label}): expected {'a finding' if fire else 'silence'}, got {got}"
            )
    print("self-test:", "PASS" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


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
    ap.add_argument("--exclude", default="", help="regex of tracked paths to skip (vendored code)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return scan(pathlib.Path(a.root), tuple(a.dual), tuple(a.core), set(a.gpl_only), a.exclude)


if __name__ == "__main__":
    sys.exit(main())
