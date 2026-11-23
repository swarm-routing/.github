#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Repository settings as code: description, topics, merge and features, rulesets, security, Actions.

Usage:
  repo_settings.py plan  [REPO...] [--local DIR]
  repo_settings.py check [REPO...] [--local DIR]
  repo_settings.py apply [REPO...] [--local DIR] [--dry-run] [--org-only]
  repo_settings.py --self-test

Each repository declares its settings in the `[settings]` table of its own
`.github/org-sync.toml` (read through the contents API, or from
DIR/<repo>/.github/org-sync.toml with --local, its workflows from
DIR/<repo>/.github/):

    [settings]
    description = "One line, at most 350 characters."
    homepage = "https://swarm-routing.github.io/projects/ARA/"   # "" for none
    topics = ["manet", "ns-3"]          # lowercase-hyphenated, at most 20
    ruleset = "protocol"                # templates/rulesets/<profile>.json: protocol, tooling,
                                        # data, site, merge-only (no ruleset); "" for neither
    required_checks = ["CI gate"]       # check-run names that run on every PR
    optional_checks = ["codecov/*"]     # checks that may run on main without being required
                                        # (fnmatch patterns): `check` does not list them
    code_scanning = false               # true only where CodeQL uploads results
    merge_queue = false                 # true: PRs merge through a merge queue (public repos only);
                                        # a table overrides MERGE_QUEUE's values, e.g.
                                        # { check_response_timeout_minutes = 60 }
    merge_methods = ["squash", "merge"] # overrides the profile's merge methods (the repository's
                                        # allow_*_merge and the main ruleset's allowed_merge_methods);
                                        # absent: the profile's (squash only). For a one-time
                                        # history-preserving merge, reverted after it (swarm-core#6)
    features = { has_wiki = true }      # overrides the profile's repository features
    security = { codeql_default_setup = false }   # false: leave that feature alone
    release_environment = true          # create the `release` environment here; false: strip
                                        # the gate (reviewers, wait timer) from an existing one

    [settings.environments.gitlab-write]   # any other environment, one table each
    reviewers = ["danieljoppi"]         # required reviewers (users); absent or []: none
    branches = ["main"]                 # deployment branches; absent or []: any branch
    prevent_self_review = false         # default false

A repository with no org-sync templates carries a settings-only file (no
`kind`); org-sync and org-bot skip it.

