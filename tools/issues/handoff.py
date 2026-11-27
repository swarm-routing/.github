#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A coordinator's state on its handoff issue, never in a local file.

Usage:
  handoff.py read REPO#N [--json]
  handoff.py append REPO#N [--status FILE] [--closed TEXT]... [--released TEXT]...
                     [--worker TEXT]... [--maintainer TEXT]... [--scheduled TEXT]...
                     [--at TIME] [--dry-run]
  handoff.py --self-test

REPO is a swarm-routing repository, bare (`.github#921`) or in full. The
issue must be open and labelled `handoff` (the Handoff form).

`append` writes one coordinator pass, in a fixed shape: the parts Closed,
Released, Running workers, Maintainer items and Scheduled, each a list (`none`
when empty). `--status FILE` is `tools/status/status.py --json`'s output (`-`:
stdin): each repository's latest release goes under Released
(`REPO TAG commit SHA12 doi DOI`) and the unticked boxes of the newest
`[maintainer]` issue under Maintainer items, after the ones given by hand. The
pass is posted as a comment headed `Coordinator pass <TIME>` (`--at`, default
now, UTC) and marked `<!-- coordinator-state -->`, and the issue body's
state section (`### State`, the Handoff form's, or `## Current state`) is
replaced by the same parts, up to the next heading of its level or above; a
body without one gets `### State` appended. Nothing else in the body changes.
Each item is one line (newlines folded to spaces). `--dry-run` prints the
requests (JSON) instead of sending them.

`read` prints the body's state section and the newest marked pass comment
(its time and link, then its text); `--json` as one document. A new session
starts from it instead of a local file (swarm-routing/.github#1009: the
coordinator's `ROADMAP_STATE.md` was lost with its container and re-posted
to #921 by hand).

GitHub is read through `gh api` (the caller's login, or GH_TOKEN), as
tools/issues/criteria.py does. Stdlib only.
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria  # noqa: E402

ORG = criteria.ORG
MARK = "<!-- coordinator-state -->"
PARTS = (
    ("closed", "Closed"),
    ("released", "Released"),
    ("worker", "Running workers"),
    ("maintainer", "Maintainer items"),
    ("scheduled", "Scheduled"),
)
STATE = re.compile(r"^(#{2,3})\s+(?:State|Current state)\s*$", re.I)
HEADING = re.compile(r"^(#{1,6})\s")
FENCE = criteria.FENCE


def one_line(text):
    return " ".join(str(text).split())


def from_status(snap):
    """(released, maintainer items) from status.py's --json snapshot."""
    released = []
    for f in snap.get("repos") or []:
        rel = f.get("release")
        if "error" in f or not rel:
            continue
        doi = rel.get("doi") or f"- ({rel.get('doi_note') or 'none'})"
        released.append(
            f"{f['repo']} {rel['tag']} commit {(rel.get('commit') or '?')[:12]} doi {doi}"
        )
    m = snap.get("maintainer") or {}
    items = [f"{ORG}/.github#{m['number']} {t}" for t in m.get("unticked") or []]
    return released, items


def parts_of(a, snap=None):
    got = {k: [one_line(t) for t in getattr(a, k) or [] if one_line(t)] for k, _ in PARTS}
    if snap is not None:
        released, items = from_status(snap)
        got["released"] += released
        got["maintainer"] += items
    return got


def render(parts):
    out = []
    for key, title in PARTS:
        out.append(f"**{title}**")
        out += [f"- {t}" for t in parts[key]] or ["- none"]
        out.append("")
    return "\n".join(out).rstrip("\n")


def state_span(lines):
    """(start, end) of the state section's content lines, or None."""
    fence = None
    for i, line in enumerate(lines):
        f = FENCE.match(line)
        if f:
            fence = f.group(1) if fence is None else (None if f.group(1) == fence else fence)
            continue
        m = None if fence else STATE.match(line)
        if m:
            level, j, fence2 = len(m.group(1)), i + 1, None
            while j < len(lines):
                f = FENCE.match(lines[j])
                if f:
                    fence2 = (
                        f.group(1) if fence2 is None else (None if f.group(1) == fence2 else fence2)
                    )
                h = None if fence2 else HEADING.match(lines[j])
                if h and len(h.group(1)) <= level:
                    break
                j += 1
            return i + 1, j
    return None


def with_state(body, text):
    lines = (body or "").split("\n")
    span = state_span(lines)
    if span is None:
        return (body or "").rstrip("\n") + "\n\n### State\n\n" + text + "\n"
    start, end = span
    tail = [""] if end < len(lines) else []
    return "\n".join(lines[:start] + ["", text] + tail + lines[end:])


def state_of(body):
    lines = (body or "").split("\n")
    span = state_span(lines)
    return None if span is None else "\n".join(lines[span[0] : span[1]]).strip()


def handoff_issue(repo, n):
    got = criteria.issue(repo, n)
    if got["state"] != "open":
        raise SystemExit(f"{repo}#{n} is {got['state']}: a pass goes on an open handoff issue")
    names = {(lab.get("name") if isinstance(lab, dict) else lab) for lab in got.get("labels") or []}
    if "handoff" not in names:
        raise SystemExit(f"{repo}#{n} has no `handoff` label: not a handoff issue")
    return got


def cmd_append(a):
    repo, n = criteria.parse_ref(a.ref)
    snap = None
    if a.status:
        if a.status == "-":
            snap = json.load(sys.stdin)
        else:
            with open(a.status, encoding="utf-8") as f:
                snap = json.load(f)
    parts = parts_of(a, snap)
    got = handoff_issue(repo, n)
    at = a.at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    text = render(parts)
    comment = f"{MARK}\n## Coordinator pass {one_line(at)}\n\n{text}{criteria.FOOTER}"
    path = f"repos/{ORG}/{repo}/issues/{n}"
    criteria.send(a.dry_run, "POST", f"{path}/comments", {"body": comment})
    body = with_state(got.get("body") or "", text)
    if body != (got.get("body") or ""):
        criteria.send(a.dry_run, "PATCH", path, {"body": body})
    counts = ", ".join(f"{k} {len(parts[k])}" for k, _ in PARTS)
    print(f"{repo}#{n}: pass {one_line(at)} appended ({counts})")
    return 0


def comments(repo, n):
    out, page = [], 1
    while True:
        got = criteria.gh_api(
            "GET", f"repos/{ORG}/{repo}/issues/{n}/comments?per_page=100&page={page}"
        )
        out += got or []
        if not got or len(got) < 100:
            return out
        page += 1


def cmd_read(a):
    repo, n = criteria.parse_ref(a.ref)
    got = criteria.issue(repo, n)
    passes = [c for c in comments(repo, n) if (c.get("body") or "").startswith(MARK)]
    last = passes[-1] if passes else None
    doc = {
        "repo": f"{ORG}/{repo}",
        "number": n,
        "title": got["title"],
        "state": state_of(got.get("body")),
        "passes": len(passes),
        "last": None
        if last is None
        else {
            "created_at": last.get("created_at"),
            "url": last.get("html_url"),
            "body": last["body"][len(MARK) :].replace(criteria.FOOTER, "").strip(),
        },
    }
    if a.json:
        print(json.dumps(doc, indent=2))
        return 0
    print(f"{repo}#{n} {got['title']}")
    print("state:" if doc["state"] is not None else "state: none")
    if doc["state"]:
        print(doc["state"])
    if last is None:
        print("last pass: none")
    else:
        print(f"last pass ({len(passes)} in all): {last.get('created_at')} {last.get('html_url')}")
        print(doc["last"]["body"])
    return 0


# --- self-test --------------------------------------------------------------

FORM_BODY = """### Goal

Ship v0.3.

### State

old notes
```
### State
```

### Next steps, in order

1. the rest
"""

SNAP = {
    "repos": [
        {
            "repo": "AntHocNet",
            "release": {
                "tag": "v0.2.0",
                "commit": "a" * 40,
                "doi": "10.5281/zenodo.1",
                "doi_note": "",
            },
        },
        {"repo": "skills", "release": None},
        {"repo": "secret", "error": "HTTP 403"},
        {
            "repo": "site",
            "release": {"tag": "v1.0.0", "commit": "b" * 40, "doi": None, "doi_note": "opted out"},
        },
    ],
    "maintainer": {"number": 568, "title": "[maintainer] x", "unticked": ["merge #9"]},
}


class Fake:
    def __init__(self):
        lab = [{"name": "handoff"}]
        self.issues = {
            921: {"number": 921, "title": "h", "state": "open", "body": FORM_BODY, "labels": lab},
            922: {"number": 922, "title": "bare", "state": "open", "body": "notes", "labels": lab},
            923: {"number": 923, "title": "no label", "state": "open", "body": "", "labels": []},
            924: {"number": 924, "title": "done", "state": "closed", "body": "", "labels": lab},
        }
        self.comments = {k: [] for k in self.issues}
        self.writes = []

    def __call__(self, method, path, body=None):
        m = re.fullmatch(rf"repos/{ORG}/\.github/issues/(\d+)(/comments)?(\?page=\d+|\?.*)?", path)
        if not m or int(m.group(1)) not in self.issues:
            raise criteria.GhError(path, "Not Found (HTTP 404)")
        n = int(m.group(1))
        if method != "GET":
            self.writes.append((method, path, body))
        if m.group(2):
            if method == "POST":
                c = {
                    "body": body["body"],
                    "created_at": f"2026-11-27T0{len(self.comments[n])}:00:00Z",
                    "html_url": f"https://github.com/{ORG}/.github/issues/{n}#c{len(self.comments[n])}",
                }
                self.comments[n].append(c)
                return c
            return [dict(c) for c in self.comments[n]]
        if method == "PATCH":
            self.issues[n].update(body)
        return dict(self.issues[n])


def self_test():
    fails = []

    def ok(cond, what):
        if not cond:
            fails.append(what)

    def run_(argv):
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = main(argv)
        except SystemExit as e:
            return "exit", str(e)
        return rc, out.getvalue()

    import contextlib
    import io

    real = criteria.gh_api
    fake = Fake()
    criteria.gh_api = fake
    try:
        released, items = from_status(SNAP)
        ok(
            released
            == [
                f"AntHocNet v0.2.0 commit {'a' * 12} doi 10.5281/zenodo.1",
                f"site v1.0.0 commit {'b' * 12} doi - (opted out)",
            ],
            f"from_status released: {released}",
        )
        ok(items == [f"{ORG}/.github#568 merge #9"], f"from_status items: {items}")

        status = os.path.join(
            os.environ.get("TMPDIR", "/tmp"), f"handoff-selftest-{os.getpid()}.json"
        )
        with open(status, "w", encoding="utf-8") as f:
            json.dump(SNAP, f)
        try:
            rc, out = run_(
                [
                    "append",
                    ".github#921",
                    "--status",
                    status,
                    "--closed",
                    "swarm-routing/.github#997 (PR #999)",
                    "--worker",
                    "skills: pr-shepherd\ntext",
                    "--at",
                    "2026-11-27T16:00Z",
                ]
            )
        finally:
            os.remove(status)
        ok(
            rc == 0 and "pass 2026-11-27T16:00Z appended (closed 1, released 2, worker 1" in out,
            f"append: {rc} {out}",
        )
        c = fake.comments[921][-1]["body"]
        ok(
            c.startswith(MARK + "\n## Coordinator pass 2026-11-27T16:00Z\n"),
            "comment: marker and heading",
        )
        ok("**Running workers**\n- skills: pr-shepherd text\n" in c, "comment: an item is one line")
        ok("**Scheduled**\n- none" in c, "comment: an empty part says none")
        ok(
            "**Maintainer items**\n- swarm-routing/.github#568 merge #9" in c,
            "comment: maintainer from status",
        )
        ok(c.endswith(criteria.FOOTER), "comment: footer")
        body = fake.issues[921]["body"]
        ok(
            "old notes" not in body and "**Closed**\n- swarm-routing/.github#997 (PR #999)" in body,
            "body: state replaced",
        )
        ok(
            body.startswith("### Goal\n\nShip v0.3.\n\n### State\n\n**Closed**"),
            "body: before kept",
        )
        ok(
            body.endswith("\n\n### Next steps, in order\n\n1. the rest\n"),
            f"body: after kept: {body!r}",
        )
        ok(
            body.count("### State") == 1,
            "body: a fenced heading inside the section is replaced with it",
        )
        ok([w[0] for w in fake.writes] == ["POST", "PATCH"], f"writes: {fake.writes}")

        # a second pass replaces the section again, and read shows the newest
        rc, out = run_(
            ["append", "swarm-routing/.github#921", "--scheduled", "16:30 re-check", "--at", "T2"]
        )
        body = fake.issues[921]["body"]
        ok(
            rc == 0 and body.count("**Closed**") == 1 and "- 16:30 re-check" in body,
            "second pass: one section",
        )
        ok("Next steps, in order" in body, "second pass: the rest kept")
        rc, out = run_(["read", ".github#921"])
        ok(rc == 0 and "last pass (2 in all): 2026-11-27T01:00:00Z" in out, f"read: newest: {out}")
        ok(
            "## Coordinator pass T2" in out and "Generated by" not in out,
            "read: the pass text, no footer",
        )
        rc, out = run_(["read", ".github#921", "--json"])
        doc = json.loads(out)
        ok(
            doc["passes"] == 2 and doc["state"].startswith("**Closed**\n- none"),
            f"read --json: {doc}",
        )
        fake.comments[921].append({"body": "a plain comment", "created_at": "z", "html_url": "u"})
        rc, out = run_(["read", ".github#921", "--json"])
        ok(json.loads(out)["passes"] == 2, "read: an unmarked comment is not a pass")

        # a body with no state section gets one appended
        rc, out = run_(["append", ".github#922", "--at", "T3"])
        ok(
            fake.issues[922]["body"].startswith("notes\n\n### State\n\n**Closed**\n- none"),
            "no section: appended",
        )
        rc, out = run_(["read", ".github#923"])
        ok(
            rc == 0 and "state: none" in out and "last pass: none" in out,
            f"read: nothing yet: {out}",
        )

        # refusals, before any write
        n = len(fake.writes)
        rc, out = run_(["append", ".github#923", "--at", "T"])
        ok(rc == "exit" and "no `handoff` label" in out, f"no label refused: {out}")
        rc, out = run_(["append", ".github#924", "--at", "T"])
        ok(rc == "exit" and "is closed" in out, f"closed refused: {out}")
        rc, out = run_(["append", "evil/x#1"])
        ok(rc == "exit" and "not a" in out, "another owner refused")
        ok(len(fake.writes) == n, "refusals write nothing")

        # --dry-run sends nothing
        rc, out = run_(["append", ".github#922", "--closed", "x", "--at", "T", "--dry-run"])
        ok(
            rc == 0 and len(fake.writes) == n and '"method": "POST"' in out,
            "dry run writes nothing",
        )
    finally:
        criteria.gh_api = real

    for f in fails:
        print(f"FAIL: {f}")
    print(f"handoff.py self-test: {'ok' if not fails else f'{len(fails)} failed'}")
    return 1 if fails else 0


# --- main -------------------------------------------------------------------


def parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("read")
    r.add_argument("ref")
    r.add_argument("--json", action="store_true")
    w = sub.add_parser("append")
    w.add_argument("ref")
    w.add_argument("--status", help="status.py --json output (`-`: stdin)")
    for key, title in PARTS:
        w.add_argument(f"--{key}", action="append", help=f"an item under {title}")
    w.add_argument("--at", help="the pass's time (default now, UTC)")
    w.add_argument("--dry-run", action="store_true")
    return ap


def main(argv=None):
    ap = parser()
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.self_test:
        return self_test()
    fn = {"read": cmd_read, "append": cmd_append}.get(a.cmd)
    if fn is None:
        ap.print_help()
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
