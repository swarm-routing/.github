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
  fidelity.py verify FILE --text KEY=PATH [...]
                                      each [KEY] locator against the source's extracted
                                      text (pdfx.py text): the place exists, and a Table N
                                      row's value is in that table; exit 1 on a miss
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
# (pattern, how the error message shows it): one list, so the two cannot drift
LOCATORS = (
    (r"§\s?\d+(\.\d+)*[a-z]?", "§x"),
    (r"Table\s\d+(\.\d+)*", "Table N"),
    (r"Fig\.\s\d+(\.\d+)*[a-z]?", "Fig. N"),
    (r"Listing\s\d+(\.\d+)*", "Listing N"),
    (r"Alg\.\s\d+(\.\d+)*", "Alg. N"),
    (r"eq\.\s\d+(\.\d+)*", "eq. N"),
    (r"pp?\.\s\d+(–\d+)?", "p. N / pp. N–M"),
    (r"ch\.\s\d+", "ch. N"),
    (r"App\.\s[A-Z]", "App. X"),
)
LOCATOR = "(" + "|".join(pat for pat, _ in LOCATORS) + ")"
SHOWN = ", ".join(f"`[KEY] {shown}`" for _, shown in LOCATORS)
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
                f"`{p}` is not {SHOWN}, `repo choice: …` or `unknown`",
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
    unknowns, choices, open_rows = [], [], []
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
            status = row[3].strip().lower()
            if (
                name == "Mechanisms"
                and kind != "unknown"
                and (status == "unknown" or status.startswith("unknown:"))
            ):
                # a cited section, or a repo choice, that does not settle the mechanism
                open_rows.append(label)
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
        "open": open_rows,
        "anchor": anchors[0] if anchors else None,
    }
    return problems, summary


# --- verify: locators and values against the source's extracted text --------------------

LEADERS = re.compile(r"(\s\.){3,}|\.{4,}")  # a table-of-contents line, not the body
HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z]")  # "4.2.5 Route", "4.1. Simulation"
WORDS = dict(enumerate("zero one two three four five six seven eight nine ten".split()))
WORDS = {str(k): v for k, v in WORDS.items()}
CAPTION = re.compile(r"^(Table|Figure|Fig\.|Listing)\s+(\d+(?:\.\d+)*)\b")


def _norm(s):
    # pdftotext splits numbers ("2 . 0"), ligatures, and stray spaces
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("−", "-")
    return re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", s)


STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "per",
    "value",
    "number",
    "after",
    "before",
    "scenario",
}


def _label_words(text):
    """The words that name a parameter: 3+ letters, or a Greek symbol, lower-cased."""
    words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)} - STOP
    return words | set(re.findall(r"[α-ωΑ-Ω]", text))


def _blocks(lines):
    """Index the body: {('§', '4.2.5'): (start, end), ('Table', '4.1'): ...}."""
    marks = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or LEADERS.search(line):
            continue
        m = CAPTION.match(line)
        if m:
            kind = "Figure" if m.group(1) in ("Figure", "Fig.") else m.group(1)
            marks.append((i, (kind, m.group(2))))
            continue
        m = HEADING.match(line)
        if m and len(line) < 90:
            marks.append((i, ("§", m.group(1))))
    out = {}
    for n, (i, key) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
        if key[0] in ("Table", "Figure", "Listing"):
            end = min(end, i + 60)  # a caption's block is short
        if key[0] == "Table":
            # rows are short lines; a bare page number or running prose ends the table
            for j in range(i + 1, end):
                row = lines[j].strip()
                if re.fullmatch(r"\d{1,4}", row) or len(row) > 70:
                    end = j
                    break
        out.setdefault(key, (i, end))
    return out


