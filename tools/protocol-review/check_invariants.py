#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""The org's golden rules (1-9), checked mechanically on a repository's diff.

    check_invariants.py [REPO_DIR] [--base REF] [--pr-body FILE] [--json]
                                    PASS/WARN/FAIL per rule, HINTs; exit 1 on a FAIL
    check_invariants.py --self-test

The diff is everything between the merge base with REF (default origin/main)
and the working tree, untracked files included. Each check prints one line
and, under it, the files or lines it is about; the agent reads this summary,
not the diff (AntHocNet ADR-0014). FAIL means a broken invariant; WARN means
"look and confirm". It checks what is cheap to check and easy to miss. It
does not judge correctness, pairing (rule 6) or whether a structure is
bounded (rule 7): that is the reviewer's part. For those two it prints HINT
lines, candidate spots to judge first, which never change the exit code:

    rule 7  a container declared in the diff (core/ or a simulator dir) that
            grows in the diff (push_back, emplace, insert, [] =) with no
            pop/erase/clear/resize or max/cap/limit name on it in the changed files
    rule 6  a sentence in the changed Markdown or the --pr-body text with a seed
            or run count below 20, or a comparison (a number with "beats",
            "better than", "vs", a metric such as PDR, or a protocol name) and
            no seed count

--json prints the same checks as {"result": …, "checks": [{level, message, items}]}.

A repository tunes it in `.github/org-sync.toml` (the org-sync config every
adopting repo has), all keys optional:

    dual = ["core/", "tools/"]          # already there: the dual-licensed roots
    [review]
    core = ["core/"]                    # simulator-free code (rules 2 and 5)
    core_tests = ["core/tests/"]        # where its tests live
    wire = ["core/include/ara/wire_*"]  # wire-format files (rule 3), fnmatch patterns
    wire_version = "kWireVersion"       # the version constant a wire change bumps
    sim_dirs = ["ns3/"]                 # simulator code: rule 5 applies, as a WARN

Generalised from AntHocNet's .claude/skills/protocol-review/check_invariants.sh
(now anthocnet-review). Stdlib only.
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib

SOURCE = (".h", ".hpp", ".cc", ".cpp", ".py", ".sh")
CXX = (".h", ".hpp", ".cc", ".cpp")
COPYRIGHT = "Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)"
DUAL, GPL = "MIT OR GPL-2.0-only", "GPL-2.0-only"
SHA_PIN = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([0-9a-f]{40})\s*#\s*v\d")
USES = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@(\S+)")
NONDET = re.compile(
    r"\b(?:std::)?(?:s?rand)\s*\(|std::random_device|\btime\s*\(\s*(?:nullptr|NULL|0)\s*\)"
    r"|system_clock::now|steady_clock::now|high_resolution_clock::now"
)
UNORDERED = re.compile(r"std::unordered_(?:map|set|multimap|multiset)\b")
# rule 7 hints: a growing container type, how it grows, how it is kept bounded
CONTAINER = re.compile(
    r"\b(?:std::)?((?:unordered_)?(?:multi)?(?:map|set)|vector|deque|(?:forward_)?list"
    r"|(?:priority_)?queue)\s*<"
)
GROW = r"push_back|push_front|push|emplace\w*|try_emplace|insert\w*"
SHRINK = r"pop\w*|erase|clear|resize|shrink_to_fit|extract"
CAP = re.compile(r"(?i)max|cap|limit")
# rule 6 hints: seed counts, percentages, protocol-versus-protocol claims
SEEDS = re.compile(
    r"(?<![\w.-])(\d+)(?:\s+|-)(?:(?:paired|independent|random|more|different)\s+)?"
    r"(?:seeds?|runs|replications)\b",
    re.I,
)
PERCENT = re.compile(r"\d\s*%")
COMPARE = re.compile(
    r"(?<![\w-])(?:beats?|outperform\w*|(?:better|worse|higher|lower|faster|slower) than"
    r"|ahead of|versus|vs\.?)(?![\w-])",
    re.I,
)
METRIC = re.compile(r"\b(?:PDR|delivery ratio|throughput|delay|latency|overhead|NRL)\b", re.I)
PROTOCOL = re.compile(
    r"\b(?:AntHocNet|AODV|AOMDV|OLSR|DSDV|DSR|HWMP|GPSR|ARA|BeeAdHoc|Termite|HOPNET)\b", re.I
)
# what is not prose: inline code, link targets, issue and PR numbers
NOT_PROSE = re.compile(r"`[^`]*`|\]\([^)]*\)|https?://\S+|\b[\w.-]*#\d+")
# a line that is its own unit: a table row, a list item, a heading, a rule
OWN_UNIT = re.compile(r"\s*(?:\||[-*+]\s|\d+[.)]\s|#|---|===)")
SENTENCE = re.compile(r"(?<!vs\.)(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-Z(\"])")


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"check_invariants: git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def config(repo):
    path = os.path.join(repo, ".github/org-sync.toml")
    cfg = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    rv = cfg.get("review", {})
    return {
        "dual": cfg.get("dual", []),
        "core": rv.get("core", ["core/"]),
        "core_tests": rv.get("core_tests", ["core/tests/"]),
        "wire": rv.get("wire", []),
        "wire_version": rv.get("wire_version", ""),
        "sim_dirs": rv.get("sim_dirs", ["ns3/", "model/", "helper/"]),
    }


