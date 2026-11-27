#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""An org status snapshot for coordinators: one line per fact, from the sources.

Usage:
  status.py [--repos A,B] [--json]
  status.py --self-test

Read-only. For each repository of tools/pr-status/pr_status.py's
DEFAULT_REPOS, the org's public repositories as this checkout lists them (or
only --repos), it prints:

  REPO release TAG commit SHA doi DOI       the latest GitHub release, the commit
                                            its tag names, and the version's
                                            Zenodo DOI (or why there is none)
  REPO release none                         no release yet
  REPO scope release:vX.Y.Z open N [next]   open issues per release label; `next`
                                            marks the lowest version above the
                                            latest release
  REPO p1 #N TITLE                          each open priority:P1 issue
  REPO security #N TITLE                    each open `[security]` alert ticket
  REPO handoff #N TITLE                     each open `handoff` issue

and then, from swarm-routing/.github's newest open `[maintainer]` issue:

  .github maintainer #N TITLE
  .github maintainer #N item: TEXT          each unticked checkbox

The DOI is read from Zenodo with tools/zenodo/zenodo.py's code (its
opt-out, its concept lookup, the concept's versions), never typed: a
repository with `zenodo = false` says `doi -: opted out`, one with no concept
`doi none: no concept`, a tag Zenodo has not archived `doi none: not
archived`. A Zenodo error is reported on the line (`doi ?: ...`) and the
snapshot goes on. Only `repos/{owner}/{repo}/...` endpoints are called, never
`orgs/...`: a cloud session refuses the org-wide API ("sessions are bound to
their configured repositories", HTTP 403; #1005), so the list comes from the
checkout, not from GitHub. A repository GitHub will not show (a 403) is one
`REPO error ...` line, the rest is still read, and the exit code is 1. The
checkboxes are read with
tools/issues/criteria.py's parser. `--json` prints the same facts as one JSON
document. GitHub is read through `gh api` (the caller's login, or GH_TOKEN);
Zenodo's public API needs no token. Stdlib only.

The facts were carried from memory before (swarm-routing/.github#1008, epic
#1005): three "pending" items given to the maintainer were already done.
"""

import argparse
import json
import os
import re
import sys

ORG = "swarm-routing"
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _d in ("zenodo", "issues", "pr-status"):
    sys.path.insert(0, os.path.join(TOOLS, _d))
import criteria  # noqa: E402
import zenodo  # noqa: E402
from pr_status import DEFAULT_REPOS  # noqa: E402

RELEASE_LABEL = re.compile(r"^release:(v\d+\.\d+\.\d+)$")
MAINTAINER_REPO = ".github"


def open_issues(gh, repo):
    return [i for i in gh.paged(f"repos/{ORG}/{repo}/issues?state=open") if "pull_request" not in i]


def labels(issue):
    return {lab["name"] for lab in issue.get("labels", [])}


def doi_of(gh, zen, repo, tag):
    """(doi or None, why) for the tag's Zenodo version, through zenodo.py."""
    full = f"{ORG}/{repo}"
    try:
        if zenodo.opted_out(gh, full):
            return None, "opted out"
        concept, _ = zenodo.recorded_concept(gh, full)
        if not concept:
            return None, "no concept"
        versions, _ = zen.versions(concept)
    except zenodo.Failure as e:
        return None, f"error: {e}"
    for v in versions:
        if zenodo.norm(v["version"]) == zenodo.norm(tag) and v["doi"]:
            return v["doi"], f"concept {concept}"
    return None, f"not archived (concept {concept})"


def release_of(gh, zen, repo):
    rel = gh.run(f"repos/{ORG}/{repo}/releases/latest")
    if not rel:
        return None
    tag = rel["tag_name"]
    commit = gh.run(f"repos/{ORG}/{repo}/commits/{tag}") or {}
    doi, why = doi_of(gh, zen, repo, tag)
    return {
        "tag": tag,
        "published": rel.get("published_at"),
        "commit": commit.get("sha"),
        "doi": doi,
        "doi_note": why,
    }


def scope_of(issues, latest):
    """{label: open count} per release label, and the next version's label."""
    counts = {}
    for i in issues:
        for lab in labels(i):
            if RELEASE_LABEL.match(lab):
                counts[lab] = counts.get(lab, 0) + 1
    base = zenodo.semver(latest) if latest else (-1, -1, -1)
    above = [lab for lab in counts if zenodo.semver(lab.split(":", 1)[1]) > base]
    nxt = min(above, key=lambda lab: zenodo.semver(lab.split(":", 1)[1])) if above else None
    ordered = sorted(counts, key=lambda lab: zenodo.semver(lab.split(":", 1)[1]))
    return [{"label": lab, "open": counts[lab], "next": lab == nxt} for lab in ordered]


def brief(issue):
    return {"number": issue["number"], "title": issue["title"]}


def repo_facts(gh, zen, repo, issues):
    rel = release_of(gh, zen, repo)
    by_num = sorted(issues, key=lambda i: i["number"])
    return {
        "repo": repo,
        "release": rel,
        "scope": scope_of(issues, rel["tag"] if rel else None),
        "p1": [brief(i) for i in by_num if "priority:P1" in labels(i)],
        "security": [brief(i) for i in by_num if i["title"].startswith("[security]")],
        "handoff": [brief(i) for i in by_num if "handoff" in labels(i)],
    }


def maintainer_of(issues):
    m = [i for i in issues if i["title"].startswith("[maintainer]")]
    if not m:
        return None
    i = max(m, key=lambda i: (i.get("created_at") or "", i["number"]))
    items = [t for _, done, t in criteria.boxes(i.get("body")) if not done]
    return dict(brief(i), unticked=items)


def snapshot(gh, zen, repos=None):
    names = repos or sorted(DEFAULT_REPOS)
    out, cache = {"repos": [], "maintainer": None}, {}
    for r in names:
        try:
            cache[r] = open_issues(gh, r)
            out["repos"].append(repo_facts(gh, zen, r, cache[r]))
        except zenodo.Failure as e:  # this repository unreadable (a 403): say so, go on
            out["repos"].append({"repo": r, "error": str(e)})
    try:
        if MAINTAINER_REPO not in cache:
            cache[MAINTAINER_REPO] = open_issues(gh, MAINTAINER_REPO)
        out["maintainer"] = maintainer_of(cache[MAINTAINER_REPO])
    except zenodo.Failure as e:
        out["maintainer"] = {"error": str(e)}
    return out


def failed(snap):
    return any("error" in f for f in snap["repos"]) or "error" in (snap["maintainer"] or {})


def lines(snap):
    out = []
    for f in snap["repos"]:
        if "error" in f:
            out.append(f"{f['repo']} error {f['error']}")
            continue
        r, rel = f["repo"], f["release"]
        if rel is None:
            out.append(f"{r} release none")
        else:
            sha = (rel["commit"] or "?")[:12]
            if rel["doi"]:
                doi = f"doi {rel['doi']}"
            elif rel["doi_note"] == "opted out":
                doi = "doi -: opted out"
            elif rel["doi_note"].startswith("error"):
                doi = f"doi ?: {rel['doi_note']}"
            else:
                doi = f"doi none: {rel['doi_note']}"
            out.append(f"{r} release {rel['tag']} commit {sha} {doi}")
        for s in f["scope"]:
            out.append(f"{r} scope {s['label']} open {s['open']}" + (" next" if s["next"] else ""))
        for kind in ("p1", "security", "handoff"):
            out += [f"{r} {kind} #{i['number']} {i['title']}" for i in f[kind]]
    m = snap["maintainer"]
    if m is None:
        out.append(f"{MAINTAINER_REPO} maintainer none")
    elif "error" in m:
        out.append(f"{MAINTAINER_REPO} maintainer error {m['error']}")
    else:
        out.append(f"{MAINTAINER_REPO} maintainer #{m['number']} {m['title']}")
        out += [f"{MAINTAINER_REPO} maintainer #{m['number']} item: {t}" for t in m["unticked"]]
    return out


# --- self-test --------------------------------------------------------------


def _issue(n, title, labs=(), body="", created="2026-11-20T00:00:00Z"):
    return {
        "number": n,
        "title": title,
        "labels": [{"name": x} for x in labs],
        "body": body,
        "created_at": created,
    }


class FakeGitHub(zenodo.GitHub):
    """zenodo.GitHub with its one read (`run`) answered from a dict."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def run(self, path, raw=False):
        self.calls.append(path)
        p = path.split("?")[0]
        if p.startswith("orgs/"):  # a cloud session refuses the org-wide API
            raise zenodo.Failure(
                f"gh api {path}: sessions are bound to their configured repositories (HTTP 403)"
            )
        if p.startswith(f"repos/{ORG}/secret/"):
            raise zenodo.Failure(f"gh api {path}: not enabled for this session (HTTP 403)")
        if p.endswith("/issues"):
            page = int(re.search(r"[?&]page=(\d+)", path).group(1))
            return self.routes.get(p, [])[(page - 1) * 100 : page * 100]
        return self.routes.get(p)


class FakeZenodo:
    def __init__(self, concepts):
        self.concepts = concepts

    def versions(self, concept):
        got = self.concepts.get(concept)
        if got is None:
            raise zenodo.Failure(f"zenodo: GET /records/{concept}: HTTP 503: down")
        return got, "x"


def _b64(text):
    import base64

    return {"content": base64.b64encode(text.encode()).decode()}


def self_test():
    fails = []

    def ok(cond, what):
        if not cond:
            fails.append(what)

    R = f"repos/{ORG}"
    routes = {
        # AntHocNet: archived on Zenodo, a release scope, a P1, a handoff
        f"{R}/AntHocNet/releases/latest": {"tag_name": "v2.7.0", "published_at": "2026-11-20"},
        f"{R}/AntHocNet/commits/v2.7.0": {"sha": "a" * 40},
        f"{R}/AntHocNet/contents/CITATION.cff": _b64("doi: 10.5281/zenodo.111\n"),
        f"{R}/AntHocNet/issues": [
            _issue(5, "next one", ["release:v2.8.0", "priority:P1"]),
            _issue(6, "later", ["release:v3.0.0"]),
            _issue(7, "next two", ["release:v2.8.0", "handoff"]),
            _issue(8, "shipped but open", ["release:v2.7.0"]),
            {"number": 9, "title": "a PR", "labels": [], "pull_request": {}},
        ],
        # skills: opted out of Zenodo
        f"{R}/skills/releases/latest": {"tag_name": "v1.0.0"},
        f"{R}/skills/commits/v1.0.0": {"sha": "b" * 40},
        f"{R}/skills/contents/.github/org-sync.toml": _b64("zenodo = false\n"),
        # ARA: a concept Zenodo cannot answer for, and a tag it lacks elsewhere
        f"{R}/ARA/releases/latest": {"tag_name": "v0.3.0"},
        f"{R}/ARA/commits/v0.3.0": {"sha": "c" * 40},
        f"{R}/ARA/contents/.github/org-sync.toml": _b64("zenodo_concept = 333\n"),
        # .github: alert tickets and two maintainer issues, the newest read
        f"{R}/.github/releases/latest": {"tag_name": "v0.9.0"},
        f"{R}/.github/commits/v0.9.0": {"sha": "d" * 40},
        f"{R}/.github/contents/CITATION.cff": _b64("doi: 10.5281/zenodo.444\n"),
        f"{R}/.github/issues": [
            _issue(762, "[security] Scorecard PinnedDependenciesID: 2 repositories"),
            _issue(900, "[maintainer] old list", body="- [ ] stale", created="2026-11-01T0"),
            _issue(
                1004,
                "[maintainer] actions only the maintainer can take",
                ["priority:P1"],
                "- [x] done\n- [ ] decide #1004 access\n```\n- [ ] fenced\n```\n",
                "2026-11-27T00:00:00Z",
            ),
        ],
    }
    zen = FakeZenodo(
        {
            "111": [
                {"version": "2.6.0", "doi": "10.5281/zenodo.110"},
                {"version": "v2.7.0", "doi": "10.5281/zenodo.112"},
            ],
            "444": [{"version": "v0.8.0", "doi": "10.5281/zenodo.445"}],
        }
    )
    gh = FakeGitHub(routes)
    snap = snapshot(gh, zen, [".github", "ARA", "AntHocNet", "new", "skills"])
    got = lines(snap)
    want = [
        ".github release v0.9.0 commit dddddddddddd doi none: not archived (concept 444)",
        ".github security #762 [security] Scorecard PinnedDependenciesID: 2 repositories",
        ".github p1 #1004 [maintainer] actions only the maintainer can take",
        "ARA release v0.3.0 commit cccccccccccc doi ?: error: zenodo: GET /records/333: "
        "HTTP 503: down",
        "AntHocNet release v2.7.0 commit aaaaaaaaaaaa doi 10.5281/zenodo.112",
        "AntHocNet scope release:v2.7.0 open 1",
        "AntHocNet scope release:v2.8.0 open 2 next",
        "AntHocNet scope release:v3.0.0 open 1",
        "AntHocNet p1 #5 next one",
        "AntHocNet handoff #7 next two",
        "new release none",
        "skills release v1.0.0 commit bbbbbbbbbbbb doi -: opted out",
        ".github maintainer #1004 [maintainer] actions only the maintainer can take",
        ".github maintainer #1004 item: decide #1004 access",
    ]
    for w in want:
        ok(w in got, f"missing line: {w}")
    ok(not any("fenced" in g or "stale" in g or "a PR" in g for g in got), "fence, old, PR")
    ok(len(got) == len(want), f"extra lines: {sorted(set(got) - set(want))}")
    # --repos: only those, and the maintainer issue still read from .github
    gh = FakeGitHub(routes)
    snap = snapshot(gh, zen, ["new"])
    got = lines(snap)
    ok(got[0] == "new release none" and got[-1].endswith("item: decide #1004 access"), "--repos")
    ok(not any(c.startswith(f"orgs/{ORG}/repos") for c in gh.calls), "--repos lists no org")
    doc = json.loads(json.dumps(snapshot(FakeGitHub(routes), zen, ["AntHocNet"])))
    a = doc["repos"][0]
    ok(
        a["release"]["commit"] == "a" * 40
        and a["release"]["doi"] == "10.5281/zenodo.112"
        and [s["label"] for s in a["scope"] if s["next"]] == ["release:v2.8.0"],
        f"json: {a}",
    )
    # a repository with no release: every release label is above it
    ok(
        [s["next"] for s in scope_of([_issue(1, "x", ["release:v0.1.0"])], None)] == [True],
        "first release is next",
    )
    ok(lines({"repos": [], "maintainer": None}) == [".github maintainer none"], "no maintainer")
    # an unreadable repository is one error line; the others are still read
    snap = snapshot(FakeGitHub(routes), zen, ["secret", "new"])
    got = lines(snap)
    ok(
        got[0].startswith("secret error gh api") and got[1] == "new release none" and failed(snap),
        f"a 403 repository: {got[:2]}",
    )
    ok(not failed(snapshot(FakeGitHub(routes), zen, ["new"])), "no error, exit 0")
    # no --repos: the checkout's list (DEFAULT_REPOS), only repository-scoped calls,
    # where a cloud session's 403 on orgs/... used to stop the snapshot (#1005)
    gh = FakeGitHub(routes)
    snap = snapshot(gh, zen)
    ok([f["repo"] for f in snap["repos"]] == sorted(DEFAULT_REPOS), "default: DEFAULT_REPOS")
    ok(all(c.startswith(f"repos/{ORG}/") for c in gh.calls), "default: repos/... calls only")
    ok(not failed(snap), "default: no error with orgs/ refused")
    if fails:
        for f in fails:
            print("FAIL:", f)
        return 1
    print("status.py self-test: ok")
    return 0


# --- main -------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--repos", help="comma-separated repository names (default: pr_status.py's DEFAULT_REPOS)"
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.self_test:
        return self_test()
    repos = [r.strip() for r in a.repos.split(",") if r.strip()] if a.repos else None
    for r in repos or []:
        if not re.fullmatch(r"[\w.-]+", r):
            raise SystemExit(f"{r}: a repository name, without the owner")
    zen = zenodo.Zenodo(zenodo.ZENODO[False], log=sys.stderr)
    snap = snapshot(zenodo.GitHub(), zen, repos)
    if a.json:
        print(json.dumps(snap, indent=2))
    else:
        print("\n".join(lines(snap)))
    return 1 if failed(snap) else 0


if __name__ == "__main__":
    sys.exit(main())
