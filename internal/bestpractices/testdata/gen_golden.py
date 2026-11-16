#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Write the golden files the Go port is compared with (#531's byte-identical rule).

Run from the repository root, at the commit the port starts from:

  python3 -I internal/bestpractices/testdata/gen_golden.py

It runs tools/bestpractices/bestpractices.py (the Python version) on the
fixture repositories in testdata/repos.json (the self-test's fixtures) and on
fake sites and GitHubs built from the self-test's cases, and writes, per
case, the inputs and what the Python printed: stdout, stderr, the exit code,
every file written, and every call made to the fakes. bestpractices_test.go
runs the Go port on the same inputs and compares byte for byte. Deleted with
the Python tool, once the workflow runs the Go one.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "..", "..", "tools", "bestpractices", "bestpractices.py")
spec = importlib.util.spec_from_file_location("bp", TOOL)
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

ORG = bp.ORG
TODAY = "2026-11-13"
GENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@example.org",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@example.org",
    GIT_AUTHOR_DATE="2026-11-01T00:00:00Z",
    GIT_COMMITTER_DATE="2026-11-01T00:00:00Z",
)

with open(os.path.join(HERE, "repos.json")) as fh:
    REPOS = json.load(fh)


def make(work, name):
    d = os.path.join(work, name)
    for rel, text in REPOS[name]["files"].items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        with open(os.path.join(d, rel), "w") as fh:
            fh.write(text)
    if REPOS[name].get("git"):
        for cmd in (
            ["git", "init", "-q", "-b", "main", d],
            ["git", "-C", d, "add", "-A"],
            ["git", "-C", d, "commit", "-q", "-m", "init"],
            ["git", "-C", d, "remote", "add", "origin", f"https://github.com/{ORG}/{name}.git"],
        ):
            subprocess.run(cmd, check=True, capture_output=True, env=GENV)
    return d


def run_main(argv, remote=None):
    out, err = io.StringIO(), io.StringIO()
    rc = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = bp.main(argv, remote=remote) or 0
        except SystemExit as e:
            if isinstance(e.code, str):
                err.write(e.code + "\n")
                rc = 1
            else:
                rc = e.code or 0
    return rc, out.getvalue(), err.getvalue()


def answers_cases(work):
    cases = []
    specs = [
        ("proto", "Proto", ["--today", TODAY]),
        ("proto-old", "Proto", ["--today", "2028-01-01"]),
        ("tools", "Tools", ["--slug", f"{ORG}/Tools", "--today", TODAY]),
        ("tools-no-slug", "Tools", ["--today", TODAY]),
        ("tools-outside", "Tools", ["--slug", "someone/Tools", "--today", TODAY]),
        ("crypt", "Crypt", ["--slug", f"{ORG}/Crypt", "--today", TODAY]),
        ("hm", "Hm", ["--slug", f"{ORG}/Hm", "--today", TODAY]),
        ("cc", "Cc", ["--slug", f"{ORG}/Cc", "--today", TODAY]),
        ("tidy", "Tidy", ["--slug", f"{ORG}/Tidy", "--today", TODAY]),
        ("opt", "Opt", ["--slug", f"{ORG}/Opt", "--today", TODAY]),
        ("over", "Over", ["--slug", f"{ORG}/Over", "--today", TODAY]),
        ("proto-write", "Proto", ["--write", "--today", TODAY]),
    ]
    for case, repo, extra in specs:
        w = tempfile.mkdtemp(dir=work)
        d = make(w, repo)
        rc, out, err = run_main(["answers", d] + extra)
        written = None
        if "--write" in extra:
            with open(os.path.join(d, bp.OUT)) as fh:
                written = fh.read()
        cases.append(
            {
                "name": case,
                "repo": repo,
                "args": extra,
                "rc": rc,
                "stdout": out.replace(w, "$WORK"),
                "stderr": err.replace(w, "$WORK"),
                "written": written,
            }
        )
    return cases


class Lookup:
    def __init__(self, hits):
        self.hits, self.asked = hits, []

    def search(self, url):
        self.asked.append(url)
        return self.hits


HITS = [
    {"id": 16656, "repo_url": f"https://github.com/{ORG}/Proto", "badge_level": "in_progress"},
    {"id": 99, "repo_url": "https://github.com/someone/else"},
]