def diff(repo, base):
    """(changed files, {file: [(line number, added line)]}, new files, merge base)."""
    mb = git(repo, "merge-base", base, "HEAD", check=False).strip() or base

    def names(*args):
        # NUL-separated: a path with spaces or non-ASCII characters stays whole
        return {n for n in git(repo, *args, "-z").split("\0") if n}

    changed = names("diff", "--name-only", mb)
    new = names("diff", "--name-only", "--diff-filter=A", mb)
    untracked = names("ls-files", "--others", "--exclude-standard")
    changed |= untracked
    new |= untracked
    added = {}
    for f in sorted(changed - untracked):
        # one diff per file, so the file name never has to be parsed back out
        n, in_hunk = 0, False
        for line in git(repo, "diff", "-U0", mb, "--", f).splitlines():
            hunk = re.match(r"@@ -\S+ \+(\d+)", line)
            if hunk:
                n, in_hunk = int(hunk.group(1)), True
            elif in_hunk and line.startswith("+"):
                # inside a hunk every '+' line is added, even `++i;` (shown as `+++i;`);
                # the `+++ b/file` header only comes before the first hunk
                added.setdefault(f, []).append((n, line[1:]))
                n += 1
    for f in untracked:
        p = os.path.join(repo, f)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                added[f] = list(enumerate(fh.read().splitlines(), 1))
    changed = {f for f in changed if os.path.exists(os.path.join(repo, f))}
    return sorted(changed), added, sorted(new & set(changed)), mb


def under(path, roots):
    return any(r == "" or path == r.rstrip("/") or path.startswith(r) for r in roots)


def head(repo, f, n=6):
    try:
        with open(os.path.join(repo, f), encoding="utf-8", errors="replace") as fh:
            return [next(fh, "") for _ in range(n)]
    except OSError:
        return []


class Report:
    def __init__(self):
        self.lines, self.fail, self.warn = [], False, False
        self.checks, self.hints = [], 0

    def add(self, level, msg, items=()):
        self.checks.append({"level": level, "message": msg, "items": list(items)})
        self.hints += level == "HINT"
        self.lines.append(f"{level:5} {msg}")
        self.lines += [f"        {i}" for i in list(items)[:12]]
        if len(items) > 12:
            self.lines.append(f"        … and {len(items) - 12} more")
        self.fail |= level == "FAIL"
        self.warn |= level == "WARN"


def _match_angle(text, i):
    """Index just past the `>` closing the `<` at text[i], or -1."""
    depth = 0
    for j in range(i, len(text)):
        depth += {"<": 1, ">": -1}.get(text[j], 0)
        if depth == 0:
            return j + 1
    return -1


