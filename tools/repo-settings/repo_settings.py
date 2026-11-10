#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Repository settings as code: description, homepage, topics, merge settings and the branch ruleset.

Usage:
  repo_settings.py plan  [REPO...] [--local DIR]
  repo_settings.py check [REPO...] [--local DIR]
  repo_settings.py apply [REPO...] [--local DIR] [--dry-run]
  repo_settings.py --self-test

Each repository declares its settings in the `[settings]` table of its own
`.github/org-sync.toml` (read through the contents API, or from
DIR/<repo>/.github/org-sync.toml with --local):

    [settings]
    description = "One line, at most 350 characters."
    homepage = "https://swarm-routing.github.io/arena/ARA/"   # "" for none
    topics = ["manet", "ns-3"]          # lowercase-hyphenated, at most 20
    ruleset = "protocol"                # templates/rulesets/<profile>.json: protocol, tooling,
                                        # data, site, merge-only (no ruleset); "" for neither
    required_checks = ["CI gate"]       # check-run names that run on every PR
    code_scanning = false               # true only where CodeQL uploads results

A repository with no org-sync templates carries a settings-only file (no
`kind`); org-sync and org-bot skip it.

A profile (`templates/rulesets/<profile>.json`) holds the merge settings
(squash only, PR title and body as the squash commit, delete the branch on
merge) and the branch ruleset in the REST API shape. The ruleset's
`code_scanning` and `code_quality` rules are kept only with `code_scanning =
true` (a repository that never uploads CodeQL results would hold every PR
waiting for them), and `required_status_checks` takes `required_checks`
(GitHub Actions checks), dropped when there are none: a required check that a
`paths:` filter skips blocks a PR forever, so list only always-running jobs.

`plan` lists the differences between the live repository and its
declaration, `check` does the same and exits 1 on drift, `apply` writes only
the differences (`--dry-run`: says what it would write). A repository with no
`[settings]` is never touched; the only rulesets managed are those named in
a profile (`main`), and none is ever deleted. Without REPO the org listing is
used (all repositories, not archived, not forks). The values of a private
repository are never printed, only which fields differ, since the output may
land in a public log or issue. A write the token is not allowed (HTTP 403:
the token needs Administration: write) is reported as `refused` and `apply`
exits 2; any other failure exits 1.

