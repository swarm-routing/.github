#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Before and after a release: is the repository ready to bump, and did everything follow?

    release_check.py ready REPO_DIR [--repo OWNER/NAME] [--version X.Y.Z | --increment SIZE]
    release_check.py preflight REPO_DIR [--repo OWNER/NAME] [--downstream-consumers LIST]
    release_check.py after OWNER/NAME --tag vX.Y.Z [--org ORG] [--repos A,B]
    release_check.py ladder REPO_DIR --version X.Y.Z
    release_check.py --self-test

Read-only. It prints one line per check, `OK`, `WARN`, `FAIL` or `NEXT` (a
step that is a person's or another tool's), and exits 1 on a FAIL, so an
agent reads the verdict, not the workflow logs (AntHocNet ADR-0014).
CONTRIBUTING "Cutting a release" is the procedure; this checks its steps.

`ready` (before a dry-run or a bump), on a checkout of the repository:
  - the caller workflow uses reusable-release.yml (a repository with its own
    release workflow, as AntHocNet, is a WARN: these checks may not fit it);
  - the caller forwards `increment` to reusable-release.yml (an own
    release.yml reads `inputs.increment`), so a dispatch can force the
    version the ladder fixes (swarm-routing/.github#512);
  - the Commitizen config (`.cz.toml`, or `[tool.commitizen]` in
    `pyproject.toml`) exists, with `tag_format = "v$version"`;
  - `make dist` exists, unless the caller passes its own `build:` or an own
    release.yml assembles its assets into `dist/` (AntHocNet);
  - a repository that ships C++ (a `core/` CMake project, or an ns-3 module:
    a CMakeLists.txt calling `build_lib(`) sets `vcpkg-ports` in its caller
    (an own release.yml: a live line naming vcpkg), so every C++ release has
    its port (swarm-routing/.github#881); nothing for one without C++;
  - the version: --version, else what the bump would produce (`cz bump
    --get-next`, with --increment; 0.1.0 for a first release), a WARN when
    Commitizen is not installed or nothing bumps;
  - `docs/roadmap.md` has a row for that version (the ladder gate, as
    `ladder`); without a ladder, the org ROADMAP's release train applies (a
    WARN);
  - the `preflight` checks below;
  - with --repo and --version, no open issue is labelled `release:vX.Y.Z`;
  - with --repo, an open `bot/release` PR behind `main` (dispatch `bump`
    again; never update or push that branch by hand).

`ladder` is the ladder gate alone, offline: FAIL (exit 1) when
`docs/roadmap.md` has no row for vX.Y.Z, WARN when the repository keeps no
ladder. reusable-release.yml's bump and dry-run run it on the bumped version
before anything is built or proposed (swarm-routing/.github#430).

`preflight` (also run by reusable-release.yml's dry run before the build;
the sim-tools v1.1.3 dry runs, after the rename ns3-tools -> sim-tools):
  - the repository's current name from the GitHub API (it follows renames),
    a WARN when --repo or the checkout's origin still names the old one;
  - with `downstream-consumers` (the caller's input, or the option), the list
    parses and names this repository (`downstream-self`, default its current
    name) as a consumer: tools/downstream/downstream.sh `--check` with the
    checkout as DOWNSTREAM_LOCAL, the dry run's own call;
  - where the release workflow publishes to PyPI, the pyproject [project]
    name on PyPI and TestPyPI: not there yet (a NEXT: its pending publisher),
    or its GitHub URLs (PyPI's project_urls, the pyproject's own) name this
    repository; an old name of it is a WARN (the trusted publisher likely
    names it too: `invalid-publisher`), another repository a FAIL. PyPI does
    not expose the publisher, so a NEXT line names its settings page.
  Only a definite mismatch fails; what cannot be read is a WARN.

`after` (once the bump PR merged), through `gh api` and public URLs:
  - the GitHub release of the tag is published with SHA256SUMS and the
    provenance (`*.intoto.jsonl`);
  - its notes are not empty: something under the version heading, above
    `## Verify your download` (else the release workflow's mode
    `release-notes` re-renders them from CHANGELOG.md, #524);
  - the site saw it: an `[release-sync] <name> <tag>` issue in
    swarm-routing/swarm-routing.github.io (CONTRIBUTING step 6);
  - every org repository that locks this one (a root `*.lock` whose
    `<PREFIX>_REPO` names it) locks the tag, or has an open PR moving the lock
    to it (org-bot's `org-bot/*` bump, or a hand bump); the candidates are
    --repos, else the org's public repositories, else, where the token
    cannot list the org (an agent session), the repositories
    ROADMAP.md#epics names, as org-bot's epics fetch does (#478);
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
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request

SITE = "swarm-routing/swarm-routing.github.io"
ROADMAP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ROADMAP.md"
)
REGISTRY = "swarm-routing/vcpkg-registry"
VERIFY = "## Verify your download"
REUSABLE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?uses:[ \t]*swarm-routing/\.github/\.github/workflows/reusable-release\.yml@",
    re.M,
)
DIST_TARGET = re.compile(r"^dist\s*:", re.M)
INCREMENT = re.compile(r"\binputs\.increment\b")
# a push gate (a job's or step's `if:`) that reads the push's head commit's
# message (#943); the same expression in a step's env or run is no gate
HEAD_GATE = re.compile(r"^\s*(?:-\s*)?if:.*\bhead_commit\.message\b")
COMMENT = re.compile(r"(?:^|\s)#.*$")  # a YAML comment, to the end of the line
# an own release.yml builds its assets when a live (uncommented) line names dist/ as a path
OWN_DIST = re.compile(r"(?:^|\s)\"?(?:\./)?dist/?\"?(?=\s|$)", re.M)
WITH = re.compile(r"^[ \t]*with:[ \t]*(?:#.*)?$")
BUILD_LIB = re.compile(r"^\s*build_lib\s*\(", re.M)  # an ns-3 module's CMakeLists.txt
NOT_SHIPPED_DIRS = ("test", "tests", "testdata", "fixtures", "examples", "evals")
VCPKG = re.compile(r"\bvcpkg\b|port_bump")
KEY = re.compile(r"^[ \t]*([A-Za-z0-9_-]+):(.*)$")  # the value is stripped after the match
SHIPPED = re.compile(r"(?i)\b(?:shipped|released)\b")
NOT_SHIPPED = re.compile(
    r"(?i)\b(?:not|un)[ -]?(?:yet[ -])?(?:shipped|released)\b|\b(?:planned|upcoming|next)\b"
)


class Gh:
    """GitHub reads through `gh api`; None for a 404."""

    def get(self, path):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if r.returncode:
            if "HTTP 404" in r.stderr:
                return None
            raise RuntimeError(f"gh api {path}: {r.stderr.strip()}")
        return json.loads(r.stdout or "null")

    def get_all(self, path):
        """Every page of a list endpoint (100 a page), or None for a 404."""
        return paged(self.get, path)

    def url(self, url):
        """The JSON at a public URL, or None for a 404."""
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise


def paged(get, path, limit=50):
    """Every page of a list endpoint through get(path); None when the first is a 404."""
    out = []
    sep = "&" if "?" in path else "?"
    for page in range(1, limit + 1):
        chunk = get(f"{path}{sep}per_page=100&page={page}")
        if chunk is None:
            return None if page == 1 else out
        out.extend(chunk)
        if len(chunk) < 100:
            break
    return out


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


def with_inputs(text):
    """{input: value} of every `with:` block of a job that calls
    reusable-release.yml, merged (with_blocks has them one per call)."""
    out = {}
    for block in with_blocks(text):
        out.update(block)
    return out


def with_blocks(text):
    """[{input: value}], one per job that calls reusable-release.yml, read by
    indentation (stdlib, no YAML parser): a commented line is not a key, a key
    belongs to the block it is indented under, and a block scalar (`|`, `>-`)
    takes its indented lines, joined by spaces."""
    lines = text.splitlines()
    blocks = []

    def indent(ln):
        return len(ln) - len(ln.lstrip(" "))

    def live(ln):
        return bool(ln.strip()) and not ln.lstrip().startswith("#")

    for i, ln in enumerate(lines):
        if not REUSABLE.match(ln):
            continue
        out = {}
        blocks.append(out)
        # `uses:` and `with:` are siblings: the same indentation (a `- uses:` counts its dash)
        level = indent(ln.replace("- ", "  ", 1))
        k = i + 1
        while k < len(lines) and (not live(lines[k]) or indent(lines[k]) >= level):
            if not (live(lines[k]) and indent(lines[k]) == level and WITH.match(lines[k])):
                k += 1
                continue
            base, k = level, k + 1
            while k < len(lines) and (not live(lines[k]) or indent(lines[k]) > base):
                m = KEY.match(lines[k])
                if not (live(lines[k]) and m):
                    k += 1
                    continue
                key, val, at = (
                    m.group(1),
                    m.group(2).split(" #", 1)[0].split("\t#", 1)[0].strip(),
                    indent(lines[k]),
                )
                k += 1
                if val[:1] in ("|", ">"):
                    body = []
                    while k < len(lines) and (not lines[k].strip() or indent(lines[k]) > at):
                        body.append(lines[k].strip())
                        k += 1
                    val = " ".join(b for b in body if b)
                out[key] = val.strip().strip("\"'")
    return blocks


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


def commitizen(repo_dir, wd=""):
    """(file, table) of the Commitizen config in the working directory, or (None, None)."""
    for name in (".cz.toml", "pyproject.toml"):
        name = os.path.join(wd, name) if wd else name
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


def gate_rows(text, tag):
    """The ladder rows that are the tag's own: a table row whose first cell is the
    version (`| v0.5.0 |`, `| **v0.5.0** "gated" |`), or a heading naming it; never a
    row that only mentions it (`| v0.4.0 | prerequisites for v0.5.0 |`)."""
    out = []
    for ln in ladder_row(text, tag):
        s = ln.strip()
        if s.startswith("#"):
            out.append(ln)
        elif s.startswith("|") and ladder_row(
            s.split("|")[1].replace("*", "").strip()[: len(tag) + 1], tag
        ):
            out.append(ln)
    return out


def ladder(repo_dir, version, r=None):
    """The ladder gate: the version's row in docs/roadmap.md (swarm-routing/.github#430)."""
    r = r or Report()
    roadmap = read(os.path.join(repo_dir, "docs", "roadmap.md"))
    if roadmap is None:
        r.add("WARN", "ladder: no docs/roadmap.md; the org ROADMAP's release train is the scope")
    elif not version:
        r.add("WARN", "ladder: pass --version X.Y.Z (the dry-run's version) to check its row")
    elif gate_rows(roadmap, f"v{version}"):
        r.add("OK", f"ladder: docs/roadmap.md has v{version}")
    else:
        r.add(
            "FAIL",
            f"ladder: docs/roadmap.md has no row for v{version}; add the version and "
            "its exit criteria in a PR before the bump (swarm-routing/.github#430)",
        )
    return r


PYPI_INDEXES = (("PyPI", "https://pypi.org"), ("TestPyPI", "https://test.pypi.org"))
GITHUB_REPO_URL = re.compile(
    r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?=[/#?\s\"')]|$)"
)
REMOTE = re.compile(r"[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
QUOTED = re.compile(r"'([A-Za-z0-9_.-]+)'")
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def downstream_sh():
    """tools/downstream/downstream.sh: next to this file (a runner's temp
    directory, where reusable-release.yml copies both), or in its checkout."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (
        os.path.join(here, "downstream.sh"),
        os.path.join(TOOLS, "downstream", "downstream.sh"),
    ):
        if os.path.isfile(p):
            return p
    return None


def pyproject_name(text_at, wd=""):
    """The [project] name of the first pyproject.toml found (the working
    directory's, python/, the root); text_at(path) returns a file's text or None."""
    paths = [f"{wd}/pyproject.toml"] if wd else []
    for path in dict.fromkeys(paths + ["python/pyproject.toml", "pyproject.toml"]):
        text = text_at(path)
        if text:
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                continue
            name = data.get("project", {}).get("name")
            if name:
                return name, path, data.get("project", {}).get("urls") or {}
    return None, None, {}


def publishes_pypi(text):
    """A workflow that publishes to PyPI: a live (uncommented) line names it."""
    return bool(re.search(r"(?i)pypi", "\n".join(COMMENT.sub("", ln) for ln in text.splitlines())))


def origin_repo(repo_dir):
    """OWNER/NAME of the checkout's origin remote, or None."""
    try:
        # an absolute path: the directory never reads as an option
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=os.path.abspath(repo_dir),
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    m = REMOTE.search(out.stdout.strip()) if out.returncode == 0 else None
    return f"{m.group(1)}/{m.group(2)}" if m else None


def resolve(gh, repo):
    """The repository's full_name as the GitHub API has it now (a renamed one
    redirects to its new name), None for a 404; raises RuntimeError when unreadable."""
    data = gh.get(f"repos/{repo}")
    return data.get("full_name") if isinstance(data, dict) else None


def current_repo(repo_dir, repo, gh, r):
    """The repository's current OWNER/NAME (the GitHub API follows renames), or
    the given one when the API cannot be read (a WARN)."""
    given = repo or origin_repo(repo_dir)
    if not given:
        r.add("WARN", "repository: pass --repo OWNER/NAME (no origin remote to read it from)")
        return None
    try:
        now = resolve(gh, given)
    except RuntimeError as e:
        r.add(
            "WARN",
            f"repository: cannot read {given} from the GitHub API ({str(e)[:120]}); "
            "its name is taken as given",
        )
        return given
    if not now:
        r.add("FAIL", f"repository: {given} does not exist on GitHub")
        return given
    if now.lower() != given.lower():
        r.add(
            "WARN",
            f"repository: {given} was renamed {now}; the checks below use {now} (move the "
            "remote, and every file naming the old name, to it)",
        )
    else:
        r.add("OK", f"repository: {now}")
    return now


def downstream_check(repo_dir, list_path, self_name, r, script=None):
    """The consumer list parses and names this repository (reusable-release.yml's
    downstream job: DOWNSTREAM_LOCAL=<self>=<checkout>, downstream.sh)."""
    if "${{" in list_path or (self_name and "${{" in self_name):
        r.add("WARN", f"downstream: {list_path} is an expression; check the list by hand")
        return
    # absolute: the list's path never reads as one of downstream.sh's options
    path = os.path.abspath(os.path.join(repo_dir, list_path))
    if not os.path.isfile(path):
        r.add("FAIL", f"downstream: downstream-consumers names {list_path}, no such file")
        return
    script = script or downstream_sh()
    if not script:
        r.add("WARN", "downstream: tools/downstream/downstream.sh not found; the list is unchecked")
        return
    env = dict(os.environ, DOWNSTREAM_LOCAL=f"{self_name}={os.path.abspath(repo_dir)}")
    if not self_name:
        env.pop("DOWNSTREAM_LOCAL")
    out = subprocess.run(["bash", script, "--check", path], capture_output=True, text=True, env=env)
    if out.returncode:
        why = (out.stderr.strip().splitlines() or ["no output"])[-1]
        hint = (
            f" (the dry run passes DOWNSTREAM_LOCAL={self_name}=<checkout>: a line named "
            f"`{self_name}`, the repository's current name, or the caller's `downstream-self`)"
            if "is not a consumer" in why
            else ""
        )
        r.add("FAIL", f"downstream: {list_path}: {why}{hint}")
    elif not self_name:
        r.add(
            "WARN",
            f"downstream: {list_path} parses; this repository's name is unknown, "
            "so its own line is unchecked",
        )
    else:
        count = (out.stdout.strip().splitlines() or [""])[-1]
        r.add("OK", f"downstream: {count}, `{self_name}` (this repository) among them")


def url_repos(urls):
    """{OWNER/NAME} of the GitHub repositories a set of URLs names."""
    out = set()
    for u in urls:
        for m in GITHUB_REPO_URL.finditer(u or ""):
            out.add(f"{m.group(1)}/{m.group(2)}")
    return out


def repo_urls_check(where, urls, full_name, gh, r):
    """The GitHub URLs `where` holds name full_name: an old name of it is a WARN
    (a rename), another repository a FAIL, an unreadable one a WARN."""
    others = sorted(x for x in url_repos(urls) if x.lower() != full_name.lower())
    if not others and url_repos(urls):
        r.add("OK", f"{where} names {full_name}")
    for x in others:
        try:
            now = resolve(gh, x)
        except RuntimeError as e:
            r.add("WARN", f"{where} names {x}, unreadable on GitHub ({str(e)[:80]})")
            continue
        if now and now.lower() == full_name.lower():
            r.add(
                "WARN",
                f"{where} names {x}, this repository's old name (now {full_name}): a "
                "trusted publisher made for it fails with `invalid-publisher`",
            )
        elif now:
            r.add("FAIL", f"{where} names {x}, another repository than {full_name}")
        else:
            r.add("WARN", f"{where} names {x}, which does not exist on GitHub")


def pypi_check(repo_dir, callers, inputs, full_name, gh, r):
    """Where the release publishes to PyPI: the project, its repository URLs, and
    the trusted publisher a person confirms (PyPI's JSON API does not show it)."""
    flows = [(n, t) for n, t in callers if publishes_pypi(t)]
    if not flows:
        return
    wd = inputs.get("working-directory", "").strip("./")
    name, path, urls = pyproject_name(lambda p: read(os.path.join(repo_dir, p)), wd)
    if not name:
        r.add("WARN", "pypi: the release workflow names PyPI, but no pyproject [project] name")
        return
    flow, text = flows[0]
    envs = sorted(
        {
            e
            for ln in text.splitlines()
            if "environment:" in COMMENT.sub("", ln)
            for e in QUOTED.findall(ln) or [ln.split("environment:", 1)[1].strip()]
        }
    )
    where = f"repository {full_name or '?'}, workflow {flow}" + (
        f", environment {' or '.join(envs)}" if envs else ""
    )
    if full_name and urls:
        repo_urls_check(f"pypi: {path} [project.urls]", urls.values(), full_name, gh, r)
    # TestPyPI too when the workflow uploads there (its legacy upload URL)
    testpypi = bool(re.search(r"https://test\.pypi\.org/legacy/?", text))
    indexes = [ix for ix in PYPI_INDEXES if ix[0] == "PyPI" or testpypi]
    for label, base in indexes:
        try:
            data = gh.url(f"{base}/pypi/{name}/json")
        except (OSError, ValueError) as e:
            r.add("WARN", f"pypi: cannot read {name} on {label} ({str(e)[:80]})")
            continue
        if data is None:
            r.add(
                "NEXT",
                f"pypi: {name} is not on {label} yet: before the first upload the maintainer "
                f"adds a pending publisher at {base}/manage/account/publishing/ ({where})",
            )
            continue
        info = data.get("info") or {}
        pyurls = list((info.get("project_urls") or {}).values()) + [info.get("home_page") or ""]
        if full_name and url_repos(pyurls):
            repo_urls_check(f"pypi: {label}'s {name} project_urls", pyurls, full_name, gh, r)
        else:
            r.add("OK", f"pypi: {name} is on {label} (no GitHub URL in its metadata to compare)")
        r.add(
            "NEXT",
            f"pypi: confirm {label}'s trusted publisher for {name} names {where} at "
            f"{base}/manage/project/{name}/settings/publishing/ ({label}'s API does not show it; "
            "a renamed repository needs a new one)",
        )


def preflight(repo_dir, repo, gh, consumers=None, self_name=None, r=None):
    """The repository's name, its downstream list's own line and its PyPI project."""
    r = r or Report()
    flows = local_workflows(repo_dir)
    callers = caller_workflows(flows) or [(n, t) for n, t in flows if n == "release.yml"]
    inputs = {}
    for _, t in callers:
        inputs.update(with_inputs(t))
    full_name = current_repo(repo_dir, repo, gh, r)
    consumers = consumers or inputs.get("downstream-consumers")
    if consumers:
        self_name = (
            self_name
            or inputs.get("downstream-self")
            or (full_name.split("/", 1)[1] if full_name else None)
        )
        downstream_check(repo_dir, consumers, self_name, r)
    pypi_check(repo_dir, callers, inputs, full_name, gh, r)
    return r


def next_version(repo_dir, wd, increment, from_config, r, run=subprocess.run):
    """What the bump would produce: 0.1.0 for a first release (as
    reusable-release.yml), else Commitizen's `cz bump --get-next`; None (a WARN)
    when Commitizen is missing or nothing bumps."""
    tags = run(["git", "-C", repo_dir, "tag", "--list", "v[0-9]*"], capture_output=True, text=True)
    if (
        tags.returncode == 0
        and not tags.stdout.strip()
        and not from_config
        and increment != "MAJOR"
    ):
        r.add(
            "OK", "version: 0.1.0 (no v* tag: the first release; a clone without tags: fetch them)"
        )
        return "0.1.0"
    cmd = ["cz", "bump", "--get-next", "--yes"] + (["--increment", increment] if increment else [])
    try:
        out = run(cmd, cwd=os.path.join(repo_dir, wd), capture_output=True, text=True)
    except OSError:
        r.add(
            "WARN",
            "version: Commitizen is not installed (pip install commitizen); pass "
            "--version X.Y.Z to check the ladder row",
        )
        return None
    ver = out.stdout.strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else ""
    if re.fullmatch(r"\d+\.\d+\.\d+", ver):
        r.add("OK", f"version: {ver}, what the bump would produce ({' '.join(cmd)})")
        return ver
    r.add(
        "WARN",
        f"version: `{' '.join(cmd)}` exited {out.returncode} (21: nothing that bumps since the "
        "last tag, and a dry run stops there); pass --increment or --version",
    )
    return None


def cpp_shipped(repo_dir):
    """What C++ the repository ships: `core/` (a CMake project) and the ns-3
    module directories (a CMakeLists.txt calling build_lib), relative paths.
    C++ under test/, tests/, testdata/, fixtures/, examples/ or evals/ is not shipped."""
    found = []
    if os.path.isfile(os.path.join(repo_dir, "core", "CMakeLists.txt")):
        found.append("core/")
    for root, dirs, files in os.walk(repo_dir):
        rel = os.path.relpath(root, repo_dir)
        dirs[:] = sorted(
            x
            for x in dirs
            if not x.startswith(".")
            and not x.startswith("build")
            and x not in ("third_party", "vendor", "node_modules")
            and x not in NOT_SHIPPED_DIRS
            and not (rel == "." and x == "core")
        )
        if "CMakeLists.txt" in files and BUILD_LIB.search(
            read(os.path.join(root, "CMakeLists.txt")) or ""
        ):
            found.append("./" if rel == "." else rel + "/")
    return found


def vcpkg_check(repo_dir, callers, inputs, own_live, r):
    """A repository shipping C++ releases a vcpkg port (swarm-routing/.github#881, #882)."""
    shipped = cpp_shipped(repo_dir)
    if not shipped:
        return
    what = ", ".join(shipped[:5]) + (" …" if len(shipped) > 5 else "")
    ports = inputs.get("vcpkg-ports", "").split()
    if callers and ports:
        r.add("OK", f"vcpkg: C++ ({what}) released as port(s) {' '.join(ports)}")
    elif own_live is not None and not callers and VCPKG.search(own_live):
        r.add("OK", f"vcpkg: C++ ({what}); the own release.yml has a vcpkg step")
    else:
        r.add(
            "FAIL",
            f"vcpkg: the repository ships C++ ({what}) but its release sets no `vcpkg-ports`: "
            f"add the port to {REGISTRY} (templates/<port>/) and `vcpkg-ports: <port>` under "
            "the caller's `with:` (an ns-3 module's port waits on the registry's ns3 port; "
            "swarm-routing/.github#881)",
        )


def ready(repo_dir, repo, version, gh, increment=None, run=subprocess.run):
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
    inputs = {}
    for _, t in callers:
        inputs.update(with_inputs(t))
    own = [t for n, t in flows if n == "release.yml" and not callers]
    own_live = "\n".join(COMMENT.sub("", ln) for ln in own[0].splitlines()) if own else ""
    # every call of reusable-release.yml forwards it, not just one of them
    missing = [
        f".github/workflows/{n} (call {k + 1})"
        for n, t in callers
        for k, b in enumerate(with_blocks(t))
        if "increment" not in b
    ]
    if (callers and not missing) or (own and INCREMENT.search(own_live)):
        r.add("OK", "increment: the dispatch input reaches the bump")
    elif callers:
        r.add(
            "FAIL",
            f"increment: {', '.join(missing)}: the caller does not forward the `increment` input "
            "(a choice auto/PATCH/MINOR/MAJOR, passed as "
            "`increment: ${{ inputs.increment != 'auto' && inputs.increment || '' }}`; "
            "swarm-routing/.github#512)",
        )
    elif own:
        r.add(
            "FAIL",
            "increment: the own release.yml never reads `inputs.increment` (a choice "
            "auto/PATCH/MINOR/MAJOR given to `cz bump --increment`; swarm-routing/.github#512)",
        )
    # A merge queue pushes a batch at once: a gate on the head commit's
    # message skips the release whenever the bump PR is not the batch's last
    # (swarm-routing/sim-containers v1.1.0, swarm-routing/.github#943).
    head_only = [
        f".github/workflows/{n}"
        for n, t in callers
        if any(HEAD_GATE.search(COMMENT.sub("", ln)) for ln in t.splitlines())
    ]
    if head_only:
        r.add(
            "FAIL",
            f"push gate: {', '.join(head_only)} gates the release on "
            "`github.event.head_commit.message`, so a merge queue's batch with the bump PR below "
            "its head never releases; gate on every commit of the push: "
            "`contains(toJSON(github.event.commits.*.message), 'chore(release): bump version ')` "
            "(swarm-routing/.github#943; a bump already merged and never released: mode publish)",
        )
    elif callers:
        r.add("OK", "push gate: not on the head commit alone")
    wd = inputs.get("working-directory", "").strip("./")
    if wd:
        r.add("OK", f"working-directory: {wd} (the Commitizen config and make dist are read there)")
    name, cz = commitizen(repo_dir, wd)
    if cz is None:
        r.add(
            "FAIL",
            f"commitizen: no .cz.toml and no [tool.commitizen] in {wd or '.'}/pyproject.toml",
        )
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
    has_build = bool(inputs.get("build"))
    if DIST_TARGET.search(read(os.path.join(repo_dir, wd, "Makefile")) or ""):
        r.add("OK", "build: make dist")
    elif has_build:
        r.add("OK", "build: the caller's own build: input")
    elif own and OWN_DIST.search(own_live):
        r.add("OK", "build: the own release.yml builds its assets into dist/")
    else:
        r.add("FAIL", "build: no `dist:` target in the Makefile and no build: input in the caller")
    vcpkg_check(repo_dir, callers, inputs, own_live if own else None, r)
    if not version and cz is not None and "_error" not in cz:
        from_config = inputs.get("first-release-from-config", "") in ("true", "True")
        version = next_version(repo_dir, wd, increment, from_config, r, run)
    ladder(repo_dir, version, r)
    preflight(repo_dir, repo, gh, r=r)
    if repo and version:
        label = f"release:v{version}"
        listed = gh.get_all(f"repos/{repo}/issues?state=open&labels={label}")
        issues = [i for i in listed or [] if "pull_request" not in i]
        if listed is None:
            r.add("FAIL", f"scope: cannot read {repo}'s issues (wrong --repo, or no access)")
        elif issues:
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
                    f"{p['base']['ref']}: dispatch bump again, or org-bot's release-rebuild does "
                    "within the hour (never push bot/release)",
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


def bumps_lock(gh, repo, pull, lock, prefix, tag):
    """The PR changes this lock, and the lock on its head names the tag."""
    files = gh.get_all(f"repos/{repo}/pulls/{pull['number']}/files") or []
    if not any(f.get("filename") == lock for f in files):
        return False
    head = lock_values(contents_text(gh, repo, lock, ref=pull["head"]["sha"]) or "")
    return head.get(f"{prefix}_TAG") == tag


def roadmap_repos(path=ROADMAP):
    """The repository names ROADMAP.md#epics lists (tools/epics/epics.py's reader)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "epics"))
    import epics

    return epics.roadmap_repos(path)


def after(repo, tag, org, gh, consumers=None, roadmap=ROADMAP):
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
        # the notes above the verify block are never empty (#524)
        body = rel.get("body") or ""
        notes = "" if body.startswith(VERIFY) else body.split("\n" + VERIFY, 1)[0]
        if any(ln.strip() for ln in notes.splitlines()[1:]):
            r.add("OK", f"notes: {tag} has notes above '{VERIFY}'")
        else:
            r.add(
                "FAIL",
                f"notes: {tag}'s notes are empty (a heading at most); write the paragraph under "
                f"'## {tag}' in CHANGELOG.md on main (a PR), then dispatch the release workflow "
                f"with mode=release-notes tag={tag} (swarm-routing/.github#524)",
            )
    # the site's release-sync ticket (CONTRIBUTING "Cutting a release", step 6)
    want = f"[release-sync] {name} {tag}"
    issues = gh.get_all(f"repos/{SITE}/issues?state=all&sort=created") or []
    hit = [i for i in issues if i.get("title", "").strip() == want]
    if hit:
        r.add("OK", f"site: {SITE}#{hit[0]['number']} {want}")
    else:
        r.add(
            "WARN",
            f"site: no '{want}' issue yet; an hour after the release, org-bot's hourly "
            f"release-sync-watch dispatches the site's release-sync.yml with "
            f"repository={repo} tag={tag} (swarm-routing/.github#571)",
        )
    # consumers: every org repository whose root *.lock names this one
    if consumers is not None:
        candidates = [{"full_name": c if "/" in c else f"{org}/{c}"} for c in consumers]
    else:
        try:
            candidates = gh.get_all(f"orgs/{org}/repos?type=public") or []
        except RuntimeError as e:
            names = roadmap_repos(roadmap)
            candidates = [{"full_name": f"{org}/{n}"} for n in names]
            why = str(e).splitlines()[0][:120]
            if names:
                r.add(
                    "OK",
                    f"lock: {org}'s repositories from ROADMAP.md#epics ({len(names)}), "
                    f"as the org listing is refused ({why})",
                )
            else:
                r.add(
                    "WARN",
                    f"lock: cannot list {org}'s repositories ({why}) and ROADMAP.md#epics "
                    "names none; pass --repos A,B to name the consumers",
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
            pulls = gh.get_all(f"repos/{c['full_name']}/pulls?state=open") or []
            bump = [
                p for p in pulls if bumps_lock(gh, c["full_name"], p, entry["name"], prefix, tag)
            ]
            if bump:
                who = (
                    "org-bot's bump"
                    if bump[0]["head"]["ref"].startswith("org-bot/")
                    else "a hand bump"
                )
                r.add(
                    "WARN",
                    f"lock: {where} locks {have}; {who} "
                    f"{c['full_name']}#{bump[0]['number']} is open (shepherd it)",
                )
            else:
                task = "swarm-core-pin" if entry["name"] == "swarm-core.lock" else "release-lock"
                r.add(
                    "WARN",
                    f"lock: {where} locks {have}, no bump PR open: org-bot's `{task}` task "
                    "opens it within the hour (dispatch org-bot with that task to run it now); "
                    "an asset the release renamed makes it fail, and then the bump is a hand "
                    'PR (release_lock.py render, CONTRIBUTING "Dependencies")',
                )
    flows = []
    # the workflows as they were at the tag: what that release ran
    for entry in gh.get(f"repos/{repo}/contents/.github/workflows?ref={tag}") or []:
        if isinstance(entry, dict) and entry.get("name", "").endswith((".yml", ".yaml")):
            flows.append((entry["name"], contents_text(gh, repo, entry["path"], ref=tag) or ""))
    callers = caller_workflows(flows) or [(n, t) for n, t in flows if n == "release.yml"]
    inputs = {}
    for _, t in callers:
        inputs.update(with_inputs(t))
    ports = sorted(set(inputs.get("vcpkg-ports", "").split()))
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
        wd = inputs.get("working-directory", "").strip("./")
        project = pyproject_name(lambda p: contents_text(gh, repo, p, ref=tag), wd)[0]
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
        if any(SHIPPED.search(row) and not NOT_SHIPPED.search(row) for row in rows):
            r.add("OK", f"ladder: docs/roadmap.md marks {tag} shipped")
        else:
            r.add(
                "WARN",
                f"ladder: docs/roadmap.md does not mark {tag} shipped; org-bot's "
                "release-aftercare opens that PR (the shipped block, the version DOI read "
                "from Zenodo) within the hour once Zenodo has it (swarm-routing/.github#465)",
            )
    if zenodo_opted_out(contents_text(gh, repo, ".github/org-sync.toml")):
        r.add("OK", "zenodo: none (zenodo = false: no Zenodo archive, swarm-routing/.github#811)")
    else:
        r.add(
            "NEXT",
            f"zenodo: python3 -I tools/zenodo/zenodo.py status --repo {repo} (the version DOI "
            "from Zenodo, never typed; missing after the grace period: sync --dry-run, then ask)",
        )
    return r


def zenodo_opted_out(toml_text):
    """Whether an org-sync config sets the top-level `zenodo = false` (#811)."""
    try:
        return tomllib.loads(toml_text or "").get("zenodo", True) is False
    except tomllib.TOMLDecodeError:
        return False


# --- self-test --------------------------------------------------------------


class FakeGh:
    def __init__(self, routes, urls=None):
        self.routes, self.urls = routes, urls or {}

    def get(self, path):
        m = re.match(r"^(.*)[?&]per_page=100&page=(\d+)$", path)
        if not m:
            return self.routes.get(path)
        rows = self.routes.get(m.group(1))  # a list route, served 100 a page
        n = int(m.group(2))
        return None if rows is None else rows[100 * (n - 1) : 100 * n]

    def get_all(self, path):
        return paged(self.get, path)

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
        "      increment: ${{ inputs.increment != 'auto' && inputs.increment || '' }}\n"
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
                "repos/o/r/issues?state=open&labels=release:v0.4.0": [
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
        expect(
            "ready: a caller with no head-commit gate passes the push gate (#943)",
            has(rep, "OK", "push gate: not on the head commit alone"),
        )
        gated = caller.replace(
            "    uses:",
            "    if: \"${{ github.event_name != 'push' || startsWith(github.event.head_commit.message, "
            "'chore(release): bump version ') }}\"\n    uses:",
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(gated)
        rep = quiet(ready, d, "o/r", "0.4.0", gh)
        expect(
            "ready: a gate on the head commit's message fails (a batched push skips the release, #943)",
            has(rep, "FAIL", "push gate: .github/workflows/release.yml gates the release on"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(
                gated.replace("head_commit.message", "x").replace(
                    "    if:", "    # head_commit.message\n    if:"
                )
            )
        rep = quiet(ready, d, "o/r", "0.4.0", gh)
        expect(
            "ready: head_commit in a comment is no gate",
            has(rep, "OK", "push gate: not on the head commit alone"),
        )
        observed = (
            caller.replace(
                "    uses:",
                "    if: \"${{ github.event_name != 'push' || contains(toJSON(github.event.commits.*.message), "
                "'chore(release): bump version ') }}\"\n    uses:",
            )
            + "  notify:\n    runs-on: ubuntu-24.04\n    steps:\n      - env:\n"
            '          MSG: ${{ github.event.head_commit.message }}\n        run: echo "$MSG"\n'
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(observed)
        rep = quiet(ready, d, "o/r", "0.4.0", gh)
        expect(
            "ready: a push-wide gate passes, a head_commit read outside an if: is no gate",
            has(rep, "OK", "push gate: not on the head commit alone"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(caller)
        expect("ready: the ladder row v0.4.0", has(rep, "OK", "has v0.4.0"))
        expect("ready: a caller forwarding increment", has(rep, "OK", "increment"))
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
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(caller.replace("increment", "# increment"))
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: a caller that drops increment fails (#512)",
            has(rep, "FAIL", "caller does not forward the `increment` input"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(caller + caller.split("jobs:\n", 1)[1].replace("release:", "again:"))
        with open(os.path.join(d, ".github/workflows/other.yml"), "w", encoding="utf-8") as fh:
            fh.write(caller.replace("increment", "# increment"))
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: one caller of several that drops increment is named, the others not",
            has(rep, "FAIL", "other.yml (call 1): the caller does not forward")
            and not has(rep, "FAIL", "release.yml (call"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(
                caller
                + caller.split("jobs:\n", 1)[1]
                .replace("release:", "again:")
                .replace("increment", "# increment")
            )
        os.remove(os.path.join(d, ".github/workflows/other.yml"))
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: the second of two calls in one file that drops increment fails",
            has(rep, "FAIL", "release.yml (call 2)") and not has(rep, "FAIL", "(call 1)"),
        )
        own = "on:\n  workflow_dispatch:\n    inputs:\n      mode: {type: string}\njobs: {}\n"
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(own)
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: an own release.yml without inputs.increment fails",
            has(rep, "WARN", "an own") and has(rep, "FAIL", "never reads `inputs.increment`"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(own + "# cz bump --increment ${{ inputs.increment }}\n")
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: inputs.increment only in a comment is no read",
            has(rep, "FAIL", "never reads `inputs.increment`"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(
                own.replace("jobs: {}\n", "")
                + "jobs:\n  propose:\n    steps:\n      - env:\n"
                + "          INCREMENT: ${{ inputs.increment }}   # forced size\n"
                + '        run: cz bump --yes ${INCREMENT:+--increment "$INCREMENT"}\n'
            )
        rep = quiet(ready, d, None, None, gh)
        expect("ready: an own release.yml reading inputs.increment", has(rep, "OK", "increment"))
        expect(
            "ready: an own release.yml that builds nothing into dist/ fails build",
            has(rep, "FAIL", "build: no `dist:` target"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "a", encoding="utf-8") as fh:
            fh.write("      # tools/release/assemble.sh 1.0.0 dist\n")
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: dist only in a comment is no build",
            has(rep, "FAIL", "build: no `dist:` target"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "a", encoding="utf-8") as fh:
            fh.write('      - run: |\n          tools/release/assemble.sh "$VER" dist\n')
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: an own release.yml assembling into dist/ builds (AntHocNet)",
            has(rep, "OK", "build: the own release.yml builds its assets into dist/"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(
                own.replace("jobs: {}\n", "")
                + "jobs:\n  propose:\n    steps:\n      - env:\n"
                + "          INCREMENT: ${{ inputs.increment }}\n"
                + "        run: |\n          mkdir -p ./dist/\n          cp out/* ./dist/\n"
            )
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: ./dist/ is the same path as dist/",
            has(rep, "OK", "build: the own release.yml builds its assets into dist/"),
        )
        expect(
            "ready: no C++, no vcpkg line (#882)",
            not any(m.startswith("vcpkg:") for _, m in rep.lines),
        )
        os.makedirs(os.path.join(d, "core"))
        with open(os.path.join(d, "core", "CMakeLists.txt"), "w", encoding="utf-8") as fh:
            fh.write("project(r-core CXX)\n")
        with open(os.path.join(d, ".github/workflows/release.yml"), "a", encoding="utf-8") as fh:
            fh.write("      # vcpkg: tools/port_bump.py, later\n")
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: a core/ CMake project whose own release.yml names vcpkg only in a comment fails",
            has(rep, "FAIL", "vcpkg: the repository ships C++ (core/)"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "a", encoding="utf-8") as fh:
            fh.write("      - run: python3 registry/tools/port_bump.py bump --port r-core\n")
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: an own release.yml with a vcpkg step passes (AntHocNet)",
            has(rep, "OK", "own release.yml has a vcpkg step"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(caller)
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: a core/ caller with vcpkg-ports passes",
            has(rep, "OK", "vcpkg: C++ (core/) released as port(s) swarm-core"),
        )
        with open(os.path.join(d, ".github/workflows/release.yml"), "w", encoding="utf-8") as fh:
            fh.write(caller.replace("vcpkg-ports: swarm-core", "vcpkg-ports: ''"))
        for mod, text in (
            ("ns3", "build_lib(\n  LIBNAME r\n  SOURCE_FILES model/r.cc\n)\n"),
            ("build/ns3", "build_lib(LIBNAME stale)\n"),
            ("docs", "# build_lib( in a comment\n"),
        ):
            os.makedirs(os.path.join(d, mod), exist_ok=True)
            with open(os.path.join(d, mod, "CMakeLists.txt"), "w", encoding="utf-8") as fh:
                fh.write(text)
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: an empty vcpkg-ports fails, naming core/ and the ns-3 module, not build/",
            has(rep, "FAIL", "ships C++ (core/, ns3/) but its release sets no `vcpkg-ports`")
            and rep.failed(),
        )
        os.remove(os.path.join(d, "core", "CMakeLists.txt"))
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: an ns-3 module alone fails without vcpkg-ports",
            has(rep, "FAIL", "ships C++ (ns3/)"),
        )
        shutil.rmtree(os.path.join(d, "ns3"))
        for fx in (
            "test/fixtures/hello",
            "tests/x",
            "testdata/y",
            "examples/z",
            "ns3/test/t",
            "skills/x/evals/e/files/ns3/m",
        ):
            os.makedirs(os.path.join(d, fx), exist_ok=True)
            with open(os.path.join(d, fx, "CMakeLists.txt"), "w", encoding="utf-8") as fh:
                fh.write("build_lib(LIBNAME fixture)\n")
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: C++ only under test/, tests/, testdata/, examples/, evals/ ships nothing (#932)",
            not any(m.startswith("vcpkg:") for _, m in rep.lines),
        )
        os.makedirs(os.path.join(d, "core"), exist_ok=True)
        with open(os.path.join(d, "core", "CMakeLists.txt"), "w", encoding="utf-8") as fh:
            fh.write("project(r-core CXX)\n")
        rep = quiet(ready, d, None, None, gh)
        expect(
            "ready: fixtures beside a core/ without vcpkg-ports still fails, naming only core/",
            has(rep, "FAIL", "ships C++ (core/) but its release sets no `vcpkg-ports`"),
        )
    flow = (
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "  release:\n"
        "    # uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main\n"
        "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main\n"
        "    with:\n"
        "      working-directory: python   # the package\n"
        "      vcpkg-ports: >-\n"
        "        swarm-core\n"
        "        ara-core\n"
        "      # build: make wheel\n"
        "  other:\n"
        "    with:\n"
        "      build: not ours\n"
    )
    got = with_inputs(flow)
    expect(
        "with_inputs: the caller's inputs, a folded block, comments and other jobs left out",
        got == {"working-directory": "python", "vcpkg-ports": "swarm-core ara-core"},
    )
    expect(
        "with_inputs: a commented-out caller is no caller",
        not with_inputs(
            "jobs:\n  r:\n    # uses: swarm-routing/.github/.github/workflows/"
            "reusable-release.yml@main\n    with:\n      build: x\n"
        )
        and not caller_workflows(
            [
                (
                    "a.yml",
                    "#  uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main\n",
                )
            ]
        ),
    )
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github", "workflows"))
        os.makedirs(os.path.join(d, "python"))
        files = {
            ".github/workflows/release.yml": flow,
            "python/pyproject.toml": '[tool.commitizen]\nversion = "1.0.0"\ntag_format = "v$version"\n',
            "Makefile": "dist:\n\ttrue\n",
        }
        for p, t in files.items():
            with open(os.path.join(d, p), "w", encoding="utf-8") as fh:
                fh.write(t)
        rep = quiet(ready, d, "o/gone", "1.1.0", FakeGh({}))
        expect(
            "ready: the working-directory's Commitizen config",
            has(rep, "OK", "python/pyproject.toml, version 1.0.0"),
        )
        expect(
            "ready: make dist is looked for in the working-directory, a `build:` job is no input",
            has(rep, "FAIL", "build: no `dist:` target"),
        )
        expect(
            "ready: an unreadable --repo fails the scope, never OK",
            has(rep, "FAIL", "cannot read o/gone's issues") and not has(rep, "OK", "scope"),
        )
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "docs"))
        with open(os.path.join(d, "docs", "roadmap.md"), "w", encoding="utf-8") as fh:
            fh.write("| v0.3.0 | shipped |\n| v0.4.0 | planned |\n")
        expect("ladder: the version's row", not quiet(ladder, d, "0.4.0").failed())
        with open(os.path.join(d, "docs", "roadmap.md"), "a", encoding="utf-8") as fh:
            fh.write(
                '| v0.4.1 | prerequisites for v0.5.0 |\n| **v0.6.0** "gated" | x |\n## v0.7.0\n'
            )
        expect(
            "ladder: a row that only mentions the version is not its row",
            quiet(ladder, d, "0.5.0").failed(),
        )
        expect(
            "ladder: a bold first cell and a heading are rows",
            not quiet(ladder, d, "0.6.0").failed() and not quiet(ladder, d, "0.7.0").failed(),
        )
        rep = quiet(ladder, d, "0.5.0")
        expect(
            "ladder: a version missing from the ladder fails (#430)",
            rep.failed() and has(rep, "FAIL", "no row for v0.5.0"),
        )
        expect(
            "ladder: exit 1 on a missing row",
            quiet(main, ["ladder", d, "--version", "v0.5.0"]) == 1,
        )
        expect("ladder: exit 0 on its row", quiet(main, ["ladder", d, "--version", "0.4.0"]) == 0)
        os.remove(os.path.join(d, "docs", "roadmap.md"))
        rep = quiet(ladder, d, "0.5.0")
        expect(
            "ladder: no ladder warns, never fails",
            not rep.failed() and has(rep, "WARN", "no docs/roadmap.md"),
        )
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
            "body": "## v0.4.0 (2026-11-15)\n\n### Feat\n\n- x\n\n## Verify your download\n\n...\n",
            "assets": [
                {"name": "r-0.4.0.tar.gz"},
                {"name": "SHA256SUMS"},
                {"name": "r-0.4.0.intoto.jsonl"},
            ],
        },
        f"repos/{SITE}/issues?state=all&sort=created": [
            {"number": 155, "title": "[release-sync] r v0.4.0"}
        ],
        "orgs/o/repos?type=public": [
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
        "repos/o/b/pulls?state=open": [
            {
                "number": 3,
                "title": "chore: apply the org templates (org-bot)",
                "head": {"ref": "org-bot/org-sync-1"},
            },
            {
                "number": 4,
                "title": "chore(core): bump the swarm-core pin (org-bot)",
                "head": {"ref": "org-bot/swarm-core-pin", "sha": "c0ffee"},
            },
        ],
        "repos/o/b/pulls/3/files": [{"filename": ".github/workflows/org-sync.yml"}],
        "repos/o/b/pulls/4/files": [{"filename": "swarm-core.lock"}, {"filename": "Makefile"}],
        "repos/o/b/contents/swarm-core.lock?ref=c0ffee": b64(lock_new),
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
    expect("after: org-bot's PR is named as org-bot's", has(rep, "WARN", "org-bot's bump o/b#4"))
    hand_routes = dict(routes)
    hand_routes["repos/o/b/pulls?state=open"] = [
        {"number": 6, "title": "chore(deps): bump", "head": {"ref": "claude/x", "sha": "c0ffee"}}
    ]
    hand_routes["repos/o/b/pulls/6/files"] = [{"filename": "swarm-core.lock"}]
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(hand_routes), ["b"])
    expect("after: a hand bump PR counts as the bump (#478)", has(rep, "WARN", "a hand bump o/b#6"))
    rep = quiet(after, "o/r", "v0.4.0", "o", gh)
    expect(
        "after: an unrelated lock and an archived repository are skipped",
        not any("o/c" in m or "o/old" in m for _, m in rep.lines),
    )
    expect("after: the vcpkg port with its open registry PR", has(rep, "WARN", f"{REGISTRY}#9"))
    expect("after: PyPI has the version", has(rep, "OK", "r-tools 0.4.0 is on PyPI"))
    expect("after: the ladder not marked shipped", has(rep, "WARN", "does not mark v0.4.0"))
    expect("after: zenodo is a NEXT step", has(rep, "NEXT", "zenodo.py status --repo o/r"))
    out_routes = dict(routes)
    out_routes["repos/o/r/contents/.github/org-sync.toml"] = b64(
        'kind = "skills"\nzenodo = false\n[settings]\nhomepage = ""\n'
    )
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(out_routes, gh.urls))
    expect(
        "after: zenodo = false, no Zenodo step (#811)",
        has(rep, "OK", "zenodo = false") and not any("zenodo.py" in m for _, m in rep.lines),
    )
    expect("after: the notes are not empty", has(rep, "OK", "notes: v0.4.0 has notes"))
    expect("after: no FAIL", not rep.failed())

    routes["repos/o/r/releases/tags/v0.4.0"] = {
        "draft": False,
        "body": "## v0.4.0 (2026-11-16)\n\n\n## Verify your download\n\n...\n",  # BeeAdHoc v0.2.1's shape
        "assets": [{"name": "x.tar.gz"}],
    }
    del routes[f"repos/{REGISTRY}/pulls?state=open&head=swarm-routing:bot/vcpkg-r"]
    routes[f"repos/{SITE}/issues?state=all&sort=created"] = []
    routes["repos/o/b/pulls?state=open"] = []
    routes["repos/o/r/contents/docs/roadmap.md"] = b64("| v0.4.0 | shipped 2026-11-15 |\n")
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(routes))
    expect(
        "after: missing SHA256SUMS and provenance fail",
        has(rep, "FAIL", "lacks SHA256SUMS, *.intoto.jsonl"),
    )
    expect("after: no vcpkg PR fails", has(rep, "FAIL", "no bot/vcpkg-r PR"))
    expect(
        "after: empty notes fail with the release-notes dispatch",
        has(rep, "FAIL", "notes are empty") and has(rep, "FAIL", "mode=release-notes tag=v0.4.0"),
    )
    expect("after: not on PyPI fails", has(rep, "FAIL", "not on PyPI"))
    expect("after: no site issue warns with the dispatch", has(rep, "WARN", "release-sync.yml"))
    expect(
        "after: a stale consumer with no bump PR warns",
        has(rep, "WARN", "no bump PR open: org-bot's `swarm-core-pin`"),
    )
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
    nowhere = os.path.join(tempfile.mkdtemp(), "ROADMAP.md")
    rep = quiet(after, "o/r", "v0.4.0", "o", Refused(routes), None, nowhere)
    expect("after: an org listing refused warns and names --repos", has(rep, "WARN", "--repos"))
    with open(nowhere, "w") as fh:
        fh.write(
            "<!-- epics:begin -->\n### [a](https://github.com/swarm-routing/a)\n<!-- epics:end -->\n"
        )
    rep = quiet(after, "o/r", "v0.4.0", "o", Refused(routes), None, nowhere)
    expect(
        "after: an org listing refused falls back to ROADMAP.md#epics (#478)",
        has(rep, "OK", "from ROADMAP.md#epics (1)") and has(rep, "OK", "o/a swarm-core.lock"),
    )
    # an org-bot PR that changes the lock, but to another tag, is not the bump
    routes["repos/o/b/pulls?state=open"] = [
        {"number": 5, "title": "x", "head": {"ref": "org-bot/swarm-core-pin", "sha": "beef"}}
    ]
    routes["repos/o/b/pulls/5/files"] = [{"filename": "swarm-core.lock"}]
    routes["repos/o/b/contents/swarm-core.lock?ref=beef"] = b64(lock_old)
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(routes), ["b"])
    expect(
        "after: an org-bot PR whose lock names another tag is not the bump",
        has(rep, "WARN", "no bump PR open"),
    )
    routes["repos/o/r/contents/docs/roadmap.md"] = b64("| v0.4.0 | not shipped yet |\n")
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(routes), [])
    expect("after: 'not shipped' is not shipped", has(rep, "WARN", "does not mark v0.4.0"))
    # pagination: the site issue on the second page
    routes[f"repos/{SITE}/issues?state=all&sort=created"] = [
        {"number": n, "title": f"other {n}"} for n in range(150)
    ] + [{"number": 999, "title": "[release-sync] r v0.4.0"}]
    rep = quiet(after, "o/r", "v0.4.0", "o", FakeGh(routes), [])
    expect("after: a list read past its first page", has(rep, "OK", f"{SITE}#999"))
    rep = quiet(after, "o/r", "v9.9.9", "o", FakeGh({}))
    expect("after: no release fails", has(rep, "FAIL", "no published GitHub release v9.9.9"))

    # --- the preflight: the sim-tools v1.1.3 dry runs (ns3-tools renamed sim-tools) ---
    class Run:
        """subprocess.run for next_version: `git tag` lists tags, `cz` answers or is missing."""

        def __init__(self, tags, cz=None, rc=0):
            self.tags, self.cz, self.rc, self.calls = tags, cz, rc, []

        def __call__(self, cmd, **kw):
            self.calls.append(cmd)
            if cmd[0] == "git":
                return subprocess.CompletedProcess(cmd, 0, self.tags, "")
            if self.cz is None:
                raise FileNotFoundError("cz")
            return subprocess.CompletedProcess(cmd, self.rc, self.cz, "")

    r = Report()
    fake = Run("v1.1.2\n", "1.1.3\n")
    v = quiet(next_version, ".", "", "PATCH", False, r, fake)
    expect(
        "next_version: cz bump --get-next with the increment",
        v == "1.1.3" and fake.calls[-1][-2:] == ["--increment", "PATCH"],
    )
    r = Report()
    expect(
        "next_version: no v* tag is 0.1.0",
        quiet(next_version, ".", "", None, False, r, Run("")) == "0.1.0",
    )
    r = Report()
    expect(
        "next_version: no v* tag, MAJOR asks Commitizen",
        quiet(next_version, ".", "", "MAJOR", False, r, Run("", "1.0.0\n")) == "1.0.0",
    )
    r = Report()
    expect(
        "next_version: nothing that bumps (exit 21) warns, no version",
        quiet(next_version, ".", "", None, False, r, Run("v1.0.0\n", "", 21)) is None
        and has(r, "WARN", "exited 21"),
    )
    r = Report()
    expect(
        "next_version: no Commitizen warns, never fails",
        quiet(next_version, ".", "", None, False, r, Run("v1.0.0\n")) is None
        and has(r, "WARN", "not installed")
        and not r.failed(),
    )

    renamed = {
        "repos/swarm-routing/ns3-tools": {"full_name": "swarm-routing/sim-tools"},
        "repos/swarm-routing/sim-tools": {"full_name": "swarm-routing/sim-tools"},
        "repos/someone/else": {"full_name": "someone/else"},
    }
    consumers = (
        "{} | swarm-routing/sim-tools@main | 3.42+ | routing-bench={}/ns3/routing-bench | | |\n"
        "AntHocNet | swarm-routing/AntHocNet@main | 3.36+ | anthocnet=AntHocNet/ns3 | | |\n"
    )
    pypi_job = (
        "  pypi:\n    needs: release\n"
        "    environment: ${{ x == 'release' && 'release' || 'dry-run' }}\n"
        "    steps:\n      - uses: pypa/gh-action-pypi-publish@0 # v1\n"
        "        with:\n          repository-url: ${{ x && 'https://upload.pypi.org/legacy/'"
        " || 'https://test.pypi.org/legacy/' }}\n"
    )
    project = '[project]\nname = "swarm-sim-tools"\n'
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github", "workflows"))
        os.makedirs(os.path.join(d, "python"))
        files = {
            ".github/workflows/release.yml": caller
            + "      downstream-consumers: .github/downstream.txt\n"
            + pypi_job,
            ".github/downstream.txt": consumers.format("ns3-tools", "ns3-tools"),
            "python/pyproject.toml": project,
        }
        for p, t in files.items():
            with open(os.path.join(d, p), "w", encoding="utf-8") as fh:
                fh.write(t)
        gh = FakeGh(renamed)
        rep = quiet(preflight, d, "swarm-routing/ns3-tools", gh)
        expect(
            "preflight: a renamed repository is named by its current name",
            has(rep, "WARN", "swarm-routing/ns3-tools was renamed swarm-routing/sim-tools"),
        )
        expect(
            "preflight: a consumer list without the current name fails (sim-tools v1.1.3)",
            has(rep, "FAIL", "'sim-tools' is not a consumer")
            and has(rep, "FAIL", "a line named `sim-tools`"),
        )
        expect(
            "preflight: a project not on PyPI or TestPyPI is a pending-publisher NEXT",
            has(rep, "NEXT", "swarm-sim-tools is not on PyPI yet")
            and has(rep, "NEXT", "https://test.pypi.org/manage/account/publishing/")
            and has(rep, "NEXT", "workflow release.yml, environment dry-run or release"),
        )
        with open(os.path.join(d, ".github/downstream.txt"), "w", encoding="utf-8") as fh:
            fh.write(consumers.format("sim-tools", "sim-tools"))
        pypi = {
            "https://pypi.org/pypi/swarm-sim-tools/json": {
                "info": {"project_urls": {"Source": "https://github.com/swarm-routing/ns3-tools"}}
            },
            "https://test.pypi.org/pypi/swarm-sim-tools/json": {
                "info": {"project_urls": {"Source": "https://github.com/swarm-routing/sim-tools"}}
            },
        }
        rep = quiet(preflight, d, "swarm-routing/sim-tools", FakeGh(renamed, pypi))
        expect(
            "preflight: the list names the repository by its current name",
            has(rep, "OK", "downstream: downstream.txt: 2 consumers, `sim-tools`"),
        )
        expect(
            "preflight: PyPI's project_urls naming the old name warn (invalid-publisher)",
            has(rep, "WARN", "names swarm-routing/ns3-tools, this repository's old name"),
        )
        expect(
            "preflight: TestPyPI's project_urls naming the repository pass",
            has(rep, "OK", "TestPyPI's swarm-sim-tools project_urls names swarm-routing/sim-tools"),
        )
        expect(
            "preflight: the trusted publisher is a NEXT with its settings page",
            has(
                rep, "NEXT", "https://pypi.org/manage/project/swarm-sim-tools/settings/publishing/"
            ),
        )
        expect("preflight: nothing definite, no FAIL", not rep.failed())
        pypi["https://pypi.org/pypi/swarm-sim-tools/json"]["info"]["project_urls"] = {
            "Home": "https://github.com/someone/else"
        }
        rep = quiet(preflight, d, "swarm-routing/sim-tools", FakeGh(renamed, pypi))
        expect(
            "preflight: a PyPI project of another repository fails",
            has(rep, "FAIL", "names someone/else, another repository"),
        )

        class Unreadable(FakeGh):
            def get(self, path):
                raise RuntimeError("HTTP 403")

        rep = quiet(preflight, d, "swarm-routing/sim-tools", Unreadable({}, {}))
        expect(
            "preflight: an unreadable GitHub API warns and keeps the given name",
            has(rep, "WARN", "cannot read swarm-routing/sim-tools")
            and has(rep, "OK", "`sim-tools` (this repository)")
            and not rep.failed(),
        )
        rep = quiet(preflight, d, "swarm-routing/sim-tools", gh, "nope.txt")
        expect(
            "preflight: a missing consumer list fails", has(rep, "FAIL", "nope.txt, no such file")
        )
        rep = quiet(preflight, d, "swarm-routing/sim-tools", gh, None, "AntHocNet")
        expect(
            "preflight: downstream-self names the repository's line",
            has(rep, "OK", "`AntHocNet` (this repository)"),
        )
        os.makedirs(os.path.join(d, "docs"))
        with open(os.path.join(d, "docs/roadmap.md"), "w", encoding="utf-8") as fh:
            fh.write("| v1.1.2 | shipped |\n| v1.2.0 | planned |\n")
        with open(os.path.join(d, ".cz.toml"), "w", encoding="utf-8") as fh:
            fh.write(cz)
        with open(os.path.join(d, "Makefile"), "w", encoding="utf-8") as fh:
            fh.write("dist:\n\ttrue\n")
        rep = quiet(ready, d, None, None, gh, "PATCH", Run("v1.1.2\n", "1.1.3\n"))
        expect(
            "ready: the bump's version, with no ladder row, fails before a dispatch (v1.1.3)",
            has(rep, "OK", "version: 1.1.3") and has(rep, "FAIL", "no row for v1.1.3"),
        )
        expect(
            "ready: runs the preflight (no --repo, no origin: a WARN)",
            has(rep, "WARN", "pass --repo") and has(rep, "WARN", "its own line is unchecked"),
        )
    expect(
        "url_repos: owner/name from URLs, .git and paths dropped",
        url_repos(["https://github.com/o/r.git", "https://github.com/o/s/issues", None])
        == {"o/r", "o/s"},
    )

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
    p.add_argument(
        "--version", help="X.Y.Z (default: what the bump would produce, cz bump --get-next)"
    )
    p.add_argument(
        "--increment", choices=["PATCH", "MINOR", "MAJOR"], help="the bump's forced size"
    )
    p = sub.add_parser(
        "preflight", help="the repository's name, its downstream line, its PyPI project"
    )
    p.add_argument("repo_dir")
    p.add_argument("--repo", help="OWNER/NAME (default: the checkout's origin)")
    p.add_argument("--downstream-consumers", help="the consumer list (default: the caller's input)")
    p.add_argument("--downstream-self", help="its line for this repository (default: its name)")
    p = sub.add_parser("ladder", help="the ladder gate alone: the version's docs/roadmap.md row")
    p.add_argument("repo_dir")
    p.add_argument("--version", required=True, help="X.Y.Z (a leading v is dropped)")
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
        if a.cmd == "ladder":
            rep = ladder(a.repo_dir, a.version.lstrip("v"))
        elif a.cmd == "ready":
            rep = ready(a.repo_dir, a.repo, (a.version or "").lstrip("v") or None, gh, a.increment)
        elif a.cmd == "preflight":
            rep = preflight(a.repo_dir, a.repo, gh, a.downstream_consumers, a.downstream_self)
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