def register_cases(work):
    fixture = os.path.join(HERE, "anthocnet-answers.json")
    cases = []
    specs = [
        ("not-registered", [], "Proto", None, False),
        ("no-checkout", HITS, None, None, False),
        ("checkout", HITS, "Proto", None, False),
        ("answers-file", HITS, "Proto", fixture, False),
        ("checkout-json", HITS, "Proto", None, True),
    ]
    for case, hits, repo, answers_file, written in specs:
        w = tempfile.mkdtemp(dir=work)
        d = make(w, repo) if repo else "/nonexistent"
        if written:
            run_main(["answers", d, "--write", "--today", TODAY])
        argv = ["register", f"{ORG}/Proto", "--dir", d, "--today", TODAY]
        if answers_file:
            argv += ["--answers", "$FIXTURE"]
        lookup = Lookup(hits)
        rc, out, err = run_main([a.replace("$FIXTURE", fixture) for a in argv], remote=lookup)
        cases.append(
            {
                "name": case,
                "repo": repo,
                "hits": hits,
                "answers_file": bool(answers_file),
                "write_first": written,
                "rc": rc,
                "stdout": out.replace(w, "$WORK"),
                "stderr": err.replace(w, "$WORK"),
                "asked": lookup.asked,
            }
        )
    # proposal links alone, at two limits
    ans = bp.load_answers(fixture)
    for limit in (bp.PROPOSAL_LIMIT, 3000):
        cases.append(
            {
                "name": f"proposal-{limit}",
                "limit": limit,
                "urls": bp.proposal_urls("16656", ans, limit=limit),
            }
        )
    return cases


class Fake:
    """The self-test's fake site and GitHub, built from a JSON world."""

    def __init__(self, world):
        self.world = world
        self.sites = world["sites"]
        self.files = {(r, p): t for r, p, t in world["files"]}
        self.issues = world.get("issues", {})
        self.registry = world.get("registry", {})
        self.down = set(world.get("down", []))
        self.fail_writes = world.get("fail_writes", False)
        self.calls, self.searched = [], []

    def site(self, project):
        if project not in self.sites:
            raise urllib.error.URLError("404")
        return self.sites[project]

    def file(self, repo, path):
        return self.files.get((repo, path))

    def tree(self, repo):
        return set(self.world["tree"])

    def search(self, url):
        self.searched.append(url)
        if url in self.down:
            raise urllib.error.URLError("timed out")
        return self.registry.get(url, [])

    def repos(self):
        return self.world["repos"]

    def api(self, method, path, body=None, paginate=False):
        self.calls.append([method, path, body, paginate])
        if method != "GET" and self.fail_writes:
            raise bp.Failure(f"gh api {method} {path}: HTTP 502")
        if method == "GET":
            return self.issues.get(path.split("/")[2], [])
        if method == "POST" and path.endswith("/issues"):
            return {"number": 9}
        return {}