The token comes from ORG_BOT_TOKEN, else GH_TOKEN (gh's own login), never
from the command line; GitHub is reached through `gh api`. Output is one
summary line per difference (AntHocNet ADR-0014). Stdlib only; Python 3.11+.
"""

import argparse
import base64
import copy
import json
import os
import re
import subprocess
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES = os.path.join(ROOT, "templates", "rulesets")
ORG = "swarm-routing"
CONFIG = ".github/org-sync.toml"
ACTIONS_APP = 15368  # GitHub Actions: the app every required check comes from
REPO_FIELDS = ("description", "homepage", "topics")
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
RULESET_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors", "rules")
SCANNING_RULES = ("code_scanning", "code_quality")


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
    if not re.fullmatch(r"[a-z0-9-]+", name) or not os.path.exists(path):
        raise ValueError(f"unknown ruleset profile {name!r} (templates/rulesets/)")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_settings(gh, repo, local=None):
    """The repository's `[settings]` table, or None when it declares none."""
    if local:
        try:
            with open(os.path.join(local, repo, CONFIG), "rb") as f:
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


def validate(s):
    errors = []
    if len(s.get("description", "")) > 350:
        errors.append("description is longer than 350 characters")
    topics = s.get("topics", [])
    if len(topics) > 20:
        errors.append("more than 20 topics")
    errors += [f"topic {t!r} is not lowercase-hyphenated" for t in topics if not TOPIC.match(t)]
    if s.get("required_checks") and not s.get("ruleset"):
        errors.append("required_checks without a ruleset profile")
    return errors


def desired(s):
    """(repository fields, ruleset or None) that the settings table declares."""
    want = {
        "description": s.get("description", ""),
        "homepage": s.get("homepage", ""),
        "topics": sorted(s.get("topics", [])),
    }
    if not s.get("ruleset"):
        return want, None
    prof = load_profile(s["ruleset"])
    want.update(prof["repo"])
    if prof["ruleset"] is None:
        return want, None
    rs = copy.deepcopy(prof["ruleset"])
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
        rules.append(r)
    rs["rules"] = rules
    return want, rs


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


def short(v):
    if v in (None, "", []):
        return "none"
    if isinstance(v, bool):
        return json.dumps(v)
    s = ",".join(v) if isinstance(v, list) else str(v)
    return json.dumps(s if len(s) <= 70 else s[:67] + "...", ensure_ascii=False)


def plan_repo(gh, repo, local=None):
    """What differs in one repository: {repo, private, skip, changes, ruleset, notes, errors}."""
    res = {
        "repo": repo,
        "private": False,
        "skip": None,
        "changes": [],
        "ruleset": None,
        "notes": [],
    }
    s = read_settings(gh, repo, local)
    if s is None:
        res["skip"] = f"no [settings] in {CONFIG}"
        return res
    res["errors"] = validate(s)
    if res["errors"]:
        return res
    want, want_rs = desired(s)
    meta = gh.api("GET", f"repos/{ORG}/{repo}")
    res["private"] = bool(meta.get("private"))
    for k, v in want.items():
        have = meta.get(k)
        if k == "topics":
            have = sorted(have or [])
        elif k in ("description", "homepage"):
            have = have or ""
        if have != v:
            res["changes"].append((k, have, v))
    if want_rs is None:
        return res
    try:
        live = gh.api("GET", f"repos/{ORG}/{repo}/rulesets?includes_parents=false&per_page=100")
    except GhError as e:
        if e.status == 403 and "Upgrade" in str(e):
            res["notes"].append("rulesets are not available on this plan (private repository)")
            return res
        raise
    mine = [
        r
        for r in live
        if r.get("name") == want_rs["name"] and r.get("source_type", "Repository") == "Repository"
    ]
    others = sorted(r["name"] for r in live if r.get("name") != want_rs["name"])
    if others:
        res["notes"].append(f"unmanaged ruleset(s) left alone: {', '.join(others)}")
    if not mine:
        res["ruleset"] = {"action": "create", "want": want_rs, "drift": ["missing"]}
    else:
        full = gh.api("GET", f"repos/{ORG}/{repo}/rulesets/{mine[0]['id']}")
        drift = ruleset_drift(want_rs, full)
        if drift:
            res["ruleset"] = {
                "action": "update",
                "id": mine[0]["id"],
                "want": want_rs,
                "drift": drift,
            }
    return res


def drifted(res):
    return bool(res["changes"] or res["ruleset"] or res.get("errors"))


def lines(res, verb="differs"):
    name = res["repo"] + (" (private)" if res["private"] else "")
    if res["skip"]:
        return [f"{name}: skipped ({res['skip']})"]
    out = [f"{name}: invalid [settings]: {e}" for e in res.get("errors", [])]
    for k, have, want in res["changes"]:
        if res["private"]:
            out.append(f"{name} {k}: {verb}")
        else:
            out.append(f"{name} {k}: {verb}: {short(have)} -> {short(want)}")
    if res["ruleset"]:
        r = res["ruleset"]
        out.append(f"{name} ruleset {r['want']['name']}: {r['action']} ({', '.join(r['drift'])})")
    if not out:
        out.append(f"{name}: in sync")
    return out + [f"{name}: note: {n}" for n in res["notes"]]


# --- writes --------------------------------------------------------------------


def apply_repo(gh, res):
    """Write the differences; return (lines, refused)."""
    full = f"{ORG}/{res['repo']}"
    name = res["repo"] + (" (private)" if res["private"] else "")
    out, refused = [], False
    changed = {k: want for k, _, want in res["changes"]}
    writes = []
    patch = {k: v for k, v in changed.items() if k != "topics"}
    if patch:
        writes.append(("PATCH", f"repos/{full}", patch, ", ".join(sorted(patch))))
    if "topics" in changed:
        writes.append(("PUT", f"repos/{full}/topics", {"names": changed["topics"]}, "topics"))
    rs = res["ruleset"]
    if rs:
        body = {k: rs["want"][k] for k in RULESET_KEYS}
        if rs["action"] == "create":
            writes.append(
                ("POST", f"repos/{full}/rulesets", body, f"ruleset {body['name']} created")
            )
        else:
            writes.append(
                (
                    "PUT",
                    f"repos/{full}/rulesets/{rs['id']}",
                    body,
                    f"ruleset {body['name']} updated",
                )
            )
    for method, path, body, what in writes:
        try:
            gh.api(method, path, body)
            out.append(f"{name}: applied {what}")
        except GhError as e:
            if e.status in (403, 404):
                refused = True
                out.append(
                    f"{name}: refused {what} (HTTP {e.status}): the token needs Administration: write"
                )
            else:
                raise
    return out, refused


# --- commands ------------------------------------------------------------------


def org_repos(gh):
    names, page = [], 1
    while True:
        batch = gh.api("GET", f"orgs/{ORG}/repos?type=all&per_page=100&page={page}")
        names += [r["name"] for r in batch if not r.get("archived") and not r.get("fork")]
        if len(batch) < 100:
            return sorted(names, key=str.lower)
        page += 1


def run(cmd, repos, local=None, dry_run=False, gh=None):
    gh = gh or GitHub()
    if not repos:
        try:
            repos = org_repos(gh)
        except GhError as e:
            print(f"repo-settings: cannot list the org ({e}); name the repositories")
            return 1
    rc = 0
    for repo in repos:
        try:
            res = plan_repo(gh, repo, local)
        except (GhError, ValueError, tomllib.TOMLDecodeError) as e:
            print(f"{repo}: FAILED: {e}")
            rc = 1
            continue
        if cmd == "apply" and not dry_run and drifted(res) and not res.get("errors"):
            try:
                out, refused = apply_repo(gh, res)
            except GhError as e:
                print(f"{repo}: FAILED: {e}")
                rc = 1
                continue
            print("\n".join(out + [f"{res['repo']}: note: {n}" for n in res["notes"]]))
            if refused and rc == 0:
                rc = 2
            continue
        print("\n".join(lines(res, "would write" if cmd == "apply" else "differs")))
        if res.get("errors") or (cmd == "check" and drifted(res)):
            rc = 1
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    for name in ("plan", "check", "apply"):
        s = sub.add_parser(name)
        s.add_argument("repos", nargs="*", help="repository names (default: every org repository)")
        s.add_argument("--local", help="read DIR/<repo>/.github/org-sync.toml instead of the API")
        if name == "apply":
            s.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.cmd:
        p.error("a command is required")
    return run(a.cmd, a.repos, a.local, getattr(a, "dry_run", False))


# --- self-test: a fake GitHub holding repositories, contents and rulesets -----


def self_test():
    import contextlib
    import io

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    # every profile loads and has the shape the tool relies on
    for f in sorted(os.listdir(PROFILES)):
        prof = load_profile(f[: -len(".json")])
        rs = prof["ruleset"] or {**dict.fromkeys(RULESET_KEYS), "name": "main"}
        check(
            f"profile {f}",
            rs["name"] == "main"
            and all(k in rs for k in RULESET_KEYS)
            and prof["repo"]["allow_squash_merge"] is True
            and prof["repo"]["squash_merge_commit_title"] == "PR_TITLE",
        )
    try:
        load_profile("../x")
        check("unknown profile rejected", False)
    except ValueError:
        pass

    merge = load_profile("protocol")["repo"]
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
                    "dismiss_stale_reviews_on_push": False,
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
                    "strict_required_status_checks_policy": True,
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
        'ruleset = "protocol"\nrequired_checks = ["check / org-sync"]\n',
        "plain": 'kind = "protocol"\n',
        "papers": '[settings]\ndescription = "Secret workspace."\ntopics = ["papers"]\nruleset = "merge-only"\n',
        "bad": '[settings]\ndescription = "x"\ntopics = ["Bad_Topic"]\n',
    }

    class FakeGitHub:
        def __init__(self, deny_writes=False):
            self.calls, self.deny = [], deny_writes
            self.repos = {
                "AntHocNet": dict(
                    merge,
                    description="Ant routing.",
                    homepage="https://x/AntHocNet/",
                    topics=["aco", "manet"],
                    private=False,
                ),
                "ARA": dict(
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
                ),
                "plain": dict(private=False, topics=[]),
                "nocfg": dict(private=False, topics=[]),
                "papers": dict(private=True, description=None, homepage=None, topics=[]),
                "bad": dict(private=False, topics=[]),
            }
            self.rulesets = {
                "AntHocNet": [copy.deepcopy(anthocnet_live)],
                "ARA": [
                    copy.deepcopy(targets_nothing),
                    {"id": 5, "name": "legacy", "source_type": "Repository"},
                ],
            }

        def api(self, method, path, body=None):
            self.calls.append((method, path, body))
            m = re.match(rf"repos/{ORG}/([^/?]+)(.*)$", path)
            repo, rest = m.group(1), m.group(2)
            if method != "GET" and self.deny:
                raise GhError(method, path, "Resource not accessible by integration (HTTP 403)")
            if rest == f"/contents/{CONFIG}":
                if repo not in toml:
                    raise GhError(method, path, "Not Found (HTTP 404)")
                return {"content": base64.b64encode(toml[repo].encode()).decode()}
            if rest == "" and method == "GET":
                return copy.deepcopy(self.repos[repo])
            if rest == "" and method == "PATCH":
                self.repos[repo].update(body)
                return {}
            if rest == "/topics":
                self.repos[repo]["topics"] = sorted(body["names"])
                return {}
            if rest.startswith("/rulesets?"):
                if self.repos[repo]["private"]:
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
                self.rulesets.setdefault(repo, []).append(
                    dict(body, id=99, source_type="Repository")
                )
                return {"id": 99}
            m2 = re.match(r"/rulesets/(\d+)$", rest)
            if m2:
                rs = next(r for r in self.rulesets[repo] if r["id"] == int(m2.group(1)))
                if method == "PUT":
                    rs.update(body)
                return copy.deepcopy(rs)
            raise AssertionError(f"unexpected call {method} {path}")

    def go(cmd, repos, gh, dry=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = run(cmd, repos, dry_run=dry, gh=gh)
        return rc, out.getvalue()

    def writes(gh):
        return [c for c in gh.calls if c[0] != "GET"]

    # AntHocNet's hand-set ruleset is exactly the protocol profile with CI gate + code scanning
    gh = FakeGitHub()
    rc, out = go("check", ["AntHocNet"], gh)
    check("AntHocNet in sync with the protocol profile", rc == 0 and "AntHocNet: in sync" in out)

    # ARA: every field drifts, the ruleset targets nothing, an unmanaged one exists
    rc, out = go("check", ["ARA"], gh)
    check("check exits 1 on drift", rc == 1)
    for want in (
        'ARA description: differs: none -> "ARA."',
        "ARA topics: differs",
        "ARA allow_merge_commit: differs",
        "ARA squash_merge_commit_title: differs",
        "ARA ruleset main: update (conditions, +copilot_code_review, +pull_request, +required_status_checks)",
        "unmanaged ruleset(s) left alone: legacy",
    ):
        check(f"check line: {want}", want in out)
    check("no scanning rules without code_scanning", "code_scanning" not in out)
    check("plan exits 0 on drift", go("plan", ["ARA"], gh)[0] == 0)
    check("plan and check write nothing", writes(gh) == [])

    # --dry-run writes nothing
    rc, out = go("apply", ["ARA"], gh, dry=True)
    check("dry run", rc == 0 and "would write" in out and writes(gh) == [])

    # apply: only the differences, the managed ruleset updated in place, legacy untouched
    rc, out = go("apply", ["ARA"], gh)
    w = writes(gh)
    check("apply exit 0", rc == 0)
    check(
        "apply PATCH repo",
        any(
            c[0] == "PATCH" and c[2]["allow_merge_commit"] is False and "topics" not in c[2]
            for c in w
        ),
    )
    check("apply PUT topics", ("PUT", f"repos/{ORG}/ARA/topics", {"names": ["ara"]}) in w)
    check(
        "apply updates ruleset 26312048",
        any(c[0] == "PUT" and c[1].endswith("/rulesets/26312048") for c in w),
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

    # a missing ruleset is created
    gh = FakeGitHub()
    gh.rulesets["ARA"] = []
    go("apply", ["ARA"], gh)
    check("ruleset created", any(c[0] == "POST" and c[1].endswith("/rulesets") for c in writes(gh)))
    check("created ruleset in sync", go("check", ["ARA"], gh)[0] == 0)

    # repositories without [settings] or without org-sync.toml are skipped, never written
    gh = FakeGitHub()
    rc, out = go("apply", ["plain", "nocfg"], gh)
    check(
        "skipped",
        rc == 0 and "plain: skipped" in out and "nocfg: skipped" in out and writes(gh) == [],
    )

    # a private repository: which fields differ, never their values; rulesets unavailable is a note
    gh = FakeGitHub()
    rc, out = go("check", ["papers"], gh)
    check(
        "private masked",
        rc == 1
        and "papers (private) description: differs" in out
        and "papers (private) allow_merge_commit: differs" in out
        and "Secret" not in out
        and "ruleset" not in out,
    )
    rc, out = go("apply", ["papers"], gh)
    check("private apply masked", "Secret" not in out and "papers (private): applied" in out)

    # invalid settings are reported and never applied
    gh = FakeGitHub()
    rc, out = go("apply", ["bad"], gh)
    check("invalid topic", rc == 1 and "not lowercase-hyphenated" in out and writes(gh) == [])

    # a token without Administration: write: refused, exit 2, check still reports drift (exit 1)
    gh = FakeGitHub(deny_writes=True)
    rc, out = go("apply", ["ARA"], gh)
    check("403 refused", rc == 2 and "refused" in out and "Administration: write" in out)
    check("check with a read-only token", go("check", ["ARA"], gh)[0] == 1)

    # covers(): GitHub's added defaults are ignored, a list must match exactly
    check("covers ignores added keys", covers({"a": 1}, {"a": 1, "b": 2}))
    check("covers lists exact", not covers([1], [1, 2]) and covers([2, 1], [1, 2]))

    for f in failures:
        print(f"FAIL: {f}")
    print(f"repo_settings.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