def container_hints(repo, files, numbered):
    """Rule 7: a container declared in the diff that grows in the diff, with no
    pop/erase/clear/resize or max/cap/limit name on it anywhere in the changed files."""
    texts = {}
    for f in files:
        try:
            with open(os.path.join(repo, f), encoding="utf-8", errors="replace") as fh:
                texts[f] = fh.read().splitlines()
        except OSError:
            texts[f] = []
    hints = []
    for f in files:
        for n, line in numbered.get(f, []):
            for m in CONTAINER.finditer(line):
                end = _match_angle(line, m.end() - 1)
                d = re.match(r"\s*(\w+)\s*(?:[;={]|$)", line[end:]) if end > 0 else None
                if not d:
                    continue
                name, kind = d.group(1), m.group(1)
                grow = re.compile(
                    rf"\b{name}\s*(?:\.|->)\s*({GROW})\s*\(|\b{name}\s*\[[^\]]*\]\s*(=)(?!=)"
                )
                bound = re.compile(
                    rf"\b{name}\s*(?:\.|->)\s*(?:{SHRINK})\b|\berase(?:_if)?\s*\(\s*{name}\b"
                )
                at = [
                    (g, gn, gm.group(1) or "[]=")
                    for g in files
                    for gn, gl in numbered.get(g, [])
                    if (gm := grow.search(gl))
                ]
                capped = any(
                    bound.search(tl)
                    or (re.search(rf"\b{name}\b", tl) and CAP.search(tl.replace(name, "")))
                    for g in files
                    for tl in texts[g]
                )
                if at and not capped:
                    g, gn, op = at[0]
                    hints.append(f"{f}:{n} {name} ({kind}): {op} at {g}:{gn}, no cap or eviction")
    return hints


def _sentences(lines):
    """[(line number, sentence)] from [(line number, text)], paragraphs joined."""
    out, para, fence = [], [], False

    def flush():
        text, starts = "", []
        for n, t in para:
            starts.append((len(text), n))
            text += t.strip() + " "
        pos = 0
        for sent in SENTENCE.split(text):
            pos = text.find(sent, pos)
            if sent.strip():
                out.append((next(ln for off, ln in reversed(starts) if off <= pos), sent.strip()))
            pos += len(sent)
        para.clear()

    prev = None
    for n, t in lines:
        if t.lstrip().startswith("```"):
            fence = not fence
            flush()
            continue
        if fence or not t.strip() or (prev is not None and n != prev + 1) or OWN_UNIT.match(t):
            flush()
        if not fence and t.strip():
            para.append((n, t))
        prev = n
    flush()
    return out


def claim_hints(sources):
    """Rule 6: a sentence with a seed/run count below 20, or a comparison claim
    with no count: a number with a comparison ("beats", "better than", "vs"), a
    metric (PDR, delay, …) or a protocol name."""
    hints = []
    for label, lines in sources:
        for n, sent in _sentences(lines):
            prose = NOT_PROSE.sub(" ", sent)
            counts = [int(m.group(1)) for m in SEEDS.finditer(prose)]
            number = PERCENT.search(prose) or (COMPARE.search(prose) and re.search(r"\d", prose))
            claim = number and (
                COMPARE.search(prose) or METRIC.search(prose) or PROTOCOL.search(prose)
            )
            if counts and min(counts) < 20:
                why = f"{min(counts)} seeds/runs, below 20"
            elif claim and not counts:
                why = "no seed count"
            else:
                continue
            short = sent if len(sent) <= 90 else sent[:87] + "…"
            hints.append(f'{label}:{n} "{short}" ({why})')
    return hints


