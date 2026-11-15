#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Before and after a release: is the repository ready to bump, and did everything follow?

    release_check.py ready REPO_DIR [--repo OWNER/NAME] [--version X.Y.Z]
    release_check.py after OWNER/NAME --tag vX.Y.Z [--org ORG] [--repos A,B]
    release_check.py --self-test

Read-only. It prints one line per check, `OK`, `WARN`, `FAIL` or `NEXT` (a
step that is a person's or another tool's), and exits 1 on a FAIL, so an
agent reads the verdict, not the workflow logs (AntHocNet ADR-0014).
CONTRIBUTING "Cutting a release" is the procedure; this checks its steps.

`ready` (before a dry-run or a bump), on a checkout of the repository:
  - the caller workflow uses reusable-release.yml (a repository with its own
    release workflow, as AntHocNet, is a WARN: these checks may not fit it);
  - the Commitizen config (`.cz.toml`, or `[tool.commitizen]` in
    `pyproject.toml`) exists, with `tag_format = "v$version"`;
  - `make dist` exists, unless the caller passes its own `build:`;
  - with --version, `docs/roadmap.md` has a row for vX.Y.Z (the ladder gate
    the workflow does not enforce yet, swarm-routing/.github#430); without a
    ladder, the org ROADMAP's release train applies (a WARN);
  - with --repo and --version, no open issue is labelled `release:vX.Y.Z`;
  - with --repo, an open `bot/release` PR behind `main` (dispatch `bump`
    again; never update or push that branch by hand).

`after` (once the bump PR merged), through `gh api` and public URLs:
  - the GitHub release of the tag is published with SHA256SUMS and the
    provenance (`*.intoto.jsonl`);
  - the site saw it: an `[release-sync] <name> <tag>` issue in
    swarm-routing/swarm-routing.github.io (CONTRIBUTING step 6);
  - every org repository that locks this one (a root `*.lock` whose
    `<PREFIX>_REPO` names it) locks the tag, or has org-bot's open
    `org-bot/*` bump PR; the candidates are the org's public repositories,
    or --repos (a token bound to some repositories cannot list the org);
  - each `vcpkg-ports` port the caller names has the version as its
    swarm-routing/vcpkg-registry baseline, or the open `bot/vcpkg-<name>` PR;
  - where the release workflow publishes to PyPI, PyPI has the version;
  - `docs/roadmap.md` on main marks the version shipped (WARN, #430);
  - NEXT: the Zenodo version DOI, read with `zenodo.py status` (never typed).

GitHub reads go through `gh api` (GH_TOKEN); PyPI through its JSON API.
Stdlib only, Python 3.11+ (tomllib).
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request

SITE = "swarm-routing/swarm-routing.github.io"
REGISTRY = "swarm-routing/vcpkg-registry"
REUSABLE = re.compile(r"uses:\s*swarm-routing/\.github/\.github/workflows/reusable-release\.yml@")
VCPKG_PORTS = re.compile(r"^\s*vcpkg-ports:\s*[\"']?([a-z0-9 -]+?)[\"']?\s*(?:#.*)?$", re.M)
BUILD_INPUT = re.compile(r"^\s+build:\s*\S", re.M)
DIST_TARGET = re.compile(r"^dist\s*:", re.M)
SHIPPED = re.compile(r"(?i)\b(shipped|released|done)\b")


class Gh:
    """GitHub reads through `gh api`; None for a 404."""

    def get(self, path):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if r.returncode:
            if "HTTP 404" in r.stderr:
                return None
            raise RuntimeError(f"gh api {path}: {r.stderr.strip()}")
        return json.loads(r.stdout or "null")

    def url(self, url):
        """The JSON at a public URL, or None for a 404."""
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise


class Report:
    def __init__(self):
        self.lines = []

    def add(self, level, msg):
        self.lines.append((level, msg))
        print(f"{level:<5} {msg}")

    def failed(self):
        return any(level == "FAIL" for level, _ in self.lines)


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def caller_workflows(texts):
    """[(name, text)] of the workflows that call reusable-release.yml."""
    return [(n, t) for n, t in texts if REUSABLE.search(t)]


def local_workflows(repo_dir):
    d = os.path.join(repo_dir, ".github", "workflows")
    out = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith((".yml", ".yaml")):
            out.append((n, read(os.path.join(d, n)) or ""))
    return out


def commitizen(repo_dir):
    """(file, table) of the Commitizen config, or (None, None)."""
    for name in (".cz.toml", "pyproject.toml"):
        text = read(os.path.join(repo_dir, name))
        if text is None:
            continue
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            return name, {"_error": str(e)}
        table = data.get("tool", {}).get("commitizen")
        if table is not None:
            return name, table
    return None, None


def ladder_row(text, tag):
    """The ladder lines that name the tag as a version (v0.4.0, not v0.4.0-rc or v0.4.01)."""
    pat = re.compile(r"(?<![\w.])" + re.escape(tag) + r"(?![\w.-]|\.\d)")
    return [ln for ln in text.splitlines() if pat.search(ln)]


def ready(repo_dir, repo, version, gh):
    r = Report()
    flows = local_workflows(repo_dir)
    callers = caller_workflows(flows)
    if callers:
        r.add("OK", "caller: " + ", ".join(f".github/workflows/{n}" for n, _ in callers))
    elif any(n == "release.yml" for n, _ in flows):
        r.add(
            "WARN",
            "caller: an own .github/workflows/release.yml, not reusable-release.yml; "
            "these checks follow the org workflow",
        )
    else:
        r.add(
            "FAIL",
            "caller: no workflow calls reusable-release.yml (copy the caller from its "
            "comment block)",
        )
    name, cz = commitizen(repo_dir)
    if cz is None:
        r.add("FAIL", "commitizen: no .cz.toml and no [tool.commitizen] in pyproject.toml")
    elif "_error" in cz:
        r.add("FAIL", f"commitizen: {name} does not parse: {cz['_error']}")
    elif cz.get("tag_format") != "v$version":
        r.add("FAIL", f"commitizen: {name} tag_format is {cz.get('tag_format')!r}, not 'v$version'")
    else:
        r.add(
            "OK",
            f"commitizen: {name}, version {cz.get('version', '?')}, "
            f"major_version_zero = {str(cz.get('major_version_zero', False)).lower()}",
        )
    has_build = any(BUILD_INPUT.search(t) for _, t in callers)
    if DIST_TARGET.search(read(os.path.join(repo_dir, "Makefile")) or ""):
        r.add("OK", "build: make dist")
    elif has_build:
        r.add("OK", "build: the caller's own build: input")
    else:
        r.add("FAIL", "build: no `dist:` target in the Makefile and no build: input in the caller")
    roadmap = read(os.path.join(repo_dir, "docs", "roadmap.md"))
    if roadmap is None:
        r.add("WARN", "ladder: no docs/roadmap.md; the org ROADMAP's release train is the scope")
    elif not version:
        r.add("WARN", "ladder: pass --version X.Y.Z (the dry-run's version) to check its row")
    elif ladder_row(roadmap, f"v{version}"):
        r.add("OK", f"ladder: docs/roadmap.md has v{version}")
    else:
        r.add(
            "FAIL",
            f"ladder: docs/roadmap.md has no row for v{version}; add the version and "
            "its exit criteria in a PR before the bump (swarm-routing/.github#430)",
        )
    if repo and version:
        label = f"release:v{version}"
        issues = gh.get(f"repos/{repo}/issues?state=open&per_page=100&labels={label}") or []
        issues = [i for i in issues if "pull_request" not in i]
        if issues:
            r.add(
                "FAIL",
                f"scope: {len(issues)} open issue(s) labelled {label}: "
                + ", ".join(f"#{i['number']}" for i in issues[:10]),
            )
        else:
            r.add("OK", f"scope: no open issue labelled {label}")
    if repo:
        owner = repo.split("/")[0]
        pulls = gh.get(f"repos/{repo}/pulls?state=open&head={owner}:bot/release") or []
        for p in pulls:
            cmp = gh.get(f"repos/{repo}/compare/{p['base']['ref']}...bot/release") or {}
            behind = cmp.get("behind_by", 0)
            if behind:
                r.add(
                    "WARN",
                    f"bump PR #{p['number']} is {behind} commit(s) behind "
                    f"{p['base']['ref']}: dispatch bump again (never push bot/release)",
                )
            else:
                r.add("OK", f"bump PR #{p['number']} {p['title']!r} is on {p['base']['ref']}")
    r.add(
        "NEXT",
        "dispatch the caller with mode dry-run, read the artifact (version, assets, "
        "SHA256SUMS, .intoto.jsonl), then mode bump, on the maintainer's request only",
    )
    return r


def contents_text(gh, repo, path, ref=None):
    q = f"?ref={ref}" if ref else ""
    data = gh.get(f"repos/{repo}/contents/{path}{q}")
    if not isinstance(data, dict) or "content" not in data:
        return None
    return base64.b64decode(data["content"]).decode("utf-8", "replace")


def lock_values(text):
    out = {}
    for ln in text.splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def after(repo, tag, org, gh, consumers=None):
    r = Report()
    owner, name = repo.split("/", 1)
    version = tag.lstrip("v")
    rel = gh.get(f"repos/{repo}/releases/tags/{tag}")
    if not rel or rel.get("draft"):
        r.add(
            "FAIL",
            f"release: no published GitHub release {tag}; read the release run "
            "(a failed publish: Re-run all jobs, never Re-run failed jobs)",
        )
    else:
        assets = [a["name"] for a in rel.get("assets", [])]
        missing = [
            m
            for m, ok in (
                ("SHA256SUMS", "SHA256SUMS" in assets),
                ("*.intoto.jsonl", any(a.endswith(".intoto.jsonl") for a in assets)),
            )
            if not ok
        ]
        if missing:
            r.add("FAIL", f"release: {tag} lacks {', '.join(missing)}")
        else:
            r.add("OK", f"release: {tag} published, {len(assets)} asset(s)")
    # the site's release-sync ticket (CONTRIBUTING "Cutting a release", step 6)
    want = f"[release-sync] {name} {tag}"
    issues = gh.get(f"repos/{SITE}/issues?state=all&per_page=100&sort=created") or []
    hit = [i for i in issues if i.get("title", "").strip() == want]
    if hit:
        r.add("OK", f"site: {SITE}#{hit[0]['number']} {want}")
    else:
        r.add(
            "WARN",
            f"site: no '{want}' issue yet; an hour after the release, dispatch the "
            f"site's release-sync.yml with repository={repo} tag={tag} and check that run",
        )
    # consumers: every org repository whose root *.lock names this one
    if consumers is not None:
        candidates = [{"full_name": c if "/" in c else f"{org}/{c}"} for c in consumers]
    else:
        try:
            candidates = gh.get(f"orgs/{org}/repos?per_page=100&type=public") or []
        except RuntimeError as e:
            candidates = []
            r.add(
                "WARN",
                f"lock: cannot list {org}'s repositories ({str(e).splitlines()[0][:120]}); "
                "pass --repos A,B to name the consumers",
            )
    for c in candidates:
        if c.get("archived") or c["full_name"] == repo:
            continue
        for entry in gh.get(f"repos/{c['full_name']}/contents") or []:
            if not (isinstance(entry, dict) and entry.get("name", "").endswith(".lock")):
                continue
            vals = lock_values(contents_text(gh, c["full_name"], entry["name"]) or "")
            prefix = next(
                (k[:-5] for k, v in vals.items() if k.endswith("_REPO") and v == repo), None
            )
            if prefix is None:
                continue
            have = vals.get(f"{prefix}_TAG")
            where = f"{c['full_name']} {entry['name']}"
            if have == tag:
                r.add("OK", f"lock: {where} locks {tag}")
                continue
            pulls = gh.get(f"repos/{c['full_name']}/pulls?state=open&per_page=100") or []
            bump = [
                p
                for p in pulls
                if p["head"]["ref"].startswith("org-bot/")
                and re.search(r"pin|lock", p["head"]["ref"] + " " + p["title"], re.I)
            ]
            if bump:
                r.add(
                    "WARN",
                    f"lock: {where} locks {have}; org-bot's bump "
                    f"{c['full_name']}#{bump[0]['number']} is open (shepherd it)",
                )
            else:
                r.add(
                    "WARN",
                    f"lock: {where} locks {have}, no org-bot bump PR open: org-bot "
                    "bumps swarm-core.lock once the pin check is red; any other lock is a "
                    'hand PR (release_lock.py render, CONTRIBUTING "Dependencies")',
                )
    flows = []
    # the workflows as they were at the tag: what that release ran
    for entry in gh.get(f"repos/{repo}/contents/.github/workflows?ref={tag}") or []:
        if isinstance(entry, dict) and entry.get("name", "").endswith((".yml", ".yaml")):
            flows.append((entry["name"], contents_text(gh, repo, entry["path"], ref=tag) or ""))
    callers = caller_workflows(flows) or [(n, t) for n, t in flows if n == "release.yml"]
    ports = sorted(
        {p for _, t in callers for m in VCPKG_PORTS.finditer(t) for p in m.group(1).split()}
    )
    if ports:
        baseline = json.loads(contents_text(gh, REGISTRY, "versions/baseline.json") or "{}")
        for port in ports:
            have = baseline.get("default", {}).get(port, {}).get("baseline")
            if have == version:
                r.add("OK", f"vcpkg: {port} {version} is the registry baseline")
                continue
            pulls = gh.get(f"repos/{REGISTRY}/pulls?state=open&head=swarm-routing:bot/vcpkg-{name}")
            if pulls:
                r.add(
                    "WARN",
                    f"vcpkg: {port} baseline {have}; {REGISTRY}#{pulls[0]['number']} "
                    "is open (shepherd it)",
                )
            else:
                r.add(
                    "FAIL",
                    f"vcpkg: {port} baseline {have}, no bot/vcpkg-{name} PR: re-run the "
                    "release's vcpkg job, or tools/port_bump.py bump by hand (registry README)",
                )
    if any(re.search(r"(?i)pypi", t) for _, t in callers):
        project = None
        for path in ("python/pyproject.toml", "pyproject.toml"):
            text = contents_text(gh, repo, path, ref=tag)
            if text:
                project = tomllib.loads(text).get("project", {}).get("name")
                if project:
                    break
        if not project:
            r.add("WARN", "pypi: the release workflow names PyPI, but no pyproject [project] name")
        elif gh.url(f"https://pypi.org/pypi/{project}/{version}/json"):
            r.add("OK", f"pypi: {project} {version} is on PyPI")
        else:
            r.add(
                "FAIL",
                f"pypi: {project} {version} is not on PyPI; read the release run's "
                "pypi job (trusted publishing)",
            )
    roadmap = contents_text(gh, repo, "docs/roadmap.md")
    if roadmap is not None:
        rows = ladder_row(roadmap, tag)
        if rows and any(SHIPPED.search(row) for row in rows):
            r.add("OK", f"ladder: docs/roadmap.md marks {tag} shipped")
        else:
            r.add(
                "WARN",
                f"ladder: docs/roadmap.md does not mark {tag} shipped; a docs PR with "
                "the version DOI read from Zenodo (swarm-routing/.github#430)",
            )
    r.add(
        "NEXT",
        f"zenodo: python3 -I tools/zenodo/zenodo.py status --repo {repo} (the version "
        "DOI from Zenodo, never typed; missing after the grace period: sync --dry-run, then ask)",
    )
    return r


# --- self-test --------------------------------------------------------------


class FakeGh:
    def __init__(self, routes, urls=None):
        self.routes, self.urls = routes, urls or {}

    def get(self, path):
        return self.routes.get(path)

    def url(self, url):
        return self.urls.get(url)


def b64(text):
    return {"content": base64.b64encode(text.encode()).decode()}


def self_test():
    import contextlib
    import io

    fails = []

    def expect(what, cond):
        print(("ok   " if cond else "FAIL ") + what)
        if not cond:
            fails.append(what)

    def quiet(fn, *a):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*a)

    def has(rep, level, text):
        return any(lv == level and text in m for lv, m in rep.lines)

    caller = (
        "jobs:\n  release:\n    uses: swarm-routing/.github/.github/workflows/"
        "reusable-release.yml@main\n    with:\n      vcpkg-ports: swarm-core\n"
    )
    cz = '[tool.commitizen]\nversion = "0.3.0"\ntag_format = "v$version"\nmajor_version_zero = true\n'
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github", "workflows"))
        os.makedirs(os.path.join(d, "docs"))
        files = {
            ".github/workflows/release.yml": caller,
            ".cz.toml": cz,
            "Makefile": "dist: ## the release asset\n\t./dist.sh\n",
            "docs/roadmap.md": "| v0.3.0 | shipped |\n| v0.4.0 | planned |\n",
        }
        for p, t in files.items():
            with open(os.path.join(d, p), "w", encoding="utf-8") as fh:
                fh.write(t)
        gh = FakeGh(
            {
                "repos/o/r/issues?state=open&per_page=100&labels=release:v0.4.0": [
                    {"number": 7},
                    {"number": 9, "pull_request": {}},
                ],
                "repos/o/r/pulls?state=open&head=o:bot/release": [
                    {
                        "number": 12,
                        "title": "chore(release): bump version 0.3.0 to 0.4.0",
                        "base": {"ref": "main"},
                    }
                ],
                "repos/o/r/compare/main...bot/release": {"behind_by": 2},
            }
        )
        rep = quiet(ready, d, "o/r", "0.4.0", gh)
        expect(
            "ready: caller, commitizen, make dist found",
            has(rep, "OK", "caller")
            and has(rep, "OK", ".cz.toml, version 0.3.0")
            and has(rep, "OK", "make dist"),
        )
        expect("ready: the ladder row v0.4.0", has(rep, "OK", "has v0.4.0"))
        expect(
            "ready: an open release-labelled issue fails (PRs not counted)",
            has(rep, "FAIL", "1 open issue(s) labelled release:v0.4.0: #7"),
        )
        expect(
            "ready: a behind bot/release says dispatch bump again",
            has(rep, "WARN", "2 commit(s) behind main: dispatch bump again"),
        )
        rep = quiet(ready, d, None, "0.4.1", gh)
        expect(
            "ready: a version with no ladder row fails (#430)",
            has(rep, "FAIL", "no row for v0.4.1") and rep.failed(),
        )
        expect(
            "ready: v0.4.0 does not match v0.4.01 or v0.4.0-rc",
            not ladder_row("v0.4.01 and v0.4.0-rc1", "v0.4.0")
            and ladder_row("| v0.4.0 |", "v0.4.0"),
        )
        with open(os.path.join(d, ".cz.toml"), "w", encoding="utf-8") as fh:
            fh.write(cz.replace('"v$version"', '"$version"'))
        os.remove(os.path.join(d, "Makefile"))
        rep = quiet(ready, d, None, None, gh)
        expect("ready: a tag_format without v fails", has(rep, "FAIL", "tag_format"))
        expect("ready: no make dist and no build: input fails", has(rep, "FAIL", "build:"))
        expect("ready: no --version warns on the ladder", has(rep, "WARN", "pass --version"))
    with tempfile.TemporaryDirectory() as d:
        rep = quiet(ready, d, None, "0.1.0", FakeGh({}))
        expect(
            "ready: an empty repository fails the caller and commitizen",
            has(rep, "FAIL", "no workflow calls")
            and has(rep, "FAIL", "no .cz.toml")
            and has(rep, "WARN", "no docs/roadmap.md"),
        )

    lock_new = "SWARM_CORE_REPO=o/r\nSWARM_CORE_TAG=v0.4.0\n"
    lock_old = "# header\nSWARM_CORE_REPO=o/r\nSWARM_CORE_TAG=v0.3.0\n"
    pyproject = '[project]\nname = "r-tools"\n'
    routes = {
        "repos/o/r/releases/tags/v0.4.0": {
            "draft": False,
            "assets": [
                {"name": "r-0.4.0.tar.gz"},
                {"name": "SHA256SUMS"},
                {"name": "r-0.4.0.intoto.jsonl"},
            ],
        },
        f"repos/{SITE}/issues?state=all&per_page=100&sort=created": [
            {"number": 155, "title": "[release-sync] r v0.4.0"}
        ],
        "orgs/o/repos?per_page=100&type=public": [
            {"full_name": "o/a"},
            {"full_name": "o/b"},
            {"full_name": "o/c"},
            {"full_name": "o/old", "archived": True},
            {"full_name": "o/r"},
        ],
        "repos/o/a/contents": [{"name": "swarm-core.lock"}, {"name": "README.md"}],
        "repos/o/a/contents/swarm-core.lock": b64(lock_new),
        "repos/o/b/contents": [{"name": "swarm-core.lock"}],
        "repos/o/b/contents/swarm-core.lock": b64(lock_old),
        "repos/o/b/pulls?state=open&per_page=100": [
            {
                "number": 3,
                "title": "chore: apply the org templates (org-bot)",
                "head": {"ref": "org-bot/org-sync-1"},
            },
            {
                "number": 4,
                "title": "chore(core): bump the swarm-core pin (org-bot)",
                "head": {"ref": "org-bot/swarm-core-pin"},
            },
        ],
        "repos/o/c/contents": [{"name": "other.lock"}],
        "repos/o/c/contents/other.lock": b64("X_REPO=o/elsewhere\nX_TAG=v1.0.0\n"),
        "repos/o/r/contents/.github/workflows?ref=v0.4.0": [
            {"name": "release.yml", "path": ".github/workflows/release.yml"}
        ],
        "repos/o/r/contents/.github/workflows/release.yml?ref=v0.4.0": b64(
            caller.replace("swarm-core\n", "swarm-core   # the port bump PR\n") + "  pypi:\n    x\n"
        ),
        f"repos/{REGISTRY}/contents/versions/baseline.json": b64(
            '{"default": {"swarm-core": {"baseline": "0.3.0"}}}'
        ),
        f"repos/{REGISTRY}/pulls?state=open&head=swarm-routing:bot/vcpkg-r": [{"number": 9}],
        "repos/o/r/contents/python/pyproject.toml?ref=v0.4.0": b64(pyproject),
        "repos/o/r/contents/docs/roadmap.md": b64("| v0.4.0 | planned |\n"),
    }
    gh = FakeGh(routes, {"https://pypi.org/pypi/r-tools/0.4.0/json": {"info": {}}})
    rep = quiet(after, "o/r", "v0.4.0", "o", gh)
    expect("after: the release and its provenance", has(rep, "OK", "v0.4.0 published, 3 asset"))
    expect("after: the site's release-sync issue", has(rep, "OK", f"{SITE}#155"))
    expect("after: a consumer on the tag", has(rep, "OK", "o/a swarm-core.lock locks v0.4.0"))
    expect(
        "after: a stale consumer with org-bot's pin PR (not the template PR)",
        has(rep, "WARN", "o/b#4 is open"),
    )
    expect(
        "after: an unrelated lock and an archived repository are skipped",
        not any("o/c" in m or "o/old" in m for _, m in rep.lines),
    )
    expect("after: the vcpkg port with its open registry PR", has(rep, "WARN", f"{REGISTRY}#9"))
    expect("after: PyPI has the version", has(rep, "OK", "r-tools 0.4.0 is on PyPI"))
    expect("after: the ladder not marked shipped", has(rep, "WARN", "does not mark v0.4.0"))
    expect("after: zenodo is a NEXT step", has(rep, "NEXT", "zenodo.py status --repo o/r"))
    expect("after: no FAIL", not rep.failed())

    routes["repos/o/r/releases/tags/v0.4.0"] = {"draft": False, "assets": [{"name": "x.tar.gz"}]}
    del routes[f"repos/{REGISTRY}/pulls?state=open&head=swarm-routing:bot/vcpkg-r"]
    routes[f"repos/{SITE}/issues?state=all&per_page=100&sort=created"] = []
    routes["repos/o/b/pulls?state=open&per_page=100"] = []
    routes["repos/o/r/contents/docs/roadmap.md"] = b64("| v0.4.0 | shipped 2026-11-15 |\n")
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(routes))
    expect(
        "after: missing SHA256SUMS and provenance fail",
        has(rep, "FAIL", "lacks SHA256SUMS, *.intoto.jsonl"),
    )
    expect("after: no vcpkg PR fails", has(rep, "FAIL", "no bot/vcpkg-r PR"))
    expect("after: not on PyPI fails", has(rep, "FAIL", "not on PyPI"))
    expect("after: no site issue warns with the dispatch", has(rep, "WARN", "release-sync.yml"))
    expect("after: a stale consumer with no bump PR warns", has(rep, "WARN", "no org-bot bump"))
    expect("after: the ladder marked shipped", has(rep, "OK", "marks v0.4.0 shipped"))
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(routes), ["a"])
    expect(
        "after: --repos names the consumers",
        has(rep, "OK", "o/a swarm-core.lock") and not any("o/b" in m for _, m in rep.lines),
    )

    class Refused(FakeGh):
        def get(self, path):
            if path.startswith("orgs/"):
                raise RuntimeError("gh api orgs/o/repos: HTTP 403")
            return super().get(path)

    rep = quiet(after, "o/r", "v0.4.0", "o", Refused(routes))
    expect("after: an org listing refused warns and names --repos", has(rep, "WARN", "--repos"))
    rep = quiet(after, "o/r", "v9.9.9", "o", FakeGh({}))
    expect("after: no release fails", has(rep, "FAIL", "no published GitHub release v9.9.9"))

    if fails:
        print(f"release_check: {len(fails)} failed")
        sys.exit(1)
    print("release_check: all ok")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--self-test"]:
        self_test()
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ready", help="before a dry-run or a bump")
    p.add_argument("repo_dir")
    p.add_argument("--repo", help="OWNER/NAME, for the issue scope and the bump PR")
    p.add_argument("--version", help="the version the dry-run computed, X.Y.Z")
    p = sub.add_parser("after", help="once the bump PR merged")
    p.add_argument("repo", help="OWNER/NAME")
    p.add_argument("--tag", required=True, help="vX.Y.Z")
    p.add_argument("--org", default="swarm-routing")
    p.add_argument(
        "--repos",
        help="the consumers to look at, NAME or OWNER/NAME, comma-separated "
        "(default: every public repository of --org)",
    )
    a = ap.parse_args(argv)
    gh = Gh()
    try:
        if a.cmd == "ready":
            rep = ready(a.repo_dir, a.repo, (a.version or "").lstrip("v") or None, gh)
        else:
            if not re.fullmatch(r"v\d+\.\d+\.\d+", a.tag):
                ap.error(f"--tag {a.tag}: not vX.Y.Z")
            repos = [x.strip() for x in a.repos.split(",") if x.strip()] if a.repos else None
            rep = after(a.repo, a.tag, a.org, gh, repos)
    except RuntimeError as e:
        print(f"release_check: {e}", file=sys.stderr)
        return 2
    print("FAIL  see above" if rep.failed() else "OK    nothing failed")
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
