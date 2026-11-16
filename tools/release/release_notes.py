#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A release's notes: never empty, and re-rendered from CHANGELOG.md (swarm-routing/.github#524).

    release_notes.py notes --rendered FILE --changelog FILE --tag vX.Y.Z --out FILE [--require-body]
    release_notes.py rerender --release-json FILE --changelog FILE --tag vX.Y.Z --out FILE
    release_notes.py --self-test

The notes of a release are the version's section of CHANGELOG.md: its
`## vX.Y.Z ...` heading and everything up to the next `## ` heading. A
section is empty when nothing but blank lines follows its heading, which is
what Commitizen writes for a release with no `feat` or `fix` commit (a docs or
lock-bump release, swarm-routing/BeeAdHoc v0.2.1).

`notes` (reusable-release.yml's build job): the notes are FILE (Commitizen's
rendering in a bump or dry run, the merged commit's CHANGELOG.md section in a
release) unless it has no body; then the version's section of --changelog.
Prints `notes: rendered`, `notes: changelog` or `notes: empty` and writes the
chosen notes (the heading alone when both are empty) to --out. With
--require-body, empty notes exit 1, so a release fails before anything is
tagged or published.

`rerender` (reusable-release.yml's mode `release-notes`): the body of an
existing release (a `GET /repos/{repo}/releases/tags/{tag}` response) gets the
version's section of --changelog in place of everything above its
`## Verify your download` heading; that heading and everything after it are
kept byte for byte. Writes `{"body": ...}` (the PATCH payload) to --out and
prints `changed` or `unchanged`. Exits 1 when the section is empty or
missing, or the body has no verify block.

Stdlib only; exit 2 on a usage or read error.
"""

import argparse
import json
import os
import sys
import tempfile

VERIFY = "## Verify your download"


def section(text, tag):
    """The version's section, heading included, as reusable-release.yml's awk cut it; '' if none."""
    out, on = [], False
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if not on:
            if bare == f"## {tag}" or bare.startswith(f"## {tag} "):
                on = True
                out.append(line)
            continue
        if bare.startswith("## "):
            break
        out.append(line)
    return "".join(out)


def has_body(sec):
    """True when the section holds anything but its heading and blank lines."""
    return any(ln.strip() for ln in sec.splitlines()[1:])


def notes(rendered, changelog, tag):
    """(source, text): the rendered notes, else the changelog's section, else the heading alone."""
    if has_body(rendered):
        return "rendered", rendered
    sec = section(changelog, tag)
    if has_body(sec):
        return "changelog", sec
    heading = (rendered.splitlines() or sec.splitlines() or [f"## {tag}"])[0]
    return "empty", heading + "\n"


def rerender(body, changelog, tag):
    """The new release body: the section above the verify block, the block byte for byte."""
    sec = section(changelog, tag)
    if not has_body(sec):
        raise ValueError(f"CHANGELOG.md has no paragraph under '## {tag}'")
    if body.startswith(VERIFY + "\n") or body.startswith(VERIFY + "\r\n"):
        cut = 0
    else:
        cut = body.find("\n" + VERIFY + "\n")
        if cut < 0:
            cut = body.find("\n" + VERIFY + "\r\n")
        if cut < 0:
            raise ValueError(f"the release body has no '{VERIFY}' block")
        cut += 1
    tail = body[cut:]
    # The publish job's layout: the section as cut, an empty line, the verify block.
    return (sec if sec.endswith("\n") else sec + "\n") + "\n" + tail


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def self_test():
    fails = []

    def expect(what, cond):
        print(("ok   " if cond else "FAIL ") + what)
        if not cond:
            fails.append(what)

    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture-notes")
    docs_only = read(os.path.join(here, "CHANGELOG.docs-only.md"))  # Commitizen's bump, as written
    written = read(os.path.join(here, "CHANGELOG.md"))  # the same, with the paragraph
    rel = json.loads(read(os.path.join(here, "release-v0.2.1.json")))
    body = rel["body"]
    tail = body[body.index(VERIFY) :]

    # notes: a docs-only release
    rendered = "## v0.2.1 (2026-11-16)\n\n"  # cz bump --changelog-to-stdout, no feat/fix
    expect("an empty section has no body", not has_body(section(docs_only, "v0.2.1")))
    expect("a feat section has a body", has_body(section(docs_only, "v0.2.0")))
    src, text = notes(rendered, written, "v0.2.1")
    expect(
        "docs-only: the notes come from CHANGELOG.md",
        src == "changelog"
        and text.startswith("## v0.2.1 (2026-11-16)\n\nA patch release")
        and "## v0.2.0" not in text,
    )
    src, text = notes(rendered, docs_only, "v0.2.1")
    expect(
        "docs-only, CHANGELOG.md empty too: empty, the heading alone",
        src == "empty" and text == "## v0.2.1 (2026-11-16)\n",
    )
    src, text = notes(section(docs_only, "v0.2.0"), docs_only, "v0.2.0")
    expect("a feat release keeps its rendered notes", src == "rendered" and "### Feat" in text)
    expect("v0.2.1 is not v0.2.10", section("## v0.2.10 (x)\n\nother\n", "v0.2.1") == "")

    # rerender: BeeAdHoc v0.2.1's published body
    new = rerender(body, written, "v0.2.1")
    expect(
        "rerender: the paragraph above the verify block",
        new.startswith("## v0.2.1 (2026-11-16)\n\nA patch release"),
    )
    expect(
        "rerender: the verify block byte for byte",
        new[new.index(VERIFY) :] == tail and new.endswith(tail),
    )
    expect(
        "rerender: the publish job's layout (section, empty line, block)",
        new == section(written, "v0.2.1") + "\n" + tail,
    )
    expect("rerender: idempotent", rerender(new, written, "v0.2.1") == new)
    expect("rerender: the old empty heading is gone", new.count("## v0.2.1") == 1)
    for what, args in (
        ("an empty section refuses", (body, docs_only, "v0.2.1")),
        ("no section refuses", (body, written, "v9.9.9")),
        ("no verify block refuses", ("## v0.2.1\n\nx\n", written, "v0.2.1")),
    ):
        try:
            rerender(*args)
            expect(f"rerender: {what}", False)
        except ValueError:
            expect(f"rerender: {what}", True)

    # the command line, as the workflow calls it
    with tempfile.TemporaryDirectory() as d:
        r, out = os.path.join(d, "changes.md"), os.path.join(d, "out")
        write(r, rendered)
        cl = os.path.join(here, "CHANGELOG.docs-only.md")
        expect(
            "cli notes --require-body: empty exits 1",
            main(
                [
                    "notes",
                    "--rendered",
                    r,
                    "--changelog",
                    cl,
                    "--tag",
                    "v0.2.1",
                    "--out",
                    out,
                    "--require-body",
                ]
            )
            == 1,
        )
        expect(
            "cli notes: empty without --require-body exits 0",
            main(["notes", "--rendered", r, "--changelog", cl, "--tag", "v0.2.1", "--out", out])
            == 0,
        )
        cl = os.path.join(here, "CHANGELOG.md")
        expect(
            "cli notes --require-body: from CHANGELOG.md, exit 0",
            main(
                [
                    "notes",
                    "--rendered",
                    r,
                    "--changelog",
                    cl,
                    "--tag",
                    "v0.2.1",
                    "--out",
                    out,
                    "--require-body",
                ]
            )
            == 0
            and read(out) == section(written, "v0.2.1"),
        )
        rj = os.path.join(here, "release-v0.2.1.json")
        expect(
            "cli rerender: the PATCH payload",
            main(
                [
                    "rerender",
                    "--release-json",
                    rj,
                    "--changelog",
                    cl,
                    "--tag",
                    "v0.2.1",
                    "--out",
                    out,
                ]
            )
            == 0
            and json.loads(read(out)) == {"body": new},
        )
    if fails:
        print(f"{len(fails)} failed")
        sys.exit(1)
    print("all passed")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--self-test"]:
        self_test()
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("notes", help="the build job's notes: rendered, else CHANGELOG.md's section")
    p.add_argument("--rendered", required=True)
    p.add_argument("--changelog", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--require-body", action="store_true", help="empty notes exit 1")
    p = sub.add_parser("rerender", help="an existing release's body from CHANGELOG.md")
    p.add_argument("--release-json", required=True)
    p.add_argument("--changelog", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        changelog = read(a.changelog) if os.path.exists(a.changelog) else ""
        if a.cmd == "notes":
            src, text = notes(read(a.rendered), changelog, a.tag)
            write(a.out, text)
            print(f"notes: {src}")
            if src == "empty" and a.require_body:
                print(
                    f"release_notes: no paragraph for {a.tag}: the rendered notes and CHANGELOG.md's section are empty",
                    file=sys.stderr,
                )
                return 1
            return 0
        body = json.loads(read(a.release_json))["body"] or ""
        try:
            new = rerender(body, changelog, a.tag)
        except ValueError as e:
            print(f"release_notes: {e}", file=sys.stderr)
            return 1
        write(a.out, json.dumps({"body": new}))
        print("unchanged" if new == body else "changed")
        return 0
    except (OSError, KeyError, json.JSONDecodeError) as e:
        print(f"release_notes: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