def check(repo, base="origin/main", pr_body=None):
    cfg = config(repo)
    changed, numbered, new, mb = diff(repo, base)
    added = {f: [t for _, t in lines] for f, lines in numbered.items()}
    r = Report()
    # .claude/ ships nothing (rule 9), so the licence gate skips it, as
    # check-headers.py does with the repo's exclusions
    src = [f for f in changed if f.endswith(SOURCE) and not f.startswith(".claude/")]

    # rule 1: every original source file states its licence, matching its directory
    bad = []
    for f in src:
        text = "".join(head(repo, f))
        want = DUAL if under(f, cfg["dual"]) else GPL
        m = re.search(r"SPDX-License-Identifier:\s*(.+)", text)
        if not m:
            bad.append(f"{f}: no SPDX-License-Identifier in the first lines (add the org header)")
        elif m.group(1).strip() != want and not (want == GPL and m.group(1).strip() == DUAL):
            bad.append(f"{f}: {m.group(1).strip()}, its directory is {want}")
    if bad:
        r.add("FAIL", "rule 1: licence headers (LICENSING.md per directory)", bad)
    elif src:
        r.add("PASS", f"rule 1: licence headers on {len(src)} changed source file(s)")
    licensing = ""
    if os.path.exists(os.path.join(repo, "LICENSING.md")):
        with open(os.path.join(repo, "LICENSING.md"), encoding="utf-8") as fh:
            licensing = fh.read()
    tops = sorted({f.split("/")[0] + "/" for f in new if "/" in f and not f.startswith(".")})
    missing = [
        d
        for d in tops
        if f"`{d}" not in licensing
        and f"`{d.rstrip('/')}`" not in licensing
        and not git(repo, "ls-tree", "--name-only", mb, d.rstrip("/"), check=False).strip()
    ]
    if licensing and missing:
        r.add("WARN", "rule 1: a new directory needs its row in LICENSING.md", missing)

    # rule 2: core/ includes only the standard library and other core/ files
    bad = []
    for f in changed:
        if not (under(f, cfg["core"]) and f.endswith(CXX)):
            continue
        for line in added.get(f, []):
            m = re.match(r'\s*#\s*include\s*([<"])([^>"]+)[>"]', line)
            if not m:
                continue
            path = m.group(2)
            in_core = any(
                os.path.isfile(os.path.join(repo, c, sub, path))
                for c in cfg["core"]
                for sub in ("", "include")
            )
            if m.group(1) == "<" and "/" in path and not in_core:
                bad.append(f"{f}: #include <{path}>")
            elif m.group(1) == '"' and (
                path.startswith(("ns3/", "ns2/", "emscripten"))
                or not under(os.path.normpath(os.path.join(os.path.dirname(f), path)), cfg["core"])
                and not in_core
            ):
                bad.append(f'{f}: #include "{path}"')
    if bad:
        r.add("FAIL", "rule 2: core/ includes only the standard library and core/ files", bad)
    elif any(under(f, cfg["core"]) for f in changed):
        r.add("PASS", "rule 2: core/ includes stay inside the standard library and core/")

    # rule 3: a wire-format change bumps the version byte
    wire = [f for f in changed if any(fnmatch.fnmatch(f, p) for p in cfg["wire"])]
    if wire:
        bumped = cfg["wire_version"] and any(
            cfg["wire_version"] in ln for lines in added.values() for ln in lines
        )
        if bumped:
            r.add("PASS", f"rule 3: wire files changed and {cfg['wire_version']} is in the diff")
        else:
            r.add(
                "WARN",
                "rule 3: wire files changed, no version bump in the diff "
                f"({cfg['wire_version'] or 'set review.wire_version'}); also the roundtrip/fuzz tests",
                wire,
            )

    # rule 4: no contrib module named core
    bad = []
    for f in changed:
        if os.path.basename(f) == "CMakeLists.txt":
            for line in added.get(f, []):
                if re.search(r"LIBNAME\s+core\b", line):
                    bad.append(f"{f}: {line.strip()}")
    if bad:
        r.add("FAIL", "rule 4: no contrib module named `core` (use swarm-core)", bad)

    # rule 5: determinism (randomness and time through injected ports)
    core_bad, sim_bad, order = [], [], []
    for f in changed:
        if not f.endswith(CXX):
            continue
        for line in added.get(f, []):
            if NONDET.search(line):
                (core_bad if under(f, cfg["core"]) else sim_bad).append(f"{f}: {line.strip()}")
            if under(f, cfg["core"]) and UNORDERED.search(line):
                order.append(f"{f}: {line.strip()}")
    if core_bad:
        r.add(
            "FAIL",
            "rule 5: libc rand or a wall clock in core/ (use the injected RNG/clock ports)",
            core_bad,
        )
    if sim_bad:
        r.add(
            "WARN",
            "rule 5: libc rand or a wall clock outside core/ (simulator streams only)",
            sim_bad,
        )
    if order:
        r.add(
            "WARN",
            "rule 5: an unordered container in core/; never let its order reach an output",
            order,
        )
    if any(f.endswith(CXX) for f in changed) and not (core_bad or sim_bad):
        r.add("PASS", "rule 5: no libc rand or wall clock added")

    # core logic changes carry a core test (the protocol repos' own rule)
    core_src = [f for f in changed if under(f, cfg["core"]) and not under(f, cfg["core_tests"])]
    core_src = [f for f in core_src if f.endswith(CXX)]
    if core_src and not any(under(f, cfg["core_tests"]) for f in changed):
        r.add("WARN", "core/ logic changed but no core test changed", core_src)

    # rule 8: CI hygiene in workflows
    unpinned, retention = [], []
    for f in changed:
        if not (f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))):
            continue
        for line in added.get(f, []):
            m = USES.match(line)
            if (
                m
                and not m.group(1).startswith(("./", "docker://"))
                # only the org's own reusable workflows may follow @main (rule 10)
                and not m.group(1).startswith("swarm-routing/.github/.github/workflows/")
            ):
                if not SHA_PIN.match(line):
                    unpinned.append(f"{f}: {line.strip()}")
            m = re.search(r"retention-days:\s*(\d+)", line)
            if m and int(m.group(1)) > 7:
                retention.append(f"{f}: {line.strip()}")
    if unpinned:
        r.add(
            "FAIL", "rule 8: actions pinned by full commit SHA with a `# vX.Y.Z` comment", unpinned
        )
    if retention:
        r.add("FAIL", "rule 8: transient artifacts keep retention-days <= 7", retention)
    if any(f.startswith(".github/workflows/") for f in changed) and not (unpinned or retention):
        r.add("PASS", "rule 8: workflow actions pinned, retention within 7 days")

    # rule 9: nothing shipped depends on .claude/
    bad = []
    for f in changed:
        if f.startswith(".claude/") or f in ("AGENTS.md", "CLAUDE.md") or f.endswith(".md"):
            continue
        for line in added.get(f, []):
            if re.search(
                r"\.claude/skills/\S+\.(py|sh)|[\"']\.claude[\"'],\s*[\"']skills[\"']", line
            ):
                bad.append(f"{f}: {line.strip()}")
    if bad:
        r.add(
            "FAIL", "rule 9: a shipped file depends on a .claude/ script (move it to tools/)", bad
        )

    if not r.lines:
        r.add("PASS", "nothing in the diff that these rules cover")

    # rules 6 and 7 need judgement: HINT lines point at candidate spots, never fail
    grown = [
        f
        for f in changed
        if f.endswith(CXX) and (under(f, cfg["core"]) or under(f, cfg["sim_dirs"]))
    ]
    hints = container_hints(repo, grown, numbered)
    if hints:
        r.add("HINT", "rule 7: a new container grows with no cap or eviction in sight", hints)
    sources = [(f, numbered.get(f, [])) for f in changed if f.endswith(".md")]
    if pr_body:
        with open(pr_body, encoding="utf-8", errors="replace") as fh:
            sources.append(("PR body", list(enumerate(fh.read().splitlines(), 1))))
    hints = claim_hints(sources)
    if hints:
        r.add("HINT", "rule 6: a comparison needs >= 20 paired seeds and its run linked", hints)

    r.lines.append("----")
    tail = f"; {r.hints} hint(s) to judge (rules 6, 7)" if r.hints else ""
    if r.fail:
        r.lines.append("FAIL  invariant violation: fix before merge" + tail)
    elif r.warn:
        r.lines.append("WARN  review the warnings above" + tail)
    else:
        r.lines.append("PASS  mechanical invariants clean" + tail)
    return r


