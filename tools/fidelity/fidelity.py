#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A protocol's fidelity sheet (docs/fidelity.md): the shape, the check, the row.

A comparator counts only after its fidelity sheet exists (org rule 6, first
gate). The sheet maps every mechanism and every parameter to the paper section
that gives it, or says plainly that it is a repo choice or unknown. This tool
keeps that mapping honest; the reading of the paper is still the author's.

  fidelity.py skeleton --protocol NAME [--key KEY --citation TEXT]   empty sheet, org shape
  fidelity.py check FILE              shape and Source cells valid (a reference, a reasoned
                                      repo choice, or unknown); lists the unknowns and
                                      repo choices; exit 1 on a problem. Passing does not
                                      mean every row comes from the paper.
  fidelity.py row FILE [--protocol]   one summary row (the .github#54 review shape); the
                                      name comes from the sheet's H1 unless --protocol
  fidelity.py --self-test

The sheet has four required sections, each a Markdown table:

  ## Sources            | Key | Citation | Access |
  ## Mechanisms         | Mechanism | Source | Implementation | Status |
  ## Parameters         | Parameter | Value | Source | Notes |
  ## Anchor candidate   | Trend | Scenario | Metric | Comparators | Source |

and may add `## Differences from <arm>` (| Paper | Arm | Difference |) and any
prose. A Source cell is one or more references `[KEY] §3.1`, `[KEY] Table 4.1`,
`[KEY] Fig. 2`, `[KEY] Listing 13.17`, `[KEY] eq. 4.3`,
`[KEY] p. 84` (joined by `;`), or `repo choice: <reason>`, or
`unknown`. KEY must be a row of Sources. A parameter whose source is `unknown`
may have the value `—`; any other value needs a source. Stdlib only.
"""

import argparse
import os
import re
import sys
import tempfile

REQUIRED = {
    "Sources": ["Key", "Citation", "Access"],
    "Mechanisms": ["Mechanism", "Source", "Implementation", "Status"],
    "Parameters": ["Parameter", "Value", "Source", "Notes"],
    "Anchor candidate": ["Trend", "Scenario", "Metric", "Comparators", "Source"],
}
OPTIONAL_PREFIX = "Differences from"
ACCESS = {"open", "browser", "institution", "author", "in hand"}
LOCATOR = r"(§\s?\d+(\.\d+)*[a-z]?|Table\s\d+(\.\d+)*|Fig\.\s\d+(\.\d+)*[a-z]?|Listing\s\d+(\.\d+)*|Alg\.\s\d+(\.\d+)*|eq\.\s\d+(\.\d+)*|pp?\.\s\d+(–\d+)?|ch\.\s\d+|App\.\s[A-Z])"
REF = re.compile(r"^\[([A-Za-z0-9_-]+)\]\s+" + LOCATOR + r"(\s*,\s*" + LOCATOR + r")*$")
EMPTY = {"", "—", "-", "–"}


class Failure(Exception):
    pass


def split_row(line):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def parse(text):
    """{section title: [header, [rows]]}; tables are the first one under each ## heading."""
    sections, title, table = {}, None, None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m:
            title, table = m.group(1), None
            continue
        if title is None or not line.lstrip().startswith("|"):
            if table is not None and title in sections:
                table = "done"
            continue
        if table == "done":
            continue
        cells = split_row(line)
        if table is None:
            table = "header"
            sections[title] = [cells, []]
        elif table == "header":
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                table = "body"
            else:
                raise Failure(f"## {title}: the table has no separator row")
        else:
            sections[title][1].append(cells)
    return sections


def source_kind(cell, keys):
    """('ref'|'repo'|'unknown', problem or None)."""
    c = cell.strip()
    low = c.lower()
    if low == "unknown":
        return "unknown", None
    if low.startswith("repo choice"):
        reason = c.split(":", 1)[1].strip() if ":" in c else ""
        return "repo", None if reason else "a repo choice needs a reason (`repo choice: <why>`)"
    parts = [p.strip() for p in c.split(";") if p.strip()]
    if not parts:
        return "ref", "empty source"
    for p in parts:
        m = REF.match(p)
        if not m:
            return (
                "ref",
                f"`{p}` is not `[KEY] §x`, `[KEY] Table N`, `[KEY] Fig. N`, `[KEY] eq. N`, `repo choice: …` or `unknown`",
            )
        if m.group(1) not in keys:
            return "ref", f"`[{m.group(1)}]` is not a key in ## Sources"
    return "ref", None


def check_text(text):
    """(problems, summary)."""
    problems = []
    try:
        sections = parse(text)
    except Failure as e:
        return [str(e)], None
    for name, cols in REQUIRED.items():
        if name not in sections:
            problems.append(f"missing section `## {name}` with a table")
            continue
        header = sections[name][0]
        if header != cols:
            problems.append(f"## {name}: columns are {header}, want {cols}")
    if problems:
        return problems, None
    keys = set()
    for i, row in enumerate(sections["Sources"][1], 1):
        if len(row) != 3 or any(c in EMPTY for c in row[:2]):
            problems.append(f"## Sources row {i}: needs Key, Citation and Access")
            continue
        keys.add(row[0].strip("[]"))
        if row[2].lower() not in ACCESS:
            problems.append(f"## Sources row {i}: access `{row[2]}` is not one of {sorted(ACCESS)}")
    if not keys:
        problems.append("## Sources: no source; a sheet cites at least the paper")
    counts = {"Mechanisms": {}, "Parameters": {}}
    unknowns, choices = [], []
    for name, src_col in (("Mechanisms", 1), ("Parameters", 2)):
        rows = sections[name][1]
        if not rows:
            problems.append(f"## {name}: empty table")
        for i, row in enumerate(rows, 1):
            if len(row) != len(REQUIRED[name]):
                problems.append(f"## {name} row {i}: {len(row)} cells, want {len(REQUIRED[name])}")
                continue
            label = row[0]
            if label in EMPTY:
                problems.append(f"## {name} row {i}: no {REQUIRED[name][0].lower()}")
            kind, err = source_kind(row[src_col], keys)
            if err:
                problems.append(f"## {name} `{label}`: {err}")
                continue
            counts[name][kind] = counts[name].get(kind, 0) + 1
            if kind == "unknown":
                unknowns.append(label)
            if kind == "repo":
                choices.append(label)
            if name == "Parameters" and row[1] in EMPTY and kind != "unknown":
                problems.append(
                    f"## Parameters `{label}`: no value, but its source is not `unknown`"
                )
            if name == "Mechanisms" and row[3] in EMPTY:
                problems.append(
                    f"## Mechanisms `{label}`: empty status (as written, deviation: …, not implemented: …, or unknown)"
                )
    anchors = sections["Anchor candidate"][1]
    if not anchors:
        problems.append(
            "## Anchor candidate: empty; write the trend to reproduce, or `none: <why>`"
        )
    for i, row in enumerate(anchors, 1):
        if len(row) != 5:
            problems.append(f"## Anchor candidate row {i}: {len(row)} cells, want 5")
            continue
        if row[0].lower().startswith("none"):
            continue
        _, err = source_kind(row[4], keys)
        if err:
            problems.append(f"## Anchor candidate row {i}: {err}")
    for title, (header, rows) in sections.items():
        if title.startswith(OPTIONAL_PREFIX) and header != ["Paper", "Arm", "Difference"]:
            problems.append(
                f"## {title}: columns are {header}, want ['Paper', 'Arm', 'Difference']"
            )
    summary = {
        "sources": [r for r in sections["Sources"][1] if len(r) == 3],
        "counts": counts,
        "unknowns": unknowns,
        "choices": choices,
        "anchor": anchors[0] if anchors else None,
    }
    return problems, summary


def skeleton(protocol, key="P1", citation="TODO: authors, title, venue, year, DOI"):
    return f"""# {protocol}: fidelity sheet

What the paper specifies, what this implementation does, and where they differ.
Every row cites its source (`[KEY] §x`, `Table N`, `Fig. N`, `eq. N`), or says
`repo choice: <reason>`, or `unknown`. Checked by
`swarm-routing/.github` `tools/fidelity/fidelity.py check`.

## Sources

| Key | Citation | Access |
|---|---|---|
| {key} | {citation} | in hand |

## Mechanisms

| Mechanism | Source | Implementation | Status |
|---|---|---|---|
| TODO | unknown | — | unknown |

## Parameters

| Parameter | Value | Source | Notes |
|---|---|---|---|
| TODO | — | unknown | |

## Anchor candidate

| Trend | Scenario | Metric | Comparators | Source |
|---|---|---|---|---|
| TODO | TODO | TODO | TODO | unknown |
"""


def protocol_name(text, directory):
    """The name skeleton() wrote in the H1; else the sheet's directory."""
    h1 = re.search(r"^#\s+(.+?):\s*fidelity sheet\s*$", text, re.M)
    return h1.group(1).strip() if h1 else os.path.basename(directory)


def row_line(summary, protocol):
    srcs = "; ".join(f"[{r[0]}] {r[1]}" for r in summary["sources"])
    access = ", ".join(sorted({r[2] for r in summary["sources"]}))
    m, p = summary["counts"]["Mechanisms"], summary["counts"]["Parameters"]
    fid = (
        f"{sum(m.values())} mechanisms ({m.get('ref', 0)} sourced, {m.get('repo', 0)} repo choice, {m.get('unknown', 0)} unknown); "
        f"{sum(p.values())} parameters ({p.get('ref', 0)} sourced, {p.get('repo', 0)} repo choice, {p.get('unknown', 0)} unknown)"
    )
    missing = ", ".join(summary["unknowns"]) or "none"
    a = summary["anchor"]
    anchor = f"{a[0]} ({a[1]}; {a[2]}; vs {a[3]}; {a[4]})" if a else "none"
    cells = [protocol, srcs, access, fid, missing, anchor]
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def self_test():
    failures = []

    def expect(name, cond):
        if not cond:
            failures.append(name)

    good = (
        skeleton("ARA", "G02", "Güneş, Sorges & Bouazizi, ARA, IWAHN 2002")
        .replace(
            "| TODO | unknown | — | unknown |",
            "| FANT flooded, duplicates destroyed | [G02] §3.1 | `core/` | as written |\n"
            "| Backward ant path | unknown | retraces the FANT | deviation: path not stated |",
        )
        .replace(
            "| TODO | — | unknown | |",
            "| evaporation q | — | unknown | not in the paper |\n"
            "| relay jitter | 10 ms | repo choice: AODV's jitter | |\n"
            "| table size | 64 | [G02] Table 1, Fig. 2 | |",
        )
        .replace(
            "| TODO | TODO | TODO | TODO | unknown |",
            "| ARA beats AODV on PDR at high mobility | 50 nodes, RWP | PDR | AODV | [G02] Fig. 4 |",
        )
    )
    probs, summ = check_text(good)
    expect("a well-formed sheet passes", probs == [])
    expect("unknowns listed", summ and summ["unknowns"] == ["Backward ant path", "evaporation q"])
    expect("repo choices listed", summ and summ["choices"] == ["relay jitter"])
    expect("counts", summ and summ["counts"]["Parameters"] == {"unknown": 1, "repo": 1, "ref": 1})
    line = row_line(summ, "ARA")
    expect("row names the missing defaults", "Backward ant path, evaporation q" in line)
    expect("row carries the anchor", "ARA beats AODV" in line and "[G02] Fig. 4" in line)

    def bad(old, new, needle):
        probs, _ = check_text(good.replace(old, new))
        expect(f"rejects: {needle}", any(needle in p for p in probs))

    bad("| table size | 64 | [G02] Table 1, Fig. 2 |", "| table size | 64 | |", "empty source")
    bad(
        "| table size | 64 | [G02] Table 1, Fig. 2 |",
        "| table size | 64 | the paper |",
        "is not `[KEY]",
    )
    bad("[G02] §3.1", "[X99] §3.1", "not a key in ## Sources")
    bad("repo choice: AODV's jitter", "repo choice", "needs a reason")
    bad("| evaporation q | — | unknown |", "| evaporation q | — | [G02] §3.2 |", "no value")
    bad("| as written |", "| |", "empty status")
    bad("| in hand |", "| paywalled |", "access `paywalled`")
    bad("## Parameters", "## Params", "missing section `## Parameters`")
    bad("| Parameter | Value | Source | Notes |", "| Parameter | Source | Notes |", "columns are")
    bad("[G02] Fig. 4 |", "maybe |", "Anchor candidate row 1")
    for loc in ("Listing 13.17", "Alg. 2", "p. 84", "pp. 72–74", "ch. 13", "§4.2.5, p. 74"):
        probs, _ = check_text(good.replace("[G02] Table 1, Fig. 2", f"[G02] {loc}"))
        expect(f"accepts locator {loc}", probs == [])
    expect("skeleton is the org shape", all(f"## {s}" in skeleton("X") for s in REQUIRED))
    probs, _ = check_text(skeleton("X"))
    expect("skeleton passes check (TODO rows are unknown)", probs == [])

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "fidelity.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(good)
        expect("main check exit 0", main(["check", p]) == 0)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(good.replace("[G02] §3.1", "[G02] somewhere"))
        expect("main check exit 1", main(["check", p]) == 1)
        docs = os.path.join(d, "docs")
        os.makedirs(docs)
        with open(os.path.join(docs, "fidelity.md"), "w", encoding="utf-8") as fh:
            fh.write(good)
        expect("row names the protocol from the H1, not docs/", protocol_name(good, docs) == "ARA")
        expect("row falls back to the directory", protocol_name("no h1", docs) == "docs")

    for f in failures:
        print(f"FAIL: {f}")
    print(f"fidelity.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("skeleton")
    s.add_argument("--protocol", required=True)
    s.add_argument("--key", default="P1")
    s.add_argument("--citation", default="TODO: authors, title, venue, year, DOI")
    c = sub.add_parser("check")
    c.add_argument("file")
    r = sub.add_parser("row")
    r.add_argument("file")
    r.add_argument("--protocol", default="")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.cmd == "skeleton":
        sys.stdout.write(skeleton(args.protocol, args.key, args.citation))
        return 0
    if args.cmd in ("check", "row"):
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
        problems, summary = check_text(text)
        if args.cmd == "check":
            for prob in problems:
                print(f"{args.file}: {prob}")
            if summary:
                m, q = summary["counts"]["Mechanisms"], summary["counts"]["Parameters"]
                print(
                    f"{args.file}: {sum(m.values())} mechanisms, {sum(q.values())} parameters; "
                    f"unknown: {', '.join(summary['unknowns']) or 'none'}; "
                    f"repo choice: {', '.join(summary['choices']) or 'none'}"
                )
            print(f"fidelity check: {'ok' if not problems else f'{len(problems)} problem(s)'}")
            return 1 if problems else 0
        if problems:
            for prob in problems:
                print(f"{args.file}: {prob}", file=sys.stderr)
            return 1
        name = args.protocol or protocol_name(text, os.path.dirname(os.path.abspath(args.file)))
        print(row_line(summary, name))
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