def _locators(cell):
    """[(key, kind, number)] for the Table/Fig./Listing/§/eq. locators of a Source cell."""
    out = []
    for part in cell.split(";"):
        m = re.match(r"\s*\[([A-Za-z0-9_-]+)\]\s+(.*)", part)
        if not m:
            continue
        for loc in m.group(2).split(","):
            loc = loc.strip()
            for pat, kind in (
                (r"Table\s(\d+(?:\.\d+)*)", "Table"),
                (r"Fig\.\s(\d+(?:\.\d+)*)", "Figure"),
                (r"Listing\s(\d+(?:\.\d+)*)", "Listing"),
                (r"§\s?(\d+(?:\.\d+)*)", "§"),
                (r"eq\.\s(\d+(?:\.\d+)*)", "eq."),
            ):
                lm = re.fullmatch(pat + r"[a-z]?", loc)
                if lm:
                    out.append((m.group(1), kind, lm.group(1)))
    return out


def verify_text(sheet, texts):
    """(errors, warnings) for a sheet against {KEY: extracted text}."""
    sections = parse(sheet)
    index = {k: (_norm(v).splitlines(), _blocks(_norm(v).splitlines())) for k, v in texts.items()}
    errors, warns, checked = [], [], 0
    for name, src_col, val_col in (("Mechanisms", 1, None), ("Parameters", 2, 1)):
        for row in sections.get(name, [None, []])[1]:
            if len(row) <= src_col:
                continue
            value = row[val_col] if val_col is not None else ""
            first = re.search(r"\d+(?:\.\d+)?", _norm(value)) if value not in EMPTY else None
            for key, kind, num in _locators(row[src_col]):
                if key not in index:
                    continue
                lines, blocks = index[key]
                checked += 1
                where = f"## {name} `{row[0]}`: [{key}] {kind} {num}"
                if kind == "eq.":
                    if not any(re.search(rf"\({re.escape(num)}\)\s*$", ln) for ln in lines):
                        warns.append(f"{where}: no '({num})' equation label found")
                    continue
                span = blocks.get((kind, num))
                if not span:
                    errors.append(f"{where}: not found in the text")
                    continue
                if not first:
                    continue
                block = lines[span[0] : span[1]]
                body = " ".join(block)
                hit = rf"(?<![\d.]){re.escape(first.group(0))}(?![\d])"
                if kind == "Table":
                    # a table row is one line: the value must sit next to a word of
                    # the parameter's name, or a small number matches any row
                    names = _label_words(row[0])
                    on_line = [ln for ln in block if re.search(hit, ln)]
                    rows = [_label_words(ln) for ln in block]
                    # a word on only one row of the table names that row
                    own = {w for w in names if sum(w in r for r in rows) == 1}

                    def names_it(ln, names=names, own=own):
                        words = _label_words(ln)
                        return names <= words or bool(own & words)

                    if on_line and (not names or any(names_it(ln) for ln in on_line)):
                        continue
                    if on_line:
                        errors.append(
                            f"{where}: {first.group(0)} is in that table, but not on a row naming "
                            f"{', '.join(sorted(names))}"
                        )
                        continue
                elif re.search(hit, body):
                    continue
                word = WORDS.get(first.group(0))
                if word and re.search(rf"\b{word}\b", body, re.I):
                    continue  # prose writes small numbers out ("the nominal value of K is zero")
                if kind == "Table":
                    errors.append(f"{where}: value {first.group(0)} is not in that table")
                else:
                    warns.append(f"{where}: value {first.group(0)} not found in that {kind}")
    return errors, warns, checked


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
    if summary["open"]:
        missing += f"; open: {', '.join(summary['open'])}"
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
    probs, summ = check_text(good.replace("| as written |", "| unknown: unicast or flooded? |"))
    expect("a sourced row with status unknown passes", probs == [])
    expect(
        "…and is listed as open", summ and summ["open"] == ["FANT flooded, duplicates destroyed"]
    )
    expect("…and the row carries it", "open: FANT flooded" in row_line(summ, "ARA"))
    expect("no open rows by default", summ and check_text(good)[1]["open"] == [])
    for st, want in (
        ("unknown", True),
        ("Unknown: which acknowledgement?", True),
        ("unknownness", False),
    ):
        _, s = check_text(good.replace("| as written |", f"| {st} |"))
        expect(f"status `{st}` open={want}", bool(s and s["open"]) == want)
    probs, _ = check_text(good.replace("[G02] §3.1", "[G02] the paper"))
    expect("the error names every locator form", probs and all(s in probs[0] for _, s in LOCATORS))
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

    paper = (
        "Contents\n4.2.5 Route Selection . . . . . . 74\n"
        "4.2.5 Route Selection\nThe nominal value of K is zero, F sharpens (4.3)\n"
        "4.3 Properties\ntext\n"
        "Table 4.1: Simulation Parameters\ninitial pheromone 1\npheromone ceiling 10000\n"
        "τ (decay rate) 0 . 105\nRREQs per Route Request 2\n"
        "7.3.1 Setup\nF = 10 . 0, τ = 2 . 0\n"
    )
    vsheet = (
        skeleton("T", "R05", "Roth 2005")
        .replace(
            "| TODO | — | unknown | |",
            "| ceiling | 10000 | [R05] Table 4.1 | |\n"
            "| decay τ | 0.105 per 1 s | [R05] Table 4.1 | |\n"
            "| K | 0 | [R05] §4.2.5 | |\n"
            "| F | 10 | [R05] Table 4.1 | |\n"
            "| γc | 1 | [R05] Table 7.9 | |",
        )
        .replace(
            "| TODO | unknown | — | unknown |",
            "| route selection | [R05] §4.2.5, eq. 4.3 | x | as written |",
        )
    )
    errs, warns, n = verify_text(vsheet, {"R05": paper})
    expect(
        "verify: a value in its table passes", not any("ceiling" in e or "decay" in e for e in errs)
    )
    expect(
        "verify: a value missing from the table fails",
        any("`F`" in e and ("not in that table" in e or "not on a row naming" in e) for e in errs),
    )
    small = vsheet.replace(
        "| F | 10 | [R05] Table 4.1 | |", "| pheromone sensitivity F | 1 | [R05] Table 4.1 | |"
    )
    errs2, _, _ = verify_text(small, {"R05": paper})
    expect(
        "verify: a small number on another row's line fails",
        any("sensitivity" in e and "not on a row naming" in e for e in errs2),
    )
    expect(
        "verify: a missing locator fails", any("Table 7.9" in e and "not found" in e for e in errs)
    )
    expect(
        "verify: a section value and an equation label pass",
        not any("§ 4.2.5" in w for w in warns) and not any("eq." in w for w in warns),
    )
    expect("verify: the table of contents is not the body", n >= 6)
    dotted = "3. The Routing Algorithm\n3.1. Route Discovery Phase\nants\n4.1. Simulation Environment\n50 nodes\n"
    e3, _, _ = verify_text(
        skeleton("A", "G02", "G").replace(
            "| TODO | — | unknown | |", "| nodes | 50 | [G02] §4.1 | |"
        ),
        {"G02": dotted},
    )
    expect("verify: headings written '4.1.' are found", e3 == [])
    probs, _ = check_text(vsheet)
    expect("verify fixture is itself a valid sheet", probs == [])

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
    v = sub.add_parser("verify")
    v.add_argument("file")
    v.add_argument("--text", action="append", required=True, metavar="KEY=PATH")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.cmd == "verify":
        texts = {}
        for kv in args.text:
            key, _, path = kv.partition("=")
            with open(path, encoding="utf-8", errors="replace") as fh:
                texts[key] = fh.read()
        with open(args.file, encoding="utf-8") as fh:
            errors, warns, checked = verify_text(fh.read(), texts)
        for e in errors:
            print(f"FAIL {e}")
        for w in warns:
            print(f"WARN {w}")
        print(
            f"fidelity verify: {checked} locator(s) checked; "
            f"{len(errors)} miss(es), {len(warns)} warning(s)"
        )
        return 1 if errors else 0
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
                    f"repo choice: {', '.join(summary['choices']) or 'none'}; "
                    f"open (sourced, status unknown): {', '.join(summary['open']) or 'none'}"
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