def check_cases(work):
    w = tempfile.mkdtemp(dir=work)
    full = make(w, "Proto")
    ans = bp.answers(full, today=TODAY)
    text = bp.to_json(ans)
    proposed = json.loads(text)
    tree = sorted(set(bp.files_of(full)) | {"docs"})

    def site_entry(repo, **over):
        d = {
            "repo_url": f"https://github.com/{ORG}/{repo}",
            "badge_level": "passing",
            "badge_percentage_0": 100,
            "achieved_passing_at": "2026-11-01T00:00:00Z",
        }
        d.update(proposed)
        d.update(over)
        return d

    drifting = site_entry(
        "Proto",
        build_status="Unmet",
        contribution_justification=f"See https://github.com/{ORG}/Proto/blob/main/GONE.md.",
        documentation_basics_justification=f"https://github.com/{ORG}/Proto/tree/main/docs and "
        f"https://github.com/{ORG}/other/blob/main/X.md",
        lost_passing_at="2026-11-10T00:00:00Z",
        maintained_status="?",
    )
    clean = site_entry(
        "Clean",
        contribution_justification=f"https://github.com/{ORG}/Clean/blob/main/CONTRIBUTING.md.",
    )
    files = [
        ["Proto", bp.CONFIG, 'bestpractices_project = "42"\n'],
        ["Proto", bp.OUT, text],
        ["Clean", bp.CONFIG, 'bestpractices_project = "7"\n'],
        ["Clean", bp.OUT, text],
        ["Plain", bp.CONFIG, 'kind = "protocol"\n'],
    ]
    base = {"tree": tree, "repos": ["Proto", "Clean", "Plain"], "files": files}
    plain_hit = [{"id": 8, "repo_url": f"https://github.com/{ORG}/Plain"}]
    items = bp.findings("Proto", drifting, proposed, set(tree))[1]
    same = {
        "number": 3,
        "title": bp.title_for(items),
        "body": bp.body_for("Proto", "42", items, ""),
    }
    run_env = {
        "GITHUB_RUN_ID": "123",
        "GITHUB_REPOSITORY": "swarm-routing/.github",
        "GITHUB_SERVER_URL": "https://github.com",
    }
    specs = [
        # name, world overrides, issues, token, repos, dry, env
        ("drift", {"sites": {"42": drifting, "7": clean}}, False, None, "", False, {}),
        (
            "registered-no-key",
            {
                "sites": {"42": drifting, "7": clean, "8": site_entry("Plain")},
                "registry": {f"https://github.com/{ORG}/Plain": plain_hit},
            },
            False,
            None,
            "",
            False,
            {},
        ),  # fmt: skip
        (
            "named-no-key",
            {
                "sites": {"8": site_entry("Plain")},
                "registry": {
                    f"https://github.com/{ORG}/Plain": [
                        {"id": 8, "repo_url": f"https://github.com/{ORG}/Plain/"}
                    ]
                },
            },
            False,
            None,
            "Plain",
            False,
            {},
        ),  # fmt: skip
        ("name-id", {"sites": {"42": drifting}}, False, None, "Proto=42", False, {}),
        ("clean", {"sites": {"7": clean}}, False, None, "Clean", False, {}),
        ("other-repo", {"sites": {"5": drifting}}, False, None, "Clean=5", False, {}),
        ("unreadable", {"sites": {}}, False, None, "Clean", False, {}),
        ("named-unregistered", {"sites": {}}, False, None, "Plain", False, {}),
        (
            "no-json-on-main",
            {
                "sites": {"7": clean},
                "files": [["Clean", bp.CONFIG, 'bestpractices_project = "7"\n']],
            },
            False,
            None,
            "Clean",
            False,
            {},
        ),  # fmt: skip
        (
            "lookup-down",
            {"sites": {"42": drifting, "7": clean}, "down": [f"https://github.com/{ORG}/Plain"]},
            False,
            None,
            "",
            False,
            {},
        ),  # fmt: skip
        (
            "json-not-object",
            {
                "sites": {"42": drifting, "7": clean},
                "files": [f for f in files if f[:2] != ["Proto", bp.OUT]]
                + [["Proto", bp.OUT, "[]"]],
            },
            False,
            None,
            "",
            False,
            {},
        ),  # fmt: skip
        ("site-not-object", {"sites": {"42": [], "7": clean}}, False, None, "", False, {}),
        (
            "issue-write-fails",
            {"sites": {"42": drifting, "7": clean}, "fail_writes": True},
            True,
            "t",
            "",
            False,
            {},
        ),  # fmt: skip
        ("issues-no-token", {"sites": {"42": drifting, "7": clean}}, True, None, "", False, {}),
        ("issues-dry-run", {"sites": {"42": drifting, "7": clean}}, True, "t", "", True, {}),
        ("issues-open", {"sites": {"42": drifting, "7": clean}}, True, "t", "", False, {}),
        ("issues-open-run", {"sites": {"42": drifting, "7": clean}}, True, "t", "", False, run_env),
        (
            "issues-unchanged",
            {"sites": {"42": drifting}, "issues": {"Proto": [same]}},
            True,
            "t",
            "Proto",
            False,
            {},
        ),  # fmt: skip
        (
            "issues-update",
            {
                "sites": {"42": drifting},
                "issues": {
                    "Proto": [dict(same, title=f"{bp.PREFIX} 1 finding(s)", body="- [ ] old")]
                },
            },
            True,
            "t",
            "Proto",
            False,
            {},
        ),  # fmt: skip
        (
            "issues-close",
            {"sites": {"7": clean}, "issues": {"Clean": [dict(same, number=4)]}},
            True,
            "t",
            "Clean",
            False,
            run_env,
        ),  # fmt: skip
        (
            "issues-close-dry",
            {"sites": {"7": clean}, "issues": {"Clean": [dict(same, number=4)]}},
            True,
            "t",
            "Clean",
            True,
            {},
        ),  # fmt: skip
        ("nothing-configured", {"sites": {}, "repos": ["Plain"]}, False, None, "", False, {}),
    ]
    cases = []
    for name, over, issues, token, repos, dry, env in specs:
        world = dict(base, **over)
        fake = Fake(world)
        saved = {k: os.environ.pop(k, None) for k in ("BESTPRACTICES_TOKEN", *run_env)}
        os.environ.update(env)
        if token:
            os.environ["BESTPRACTICES_TOKEN"] = token
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = bp.check(
                    type("A", (), {"repos": repos, "issues": issues, "dry_run": dry})(),
                    remote=fake,
                    gh=fake,
                )
        finally:
            for k in ("BESTPRACTICES_TOKEN", *run_env):
                os.environ.pop(k, None)
                if saved[k] is not None:
                    os.environ[k] = saved[k]
        cases.append(
            {
                "name": name,
                "world": world,
                "issues": issues,
                "token": token or "",
                "repos": repos,
                "dry_run": dry,
                "env": env,
                "rc": rc,
                "stdout": out.getvalue(),
                "calls": fake.calls,
                "searched": fake.searched,
            }
        )
    return cases


def main():
    work = tempfile.mkdtemp(prefix="bestpractices-golden-")
    try:
        for name, cases in (
            ("answers", answers_cases(work)),
            ("register", register_cases(work)),
            ("check", check_cases(work)),
        ):
            path = os.path.join(HERE, "golden", f"{name}.json")
            with open(path, "w") as fh:
                json.dump(cases, fh, indent=1, sort_keys=True, ensure_ascii=False)
                fh.write("\n")
            print(f"wrote {path}: {len(cases)} case(s)")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