# --- self-test -------------------------------------------------------------------------


def self_test():
    failures = []

    def expect(name, cond):
        if not cond:
            failures.append(name)

    hdr = f"// {COPYRIGHT}\n// SPDX-License-Identifier: {{}}\n"

    def repo(files_base, files_change, cfg='dual = ["core/"]\n'):
        d = tempfile.mkdtemp()
        git(d, "init", "-q", "-b", "main")
        git(d, "config", "user.email", "t@t")
        git(d, "config", "user.name", "t")
        files_base = {
            ".github/org-sync.toml": cfg,
            "LICENSING.md": "| `core/` | x |\n| `ns3/` | x |\n",
            **files_base,
        }
        for p, t in files_base.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
            with open(os.path.join(d, p), "w") as fh:
                fh.write(t)
        git(d, "add", "-A")
        git(d, "commit", "-qm", "base")
        for p, t in files_change.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
            with open(os.path.join(d, p), "w") as fh:
                fh.write(t)
        return check(d, base="main")

    def has(rep, level, needle):
        return any(ln.startswith(level) and needle in ln for ln in rep.lines)

    good_core = hdr.format(DUAL) + '#include <vector>\n#include "core/x.h"\nint f();\n'
    test = hdr.format(DUAL) + "int t();\n"
    ok = repo({}, {"core/a.cc": good_core, "core/tests/t.cc": test})
    expect("a clean core change passes", not ok.fail and not ok.warn)
    expect("…and reports rule 1, 2 and 5", all(has(ok, "PASS", f"rule {n}") for n in (1, 2, 5)))

    r = repo(
        {}, {"core/a.cc": "// Copyright (C) 2026 Someone\nint f();\n", "core/tests/t.cc": test}
    )
    expect("rule 1: a missing header fails", r.fail and has(r, "FAIL", "rule 1"))
    r = repo({}, {"core/a.cc": hdr.format(GPL) + "int f();\n", "core/tests/t.cc": test})
    expect("rule 1: GPL-only in a dual root fails", has(r, "FAIL", "rule 1"))
    r = repo({}, {"ns3/m.cc": hdr.format(DUAL) + "int f();\n"})
    expect(
        "rule 1: dual in a GPL directory is allowed (GPL may use dual)",
        not has(r, "FAIL", "rule 1"),
    )
    r = repo({}, {"arms/x/a.cc": hdr.format(GPL) + "int f();\n"})
    expect("rule 1: a new directory without a LICENSING row warns", has(r, "WARN", "new directory"))
    r = repo(
        {},
        {
            "ns3/m.cc": "// SPDX-License-Identifier: GPL-2.0-only\n// Copyright (C) 2026 X\nint f();\n"
        },
    )
    expect(
        "rule 1: another copyright line with the right SPDX passes", not has(r, "FAIL", "rule 1")
    )
    r = repo({}, {".claude/hooks/h.sh": "echo hi\n"})
    expect("rule 1: .claude/ is not checked", not has(r, "FAIL", "rule 1"))

    r = repo({}, {"core/a.cc": good_core + "#include <ns3/node.h>\n", "core/tests/t.cc": test})
    expect("rule 2: an ns-3 include in core/ fails", has(r, "FAIL", "rule 2"))
    r = repo({}, {"core/a.cc": good_core + '#include "../ns3/m.h"\n', "core/tests/t.cc": test})
    expect("rule 2: a quoted include leaving core/ fails", has(r, "FAIL", "rule 2"))
    r = repo({}, {"core/a.cc": good_core, "core/tests/t.cc": test + '#include "../a.h"\n'})
    expect("rule 2: a test's ../ include that stays in core/ passes", not has(r, "FAIL", "rule 2"))
    r = repo(
        {"core/include/ara/core/x.h": hdr.format(DUAL) + "int x();\n"},
        {"core/a.cc": good_core + "#include <ara/core/x.h>\n", "core/tests/t.cc": test},
    )
    expect("rule 2: an angle include of a core/ header passes", not has(r, "FAIL", "rule 2"))

    wcfg = 'dual = ["core/"]\n[review]\nwire = ["core/wire*"]\nwire_version = "kWireVersion"\n'
    r = repo(
        {},
        {"core/wire.h": hdr.format(DUAL) + "struct W { int a; };\n", "core/tests/t.cc": test},
        wcfg,
    )
    expect("rule 3: a wire change without a bump warns", has(r, "WARN", "rule 3"))
    r = repo(
        {},
        {
            "core/wire.h": hdr.format(DUAL) + "constexpr int kWireVersion = 2;\n",
            "core/tests/t.cc": test,
        },
        wcfg,
    )
    expect("rule 3: with the bump it passes", has(r, "PASS", "rule 3"))

    r = repo({}, {"CMakeLists.txt": "build_lib(LIBNAME core SOURCE_FILES a.cc)\n"})
    expect("rule 4: a module named core fails", has(r, "FAIL", "rule 4"))
    r = repo({}, {"CMakeLists.txt": "build_lib(LIBNAME swarm-core SOURCE_FILES a.cc)\n"})
    expect("rule 4: swarm-core passes", not has(r, "FAIL", "rule 4"))

    r = repo({}, {"core/a.cc": good_core + "int g() { return rand(); }\n", "core/tests/t.cc": test})
    expect("rule 5: rand() in core/ fails", has(r, "FAIL", "rule 5"))
    r = repo(
        {"core/a.cc": good_core + "int g(int i) {\n  return i;\n}\n", "core/tests/t.cc": test},
        {"core/a.cc": good_core + "int g(int i) {\n++i; return rand();\n}\n"},
    )
    expect("an added line starting with ++ (shown as +++) is still read", has(r, "FAIL", "rule 5"))
    r = repo({}, {"ns3/m.cc": hdr.format(GPL) + "auto t = std::chrono::system_clock::now();\n"})
    expect("rule 5: a wall clock in ns3/ warns", has(r, "WARN", "rule 5") and not r.fail)
    r = repo(
        {}, {"core/a.cc": good_core + "std::unordered_map<int,int> m;\n", "core/tests/t.cc": test}
    )
    expect("rule 5: an unordered container in core/ warns", has(r, "WARN", "unordered"))

    r = repo({}, {"core/a.cc": good_core})
    expect("a core change without a test warns", has(r, "WARN", "no core test"))

    pinned = "      - uses: actions/checkout@" + "a" * 40 + " # v6.0.0\n"
    r = repo({}, {".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n" + pinned})
    expect("rule 8: a SHA-pinned action passes", has(r, "PASS", "rule 8") and not r.fail)
    r = repo(
        {},
        {
            ".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v6\n"
        },
    )
    expect("rule 8: a tag-pinned action fails", has(r, "FAIL", "rule 8"))
    r = repo({}, {".github/workflows/ci.yml": pinned + "          retention-days: 30\n"})
    expect("rule 8: retention over 7 days fails", has(r, "FAIL", "retention"))
    r = repo(
        {},
        {
            ".github/workflows/ci.yml": "      - uses: swarm-routing/.github/.github/workflows/reusable-ns3-ci.yml@main\n"
        },
    )
    expect("rule 8: an org reusable workflow at @main is allowed", not r.fail)

    r = repo(
        {},
        {
            "tools/run.sh": f"# {COPYRIGHT}\n# SPDX-License-Identifier: {GPL}\nbash .claude/skills/x/y.sh\n"
        },
    )
    expect("rule 9: a shipped script calling a .claude/ script fails", has(r, "FAIL", "rule 9"))
    r = repo({}, {"docs/how.md": "run .claude/skills/x/y.sh\n"})
    expect("rule 9: a doc may mention one", not has(r, "FAIL", "rule 9"))

    r = repo(
        {},
        {".github/workflows/ci.yml": "      - uses: other-org/repo/.github/workflows/x.yml@main\n"},
    )
    expect("rule 8: a non-org reusable workflow at @main fails", has(r, "FAIL", "rule 8"))
    r = repo({}, {"core/a b.cc": "int f();\n", "core/tests/t.cc": test})
    expect(
        "a path with a space is checked, not dropped",
        has(r, "FAIL", "rule 1") and "core/a b.cc" in "\n".join(r.lines),
    )
    r = repo({}, {"core/ação.cc": "int f();\n", "core/tests/t.cc": test})
    expect(
        "a non-ASCII path is checked",
        has(r, "FAIL", "rule 1") and "core/ação.cc" in "\n".join(r.lines),
    )
    r = repo(
        {"core/x y.cc": hdr.format(DUAL) + "int x();\n"},
        {"core/x y.cc": hdr.format(DUAL) + "int r() { return rand(); }\n", "core/tests/t.cc": test},
    )
    expect("added lines of a tracked path with a space are read", has(r, "FAIL", "rule 5"))
    # rules 6 and 7: HINT lines, never a FAIL or a WARN
    unbounded_h = hdr.format(DUAL) + (
        "#include <deque>\nstruct C {\n  void On(int id);\n  std::deque<int> seen_;\n};\n"
    )
    grows = hdr.format(DUAL) + '#include "c.h"\nvoid C::On(int id) { seen_.push_back(id); }\n'
    r = repo({}, {"core/c.h": unbounded_h, "core/c.cc": grows, "core/tests/t.cc": test})
    expect(
        "rule 7: an unbounded deque is hinted, the verdict stays PASS",
        has(r, "HINT", "rule 7")
        and "core/c.h:6 seen_ (deque): push_back at core/c.cc:4" in "\n".join(r.lines)
        and not (r.fail or r.warn),
    )
    capped = grows.replace(
        "seen_.push_back(id); }",
        "seen_.push_back(id);\n  if (seen_.size() > 64) seen_.erase(seen_.begin()); }",
    )
    r = repo({}, {"core/c.h": unbounded_h, "core/c.cc": capped, "core/tests/t.cc": test})
    expect("rule 7: a deque with an erase is not hinted", not has(r, "HINT", "rule 7"))
    by_cap = grows.replace("{ seen_", "{ if (seen_.size() < cfg.maxSeen) seen_")
    r = repo({}, {"core/c.h": unbounded_h, "core/c.cc": by_cap, "core/tests/t.cc": test})
    expect("rule 7: a max name on the container is not hinted", not has(r, "HINT", "rule 7"))
    r = repo({}, {"core/c.h": unbounded_h, "core/tests/t.cc": test})
    expect("rule 7: a container that does not grow is not hinted", not has(r, "HINT", "rule 7"))
    r = repo({}, {"docs/x.cc": unbounded_h + grows.split("\n", 2)[2]})
    expect("rule 7: only core/ and simulator dirs are looked at", not has(r, "HINT", "rule 7"))

    r = repo({}, {"results.md": "# Results\n\nARA gains 4.1 % on 5 seeds.\n"})
    expect(
        "rule 6: '4.1 % on 5 seeds' is hinted, the verdict stays PASS",
        has(r, "HINT", "rule 6")
        and "results.md:3" in "\n".join(r.lines)
        and "(5 seeds/runs, below 20)" in "\n".join(r.lines)
        and r.lines[-1].startswith("PASS")
        and "1 hint(s)" in r.lines[-1],
    )
    r = repo(
        {},
        {"docs/results.md": "ARA beats AODV by 4.1 % PDR (20 paired seeds, run 123).\n"},
    )
    expect("rule 6: '20 paired seeds, run 123' is not hinted", not has(r, "HINT", "rule 6"))
    r = repo({}, {"docs/results.md": "BeeAdHoc delivers 3 % more than AODV.\n"})
    expect("rule 6: a claim with no seed count is hinted", has(r, "HINT", "rule 6"))
    r = repo(
        {},
        {
            "docs/how.md": "Coverage of `core/` is 90 %. The native-vs-WASM gate runs "
            "`parity.sh 120` on CI ([#850](https://x/850)).\n"
        },
    )
    expect("rule 6: numbers that compare no protocols are not hinted", not has(r, "HINT", "rule 6"))
    body = os.path.join(tempfile.mkdtemp(), "pr.md")
    with open(body, "w") as fh:
        fh.write("## Summary\n\nOLSR leads at 99.8 % PDR.\n")
    d = tempfile.mkdtemp()
    git(d, "init", "-q", "-b", "main")
    git(d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "b")
    r = check(d, base="main", pr_body=body)
    expect(
        "rule 6: --pr-body is read",
        has(r, "HINT", "rule 6") and "PR body:3" in "\n".join(r.lines),
    )

    r = repo({}, {"README.md": "text\n"})
    expect("a docs-only diff has nothing to check", has(r, "PASS", "nothing in the diff"))

    for f in failures:
        print(f"FAIL: {f}")
    print(f"check_invariants self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--base", default="origin/main")
    p.add_argument("--pr-body", metavar="FILE", help="also look for rule 6 claims in this text")
    p.add_argument("--json", action="store_true", help="the checks as JSON, for tools")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    repo = git(a.repo, "rev-parse", "--show-toplevel").strip()
    rep = check(repo, a.base, a.pr_body)
    if a.json:
        result = "FAIL" if rep.fail else "WARN" if rep.warn else "PASS"
        print(json.dumps({"result": result, "checks": rep.checks}, indent=1))
    else:
        print("\n".join(rep.lines))
    return 1 if rep.fail else 0


if __name__ == "__main__":
    sys.exit(main())