`--org-only` (any command) refuses, before reading anything else, a named
repository that is not one of the org's (archived repositories and forks
excluded; matched without case, then used with the org's spelling). The
`repo-settings` workflow passes it for the name a repository_dispatch carries
(the org-managed settings-apply.yml sends it when a push to main changes
`.github/org-sync.toml`, #569), so the event can only name an org repository.

A profile (`templates/rulesets/<profile>.json`) holds the merge settings
(squash only, PR title and body as the squash commit, delete the branch on
merge) and the `main` branch ruleset in the REST API shape, and takes the
parts it does not hold itself from `templates/rulesets/defaults.json` (a key
set to null there or in the profile: that part is not managed):

- `features`: has_issues, has_projects, has_wiki, has_discussions,
  allow_auto_merge, allow_update_branch, written with the merge settings;
- `security`: Dependabot alerts and security updates, secret scanning and
  push protection, private vulnerability reporting, CodeQL default setup.
  Only ever turned on, never off. Unsupported on a private repository on the
  free plan (secret scanning, push protection, private vulnerability
  reporting, CodeQL): reported as such, not as drift. A repository whose own
  workflow runs `github/codeql-action/init` or `analyze` (advanced setup,
  which default setup would conflict with) keeps it. Once default setup is
  configured, every CodeQL language the repository holds
  (`repos/{full}/languages`, plus `actions` where it has workflows) is
  added to its `languages`, the query suite kept; a configured language
  with no code left is a note, never removed (ns3-upstream-report#70);
- `actions`: the Actions policy (enabled, allowed_actions `selected`, the
  allowed patterns, default `GITHUB_TOKEN` permissions read, no PR approval,
  and the fork-PR approval policy: workflows of a fork's PR wait for a
  maintainer's approval when its author is neither a collaborator nor an
  org member,
  `actions/permissions/fork-pr-contributor-approval`; public repositories
  only, a private one is a note).
  Every `uses:` in the repository's `.github/workflows` and `.github/actions`
  must be covered by the allowed list, or the repository is refused before
  anything is written (switching it to `selected` would break its CI);
- `tag_ruleset`: the `release-tags` ruleset (v* tags: no deletion, no
  force-push, no update);
- `release_environment`: the `release` environment with required
  reviewers, only where enabled (the profile, or `[settings]`). An explicit
  `release_environment = false` in `[settings]` turns the gate off: an
  existing `release` environment keeps its deployment branch policy but loses
  its required reviewers and wait timer (it is never deleted); absent, an
  existing environment is left alone.

`[settings.environments.<name>]` declares any other environment, in every
profile (a settings-only file too): its required reviewers (users, as the
`release` environment), whether a reviewer may approve a run they started
(`prevent_self_review`, default false, so the maintainer approves the runs
his own account triggers) and its deployment branches (`branches`: a custom
branch policy naming exactly those branches; absent or empty: any branch).
`apply` creates a missing environment, sets its reviewers and branch policy,
adds the missing branch policies and removes the ones it does not declare.
The `release` environment is `release_environment`'s alone: a table for it
next to that key is refused. An environment no table names is never touched,
and none is ever deleted. A private repository on the free plan has neither
reviewers nor branch policies: reported unsupported, not drift.

The `main` ruleset's `code_scanning` and `code_quality` rules are kept only
with `code_scanning = true` (a repository that never uploads CodeQL results
would hold every PR waiting for them), and `required_status_checks` takes
`required_checks` (GitHub Actions checks), dropped when there are none: a
required check that a `paths:` filter skips blocks a PR forever, so list
only always-running jobs. `merge_queue = true` adds the `merge_queue` rule
(MERGE_QUEUE: squash, every PR of a group green, groups of up to 5, a
120-minute check timeout for ns-3 CI; a table overrides any of them). It
needs a ruleset profile and `required_checks`, and the workflow producing each
required check (a workflow that runs on `pull_request` with no `paths:`
filter, with a job named, or with the id, the check's first ` / ` segment;
`${{ }}` in a name matches any text) must also run on `merge_group`, or the queue waits for a
check that never comes: a repository where one does not is refused before
anything is written, as for the Actions allowed list. GitHub offers merge
queues on public organization repositories (and private ones on Enterprise
Cloud only), so a private repository asking for one is refused.

Checks that ran on the head of the default branch (check runs that were not
skipped, and commit statuses) but are neither in `required_checks` nor matched
by `optional_checks` are listed as `<repo>: unrequired check: <name>` (a
private repository: only their number). It is information, never drift: a
check run on `main` may not run on every PR, and only such checks can be
required. Listed only where the profile has a `main` ruleset; the daily
workflow keeps one `[settings] <repo>: …` issue per listed repository (#177).

`plan` lists the differences between the live repository and its
declaration, `check` does the same and exits 1 on drift (or on a setting it
cannot read), `apply` writes only the differences (`--dry-run`: says what it
would write). A repository with no `[settings]` is never touched; the only
rulesets managed are those named in a profile (`main`, `release-tags`), and
none is ever deleted; neither is an environment (only a deployment branch
policy an environment's table no longer names is). Without REPO the org listing
is used (all repositories, not archived, not forks). The values of a private
repository are never printed, only which fields differ, and neither is its
name: it is `private repository N` (N in the order of the run), since the
output lands in a public log or issue (#622). A write the token is not allowed (HTTP 403 or
404: the token needs Administration: write; 409: an organization policy
overrides it) is reported as `refused` and `apply` exits 2; any other failure
exits 1.

The token comes from ORG_BOT_TOKEN, else GH_TOKEN (gh's own login), never
from the command line; GitHub is reached through `gh api`. A fine-grained
token needs, on every repository: Administration read and write (every
write, and reading the rulesets, security and Actions settings), Contents
read (org-sync.toml and the workflows), Actions read (the environments),
Checks read and Commit statuses read (the unrequired checks; unreadable is a
note, not drift), Metadata read. Output is one summary line per difference (AntHocNet
ADR-0014). Stdlib only; Python 3.11+.
"""

import argparse
import base64
import copy
import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES = os.path.join(ROOT, "templates", "rulesets")
DEFAULTS = "defaults"  # templates/rulesets/defaults.json: shared parts, not a profile
ORG = "swarm-routing"
CONFIG = ".github/org-sync.toml"
ACTIONS_APP = 15368  # GitHub Actions: the app every required check comes from
REPO_FIELDS = ("description", "homepage", "topics")
REPO_NAME = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}")  # GitHub's, never a leading "-"
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
RULESET_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors", "rules")
SCANNING_RULES = ("code_scanning", "code_quality")
# the `merge_queue` rule's parameters (REST rulesets API), sized for CI that takes 10-30 minutes
MERGE_QUEUE = {
    "merge_method": "SQUASH",  # as every PR: the squash title is the commit on main
    "grouping_strategy": "ALLGREEN",  # every PR of a group must pass, not only its head
    "check_response_timeout_minutes": 120,  # a required check slower than this fails the group
    "max_entries_to_build": 5,  # queued PRs whose checks run at once: leaves runners for PR CI
    "min_entries_to_merge": 1,  # a lone PR merges without waiting for others
    "min_entries_to_merge_wait_minutes": 5,  # GitHub's default; idle while the minimum is 1
    "max_entries_to_merge": 5,  # PRs merged together in one group at most
}
# [settings] merge_methods -> the repository flag each one sets (REST repos API)
MERGE_METHODS = {
    "squash": "allow_squash_merge",
    "merge": "allow_merge_commit",
    "rebase": "allow_rebase_merge",
}
MERGE_QUEUE_ENUMS = {
    "merge_method": ("MERGE", "SQUASH", "REBASE"),
    "grouping_strategy": ("ALLGREEN", "HEADGREEN"),
}
MERGE_QUEUE_RANGES = {  # the REST API's bounds
    "check_response_timeout_minutes": (1, 360),
    "max_entries_to_build": (0, 100),
    "min_entries_to_merge": (0, 100),
    "min_entries_to_merge_wait_minutes": (0, 360),
    "max_entries_to_merge": (0, 100),
}
MERGE_GROUP = re.compile(r"^\s*merge_group\s*:|^on:\s*\[[^\]]*\bmerge_group\b", re.M)
# GitHub's values for the fork-PR approval policy, loosest first
FORK_PR_POLICIES = (
    "first_time_contributors_new_to_github",
    "first_time_contributors",
    "all_external_contributors",
)
SHARED = ("features", "security", "actions", "tag_ruleset", "release_environment")
ENV_NAME = re.compile(r"[A-Za-z0-9._-]{1,255}")
ENV_KEYS = ("reviewers", "branches", "prevent_self_review")
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
# the only DELETE the tool sends: a deployment branch policy an environment no longer declares
DELETABLE = re.compile(rf"repos/{ORG}/[^/]+/environments/[^/]+/deployment-branch-policies/\d+")
FEATURES = (
    "has_issues",
    "has_projects",
    "has_wiki",
    "has_discussions",
    "allow_auto_merge",
    "allow_update_branch",
)
# in the order they are written: security updates need alerts, push protection needs scanning
SECURITY = (
    "vulnerability_alerts",
    "automated_security_fixes",
    "secret_scanning",
    "secret_scanning_push_protection",
    "private_vulnerability_reporting",
    "codeql_default_setup",
)
PRIVATE_UNSUPPORTED = (
    "secret_scanning",
    "secret_scanning_push_protection",
    "private_vulnerability_reporting",
    "codeql_default_setup",
)
WORKFLOW_FILE = re.compile(r"^\.github/(workflows/[^/]+|actions/.+/action)\.ya?ml$")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^'\"\s#]+)", re.M)
API_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~/?&=%-]*")  # never a flag, never a space
CODEQL = re.compile(r"github/codeql-action/(init|analyze)@", re.I)
# GitHub linguist names -> the language ids CodeQL default setup takes
# (docs.github.com, REST "Update a code scanning default setup configuration")
CODEQL_LANGUAGE = {
    "C": "c-cpp",
    "C++": "c-cpp",
    "C#": "csharp",
    "Go": "go",
    "Java": "java-kotlin",
    "Kotlin": "java-kotlin",
    "JavaScript": "javascript-typescript",
    "TypeScript": "javascript-typescript",
    "Python": "python",
    "Ruby": "ruby",
    "Swift": "swift",
}
# older ids default setup may still report for a configured language
CODEQL_SAME = {"javascript": "javascript-typescript", "typescript": "javascript-typescript"}


class GhError(Exception):
    def __init__(self, method, path, stderr):
        m = re.search(r"\(HTTP (\d{3})\)", stderr)
        self.status = int(m.group(1)) if m else 0
        super().__init__(f"gh api {method} {path}: {stderr.strip()}")


class GitHub:
    def __init__(self):
        self.env = dict(os.environ)
        if os.environ.get("ORG_BOT_TOKEN"):
            self.env["GH_TOKEN"] = os.environ["ORG_BOT_TOKEN"]

    def api(self, method, path, body=None):
        if method == "DELETE" and not DELETABLE.fullmatch(path):
            raise GhError(method, path, "refused: the only DELETE is a deployment branch policy")
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE") or not API_PATH.fullmatch(path):
            raise GhError(method, path, "refused: not a plain API path")
        cmd = ["gh", "api", "-X", method, path]
        if body is not None:
            cmd += ["--input", "-"]
        r = subprocess.run(
            cmd,
            input=json.dumps(body) if body is not None else None,
            capture_output=True,
            text=True,
            env=self.env,
        )
        if r.returncode != 0:
            raise GhError(method, path, r.stderr or r.stdout)
        return json.loads(r.stdout) if r.stdout.strip() else {}


# --- declared state ------------------------------------------------------------


def load_profile(name):
    path = os.path.join(PROFILES, f"{name}.json")
    if not re.fullmatch(r"[a-z0-9-]+", name) or name == DEFAULTS or not os.path.exists(path):
        raise ValueError(f"unknown ruleset profile {name!r} (templates/rulesets/)")
    with open(path, encoding="utf-8") as f:
        prof = json.load(f)
    with open(os.path.join(PROFILES, f"{DEFAULTS}.json"), encoding="utf-8") as f:
        shared = json.load(f)
    for k in SHARED:
        prof.setdefault(k, shared[k])  # a key the profile holds, null included, wins
    return prof


def read_settings(gh, repo, local=None):
    """The repository's `[settings]` table, or None when it declares none."""
    if local:
        root = os.path.realpath(local)
        path = os.path.realpath(os.path.join(root, repo, CONFIG))
        if os.path.commonpath([root, path]) != root:
            raise ValueError(f"{repo}: {CONFIG} resolves outside {local}")
        try:
            with open(path, "rb") as f:
                text = f.read().decode()
        except FileNotFoundError:
            return None
    else:
        try:
            got = gh.api("GET", f"repos/{ORG}/{repo}/contents/{CONFIG}")
        except GhError as e:
            if e.status == 404:
                return None
            raise
        text = base64.b64decode(got.get("content", "")).decode()
    return tomllib.loads(text).get("settings")


def read_workflows(gh, repo, branch, local=None):
    """{path: text} of the repository's workflows and composite actions."""
    if local:
        root = os.path.realpath(local)
        base = os.path.realpath(os.path.join(root, repo))
        if os.path.commonpath([root, base]) != root:
            raise ValueError(f"{repo}: resolves outside {local}")
        out = {}
        for pattern in (".github/workflows/*.y*ml", ".github/actions/**/action.y*ml"):
            for p in glob.glob(os.path.join(base, pattern), recursive=True):
                p = os.path.realpath(p)
                rel = os.path.relpath(p, base).replace(os.sep, "/")
                if os.path.commonpath([base, p]) == base and WORKFLOW_FILE.match(rel):
                    with open(p, encoding="utf-8") as f:
                        out[rel] = f.read()
        return out
    branch = urllib.parse.quote(branch, safe="")
    try:
        tree = gh.api("GET", f"repos/{ORG}/{repo}/git/trees/{branch}?recursive=1")
    except GhError as e:
        if e.status in (404, 409):  # no branch, or an empty repository
            return {}
        raise
    if tree.get("truncated"):
        # a partial list could miss a `uses:` or a CodeQL workflow: never plan on it
        raise ValueError(f"{repo}: the git tree is truncated, so its workflows cannot be listed")
    out = {}
    for t in tree.get("tree", []):
        if t.get("type") == "blob" and WORKFLOW_FILE.match(t["path"]):
            path = urllib.parse.quote(t["path"], safe="/")
            got = gh.api("GET", f"repos/{ORG}/{repo}/contents/{path}?ref={branch}")
            out[t["path"]] = base64.b64decode(got.get("content", "")).decode()
    return out


def validate(s, private=False):
    """What is wrong with a settings table; a private repository's values stay out of it."""
    errors = []
    if len(s.get("description", "")) > 350:
        errors.append("description is longer than 350 characters")
    topics = s.get("topics", [])
    if len(topics) > 20:
        errors.append("more than 20 topics")
    errors += [
        "a topic is not lowercase-hyphenated"
        if private
        else f"topic {t!r} is not lowercase-hyphenated"
        for t in topics
        if not TOPIC.match(t)
    ]
    if s.get("required_checks") and not s.get("ruleset"):
        errors.append("required_checks without a ruleset profile")
    opt = s.get("optional_checks", [])
    if not isinstance(opt, list) or not all(isinstance(c, str) and c for c in opt):
        errors.append("optional_checks is not a list of check names")
    mq = s.get("merge_queue", False)
    if type(mq) is not bool and not isinstance(mq, dict):
        errors.append("merge_queue is not true, false or a table")
    elif isinstance(mq, dict):
        for k, v in mq.items():
            if k in MERGE_QUEUE_ENUMS:
                if v not in MERGE_QUEUE_ENUMS[k]:
                    errors.append(
                        f"merge_queue.{k} is not one of {', '.join(MERGE_QUEUE_ENUMS[k])}"
                    )
            elif k in MERGE_QUEUE_RANGES:
                lo, hi = MERGE_QUEUE_RANGES[k]
                if type(v) is not int or not lo <= v <= hi:
                    errors.append(f"merge_queue.{k} is not an integer from {lo} to {hi}")
            else:
                errors.append(f"merge_queue.{k} is not one of {', '.join(MERGE_QUEUE)}")
        p = {**MERGE_QUEUE, **mq}
        if type(p["min_entries_to_merge"]) is int and type(p["max_entries_to_merge"]) is int:
            if p["min_entries_to_merge"] > p["max_entries_to_merge"]:
                errors.append("merge_queue.min_entries_to_merge is above max_entries_to_merge")
    if mq is not False:
        if not s.get("ruleset") or not s.get("required_checks"):
            errors.append("merge_queue without a ruleset profile and required_checks")
        else:
            try:
                no_main = load_profile(s["ruleset"])["ruleset"] is None
            except ValueError:
                no_main = False  # an unknown profile fails on its own in desired()
            if no_main:
                errors.append(
                    f"merge_queue with the {s['ruleset']} profile, which has no main ruleset"
                )
        if private:
            errors.append("merge_queue on a private repository (public organization repos only)")
    mm = s.get("merge_methods")
    if mm is not None:
        if (
            not isinstance(mm, list)
            or not mm
            or len(set(mm)) != len(mm)
            or not all(m in MERGE_METHODS for m in mm)
        ):
            errors.append(f"merge_methods is not a non-empty list of {', '.join(MERGE_METHODS)}")
        elif not s.get("ruleset"):
            errors.append("merge_methods without a ruleset profile")
        elif isinstance(mq, dict) or mq is True:
            method = {**MERGE_QUEUE, **(mq if isinstance(mq, dict) else {})}["merge_method"]
            if isinstance(method, str) and method.lower() not in mm:
                errors.append(f"merge_queue.merge_method {method} is not in merge_methods")
    for table, allowed in (("features", FEATURES), ("security", SECURITY)):
        t = s.get(table, {})
        if not isinstance(t, dict):
            errors.append(f"{table} is not a table")
            continue
        errors += [f"{table}.{k} is not one of {', '.join(allowed)}" for k in t if k not in allowed]
        errors += [f"{table}.{k} is not true or false" for k, v in t.items() if type(v) is not bool]
    if "release_environment" in s and type(s["release_environment"]) is not bool:
        errors.append("release_environment is not true or false")
    errors += validate_environments(s)
    return errors


def validate_environments(s):
    """What is wrong with `[settings.environments]` (names and logins are not secret)."""
    envs = s.get("environments", {})
    if not isinstance(envs, dict):
        return ["environments is not a table"]
    errors = []
    for name, e in envs.items():
        if not ENV_NAME.fullmatch(name):
            errors.append(f"environments: {name!r} is not an environment name")
            continue
        if not isinstance(e, dict):
            errors.append(f"environments.{name} is not a table")
            continue
        errors += [
            f"environments.{name}.{k} is not one of {', '.join(ENV_KEYS)}"
            for k in e
            if k not in ENV_KEYS
        ]
        rev = e.get("reviewers", [])
        if not isinstance(rev, list) or not all(
            isinstance(r, str) and LOGIN.fullmatch(r) for r in rev
        ):
            errors.append(f"environments.{name}.reviewers is not a list of user logins")
        br = e.get("branches", [])
        if not isinstance(br, list) or not all(isinstance(b, str) and b.strip() for b in br):
            errors.append(f"environments.{name}.branches is not a list of branch names")
        if type(e.get("prevent_self_review", False)) is not bool:
            errors.append(f"environments.{name}.prevent_self_review is not true or false")
    if "release" in envs and "release_environment" in s:
        errors.append("environments.release next to release_environment: declare it once")
    return errors


def declared_environments(s):
    """`[settings.environments]` as a list, sorted by name (validated first)."""
    return [
        {
            "name": name,
            "reviewers": sorted(e.get("reviewers", []), key=str.lower),
            "branches": sorted(set(e.get("branches", []))),
            "prevent_self_review": e.get("prevent_self_review", False),
        }
        for name, e in sorted(s.get("environments", {}).items())
    ]


# `pull_request:` as a key, in an `on: [...]` list, or as the only trigger
PR_TRIGGERS = (
    re.compile(r"^[ \t]*pull_request[ \t]*:", re.M),
    re.compile(r"^on:[ \t]*\[[^\]\n]*\bpull_request\b", re.M),
    re.compile(r"^on:[ \t]*pull_request[ \t]*$", re.M),
)


def runs_on_pr(text):
    return any(r.search(text) for r in PR_TRIGGERS)


PR_KEY = re.compile(r"^([ \t]*)pull_request[ \t]*:[ \t]*(?:#.*)?\n", re.M)


def pr_path_filtered(text):
    """Whether the workflow's `pull_request:` trigger has a `paths:` or
    `paths-ignore:` filter. Such a workflow skips some PRs, so it can never be
    what reports a required check (CONTRIBUTING "Settings are code"); a job of
    it that shares a required check's name is another check (#576)."""
    m = PR_KEY.search(text)
    if not m:
        return False
    indent = len(m.group(1))
    for line in text[m.end() :].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= indent:
            return False
        if re.match(r"[ \t]*paths(?:-ignore)?[ \t]*:", line):
            return True
    return False


NAME_LINE = re.compile(r"^[ \t]+name:[ \t]*(\S.*)$", re.M)


def names_job(text, job):
    """Whether a workflow has a job with the id `job`, or a `name:` that gives
    `job` (an expression such as `${{ matrix.python }}` inside a name matches
    any text; a name that is only an expression is skipped)."""
    if re.search(rf"^\s+{re.escape(job)}:\s*(?:#.*)?$", text, re.M):
        return True
    for m in NAME_LINE.finditer(text):
        name = m.group(1).split(" #")[0].strip()
        if len(name) > 1 and name[0] == name[-1] and name[0] in "'\"":
            name = name[1:-1]
        parts = re.split(r"\$\{\{.*?\}\}", name)
        if not "".join(parts).strip():
            continue  # a name that is only an expression (an artifact's, a step's) names nothing
        if re.fullmatch(".+".join(re.escape(x) for x in parts), job):
            return True
    return False


def job_block(text, job):
    """The lines of the job with the id `job` (two-space indent under
    `jobs:`), or None when no job has that id."""
    m = re.search(rf"^  {re.escape(job)}:[ \t]*(?:#.*)?\n", text, re.M)
    if not m:
        return None
    end = re.search(r"^(?:  )?\S", text[m.end() :], re.M)
    return text[m.end() : m.end() + end.start()] if end else text[m.end() :]


def reports_as(text, job, nested):
    """Whether the workflow's job `job` can report a check of that shape. A
    check `X / Y` comes from a job X that calls a reusable workflow (`uses:`
    at job level), so a plain job with the id X is not it; a plain check `X`
    comes from any job named X (#294: `ai-files-review.yml`'s plain job
    `review`, which has `runs-on` and `steps`, is not the caller of
    `review / coderabbit`)."""
    if not names_job(text, job):
        return False
    block = job_block(text, job)
    if block is None or not nested:
        return True  # matched by name only, or a plain check: as before
    if re.search(r"^    uses:[ \t]*\S", block, re.M):
        return True
    # a job that runs its own steps cannot be the caller; anything else is kept
    return not re.search(r"^    (?:runs-on|steps):", block, re.M)


def without_merge_group(checks, workflows):
    """The required checks a merge group would never get: no workflow found
    with a job named (or with the id) the check's first ` / ` segment, or one
    found whose triggers have no merge_group. Only workflows that run on
    pull_request can report a required check, so a reusable (workflow_call)
    workflow whose job carries the same name is not one of them, nor one whose
    pull_request trigger is path-filtered (#576); and a check `X / Y` is
    reported only by a job X that calls a reusable workflow."""
    out = []
    for c in checks:
        job = c.split(" / ")[0]
        nested = " / " in c
        found = [
            t
            for p, t in workflows.items()
            if "/workflows/" in p
            and runs_on_pr(t)
            and not pr_path_filtered(t)
            and reports_as(t, job, nested)
        ]
        if not found or not all(MERGE_GROUP.search(t) for t in found):
            out.append(c)
    return out


def main_ruleset(prof_rs, s):
    rs = copy.deepcopy(prof_rs)
    rules = []
    for r in rs["rules"]:
        if r["type"] in SCANNING_RULES and not s.get("code_scanning"):
            continue
        if r["type"] == "required_status_checks":
            checks = s.get("required_checks", [])
            if not checks:
                continue
            r["parameters"]["required_status_checks"] = [
                {"context": c, "integration_id": ACTIONS_APP} for c in checks
            ]
        if r["type"] == "pull_request" and s.get("merge_methods"):
            r["parameters"]["allowed_merge_methods"] = list(s["merge_methods"])
        rules.append(r)
    mq = s.get("merge_queue")
    if mq:
        own = mq if isinstance(mq, dict) else {}
        rules.append({"type": "merge_queue", "parameters": {**MERGE_QUEUE, **own}})
    rs["rules"] = rules
    return rs


def desired(s):
    """What the settings table declares: repository fields, rulesets, security, Actions, environment."""
    want = {
        "repo": {
            "description": s.get("description", ""),
            "homepage": s.get("homepage", ""),
            "topics": sorted(s.get("topics", [])),
        },
        "rulesets": [],
        "security": {},
        "actions": None,
        "environment": None,
        "environment_off": None,
        "environments": declared_environments(s),
    }
    if not s.get("ruleset"):
        return want
    prof = load_profile(s["ruleset"])
    want["repo"].update(prof["repo"])
    if s.get("merge_methods"):
        want["repo"].update({flag: m in s["merge_methods"] for m, flag in MERGE_METHODS.items()})
    if prof["features"] is not None:
        want["repo"].update(prof["features"])
        want["repo"].update(s.get("features", {}))
    if prof["security"] is not None:
        sec = {**prof["security"], **s.get("security", {})}
        want["security"] = {k: True for k in SECURITY if sec.get(k)}
    want["actions"] = prof["actions"]
    env = prof["release_environment"]
    if env is not None and s.get("release_environment", env["enabled"]):
        want["environment"] = env
    elif env is not None and s.get("release_environment") is False:
        want["environment_off"] = env["name"]
    if prof["ruleset"] is not None:
        want["rulesets"].append(main_ruleset(prof["ruleset"], s))
    if prof["tag_ruleset"] is not None:
        want["rulesets"].append(copy.deepcopy(prof["tag_ruleset"]))
    return want


# --- comparison ----------------------------------------------------------------


def key(x):
    return json.dumps(x, sort_keys=True)


def covers(want, have):
    """True when `have` holds everything `want` says: dict keys GitHub adds
    with defaults are ignored; lists must match element for element, in any order."""
    if isinstance(want, dict):
        return isinstance(have, dict) and all(
            k in have and covers(v, have[k]) for k, v in want.items()
        )
    if isinstance(want, list):
        if not isinstance(have, list) or len(want) != len(have):
            return False
        return all(covers(w, h) for w, h in zip(sorted(want, key=key), sorted(have, key=key)))
    return want == have


def ruleset_drift(want, have):
    out = [
        k
        for k in ("target", "enforcement", "conditions", "bypass_actors")
        if not covers(want[k], have.get(k))
    ]
    wr = {r["type"]: r for r in want["rules"]}
    hr = {r["type"]: r for r in have.get("rules", [])}
    out += [f"+{t}" for t in sorted(wr.keys() - hr.keys())]
    out += [f"-{t}" for t in sorted(hr.keys() - wr.keys())]
    out += [f"~{t}" for t in sorted(wr.keys() & hr.keys()) if not covers(wr[t], hr[t])]
    return out


def action_allowed(use, sel):
    """Whether the Actions policy `sel` (selected-actions shape) lets `use` run."""
    if use.startswith("./"):
        return True  # an action in the same repository
    u = use.lower()
    if sel["github_owned_allowed"] and u.split("/")[0] in ("actions", "github"):
        return True
    return any(fnmatch.fnmatchcase(u, p.lower()) for p in sel["patterns_allowed"])


def short(v):
    if v in (None, "", []):
        return "none"
    if isinstance(v, bool):
        return json.dumps(v)
    s = ",".join(v) if isinstance(v, list) else str(v)
    return json.dumps(s if len(s) <= 70 else s[:67] + "...", ensure_ascii=False)


def item(res, what, have, want, *writes, unsupported=()):
    """A setting that differs, with the writes that fix it in order (status codes in
    `unsupported` mean GitHub does not offer it here: reported, not a failure)."""
    res["items"].append(
        {
            "what": what,
            "have": have,
            "want": want,
            "writes": list(writes),
            "unsupported": unsupported,
        }
    )


def probe(gh, res, what, path):
    """GET `path`: (True, body), (False, status) for 404, or None when unreadable."""
    try:
        return True, gh.api("GET", path)
    except GhError as e:
        if e.status == 404:
            return False, 404
        res["unreadable"].append(f"{what} (HTTP {e.status or '?'})")
        return None


def plan_security(gh, res, full, meta, want, workflows):
    want = dict(want)
    skipped = []
    if res["private"]:
        skipped = [k for k in PRIVATE_UNSUPPORTED if want.pop(k, False)]
    if want.get("codeql_default_setup"):
        own = sorted(p for p, text in workflows.items() if CODEQL.search(text))
        if own:
            del want["codeql_default_setup"]
            res["notes"].append(
                f"CodeQL runs in {', '.join(own)} (advanced setup): default setup left alone"
            )
    sa = meta.get("security_and_analysis")

    def status(name):
        if not isinstance(sa, dict):
            res["unreadable"].append(
                f"security {name} (no security_and_analysis: the token needs Administration: read)"
            )
            return None
        if name not in sa:
            skipped.append(name)
            return None
        return sa[name].get("status") == "enabled"

    def on(what, method, path, body=None, unsupported=()):
        item(res, f"security {what}", False, True, (method, path, body), unsupported=unsupported)

    for k in SECURITY:
        if not want.get(k):
            continue
        if k == "vulnerability_alerts":
            got = probe(gh, res, f"security {k}", f"repos/{full}/vulnerability-alerts")
            if got is not None and not got[0]:
                on(k, "PUT", f"repos/{full}/vulnerability-alerts")
        elif k == "automated_security_fixes":
            if isinstance(sa, dict) and "dependabot_security_updates" in sa:
                enabled = sa["dependabot_security_updates"].get("status") == "enabled"
            else:
                got = probe(gh, res, f"security {k}", f"repos/{full}/automated-security-fixes")
                enabled = None if got is None else bool(got[0] and got[1].get("enabled"))
            if enabled is False:
                on(k, "PUT", f"repos/{full}/automated-security-fixes")
        elif k in ("secret_scanning", "secret_scanning_push_protection"):
            if status(k) is False:
                body = {"security_and_analysis": {k: {"status": "enabled"}}}
                on(k, "PATCH", f"repos/{full}", body)
        elif k == "private_vulnerability_reporting":
            got = probe(gh, res, f"security {k}", f"repos/{full}/private-vulnerability-reporting")
            if got is not None and not got[0]:
                skipped.append(k)
            elif got is not None and not got[1].get("enabled"):
                on(k, "PUT", f"repos/{full}/private-vulnerability-reporting")
        elif k == "codeql_default_setup":
            path = f"repos/{full}/code-scanning/default-setup"
            try:
                got = gh.api("GET", path)
            except GhError as e:
                if e.status in (403, 404) and "Advanced Security" in str(e):
                    skipped.append(k)
                else:
                    res["unreadable"].append(f"security {k} (HTTP {e.status or '?'})")
                continue
            if got.get("state") != "configured":
                on(k, "PATCH", path, {"state": "configured"}, unsupported=(422,))
            else:
                plan_codeql_languages(gh, res, full, path, got, workflows)
    if skipped:
        res["notes"].append(f"unsupported here: {', '.join(skipped)}")


def plan_codeql_languages(gh, res, full, path, got, workflows):
    """Default setup is configured: every CodeQL language the repository now holds is
    analysed (swarm-routing/ns3-upstream-report#70). Languages are only added; one with
    no code left is a note, its removal the maintainer's call."""
    langs = probe(gh, res, "security codeql_languages", f"repos/{full}/languages")
    if langs is None:
        return
    found = {CODEQL_LANGUAGE[n] for n in (langs[1] if langs[0] else {}) if n in CODEQL_LANGUAGE}
    if any("/workflows/" in p for p in workflows):
        found.add("actions")
    have = list(got.get("languages") or [])
    covered = {CODEQL_SAME.get(x, x) for x in have}
    missing = sorted(found - covered)
    gone = sorted(x for x in have if CODEQL_SAME.get(x, x) not in found)
    if gone:
        res["notes"].append(
            f"CodeQL default setup analyses {', '.join(gone)}, which the repository no "
            "longer holds: removing it is the maintainer's decision"
        )
    if missing:
        body = {"state": "configured", "languages": sorted(have + missing)}
        if got.get("query_suite"):
            body["query_suite"] = got["query_suite"]
        item(
            res,
            "security codeql_languages",
            sorted(have),
            body["languages"],
            ("PATCH", path, body),
            unsupported=(422,),
        )


def plan_actions(gh, res, full, want, workflows):
    sel = want["selected_actions"]
    uses = sorted({u for text in workflows.values() for u in USES.findall(text)})
    bad = [u for u in uses if not action_allowed(u, sel)]
    if bad:
        res["errors"].append(
            "a workflow uses an action the allowed list does not cover"
            if res["private"]
            else f"actions not in defaults.json selected_actions: {', '.join(bad)}"
        )
        return
    try:
        perms = gh.api("GET", f"repos/{full}/actions/permissions")
    except GhError as e:
        res["unreadable"].append(f"actions permissions (HTTP {e.status or '?'})")
        return
    wp = want["permissions"]
    sel_write = ("PUT", f"repos/{full}/actions/permissions/selected-actions", sel)
    if not covers(wp, perms):
        have = f"{perms.get('allowed_actions')}" if perms.get("enabled") else "disabled"
        writes = [("PUT", f"repos/{full}/actions/permissions", wp)]
        if wp.get("allowed_actions") == "selected":
            writes.append(sel_write)  # only writable once the policy is `selected`
        item(res, "actions allowed_actions", have, wp["allowed_actions"], *writes)
    elif wp.get("allowed_actions") == "selected":
        try:
            have = gh.api("GET", f"repos/{full}/actions/permissions/selected-actions")
        except GhError as e:
            res["unreadable"].append(f"actions selected_actions (HTTP {e.status or '?'})")
            have = None
        if have is not None and not (
            have.get("github_owned_allowed") == sel["github_owned_allowed"]
            and have.get("verified_allowed") == sel["verified_allowed"]
            and sorted(have.get("patterns_allowed", [])) == sorted(sel["patterns_allowed"])
        ):
            item(res, "actions selected_actions", "other", "defaults.json", sel_write)
    ww = want["workflow"]
    try:
        have = gh.api("GET", f"repos/{full}/actions/permissions/workflow")
    except GhError as e:
        res["unreadable"].append(f"actions workflow permissions (HTTP {e.status or '?'})")
        have = None
    if have is not None and not covers(ww, have):

        def show(p):
            approve = "+approve" if p.get("can_approve_pull_request_reviews") else ""
            return f"{p.get('default_workflow_permissions')}{approve}"

        item(
            res,
            "actions workflow",
            show(have),
            show(ww),
            ("PUT", f"repos/{full}/actions/permissions/workflow", ww),
        )
    if want.get("fork_pr_contributor_approval"):
        plan_fork_approval(gh, res, full, want["fork_pr_contributor_approval"])


def plan_fork_approval(gh, res, full, fa):
    """Which fork PRs wait for a maintainer before their workflows run (public only:
    a private repository's fork-PR workflows are a separate, unmanaged setting)."""
    what = "actions fork_pr_contributor_approval"
    if res["private"]:
        res["notes"].append(f"unsupported here: {what} (private repository)")
        return
    path = f"repos/{full}/actions/permissions/fork-pr-contributor-approval"
    try:
        have = gh.api("GET", path)
    except GhError as e:
        if e.status in (404, 422):
            res["notes"].append(f"unsupported here: {what} (HTTP {e.status})")
        else:
            res["unreadable"].append(f"{what} (HTTP {e.status or '?'})")
        return
    if have.get("approval_policy") != fa["approval_policy"]:
        item(res, what, have.get("approval_policy"), fa["approval_policy"], ("PUT", path, fa))


def plan_environment(gh, res, full, env):
    what = f"environment {env['name']}"
    if res["private"]:
        res["notes"].append(f"unsupported here: {what} reviewers (private repository)")
        return
    got = probe(gh, res, what, f"repos/{full}/environments/{env['name']}")
    if got is None:
        return
    reviewers = sorted(env["reviewers"], key=str.lower)
    have = None
    if got[0]:
        rules = [
            r for r in got[1].get("protection_rules", []) if r.get("type") == "required_reviewers"
        ]
        have = sorted(
            (r["reviewer"].get("login", "") for r in (rules[0]["reviewers"] if rules else [])),
            key=str.lower,
        )
        psr = rules[0].get("prevent_self_review") if rules else None
        if [h.lower() for h in have] == [r.lower() for r in reviewers] and psr == env[
            "prevent_self_review"
        ]:
            return

    def body(gh):
        ids = [gh.api("GET", f"users/{login}")["id"] for login in reviewers]
        return {
            "wait_timer": 0,
            "prevent_self_review": env["prevent_self_review"],
            "reviewers": [{"type": "User", "id": i} for i in ids],
            "deployment_branch_policy": None,
        }

    item(
        res,
        what,
        have if got[0] else "missing",
        reviewers,
        ("PUT", f"repos/{full}/environments/{env['name']}", body),
    )


def plan_declared_environment(gh, res, full, env):
    """One `[settings.environments.<name>]` table: reviewers, self-review, branch policy."""
    name = env["name"]
    what = f"environment {name}"
    if res["private"] and (env["reviewers"] or env["branches"]):
        res["notes"].append(f"unsupported here: {what} protection (private repository)")
        return
    path = f"repos/{full}/environments/{urllib.parse.quote(name, safe='')}"
    got = probe(gh, res, what, path)
    if got is None:
        return
    want = {"reviewers": env["reviewers"], "branches": env["branches"]}
    want_psr = env["prevent_self_review"] if env["reviewers"] else False
    policies = {}  # branch name -> policy id, of the live environment
    if got[0]:
        rules = [
            r for r in got[1].get("protection_rules", []) if r.get("type") == "required_reviewers"
        ]
        reviewers = sorted(
            (x["reviewer"].get("login", "") for x in (rules[0]["reviewers"] if rules else [])),
            key=str.lower,
        )
        psr = rules[0].get("prevent_self_review", False) if rules else False
        dbp = got[1].get("deployment_branch_policy") or {}
        custom = bool(dbp.get("custom_branch_policies")) and not dbp.get("protected_branches")
        if custom:
            listed = probe(gh, res, what, f"{path}/deployment-branch-policies?per_page=100")
            if listed is None:
                return
            for p in listed[1].get("branch_policies", []) if listed[0] else []:
                if p.get("type", "branch") == "branch":
                    policies[p["name"]] = p["id"]
        if custom:
            branches = sorted(policies) or ["(none)"]  # a custom policy naming no branch
        else:
            branches = ["(protected branches)"] if dbp else []  # [] = any branch
        have = {"reviewers": reviewers, "branches": branches}
        if have == want and psr == want_psr:
            return
    else:
        have = "missing"

    def body(gh):
        ids = [gh.api("GET", f"users/{login}")["id"] for login in env["reviewers"]]
        return {
            "wait_timer": 0,
            "prevent_self_review": want_psr,
            "reviewers": [{"type": "User", "id": i} for i in ids],
            "deployment_branch_policy": (
                {"protected_branches": False, "custom_branch_policies": True}
                if env["branches"]
                else None
            ),
        }

    writes = [("PUT", path, body)]
    if env["branches"]:
        writes += [
            ("POST", f"{path}/deployment-branch-policies", {"name": b, "type": "branch"})
            for b in env["branches"]
            if b not in policies
        ]
        writes += [
            ("DELETE", f"{path}/deployment-branch-policies/{i}", None)
            for b, i in sorted(policies.items())
            if b not in env["branches"]
        ]

    def show(x):
        if x == "missing":
            return x
        r = ",".join(x["reviewers"]) or "none"
        b = ",".join(x["branches"]) or "any"
        return f"reviewers {r}; branches {b}"

    item(res, what, show(have), show(want), *writes)


def plan_environment_off(gh, res, full, name):
    """`release_environment = false`: an existing environment loses its gate
    (required reviewers, wait timer), keeps its deployment branch policy, and
    is never deleted; a missing one stays missing."""
    what = f"environment {name}"
    got = probe(gh, res, what, f"repos/{full}/environments/{name}")
    if got is None or not got[0]:
        return
    have = []
    for r in got[1].get("protection_rules", []):
        if r.get("type") == "required_reviewers" and r.get("reviewers"):
            have += [
                x["reviewer"].get("login", x["reviewer"].get("name", "")) for x in r["reviewers"]
            ]
        elif r.get("type") == "wait_timer" and r.get("wait_timer"):
            have.append(f"wait {r['wait_timer']} min")
    if not have:
        return
    body = {
        "wait_timer": 0,
        "prevent_self_review": False,
        "reviewers": [],
        "deployment_branch_policy": got[1].get("deployment_branch_policy"),
    }
    item(res, what, have, "ungated", ("PUT", f"repos/{full}/environments/{name}", body))


def plan_repo(gh, repo, local=None):
    """What differs in one repository: {repo, private, skip, changes, rulesets, items, notes, ...}."""
    if not REPO_NAME.fullmatch(repo) or repo in (".", ".."):
        raise ValueError(f"not a repository name: {repo!r}")
    res = {
        "repo": repo,
        "private": False,
        "skip": None,
        "changes": [],
        "rulesets": [],
        "items": [],
        "unreadable": [],
        "notes": [],
        "errors": [],
        "unrequired": [],
    }
    s = read_settings(gh, repo, local)
    if s is None:
        res["skip"] = f"no [settings] in {CONFIG}"
        return res
    meta = gh.api("GET", f"repos/{ORG}/{repo}")
    full = f"{ORG}/{repo}"
    res["private"] = bool(meta.get("private"))
    res["errors"] = validate(s, res["private"])
    if res["errors"]:
        return res
    want = desired(s)
    for k, v in want["repo"].items():
        have = meta.get(k)
        if k == "topics":
            have = sorted(have or [])
        elif k in ("description", "homepage"):
            have = have or ""
        if have != v:
            res["changes"].append((k, have, v))
    workflows = None
    if want["security"].get("codeql_default_setup") or want["actions"] or s.get("merge_queue"):
        workflows = read_workflows(gh, repo, meta.get("default_branch") or "main", local)
    if s.get("merge_queue") and want["rulesets"]:
        missing = without_merge_group(s.get("required_checks", []), workflows)
        if missing:
            res["errors"].append(
                "merge_queue: a required check's workflow has no merge_group trigger"
                if res["private"]
                else f"merge_queue: no merge_group trigger on the workflow of {', '.join(missing)}"
            )
            return res
    if want["actions"]:
        plan_actions(gh, res, full, want["actions"], workflows)
        if res["errors"]:
            return res
    if want["security"]:
        plan_security(gh, res, full, meta, want["security"], workflows or {})
    if want["environment"]:
        plan_environment(gh, res, full, want["environment"])
    elif want["environment_off"]:
        plan_environment_off(gh, res, full, want["environment_off"])
    for env in want["environments"]:
        plan_declared_environment(gh, res, full, env)
    if want["rulesets"]:
        plan_rulesets(gh, res, full, want["rulesets"])
    if any(r["name"] == "main" for r in want["rulesets"]):
        plan_unrequired(gh, res, full, meta.get("default_branch") or "main", s)
    return res


def plan_unrequired(gh, res, full, branch, s):
    """The checks that ran on the default branch's head but are neither
    required nor optional (information for `check`, never drift)."""
    ref = urllib.parse.quote(branch, safe="")
    runs, statuses = [], []
    try:
        # every page of both lists (total_count), so no check is missed
        for key, kind, into in (
            ("check_runs", "check-runs", runs),
            ("statuses", "status", statuses),
        ):
            page = 1
            while True:
                got = gh.api("GET", f"repos/{full}/commits/{ref}/{kind}?per_page=100&page={page}")
                batch = got.get(key, [])
                into += batch
                if not batch or len(into) >= got.get("total_count", 0):
                    break
                page += 1
    except GhError as e:
        if e.status in (404, 409, 422):  # no branch, or an empty repository
            return
        res["notes"].append(
            f"checks on {branch} unreadable (HTTP {e.status or '?'}): "
            "the token needs Checks and Commit statuses read"
        )
        return
    names = {r["name"] for r in runs if r.get("conclusion") != "skipped"}
    names |= {st["context"] for st in statuses}
    required = set(s.get("required_checks", []))
    optional = s.get("optional_checks", [])
    res["unrequired"] = sorted(
        (
            n
            for n in names
            if n not in required and not any(fnmatch.fnmatchcase(n, p) for p in optional)
        ),
        key=lambda n: (n.lower(), n),
    )


def plan_rulesets(gh, res, full, wanted):
    try:
        live = gh.api("GET", f"repos/{full}/rulesets?includes_parents=false&per_page=100")
    except GhError as e:
        if e.status == 403 and "Upgrade" in str(e):
            res["notes"].append("rulesets are not available on this plan (private repository)")
            return
        raise
    names = {w["name"] for w in wanted}
    others = sorted(r["name"] for r in live if r.get("name") not in names)
    if others:
        res["notes"].append(f"unmanaged ruleset(s) left alone: {', '.join(others)}")
    for want_rs in wanted:
        mine = [
            r
            for r in live
            if r.get("name") == want_rs["name"]
            and r.get("source_type", "Repository") == "Repository"
        ]
        if not mine:
            res["rulesets"].append({"action": "create", "want": want_rs, "drift": ["missing"]})
            continue
        full_rs = gh.api("GET", f"repos/{full}/rulesets/{mine[0]['id']}")
        drift = ruleset_drift(want_rs, full_rs)
        if drift:
            res["rulesets"].append(
                {"action": "update", "id": mine[0]["id"], "want": want_rs, "drift": drift}
            )


def drifted(res):
    return bool(
        res["changes"] or res["rulesets"] or res["items"] or res["unreadable"] or res["errors"]
    )


def lines(res, verb="differs"):
    name = shown(res)
    if res["skip"]:
        return [f"{name}: skipped ({res['skip']})"]
    out = [f"{name}: invalid [settings]: {e}" for e in res["errors"]]
    for k, have, want in res["changes"]:
        if res["private"]:
            out.append(f"{name} {k}: {verb}")
        else:
            out.append(f"{name} {k}: {verb}: {short(have)} -> {short(want)}")
    for it in res["items"]:
        if res["private"]:
            out.append(f"{name} {it['what']}: {verb}")
        else:
            out.append(f"{name} {it['what']}: {verb}: {short(it['have'])} -> {short(it['want'])}")
    for r in res["rulesets"]:
        out.append(f"{name} ruleset {r['want']['name']}: {r['action']} ({', '.join(r['drift'])})")
    out += [f"{name} {u}: unreadable" for u in res["unreadable"]]
    if not out:
        out.append(f"{name}: in sync")
    if res["private"] and res["unrequired"]:
        out.append(f"{name}: {len(res['unrequired'])} unrequired check(s)")
    elif not res["private"]:
        out += [f"{name}: unrequired check: {c}" for c in res["unrequired"]]
    return out + [f"{name}: note: {n}" for n in res["notes"]]


# --- writes --------------------------------------------------------------------


def apply_repo(gh, res):
    """Write the differences; return (lines, refused)."""
    full = f"{ORG}/{res['repo']}"
    name = shown(res)
    out, refused = [], False
    changed = {k: want for k, _, want in res["changes"]}
    steps = []  # (what, [(method, path, body)], unsupported status codes)
    patch = {k: v for k, v in changed.items() if k != "topics"}
    if patch:
        steps.append((", ".join(sorted(patch)), [("PATCH", f"repos/{full}", patch)], ()))
    if "topics" in changed:
        steps.append(
            ("topics", [("PUT", f"repos/{full}/topics", {"names": changed["topics"]})], ())
        )
    steps += [(it["what"], it["writes"], it["unsupported"]) for it in res["items"]]
    for rs in res["rulesets"]:
        body = {k: rs["want"][k] for k in RULESET_KEYS}
        if rs["action"] == "create":
            w = ("POST", f"repos/{full}/rulesets", body)
        else:
            w = ("PUT", f"repos/{full}/rulesets/{rs['id']}", body)
        steps.append((f"ruleset {body['name']} {rs['action']}d", [w], ()))
    for what, writes, unsupported in steps:
        try:
            for method, path, body in writes:
                gh.api(method, path, body(gh) if callable(body) else body)
            out.append(f"{name}: applied {what}")
        except GhError as e:
            if e.status in unsupported:
                out.append(f"{name}: unsupported {what} (HTTP {e.status})")
            elif e.status in (403, 404):
                refused = True
                out.append(
                    f"{name}: refused {what} (HTTP {e.status}): the token needs Administration: write"
                )
            elif e.status == 409:
                refused = True
                out.append(
                    f"{name}: refused {what} (HTTP 409): an organization policy overrides it"
                )
            else:
                raise
    return out, refused


# --- commands ------------------------------------------------------------------


def shown(res):
    """How the output names a repository: its name, or, for a private one, the
    label run gave it (`private repository N`); never the private name (#622)."""
    if res["private"]:
        return res.get("label") or "private repository"
    return res["repo"]


class Masker:
    """Labels private repositories `private repository N`, N in the order they
    are first named, and scrubs their names out of other text (#622)."""

    def __init__(self):
        self.labels = {}

    def label(self, repo):
        return self.labels.setdefault(repo, f"private repository {len(self.labels) + 1}")

    def scrub(self, text):
        for repo in sorted(self.labels, key=len, reverse=True):
            text = text.replace(f"{ORG}/{repo}", "<private>").replace(repo, "<private>")
        return text


def org_repos(gh):
    """The org's repositories, not archived, not forks: {name: private}, sorted by name."""
    found, page = {}, 1
    while True:
        batch = gh.api("GET", f"orgs/{ORG}/repos?type=all&per_page=100&page={page}")
        for r in batch:
            if not r.get("archived") and not r.get("fork"):
                found[r["name"]] = bool(r.get("private"))
        if len(batch) < 100:
            return {n: found[n] for n in sorted(found, key=str.lower)}
        page += 1


def run(cmd, repos, local=None, dry_run=False, gh=None, org_only=False):
    gh = gh or GitHub()
    private, mask = {}, Masker()
    if repos and org_only:
        try:
            private = org_repos(gh)
            known = {n.lower(): n for n in private}
        except GhError as e:
            print(f"repo-settings: cannot list the org ({e}); nothing done")
            return 1
        bad = [r for r in repos if r.lower() not in known]
        for r in bad:
            print(f"{r[:80]}: refused: not a {ORG} repository (archived ones and forks excluded)")
        if bad:
            return 1
        repos = [known[r.lower()] for r in repos]
    if not repos:
        try:
            private = org_repos(gh)
            repos = list(private)
        except GhError as e:
            print(f"repo-settings: cannot list the org ({e}); name the repositories")
            return 1
    rc = 0
    for repo in repos:
        name = mask.label(repo) if private.get(repo) else repo
        try:
            res = plan_repo(gh, repo, local)
        except (GhError, ValueError, tomllib.TOMLDecodeError) as e:
            print(f"{name}: FAILED: {mask.scrub(str(e))}")
            rc = 1
            continue
        if res["private"]:
            res["label"] = name = mask.label(repo)
        if cmd == "apply" and not dry_run and drifted(res) and not res["errors"]:
            try:
                out, refused = apply_repo(gh, res)
            except GhError as e:
                print(f"{name}: FAILED: {mask.scrub(str(e))}")
                rc = 1
                continue
            out += [f"{name} {u}: unreadable, not written" for u in res["unreadable"]]
            print("\n".join(out + [f"{name}: note: {n}" for n in res["notes"]]))
            if refused and rc == 0:
                rc = 2
            continue
        print("\n".join(lines(res, "would write" if cmd == "apply" else "differs")))
        if res["errors"] or (cmd == "check" and drifted(res)):
            rc = 1
    return rc


def GhErrorOf(f):
    """The GhError f() raises, or None (self-test helper)."""
    try:
        f()
    except GhError as e:
        return e
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    for name in ("plan", "check", "apply"):
        s = sub.add_parser(name)
        s.add_argument("repos", nargs="*", help="repository names (default: every org repository)")
        s.add_argument("--local", help="read DIR/<repo>/.github/ instead of the API")
        s.add_argument(
            "--org-only",
            action="store_true",
            help="refuse a named repository that is not one of the org's (#569)",
        )
        if name == "apply":
            s.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.cmd:
        p.error("a command is required")
    return run(a.cmd, a.repos, a.local, getattr(a, "dry_run", False), org_only=a.org_only)


# --- self-test: a fake GitHub holding repositories, contents and rulesets -----


def self_test():
    import contextlib
    import io

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    # every profile loads, has the shape the tool relies on, and takes the shared parts
    for f in sorted(os.listdir(PROFILES)):
        if f == f"{DEFAULTS}.json":
            continue
        prof = load_profile(f[: -len(".json")])
        rs = prof["ruleset"] or {**dict.fromkeys(RULESET_KEYS), "name": "main"}
        check(
            f"profile {f}",
            rs["name"] == "main"
            and all(k in rs for k in RULESET_KEYS)
            and all(k in prof for k in SHARED)
            and prof["repo"]["allow_squash_merge"] is True
            and prof["repo"]["squash_merge_commit_title"] == "PR_TITLE",
        )
    for name in ("../x", DEFAULTS):
        try:
            load_profile(name)
            check(f"profile {name} rejected", False)
        except ValueError:
            pass
    shared = load_profile("protocol")
    sel = shared["actions"]["selected_actions"]
    check(
        "defaults: features, security, tag ruleset",
        set(shared["features"]) == set(FEATURES)
        and set(shared["security"]) == set(SECURITY)
        and shared["tag_ruleset"]["name"] == "release-tags"
        and shared["tag_ruleset"]["target"] == "tag"
        and shared["release_environment"]["enabled"] is False,
    )
    check("merge-only manages no tag ruleset", load_profile("merge-only")["tag_ruleset"] is None)
    # the allowed list: GitHub's own, the listed owners/repos, local actions; nothing else
    for use, ok in (
        ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", True),
        ("github/codeql-action/init@9b32540", True),
        ("codecov/codecov-action@303a32d", True),
        ("swarm-routing/.github/.github/workflows/reusable-pr-title.yml@main", True),
        ("./.github/actions/setup-emsdk", True),
        ("evil/codecov-action@v1", False),
        ("codecov/codecov-action/sub@v1", False),
        ("docker://alpine:3", False),
    ):
        check(f"action_allowed {use}", action_allowed(use, sel) is ok)
    # this repository's own workflows are covered (they call the reusable ones and the rest)
    mine = read_workflows(None, os.path.basename(ROOT), "main", local=os.path.dirname(ROOT))
    uses = {u for text in mine.values() for u in USES.findall(text)}
    check(
        "this repository's workflows are covered by the allowed list",
        len(uses) > 5 and all(action_allowed(u, sel) for u in uses),
    )

    merge = {**shared["repo"], **shared["features"]}
    sa_on = {
        k: {"status": "enabled"}
        for k in (
            "dependabot_security_updates",
            "secret_scanning",
            "secret_scanning_push_protection",
        )
    }
    sa_off = {k: {"status": "disabled"} for k in sa_on}
    # AntHocNet's ruleset as set by hand on 2026-11-10 (rulesets/18147133)
    anthocnet_live = {
        "id": 18147133,
        "name": "main",
        "target": "branch",
        "source_type": "Repository",
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "required_reviewers": [],
                    "require_code_owner_review": False,
                    "dismissal_restriction": {"enabled": False, "allowed_actors": []},
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["squash"],
                },
            },
            {
                "type": "copilot_code_review",
                "parameters": {"review_on_push": True, "review_draft_pull_requests": False},
            },
            {
                "type": "code_scanning",
                "parameters": {
                    "code_scanning_tools": [
                        {
                            "tool": "CodeQL",
                            "security_alerts_threshold": "high_or_higher",
                            "alerts_threshold": "errors",
                        }
                    ]
                },
            },
            {"type": "code_quality", "parameters": {"severity": "errors"}},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": "CI gate", "integration_id": 15368}],
                },
            },
        ],
        "bypass_actors": [],
        "node_id": "x",
        "_links": {},
        "current_user_can_bypass": "never",
    }
    tags_live = dict(
        copy.deepcopy(shared["tag_ruleset"]), id=777, source_type="Repository", node_id="y"
    )
    targets_nothing = {
        "id": 26312048,
        "name": "main",
        "target": "branch",
        "source_type": "Repository",
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
        "bypass_actors": [],
    }
    toml = {
        "AntHocNet": '[settings]\ndescription = "Ant routing."\nhomepage = "https://x/AntHocNet/"\n'
        'topics = ["manet", "aco"]\nruleset = "protocol"\nrequired_checks = ["CI gate"]\ncode_scanning = true\n',
        "ARA": 'kind = "protocol"\n[settings]\ndescription = "ARA."\nhomepage = ""\ntopics = ["ara"]\n'
        'ruleset = "protocol"\nrequired_checks = ["check / org-sync"]\n'
        'optional_checks = ["codecov/*", "Analyze (*)"]\n'
        "features = { has_discussions = true }\nrelease_environment = true\n",
        "plain": 'kind = "protocol"\n',
        "secret-lib": '[settings]\ndescription = "Secret workspace."\ntopics = ["secret-lib"]\nruleset = "merge-only"\n',
        "bad": '[settings]\ndescription = "x"\ntopics = ["Bad_Topic"]\n',
        "secret": '[settings]\ndescription = "x"\ntopics = ["Hidden_Name"]\n',
        "bad2": '[settings]\nruleset = "tooling"\nsecurity = { nope = true, secret_scanning = 1 }\n',
        "rogue": '[settings]\nruleset = "tooling"\n',
        "lean": '[settings]\nruleset = "tooling"\nsecurity = { codeql_default_setup = false }\n',
        "empty": '[settings]\nruleset = "tooling"\n',
        "huge": '[settings]\nruleset = "tooling"\n',
    }
    ci = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@3d3c42e # v7\n"
    workflows = {
        "AntHocNet": {
            ".github/workflows/ci.yml": ci + "      - uses: codecov/codecov-action@303a32d\n"
            "      - uses: ./.github/actions/setup-emsdk\n",
            ".github/workflows/codeql.yml": ci
            + "      - uses: github/codeql-action/init@9b32540\n",
            ".github/actions/setup-emsdk/action.yml": "runs:\n  steps:\n    - uses: 'actions/cache@55cc834'\n",
            "docs/not-a-workflow.yml": "uses: evil/ignored@v1\n",
        },
        "ARA": {
            ".github/workflows/pr-title.yml": "jobs:\n  title:\n    uses: "
            "swarm-routing/.github/.github/workflows/reusable-pr-title.yml@main\n"
        },
        "rogue": {".github/workflows/x.yml": ci + "      - uses: evil/action@v1\n"},
    }

    class FakeGitHub:
        def __init__(self, deny_writes=False, org_policy=False):
            self.calls, self.deny, self.org_policy = [], deny_writes, org_policy
            fresh = dict(
                has_issues=True,
                has_projects=True,
                has_wiki=True,
                has_discussions=False,
                allow_auto_merge=False,
                allow_update_branch=False,
            )
            self.repos = {
                "AntHocNet": dict(
                    merge,
                    description="Ant routing.",
                    homepage="https://x/AntHocNet/",
                    topics=["aco", "manet"],
                    private=False,
                    security_and_analysis=copy.deepcopy(sa_on),
                ),
                "ARA": dict(
                    fresh,
                    allow_squash_merge=True,
                    allow_merge_commit=True,
                    allow_rebase_merge=True,
                    delete_branch_on_merge=True,
                    squash_merge_commit_title="COMMIT_OR_PR_TITLE",
                    squash_merge_commit_message="COMMIT_MESSAGES",
                    description=None,
                    homepage=None,
                    topics=[],
                    private=False,
                    security_and_analysis=copy.deepcopy(sa_off),
                ),
                "plain": dict(private=False, topics=[]),
                "nocfg": dict(private=False, topics=[]),
                "secret-lib": dict(
                    fresh,
                    private=True,
                    description=None,
                    homepage=None,
                    topics=[],
                    security_and_analysis=None,
                ),
                "bad": dict(private=False, topics=[]),
                "secret": dict(private=True, topics=[]),
            }
            for r in ("bad2", "rogue", "lean", "empty", "huge"):
                self.repos[r] = dict(
                    merge, private=False, topics=[], security_and_analysis=copy.deepcopy(sa_on)
                )
            for r in self.repos.values():
                r.setdefault("default_branch", "main")
            self.alerts = {"AntHocNet": True, "lean": True, "empty": True}
            self.pvr = {r: r in ("AntHocNet", "lean", "empty") for r in self.repos}
            self.codeql = {r: "not-configured" for r in self.repos}
            # what default setup analyses once configured, and what linguist sees (#70 there)
            self.codeql_langs = {r: ["actions", "c-cpp"] for r in self.repos}
            self.langs = {r: {"C++": 9000, "CMake": 300} for r in self.repos}
            good = {"enabled": True, "allowed_actions": "selected"}
            self.perms = {
                r: dict(good) for r in ("AntHocNet", "lean", "empty", "secret-lib", "rogue")
            }
            self.perms["ARA"] = {"enabled": True, "allowed_actions": "all"}
            self.selected = {r: copy.deepcopy(sel) for r in self.perms if r != "ARA"}
            self.wfperms = {r: dict(shared["actions"]["workflow"]) for r in self.perms}
            self.forkpr = {
                r: dict(shared["actions"]["fork_pr_contributor_approval"]) for r in self.perms
            }
            self.forkpr["ARA"] = {"approval_policy": "first_time_contributors"}
            self.wfperms["ARA"] = {
                "default_workflow_permissions": "write",
                "can_approve_pull_request_reviews": True,
            }
            self.envs = {}
            self.policies = {}  # (repo, environment) -> {policy id: {name, type}}
            self.rulesets = {
                "AntHocNet": [copy.deepcopy(anthocnet_live), copy.deepcopy(tags_live)],
                "ARA": [
                    copy.deepcopy(targets_nothing),
                    {"id": 5, "name": "legacy", "source_type": "Repository"},
                ],
            }
            for r in ("lean", "empty"):
                main_rs = main_ruleset(load_profile("tooling")["ruleset"], {})
                self.rulesets[r] = [
                    dict(main_rs, id=1, source_type="Repository"),
                    copy.deepcopy(tags_live),
                ]
            self.next_id = 100
            # the default branch's head: check runs (name, conclusion) and commit statuses
            self.checks = {
                "ARA": (
                    [
                        ("check / org-sync", "success"),
                        ("ci / ns-latest debug", "success"),
                        ("ci / format", "failure"),
                        ("Analyze (c-cpp)", "success"),
                        ("title / title", "skipped"),
                    ],
                    ["codecov/patch", "SonarCloud", "codecov/project", "Late status"],
                ),
                "AntHocNet": ([("CI gate", "success")], []),
            }

        def api(self, method, path, body=None):
            self.calls.append((method, path, body))
            if path == "users/danieljoppi":
                return {"login": "danieljoppi", "id": 42}
            if path.startswith(f"orgs/{ORG}/repos?"):
                listed = [{"name": r, "private": m.get("private")} for r, m in self.repos.items()]
                listed += [{"name": "old", "archived": True}, {"name": "copy", "fork": True}]
                return listed if path.endswith("&page=1") else []
            m = re.match(rf"repos/{ORG}/([^/?]+)(.*)$", path)
            repo, rest = m.group(1), m.group(2)
            if method != "GET" and self.deny:
                raise GhError(method, path, "Resource not accessible by integration (HTTP 403)")
            meta = self.repos[repo]
            if rest == f"/contents/{CONFIG}":
                if repo not in toml:
                    raise GhError(method, path, "Not Found (HTTP 404)")
                return {"content": base64.b64encode(toml[repo].encode()).decode()}
            m2 = re.match(r"/commits/main/(check-runs|status)\?per_page=100&page=(\d+)$", rest)
            if m2:
                if repo == "lean":
                    raise GhError(method, path, "Resource not accessible by integration (HTTP 403)")
                runs, statuses = self.checks.get(repo, ([], []))
                page, size = int(m2.group(2)), 3  # a small page, so ARA's lists span pages
                if m2.group(1) == "status":
                    got = [{"context": c, "state": "success"} for c in statuses]
                    key = "statuses"
                else:
                    got = [{"name": n, "conclusion": c} for n, c in runs]
                    key = "check_runs"
                return {"total_count": len(got), key: got[(page - 1) * size : page * size]}
            if rest.startswith("/git/trees/main?"):
                files = workflows.get(repo, {})
                tree = [{"path": p, "type": "blob"} for p in files]
                return {"tree": tree, "truncated": repo == "huge"}
            if rest.startswith("/contents/"):
                text = workflows[repo][rest[len("/contents/") :].split("?")[0]]
                return {"content": base64.b64encode(text.encode()).decode()}
            if rest == "" and method == "GET":
                return copy.deepcopy(meta)
            if rest == "" and method == "PATCH":
                body = copy.deepcopy(body)
                for k, v in body.pop("security_and_analysis", {}).items():
                    meta["security_and_analysis"][k] = v
                meta.update(body)
                return {}
            if rest == "/topics":
                meta["topics"] = sorted(body["names"])
                return {}
            if rest == "/vulnerability-alerts":
                if method == "PUT":
                    self.alerts[repo] = True
                elif not self.alerts.get(repo):
                    raise GhError(method, path, "Not Found (HTTP 404)")
                return {}
            if rest == "/automated-security-fixes":
                if method == "PUT":
                    self.alerts.setdefault(f"{repo}/fixes", True)
                    if meta.get("security_and_analysis"):
                        meta["security_and_analysis"]["dependabot_security_updates"] = {
                            "status": "enabled"
                        }
                    return {}
                return {"enabled": bool(self.alerts.get(f"{repo}/fixes")), "paused": False}
            if rest == "/private-vulnerability-reporting":
                if meta["private"]:
                    raise GhError(method, path, "Not Found (HTTP 404)")
                if method == "PUT":
                    self.pvr[repo] = True
                return {"enabled": self.pvr[repo]}
            if rest == "/code-scanning/default-setup":
                if meta["private"]:
                    raise GhError(
                        method,
                        path,
                        "Advanced Security must be enabled for this repository to use code scanning. (HTTP 403)",
                    )
                if method == "PATCH":
                    if repo == "empty":
                        raise GhError(method, path, "no CodeQL-supported language (HTTP 422)")
                    self.codeql[repo] = body["state"]
                    if "languages" in body:
                        self.codeql_langs[repo] = list(body["languages"])
                    return {"run_id": 1}
                got = {"state": self.codeql[repo], "query_suite": "default"}
                if self.codeql[repo] == "configured":
                    got["languages"] = list(self.codeql_langs[repo])
                return got
            if rest == "/languages":
                return dict(self.langs[repo])
            if rest.startswith("/actions/permissions"):
                if repo == "lean":
                    raise GhError(method, path, "not permitted through this proxy (HTTP 403)")
                sub = rest[len("/actions/permissions") :]
                if method == "PUT" and self.org_policy:
                    raise GhError(method, path, "set by the organization (HTTP 409)")
                if sub == "":
                    if method == "PUT":
                        self.perms[repo] = dict(body)
                    return dict(self.perms[repo])
                if sub == "/selected-actions":
                    if self.perms[repo]["allowed_actions"] != "selected":
                        raise GhError(method, path, "allowed_actions is not selected (HTTP 409)")
                    if method == "PUT":
                        self.selected[repo] = copy.deepcopy(body)
                    return copy.deepcopy(self.selected[repo])
                if sub == "/workflow":
                    if method == "PUT":
                        self.wfperms[repo] = dict(body)
                    return dict(self.wfperms[repo])
                if sub == "/fork-pr-contributor-approval":
                    if self.repos[repo].get("private"):
                        raise GhError(method, path, "public repositories only (HTTP 422)")
                    if method == "PUT":
                        if body.get("approval_policy") not in FORK_PR_POLICIES:
                            raise GhError(method, path, "invalid approval_policy (HTTP 422)")
                        self.forkpr[repo] = dict(body)
                    return dict(self.forkpr[repo])
            m2 = re.match(
                r"/environments/([^/]+)/deployment-branch-policies(?:/(\d+)|\?per_page=100)?$", rest
            )
            if m2:
                env = self.envs.get((repo, m2.group(1)))
                if env is None:
                    raise GhError(method, path, "Not Found (HTTP 404)")
                pols = self.policies.setdefault((repo, m2.group(1)), {})
                if method == "POST":
                    if not (env["deployment_branch_policy"] or {}).get("custom_branch_policies"):
                        raise GhError(method, path, "custom policies are off (HTTP 404)")
                    self.next_id += 1
                    pols[self.next_id] = dict(body)
                    return {"id": self.next_id, **body}
                if method == "DELETE":
                    del pols[int(m2.group(2))]
                    return {}
                got = [{"id": i, **b} for i, b in sorted(pols.items())]
                return {"total_count": len(got), "branch_policies": got}
            m2 = re.match(r"/environments/([^/]+)$", rest)
            if m2:
                if method == "PUT":
                    if body["deployment_branch_policy"] is None:
                        self.policies.pop((repo, m2.group(1)), None)
                    rules = [{"type": "wait_timer", "wait_timer": body["wait_timer"]}]
                    if body["reviewers"]:
                        rules.append(
                            {
                                "type": "required_reviewers",
                                "prevent_self_review": body["prevent_self_review"],
                                "reviewers": [
                                    {"type": "User", "reviewer": {"login": "danieljoppi", "id": i}}
                                    for i in (r["id"] for r in body["reviewers"])
                                ],
                            }
                        )
                    self.envs[(repo, m2.group(1))] = {
                        "name": m2.group(1),
                        "protection_rules": rules,
                        "deployment_branch_policy": body["deployment_branch_policy"],
                    }
                    return {}
                if (repo, m2.group(1)) not in self.envs:
                    raise GhError(method, path, "Not Found (HTTP 404)")
                return copy.deepcopy(self.envs[(repo, m2.group(1))])
            if rest.startswith("/rulesets?"):
                if meta["private"]:
                    raise GhError(
                        method,
                        path,
                        "Upgrade to GitHub Pro or make this repository public (HTTP 403)",
                    )
                return [
                    {k: r[k] for k in ("id", "name", "source_type")}
                    for r in self.rulesets.get(repo, [])
                ]
            if rest == "/rulesets" and method == "POST":
                self.next_id += 1
                self.rulesets.setdefault(repo, []).append(
                    dict(body, id=self.next_id, source_type="Repository")
                )
                return {"id": self.next_id}
            m2 = re.match(r"/rulesets/(\d+)$", rest)
            if m2:
                rs = next(r for r in self.rulesets[repo] if r["id"] == int(m2.group(1)))
                if method == "PUT":
                    rs.update(body)
                return copy.deepcopy(rs)
            raise AssertionError(f"unexpected call {method} {path}")

    def go(cmd, repos, gh, dry=False, org_only=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = run(cmd, repos, dry_run=dry, gh=gh, org_only=org_only)
        return rc, out.getvalue()

    def writes(gh):
        return [c for c in gh.calls if c[0] != "GET"]

    # --org-only (#569): the name a repository_dispatch carries must be an org repository;
    # anything else is refused before a single read of it, and nothing is written
    for name in ("evil", "old", "copy", "../ARA", "ARA/x"):
        gh = FakeGitHub()
        rc, out = go("apply", [name], gh, org_only=True)
        check(
            f"--org-only refuses {name}",
            rc == 1
            and "refused: not a swarm-routing repository" in out
            and all(c[1].startswith(f"orgs/{ORG}/repos?") for c in gh.calls),
        )
    gh = FakeGitHub()
    rc, out = go("apply", ["ara"], gh, org_only=True)
    check(
        "--org-only applies the org's spelling of a listed repository, and only it",
        rc == 0
        and "ARA: applied" in out
        and writes(gh)
        and all(f"repos/{ORG}/ARA" in c[1] for c in writes(gh))
        and not any(f"repos/{ORG}/ara" in c[1] for c in gh.calls),
    )
    gh = FakeGitHub()
    rc, out = go("check", [], gh, org_only=True)
    check("--org-only without names: every org repository, as before", "AntHocNet" in out)
    # the whole org: a private repository is never named, even in a failure (#622)
    gh = FakeGitHub()
    real_api = gh.api

    def failing_api(method, path, body=None):
        if path == f"repos/{ORG}/secret-lib/contents/{CONFIG}":
            raise GhError(method, path, "Server Error (HTTP 500)")
        return real_api(method, path, body)

    gh.api = failing_api
    rc, out = go("check", [], gh)
    check(
        "the org listing never names a private repository",
        "secret-lib" not in out
        and not re.search(r"^secret\b", out, re.M)
        and "private repository 1: invalid [settings]" in out
        and f"private repository 2: FAILED: gh api GET repos/<private>/contents/{CONFIG}" in out,
    )

    # AntHocNet: the protocol profile with CI gate + code scanning, every shared part in place;
    # its own codeql.yml keeps CodeQL default setup off
    gh = FakeGitHub()
    rc, out = go("check", ["AntHocNet"], gh)
    check("AntHocNet in sync with the protocol profile", rc == 0 and "AntHocNet: in sync" in out)
    check(
        "advanced CodeQL left alone",
        "CodeQL runs in .github/workflows/codeql.yml (advanced setup)" in out
        and not any("default-setup" in c[1] for c in gh.calls),
    )
    check("non-workflow yml ignored", not any("not-a-workflow" in c[1] for c in gh.calls))

    # ARA: every field drifts, the ruleset targets nothing, an unmanaged one exists
    rc, out = go("check", ["ARA"], gh)
    check("check exits 1 on drift", rc == 1)
    for want in (
        'ARA description: differs: none -> "ARA."',
        "ARA topics: differs",
        "ARA allow_merge_commit: differs",
        "ARA squash_merge_commit_title: differs",
        "ARA has_wiki: differs: true -> false",
        "ARA has_projects: differs: true -> false",
        "ARA allow_auto_merge: differs: false -> true",
        "ARA allow_update_branch: differs: false -> true",
        "ARA has_discussions: differs: false -> true",
        "ARA security vulnerability_alerts: differs: false -> true",
        "ARA security automated_security_fixes: differs",
        "ARA security secret_scanning: differs",
        "ARA security secret_scanning_push_protection: differs",
        "ARA security private_vulnerability_reporting: differs",
        "ARA security codeql_default_setup: differs",
        'ARA actions allowed_actions: differs: "all" -> "selected"',
        'ARA actions workflow: differs: "write+approve" -> "read"',
        'ARA actions fork_pr_contributor_approval: differs: "first_time_contributors" -> '
        '"all_external_contributors"',
        'ARA environment release: differs: "missing" -> "danieljoppi"',
        "ARA ruleset main: update (conditions, +copilot_code_review, +pull_request, +required_status_checks)",
        "ARA ruleset release-tags: create (missing)",
        "unmanaged ruleset(s) left alone: legacy",
    ):
        check(f"check line: {want}", want in out)
    check("no scanning rules without code_scanning", "code_scanning" not in out)
    # checks that ran on main: listed unless required, optional (patterns) or skipped
    check(
        "unrequired checks listed",
        "ARA: unrequired check: ci / format\n" in out
        and "ARA: unrequired check: ci / ns-latest debug\n" in out
        and "ARA: unrequired check: SonarCloud\n" in out
        and "ARA: unrequired check: Late status\n" in out,  # on the second page
    )
    check(
        "required, optional and skipped checks not listed",
        all(
            f"unrequired check: {c}" not in out
            for c in ("check / org-sync", "codecov/patch", "Analyze (c-cpp)", "title / title")
        ),
    )
    check("plan exits 0 on drift", go("plan", ["ARA"], gh)[0] == 0)
    check("plan and check write nothing", writes(gh) == [])

    # --dry-run writes nothing
    rc, out = go("apply", ["ARA"], gh, dry=True)
    check("dry run", rc == 0 and "would write" in out and writes(gh) == [])

    # apply: only the differences, in order, the managed rulesets updated or created, legacy untouched
    rc, out = go("apply", ["ARA"], gh)
    w = writes(gh)
    paths = [c[1] for c in w]
    check("apply exit 0", rc == 0)
    check(
        "apply PATCH repo",
        any(
            c[0] == "PATCH"
            and c[1] == f"repos/{ORG}/ARA"
            and c[2].get("allow_merge_commit") is False
            and c[2].get("has_wiki") is False
            and c[2].get("has_discussions") is True
            and "topics" not in c[2]
            for c in w
        ),
    )
    check("apply PUT topics", ("PUT", f"repos/{ORG}/ARA/topics", {"names": ["ara"]}) in w)
    check(
        "alerts before security updates, scanning before push protection",
        paths.index(f"repos/{ORG}/ARA/vulnerability-alerts")
        < paths.index(f"repos/{ORG}/ARA/automated-security-fixes")
        and [
            next(iter(c[2]["security_and_analysis"]))
            for c in w
            if "security_and_analysis" in (c[2] or {})
        ]
        == ["secret_scanning", "secret_scanning_push_protection"],
    )
    check(
        "policy `selected` before its patterns",
        paths.index(f"repos/{ORG}/ARA/actions/permissions")
        < paths.index(f"repos/{ORG}/ARA/actions/permissions/selected-actions"),
    )
    check(
        "fork PRs of every outside contributor wait for approval",
        (
            "PUT",
            f"repos/{ORG}/ARA/actions/permissions/fork-pr-contributor-approval",
            {"approval_policy": "all_external_contributors"},
        )
        in w
        and gh.forkpr["ARA"] == {"approval_policy": "all_external_contributors"},
    )
    check(
        "release environment with the maintainer as reviewer",
        any(
            c[1].endswith("/environments/release")
            and c[2]["reviewers"] == [{"type": "User", "id": 42}]
            for c in w
        ),
    )
    check(
        "apply updates ruleset 26312048 and creates release-tags",
        any(c[0] == "PUT" and c[1].endswith("/rulesets/26312048") for c in w)
        and any(c[0] == "POST" and c[2]["name"] == "release-tags" for c in w),
    )
    check(
        "legacy ruleset untouched",
        not any("/rulesets/5" in c[1] for c in w) and not any(c[0] == "DELETE" for c in w),
    )
    check(
        "ruleset carries the repo's checks",
        gh.rulesets["ARA"][0]["rules"][-1]["parameters"]["required_status_checks"]
        == [{"context": "check / org-sync", "integration_id": ACTIONS_APP}],
    )
    rc, out = go("check", ["ARA"], gh)
    check("in sync after apply", rc == 0 and "ARA: in sync" in out)
    check(
        "unrequired checks are not drift", rc == 0 and "ARA: unrequired check: ci / format" in out
    )
    check(
        "the required check is not listed",
        "AntHocNet: unrequired" not in go("check", ["AntHocNet"], gh)[1],
    )
    n = len(gh.calls)
    go("apply", ["ARA"], gh)
    check("apply is idempotent", writes(gh) == w and len(gh.calls) > n)

    # repositories without [settings] or without org-sync.toml are skipped, never written
    gh = FakeGitHub()
    rc, out = go("apply", ["plain", "nocfg"], gh)
    check(
        "skipped",
        rc == 0 and "plain: skipped" in out and "nocfg: skipped" in out and writes(gh) == [],
    )

    # a private repository: which fields differ, never their values; what the free plan does not
    # offer a private repository is a note, not drift; rulesets unavailable is a note
    gh = FakeGitHub()
    rc, out = go("check", ["secret-lib"], gh)
    check(
        "private masked",
        rc == 1
        and "private repository 1 description: differs" in out
        and "private repository 1 allow_merge_commit: differs" in out
        and "private repository 1 security vulnerability_alerts: differs\n" in out
        and "private repository 1 security automated_security_fixes: differs\n" in out
        and "secret-lib" not in out
        and "Secret" not in out
        and "ruleset" not in out,
    )
    check(
        "private: unsupported, not drift",
        "unsupported here: secret_scanning, secret_scanning_push_protection, "
        "private_vulnerability_reporting, codeql_default_setup"
        in out
        and "security secret_scanning" not in out
        and not any("default-setup" in c[1] for c in gh.calls),
    )
    check(
        "private: fork-PR approval is a note, never read",
        "unsupported here: actions fork_pr_contributor_approval (private repository)" in out
        and not any("fork-pr-contributor-approval" in c[1] for c in gh.calls),
    )
    rc, out = go("apply", ["secret-lib"], gh)
    check(
        "private apply masked",
        "Secret" not in out and "secret-lib" not in out and "private repository 1: applied" in out,
    )
    check("private in sync after apply", go("check", ["secret-lib"], gh)[0] == 0)

    # invalid settings are reported and never applied
    gh = FakeGitHub()
    rc, out = go("apply", ["bad", "bad2"], gh)
    check(
        "invalid settings",
        rc == 1
        and "not lowercase-hyphenated" in out
        and "security.nope is not one of" in out
        and "security.secret_scanning is not true or false" in out
        and writes(gh) == [],
    )
    rc, out = go("check", ["secret"], gh)
    check(
        "invalid private topic masked",
        rc == 1
        and "a topic is not lowercase-hyphenated" in out
        and "Hidden" not in out
        and "secret:" not in out
        and "private repository 1: invalid" in out,
    )
    # a workflow using an action outside the allowed list: refused before anything is written
    gh = FakeGitHub()
    rc, out = go("apply", ["rogue"], gh)
    check(
        "uncovered action refused",
        rc == 1
        and "actions not in defaults.json selected_actions: evil/action@v1" in out
        and writes(gh) == [],
    )
    # opt-out, an unreadable section (check fails, plan does not), a 422 is unsupported
    gh = FakeGitHub()
    rc, out = go("check", ["lean"], gh)
    check(
        "unreadable fails check",
        rc == 1
        and "lean actions permissions (HTTP 403): unreadable" in out
        and "codeql" not in out,
    )
    check("unreadable plan exit 0", go("plan", ["lean"], gh)[0] == 0)
    check(
        "unreadable checks on main are a note",
        "lean: note: checks on main unreadable (HTTP 403)" in out,
    )
    # a private repository's unrequired checks: their number, never their names
    priv = {"repo": "p", "private": True, "skip": None, "changes": [], "rulesets": []}
    priv.update(items=[], unreadable=[], notes=[], errors=[], unrequired=["Secret job"])
    check(
        "private unrequired checks counted, not named",
        lines(dict(priv, label="private repository 2"))
        == ["private repository 2: in sync", "private repository 2: 1 unrequired check(s)"],
    )
    check(
        "optional_checks must be a list of names",
        validate({"optional_checks": "codecov/*"})
        and validate({"optional_checks": [""]})
        and not validate({"optional_checks": ["codecov/*"]}),
    )
    rc, out = go("apply", ["empty"], gh)
    check(
        "CodeQL 422 unsupported",
        rc == 0 and "empty: unsupported security codeql_default_setup (HTTP 422)" in out,
    )
    # default setup configured, but a language the repository now holds is not analysed
    # (swarm-routing/ns3-upstream-report#70: Python -> Go, default setup kept `actions` only)
    gh = FakeGitHub()
    go("apply", ["ARA"], gh)
    gh.langs["ARA"] = {"Go": 50000, "Python": 10, "Makefile": 200}
    gh.codeql_langs["ARA"] = ["actions", "c-cpp"]
    rc, out = go("check", ["ARA"], gh)
    check(
        "a detected language missing from default setup is drift",
        rc == 1 and 'ARA security codeql_languages: differs: "actions,c-cpp" -> ' in out,
    )
    check(
        "a configured language with no code left is a note, never removed",
        "ARA: note: CodeQL default setup analyses c-cpp, which the repository no longer holds"
        in out,
    )
    n = len(writes(gh))
    rc, out = go("apply", ["ARA"], gh)
    check(
        "apply adds the missing languages, keeps the rest and the query suite",
        rc == 0
        and writes(gh)[n:]
        == [
            (
                "PATCH",
                f"repos/{ORG}/ARA/code-scanning/default-setup",
                {
                    "state": "configured",
                    "languages": ["actions", "c-cpp", "go", "python"],
                    "query_suite": "default",
                },
            )
        ],
    )
    check("in sync once every language is analysed", go("check", ["ARA"], gh)[0] == 0)
    n = len(writes(gh))
    go("apply", ["ARA"], gh)
    check("all present: no write", writes(gh)[n:] == [])
    # no workflows: `actions` is not wanted; javascript/typescript count as one id
    gh = FakeGitHub()
    gh.codeql["empty"] = "configured"
    gh.langs["empty"] = {"TypeScript": 100, "Python": 5}
    gh.codeql_langs["empty"] = ["javascript", "python"]
    rc, out = go("plan", ["empty"], gh)
    check(
        "no workflows: actions not wanted, older language ids understood",
        "codeql_languages" not in out and "no longer holds" not in out,
    )
    gh.langs["empty"] = {"Ruby": 100, "Python": 5}
    rc, out = go("plan", ["empty"], gh)
    check(
        "no workflows: only the language that is missing",
        '"javascript,python" -> "javascript,python,ruby"' in out and '"actions' not in out,
    )
    # a truncated tree could hide a workflow: the repository fails, nothing is written
    gh = FakeGitHub()
    rc, out = go("apply", ["huge"], gh)
    check(
        "truncated tree fails",
        rc == 1 and "huge: FAILED: huge: the git tree is truncated" in out and writes(gh) == [],
    )
    # a name that is not a repository is refused before any API call or file read
    gh = FakeGitHub()
    rc, out = go("plan", ["../x", "-X"], gh)
    check(
        "bad repository names refused",
        rc == 1 and out.count("not a repository name") == 2 and gh.calls == [],
    )

    # a token without Administration: write: refused, exit 2, check still reports drift (exit 1)
    gh = FakeGitHub(deny_writes=True)
    rc, out = go("apply", ["ARA"], gh)
    check("403 refused", rc == 2 and "refused" in out and "Administration: write" in out)
    check("check with a read-only token", go("check", ["ARA"], gh)[0] == 1)
    # an organization policy that overrides the repository's Actions settings: 409 refused
    gh = FakeGitHub(org_policy=True)
    rc, out = go("apply", ["ARA"], gh)
    check(
        "409 refused",
        rc == 2
        and "ARA: refused actions allowed_actions (HTTP 409)" in out
        and "ARA: applied topics" in out,
    )

    # the real client never hands gh a path that could read as a flag or carry a space
    for bad in ("-X", "repos/a b", "--input=/etc/passwd"):
        try:
            GitHub().api("GET", bad)
            check(f"api path {bad!r} refused", False)
        except GhError as e:
            check(f"api path {bad!r} refused", "not a plain API path" in str(e))

    # merge_queue: refused while the workflow behind a required check has no merge_group
    # trigger; then the rule joins the main ruleset, and a live queue is in sync
    gh = FakeGitHub()
    plain_toml, plain_ci = toml["AntHocNet"], workflows["AntHocNet"][".github/workflows/ci.yml"]
    toml["AntHocNet"] = plain_toml + "merge_queue = true\n"
    gate = "  ci-gate:\n    name: CI gate\n    runs-on: ubuntu-24.04\n"
    workflows["AntHocNet"][".github/workflows/ci.yml"] = "on:\n  pull_request:\n" + plain_ci + gate
    rc, out = go("apply", ["AntHocNet"], gh)
    check(
        "merge_queue refused without merge_group",
        rc == 1
        and "merge_queue: no merge_group trigger on the workflow of CI gate" in out
        and writes(gh) == [],
    )
    workflows["AntHocNet"][".github/workflows/ci.yml"] = (
        "on:\n  pull_request:\n  merge_group:\n" + plain_ci + gate
    )
    # a plain job with the caller's id does not stand in for a `X / Y` check (#294)
    plain_review = (
        "on:\n  pull_request:\njobs:\n  review:\n    runs-on: ubuntu-24.04\n    steps: []\n"
    )
    caller = (
        "on:\n  pull_request:\n  merge_group:\njobs:\n  review:\n"
        "    uses: ./.github/workflows/reusable-review-gate.yml\n"
    )
    check(
        "a plain job of the same id is not the caller of an X / Y check",
        without_merge_group(
            ["review / coderabbit"],
            {
                ".github/workflows/ai-files-review.yml": plain_review,
                ".github/workflows/review-gate.yml": caller,
            },
        )
        == [],
    )
    check(
        "an X / Y check with only a plain job of that id has no merge-group workflow",
        without_merge_group(["review / coderabbit"], {".github/workflows/a.yml": plain_review})
        == ["review / coderabbit"],
    )
    check(
        "a plain check X still matches a plain job X",
        without_merge_group(["review"], {".github/workflows/a.yml": plain_review}) == ["review"],
    )
    rc, out = go("check", ["AntHocNet"], gh)
    check("merge_queue drift", rc == 1 and "AntHocNet ruleset main: update (+merge_queue)" in out)
    rc, out = go("apply", ["AntHocNet"], gh)
    put = [c for c in writes(gh) if c[0] == "PUT" and "rulesets/18147133" in c[1]]
    mq = [r for c in put for r in c[2]["rules"] if r["type"] == "merge_queue"]
    check(
        "merge_queue applied with its parameters",
        rc == 0 and len(mq) == 1 and mq[0]["parameters"] == MERGE_QUEUE,
    )
    check("merge_queue in sync after apply", go("check", ["AntHocNet"], gh)[0] == 0)
    toml["AntHocNet"] = plain_toml + "merge_queue = { check_response_timeout_minutes = 60 }\n"
    rc, out = go("check", ["AntHocNet"], gh)
    check("merge_queue table overrides", rc == 1 and "(~merge_queue)" in out)
    toml["AntHocNet"], workflows["AntHocNet"][".github/workflows/ci.yml"] = plain_toml, plain_ci
    # release_environment: absent leaves an existing gate alone; false strips it, keeps the
    # branch policy, never deletes the environment; a missing one stays missing
    gh = FakeGitHub()
    gate = {"protected_branches": False, "custom_branch_policies": True}
    gh.envs[("AntHocNet", "release")] = {
        "name": "release",
        "protection_rules": [
            {"type": "wait_timer", "wait_timer": 5},
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "reviewer": {"login": "danieljoppi", "id": 42}}],
            },
        ],
        "deployment_branch_policy": gate,
    }
    rc, out = go("check", ["AntHocNet"], gh)
    check("absent release_environment leaves a gate alone", rc == 0 and "environment" not in out)
    toml["AntHocNet"] = plain_toml + "release_environment = false\n"
    rc, out = go("check", ["AntHocNet"], gh)
    check(
        "release_environment = false: a gate is drift",
        rc == 1
        and 'AntHocNet environment release: differs: "wait 5 min,danieljoppi" -> "ungated"' in out,
    )
    rc, out = go("apply", ["AntHocNet"], gh)
    env = gh.envs[("AntHocNet", "release")]
    check(
        "release_environment = false strips the gate, keeps the branch policy",
        rc == 0
        and [c[0] for c in writes(gh)] == ["PUT"]
        and env["deployment_branch_policy"] == gate
        and not any(r["type"] == "required_reviewers" for r in env["protection_rules"])
        and all(r.get("wait_timer", 0) == 0 for r in env["protection_rules"]),
    )
    check("ungated after apply", go("check", ["AntHocNet"], gh)[0] == 0)
    gh = FakeGitHub()
    rc, out = go("apply", ["AntHocNet"], gh)
    check(
        "release_environment = false creates nothing",
        rc == 0 and writes(gh) == [] and ("AntHocNet", "release") not in gh.envs,
    )
    toml["AntHocNet"] = plain_toml
    # [settings.environments]: any other environment, its reviewers and deployment branches;
    # one no table names is left alone, none is deleted, only an undeclared branch policy is
    gh = FakeGitHub()
    other = {"name": "github-pages", "protection_rules": [], "deployment_branch_policy": None}
    gh.envs[("AntHocNet", "github-pages")] = copy.deepcopy(other)
    toml["AntHocNet"] = plain_toml + (
        '[settings.environments.gitlab-write]\nreviewers = ["danieljoppi"]\nbranches = ["main"]\n'
        '[settings.environments.gitlab-read]\nbranches = ["main"]\n'
    )
    rc, out = go("check", ["AntHocNet"], gh)
    check(
        "a declared environment that is missing is drift",
        rc == 1
        and 'AntHocNet environment gitlab-read: differs: "missing" -> "reviewers none; branches main"'
        in out
        and 'AntHocNet environment gitlab-write: differs: "missing" -> '
        '"reviewers danieljoppi; branches main"'
        in out,
    )
    rc, out = go("apply", ["AntHocNet"], gh)
    w, r = gh.envs.get(("AntHocNet", "gitlab-write")), gh.envs.get(("AntHocNet", "gitlab-read"))
    custom = {"protected_branches": False, "custom_branch_policies": True}
    check(
        "apply creates both: reviewers, a custom branch policy naming main",
        rc == 0
        and w is not None
        and r is not None
        and [x["type"] for x in w["protection_rules"]] == ["wait_timer", "required_reviewers"]
        and w["protection_rules"][1]["prevent_self_review"] is False
        and [x["type"] for x in r["protection_rules"]] == ["wait_timer"]
        and w["deployment_branch_policy"] == custom == r["deployment_branch_policy"]
        and [b["name"] for b in gh.policies[("AntHocNet", "gitlab-write")].values()] == ["main"]
        and [b["name"] for b in gh.policies[("AntHocNet", "gitlab-read")].values()] == ["main"],
    )
    check(
        "an environment no table names is left alone",
        gh.envs[("AntHocNet", "github-pages")] == other
        and not any("github-pages" in c[1] for c in writes(gh)),
    )
    n = len(writes(gh))
    rc, out = go("apply", ["AntHocNet"], gh)
    check("declared environments in sync after apply", rc == 0 and len(writes(gh)) == n)
    gh.next_id += 1
    gh.policies[("AntHocNet", "gitlab-write")][gh.next_id] = {"name": "dev", "type": "branch"}
    rc, out = go("check", ["AntHocNet"], gh)
    check(
        "an undeclared branch policy is drift",
        rc == 1
        and 'environment gitlab-write: differs: "reviewers danieljoppi; branches dev,main"' in out,
    )
    rc, out = go("apply", ["AntHocNet"], gh)
    dels = [c for c in writes(gh)[n:] if c[0] == "DELETE"]
    check(
        "apply deletes only that branch policy",
        rc == 0
        and [c[1].rsplit("/", 1)[1] for c in dels] == [str(gh.next_id)]
        and [b["name"] for b in gh.policies[("AntHocNet", "gitlab-write")].values()] == ["main"],
    )
    gh.envs[("AntHocNet", "gitlab-read")]["deployment_branch_policy"] = None
    gh.policies.pop(("AntHocNet", "gitlab-read"))
    rc, out = go("check", ["AntHocNet"], gh)
    check(
        "any branch where main is declared is drift",
        rc == 1 and 'gitlab-read: differs: "reviewers none; branches any"' in out,
    )
    toml["AntHocNet"] = plain_toml + "[settings.environments.open]\n"
    gh = FakeGitHub()
    rc, out = go("apply", ["AntHocNet"], gh)
    check(
        "an empty table: an unprotected environment, no branch policy",
        rc == 0
        and gh.envs[("AntHocNet", "open")]["deployment_branch_policy"] is None
        and not any("deployment-branch-policies" in c[1] for c in writes(gh)),
    )
    check("an empty table in sync after apply", go("check", ["AntHocNet"], gh)[0] == 0)
    toml["AntHocNet"] = plain_toml
    check(
        "a DELETE other than a branch policy is refused before gh runs",
        all(
            "refused" in str(GhErrorOf(lambda p=p: GitHub().api("DELETE", p)))
            for p in (
                f"repos/{ORG}/x/environments/gitlab-write",
                f"repos/{ORG}/x/rulesets/5",
                f"repos/{ORG}/x/environments/a/deployment-branch-policies/1/../x",
            )
        ),
    )
    ok_env = {
        "environments": {"gitlab-write": {"reviewers": ["danieljoppi"], "branches": ["main"]}}
    }
    check("environments valid", validate(ok_env) == [])
    for name, envs, extra, want in (
        ("not a table", "gitlab", {}, "environments is not a table"),
        ("bad name", {"a b": {}}, {}, "is not an environment name"),
        ("entry not a table", {"x": 1}, {}, "environments.x is not a table"),
        ("unknown key", {"x": {"wait": 5}}, {}, "environments.x.wait is not one of"),
        ("reviewers", {"x": {"reviewers": "danieljoppi"}}, {}, "x.reviewers is not a list"),
        ("bad login", {"x": {"reviewers": ["-x"]}}, {}, "x.reviewers is not a list"),
        ("branches", {"x": {"branches": [""]}}, {}, "x.branches is not a list"),
        ("self review", {"x": {"prevent_self_review": 1}}, {}, "x.prevent_self_review"),
        ("release twice", {"release": {}}, {"release_environment": True}, "declare it once"),
    ):
        check(
            f"environments refused: {name}",
            any(want in e for e in validate({"environments": envs, **extra})),
        )
    res = {"private": True, "notes": [], "items": [], "unreadable": []}
    env0 = declared_environments(ok_env)[0]
    plan_declared_environment(FakeGitHub(), res, f"{ORG}/AntHocNet", env0)
    check(
        "a private repository: protection unsupported, not drift",
        res["items"] == []
        and res["notes"]
        == ["unsupported here: environment gitlab-write protection (private repository)"],
    )
    one_line = {".github/workflows/t.yml": "on: [pull_request, merge_group]\njobs:\n  title:\n"}
    check(
        "merge_group found in a flow list, job id matched, reusable prefix used",
        without_merge_group(["title / title", "lint"], one_line) == ["lint"],
    )
    reusable = {
        ".github/workflows/ci.yml": "on:\n  pull_request:\n  merge_group:\njobs:\n  python:\n"
        "    uses: ./.github/workflows/reusable-python-ci.yml\n",
        ".github/workflows/reusable-python-ci.yml": "on:\n  workflow_call:\njobs:\n  python:\n",
    }
    check(
        "a reusable workflow's own job is not the check's workflow",
        without_merge_group(["python / python"], reusable) == [],
    )
    matrix = {
        ".github/workflows/python.yml": "on:\n  pull_request:\n  merge_group:\njobs:\n  tests:\n"
        "    name: ns3-tool tests (Python ${{ matrix.python }})\n"
    }
    check(
        "a matrix job name matches its expanded check names",
        without_merge_group(["ns3-tool tests (Python 3.11)", "ns3-tool lint"], matrix)
        == ["ns3-tool lint"],
    )
    matrix[".github/workflows/python.yml"] = matrix[".github/workflows/python.yml"].replace(
        "  merge_group:\n", ""
    )
    only_expr = {
        ".github/workflows/r.yml": "on:\n  pull_request:\njobs:\n  r:\n    steps:\n"
        "      - uses: x\n        with:\n          name: ${{ needs.r.outputs.artifact }}\n"
    }
    check(
        "a name that is only an expression names no check",
        without_merge_group(["python / python"], {**reusable, **only_expr}) == [],
    )
    # #576: a path-filtered self-test whose job shares the required check's name
    selftest = (
        "on:\n  push:\n    branches: [main]\n  pull_request:\n"
        "    paths: ['.github/workflows/reusable-python-ci.yml']\n  workflow_dispatch:\n"
        "jobs:\n  python:\n    uses: ./.github/workflows/reusable-python-ci.yml\n"
    )
    collide = {**reusable, ".github/workflows/python-ci-selftest.yml": selftest}
    check(
        "a path-filtered workflow sharing a required check's name is not its workflow (#576)",
        without_merge_group(["python / python"], collide) == [],
    )
    check(
        "a path-filtered workflow alone does not report a required check",
        without_merge_group(
            ["python / python"], {".github/workflows/python-ci-selftest.yml": selftest}
        )
        == ["python / python"],
    )
    check(
        "the same name without merge_group, unfiltered, still refuses",
        without_merge_group(
            ["python / python"],
            {
                **collide,
                ".github/workflows/python-ci-selftest.yml": selftest.replace(
                    "    paths: ['.github/workflows/reusable-python-ci.yml']\n", ""
                ),
            },
        )
        == ["python / python"],
    )
    check(
        "paths and paths-ignore under pull_request filter; under push or a sibling they do not",
        [
            pr_path_filtered(t)
            for t in (
                "on:\n  pull_request:\n    paths: [a]\n",
                "on:\n  pull_request:\n    branches: [main]\n    paths-ignore: [a]\n",
                "on:\n  push:\n    paths: [a]\n  pull_request:\n  merge_group:\n",
                "on:\n  pull_request:\n    types: [opened]\njobs:\n  paths:\n",
                "on: [pull_request]\n",
            )
        ]
        == [True, True, False, False, False],
    )
    check(
        "pull_request as a key, in a list, as the only trigger; not pull_request_target",
        [
            runs_on_pr(t)
            for t in (
                "on:\n  pull_request:\n",
                "on: [push, pull_request]\n",
                "on: pull_request\n",
                "on:\n  pull_request_target:\n",
            )
        ]
        == [True, True, True, False],
    )
    check(
        "a matrix job without merge_group is refused",
        without_merge_group(["ns3-tool tests (Python 3.13)"], matrix)
        == ["ns3-tool tests (Python 3.13)"],
    )
    prof_rs = load_profile("protocol")["ruleset"]
    off = main_ruleset(prof_rs, {"required_checks": ["CI gate"]})
    on = main_ruleset(prof_rs, {"required_checks": ["CI gate"], "merge_queue": True})
    check("no merge_queue rule by default", "merge_queue" not in [r["type"] for r in off["rules"]])
    check(
        "merge_queue parameters in GitHub's ranges",
        on["rules"][-1]["type"] == "merge_queue"
        and MERGE_QUEUE["merge_method"] == "SQUASH"
        and MERGE_QUEUE["grouping_strategy"] in ("ALLGREEN", "HEADGREEN")
        and 1 <= MERGE_QUEUE["check_response_timeout_minutes"] <= 360
        and 0 <= MERGE_QUEUE["min_entries_to_merge_wait_minutes"] <= 360
        and MERGE_QUEUE["min_entries_to_merge"] <= MERGE_QUEUE["max_entries_to_merge"] <= 100
        and 0 <= MERGE_QUEUE["max_entries_to_build"] <= 100,
    )
    ok_s = {"ruleset": "protocol", "required_checks": ["CI gate"], "merge_queue": True}
    check("merge_queue valid", validate(ok_s) == [])
    for name, s, private, want in (
        ("not a bool", {**ok_s, "merge_queue": "yes"}, False, "merge_queue is not true, false"),
        ("unknown key", {**ok_s, "merge_queue": {"speed": 1}}, False, "merge_queue.speed"),
        (
            "out of range",
            {**ok_s, "merge_queue": {"check_response_timeout_minutes": 0}},
            False,
            "from 1 to 360",
        ),
        (
            "bad enum",
            {**ok_s, "merge_queue": {"grouping_strategy": "ALLMERGED"}},
            False,
            "ALLGREEN",
        ),
        ("min above max", {**ok_s, "merge_queue": {"min_entries_to_merge": 9}}, False, "above"),
        ("no main ruleset", {**ok_s, "ruleset": "merge-only"}, False, "has no main ruleset"),
        ("no checks", {"ruleset": "protocol", "merge_queue": True}, False, "required_checks"),
        ("private", ok_s, True, "merge_queue on a private repository"),
    ):
        check(f"merge_queue refused: {name}", any(want in e for e in validate(s, private)))

    # merge_methods: a per-repository override of the profile's merge methods
    mm_s = {**ok_s, "merge_methods": ["squash", "merge"], "merge_queue": {"merge_method": "MERGE"}}
    check("merge_methods valid", validate(mm_s) == [])
    mm_rs = main_ruleset(prof_rs, mm_s)
    pr_rule = next(r for r in mm_rs["rules"] if r["type"] == "pull_request")
    check(
        "merge_methods in the ruleset",
        pr_rule["parameters"]["allowed_merge_methods"] == ["squash", "merge"],
    )
    check(
        "merge_methods leave the profile alone",
        next(r for r in prof_rs["rules"] if r["type"] == "pull_request")["parameters"][
            "allowed_merge_methods"
        ]
        == ["squash"],
    )
    mm_repo = desired(mm_s)["repo"]
    check(
        "merge_methods set the repository flags",
        mm_repo["allow_squash_merge"] is True
        and mm_repo["allow_merge_commit"] is True
        and mm_repo["allow_rebase_merge"] is False,
    )
    check(
        "no merge_methods: the profile's flags",
        desired(ok_s)["repo"]["allow_merge_commit"] is False,
    )
    for name, s, want in (
        ("not a list", {**ok_s, "merge_methods": "merge"}, "merge_methods is not"),
        ("empty", {**ok_s, "merge_methods": []}, "merge_methods is not"),
        ("unknown", {**ok_s, "merge_methods": ["octopus"]}, "merge_methods is not"),
        ("duplicate", {**ok_s, "merge_methods": ["merge", "merge"]}, "merge_methods is not"),
        ("no profile", {"merge_methods": ["merge"]}, "without a ruleset profile"),
        ("queue method not allowed", {**ok_s, "merge_methods": ["merge"]}, "SQUASH is not in"),
    ):
        check(f"merge_methods refused: {name}", any(want in e for e in validate(s)))

    # covers(): GitHub's added defaults are ignored, a list must match exactly
    check("covers ignores added keys", covers({"a": 1}, {"a": 1, "b": 2}))
    check("covers lists exact", not covers([1], [1, 2]) and covers([2, 1], [1, 2]))

    for f in failures:
        print(f"FAIL: {f}")
    print(f"repo_settings.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
