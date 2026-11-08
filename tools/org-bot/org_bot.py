#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Open the refresh PRs that keep every org repository in step with this one.

Usage:
  org_bot.py run [--task epics|org-sync|all] [--repos A,B] [--dry-run]
  org_bot.py --self-test

Two tasks, each a generator this repository already has, run on a fresh clone
of each public repository:

  epics     tools/epics/epics.py: the README's `## Epics` section, and in
            .github also ROADMAP.md#epics and the profile's open epics.
  org-sync  tools/org-sync/org_sync.py apply, in each repository with a
            .github/org-sync.toml. Sections the repository owns
            (`org_sync.py conflicts`) are never forced; the PR lists them.

When a run changes files, the bot opens one PR per repository and task:
- the branch is `org-bot/<task>-<hash of the change>`;
- the title is a lowercase Conventional Commit;
- the body says what was generated, from which run.

If that exact change is already open as a PR, nothing happens. An older bot
PR for the same task is closed as superseded, with a pointer to the new one.
The bot never merges: CI runs on the PR because it is opened with a personal
or app token, not the workflow's own GITHUB_TOKEN. A person or an agent
merges it when CI is green.

The token comes from ORG_BOT_TOKEN, never from the command line. It is a
fine-grained token on the swarm-routing org with Contents, Pull requests and
Workflows read and write (org-sync renders a workflow file). Without it every
run is a dry run: it clones read-only and prints each change it would propose.
GitHub is read and written through `gh api`, and git authenticates through the
GIT_CONFIG_* environment, so the token is in no argument list. Output is one
summary line per repository and task (AntHocNet ADR-0014). Stdlib only.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EPICS = os.path.join(ROOT, "tools", "epics", "epics.py")
ORG_SYNC = os.path.join(ROOT, "tools", "org-sync", "org_sync.py")
ORG = "swarm-routing"
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")

TASKS = {
    "epics": {
        "title": "docs: refresh the epic list (org-bot)",
        "what": "The generated epic lists no longer match the issues labelled `epic`. "
        "Regenerated with swarm-routing/.github `tools/epics/epics.py` "
        '(CONTRIBUTING, "Epics are the public plan").',
    },
    "org-sync": {
        "title": "chore: apply the org templates (org-bot)",
        "what": "The org-managed files drifted from swarm-routing/.github `templates/`. "
        "Rendered with `tools/org-sync/org_sync.py apply`, which never overwrites a "
        "section this repository owns.",
    },
}


class Failure(SystemExit):
    pass


def sh(cmd, cwd=None, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Failure(f"{' '.join(cmd[:3])}…: {r.stderr.strip() or r.stdout.strip()}")
    return r


class GitHub:
    """GitHub through `gh api`; `token` is used for writes (and reads, when set)."""

    def __init__(self, token=None):
        self.env = dict(os.environ)
        if token:
            self.env["GH_TOKEN"] = token

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
            raise Failure(f"gh api {method} {path}: {r.stderr.strip()}")
        return json.loads(r.stdout) if r.stdout.strip() else {}


def git_env(token):
    env = dict(
        os.environ,
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME=BOT[0],
        GIT_AUTHOR_EMAIL=BOT[1],
        GIT_COMMITTER_NAME=BOT[0],
        GIT_COMMITTER_EMAIL=BOT[1],
    )
    if token:
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {cred}",
        )
    return env


def branch_for(task, diff):
    return f"org-bot/{task}-{hashlib.sha256(diff.encode()).hexdigest()[:8]}"


def apply_failed(returncode, stderr):
    """org_sync.py apply: 0 is clean, 1 with a quiet stderr is owned sections left alone."""
    return returncode > 1 or (returncode == 1 and bool(stderr.strip()))


def generate(task, repo, clone, data, out):
    """Run the task's generator in `clone`; return the lines it printed."""
    if task == "epics":
        cmds = [[sys.executable, "-I", EPICS, "readme", clone, "--repo", repo, "--data", data]]
        if repo == ".github":
            cmds += [
                [
                    sys.executable,
                    "-I",
                    EPICS,
                    "roadmap",
                    os.path.join(clone, "ROADMAP.md"),
                    "--data",
                    data,
                ],
                [
                    sys.executable,
                    "-I",
                    EPICS,
                    "profile",
                    os.path.join(clone, "profile", "README.md"),
                    "--data",
                    data,
                ],
            ]
    else:
        if not os.path.exists(os.path.join(clone, ".github", "org-sync.toml")):
            return None
        cmds = [[sys.executable, "-I", ORG_SYNC, "apply", clone]]
    for c in cmds:
        # org_sync.py apply exits 1 when sections the repository owns differ (it
        # leaves them and lists them on stdout); only a crash writes to stderr.
        r = sh(c, check=task != "org-sync")
        if task == "org-sync" and apply_failed(r.returncode, r.stderr):
            raise Failure(f"org_sync.py apply: {r.stderr.strip() or r.stdout.strip()}")
        out.append(r.stdout.strip())
    if task == "org-sync":
        r = sh([sys.executable, "-I", ORG_SYNC, "conflicts", clone], check=False)
        if r.stdout.strip():
            out.append("conflicts left to the repository:\n" + r.stdout.strip())
    return out


def pr_body(task, notes, run_url):
    lines = [
        "## What & why",
        "",
        TASKS[task]["what"],
        "",
        "## Verification",
        "",
        "Generated content only; this repository's CI runs on this PR. Generator output:",
        "",
        "```",
        *[n for n in notes if n],
        "```",
        "",
        "## Record",
        "",
        f"Opened by the org-bot ({run_url or 'a local run'}): swarm-routing/.github "
        "`tools/org-bot/org_bot.py`. A newer change to the same files closes this PR as "
        "superseded. Merge when CI is green.",
    ]
    return "\n".join(lines)


def propose(gh, repo, task, clone, notes, env, dry_run, run_url):
    """One PR for the change in `clone`, unless the same change is already open."""
    diff = sh(["git", "-C", clone, "diff"]).stdout
    status = sh(["git", "-C", clone, "status", "--porcelain"]).stdout
    if not status.strip():
        print(f"{repo} {task}: up to date")
        return None
    stat = sh(["git", "-C", clone, "diff", "--stat"]).stdout.strip().splitlines()
    branch = branch_for(task, diff + status)
    if dry_run:
        print(
            f"{repo} {task}: would open a PR from {branch} ({stat[-1].strip() if stat else 'new files'})"
        )
        return {"branch": branch, "dry_run": True}
    full = f"{ORG}/{repo}"
    open_prs = gh.api("GET", f"repos/{full}/pulls?state=open&per_page=100")
    mine = [
        p
        for p in open_prs
        if p["head"]["ref"].startswith(f"org-bot/{task}-")
        and p["head"].get("repo", {}).get("full_name", full) == full
    ]
    same = [p for p in mine if p["head"]["ref"] == branch]
    if same:
        print(f"{repo} {task}: already proposed in #{same[0]['number']}")
        return {"number": same[0]["number"], "branch": branch}
    base = gh.api("GET", f"repos/{full}")["default_branch"]
    sh(["git", "-C", clone, "checkout", "-q", "-b", branch], env=env)
    sh(["git", "-C", clone, "add", "-A"], env=env)
    msg = f"{TASKS[task]['title']}\n\nGenerated by swarm-routing/.github tools/org-bot ({run_url or 'local run'})."
    sh(["git", "-C", clone, "commit", "-q", "-m", msg], env=env)
    sh(
        ["git", "-C", clone, "push", "-q", "origin", f"+HEAD:refs/heads/{branch}"], env=env
    )  # org-bot/ is the bot's own namespace
    pr = gh.api(
        "POST",
        f"repos/{full}/pulls",
        {
            "title": TASKS[task]["title"],
            "head": branch,
            "base": base,
            "body": pr_body(task, notes, run_url),
        },
    )
    for old in mine:
        gh.api(
            "POST",
            f"repos/{full}/issues/{old['number']}/comments",
            {"body": f"Superseded by #{pr['number']}, which carries the newer generated change."},
        )
        gh.api("PATCH", f"repos/{full}/pulls/{old['number']}", {"state": "closed"})
        gh.api("DELETE", f"repos/{full}/git/refs/heads/{old['head']['ref']}")
    closed = (
        f"; closed {', '.join('#' + str(o['number']) for o in mine)} as superseded" if mine else ""
    )
    print(f"{repo} {task}: opened #{pr['number']} from {branch}{closed}")
    return {"number": pr["number"], "branch": branch}


def run(args, gh=None, clone_url=None):
    token = os.environ.get("ORG_BOT_TOKEN") or None
    dry_run = args.dry_run or not token
    if not token and not args.dry_run:
        print("org-bot: ORG_BOT_TOKEN is not set; dry run")
    gh = gh or GitHub(token)
    clone_url = clone_url or "https://github.com/{org}/{repo}.git"
    tasks = ["epics", "org-sync"] if args.task == "all" else [args.task]
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        )
    work = tempfile.mkdtemp(prefix="org-bot-")
    data = os.path.join(work, "epics.json")
    fetch = [sys.executable, "-I", EPICS, "fetch", "--out", data]
    if args.repos:
        fetch += ["--repos", args.repos]
    if args.data:
        shutil.copy(args.data, data)
    else:
        sh(fetch, env=gh.env)
    repos = [r["name"] for r in json.load(open(data))["repos"]]  # public, not archived, not forks
    env = git_env(None if dry_run else token)
    results, failed = [], []
    for repo in repos:
        clone = os.path.join(work, repo)
        try:
            sh(
                ["git", "clone", "-q", "--depth", "1", clone_url.format(org=ORG, repo=repo), clone],
                env=env,
            )
            base_sha = sh(["git", "-C", clone, "rev-parse", "HEAD"], env=env).stdout.strip()
            for task in tasks:
                # every task starts from the cloned commit, never from the last task's
                sh(["git", "-C", clone, "checkout", "-q", "--", "."], env=env)
                sh(["git", "-C", clone, "clean", "-qfd"], env=env)
                sh(["git", "-C", clone, "checkout", "-q", "--detach", base_sha], env=env)
                notes = generate(task, repo, clone, data, [])
                if notes is None:
                    continue
                results.append(
                    (repo, task, propose(gh, repo, task, clone, notes, env, dry_run, run_url))
                )
        except Failure as e:
            failed.append(repo)
            print(f"{repo}: FAILED: {e}")
    shutil.rmtree(work, ignore_errors=True)
    if failed:
        raise Failure(f"org-bot: {len(failed)} repositories failed: {', '.join(failed)}")
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--task", choices=["epics", "org-sync", "all"], default="all")
    r.add_argument("--repos", default="", help="comma-separated names (default: every public repo)")
    r.add_argument("--data", default="", help="saved `epics.py fetch` output instead of the API")
    r.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.cmd != "run":
        p.error("a command is required")
    run(args)
    return 0


# --- self-test: local bare repositories and a recording fake GitHub ----------


def self_test():
    import contextlib
    import io

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    work = tempfile.mkdtemp(prefix="org-bot-test-")
    env = git_env(None)
    remotes = os.path.join(work, "remotes")

    def make_repo(name, readme):
        src = os.path.join(work, "src", name)
        os.makedirs(src)
        with open(os.path.join(src, "README.md"), "w") as fh:
            fh.write(readme)
        sh(["git", "init", "-q", "-b", "main", src], env=env)
        sh(["git", "-C", src, "add", "-A"], env=env)
        sh(["git", "-C", src, "commit", "-q", "-m", "init"], env=env)
        sh(
            ["git", "clone", "-q", "--bare", src, os.path.join(remotes, ORG, name + ".git")],
            env=env,
        )

    stale = "# Alpha\n\n## Licence\n\nGPL.\n"
    make_repo("alpha", stale)
    data = os.path.join(work, "data.json")
    epic = {
        "number": 3,
        "title": "[epic] alpha thing",
        "state": "open",
        "state_reason": None,
        "completed": 0,
        "total": 2,
        "closed_at": None,
        "url": "https://github.com/swarm-routing/alpha/issues/3",
    }
    with open(data, "w") as fh:
        json.dump(
            {
                "org": ORG,
                "repos": [
                    {
                        "name": "alpha",
                        "url": "https://github.com/swarm-routing/alpha",
                        "epics": [epic],
                    }
                ],
            },
            fh,
        )

    class FakeGitHub:
        env = dict(os.environ)

        def __init__(self, open_prs=()):
            self.calls, self.open = [], list(open_prs)

        def api(self, method, path, body=None):
            self.calls.append((method, path, body))
            if method == "GET" and "/pulls?" in path:
                return self.open
            if method == "GET":
                return {"default_branch": "main"}
            if method == "POST" and path.endswith("/pulls"):
                return {"number": 42}
            return {}

    clone_url = "file://" + remotes + "/{org}/{repo}.git"

    def go(gh, dry=False, token="tok", task="epics"):
        ns = argparse.Namespace(task=task, repos="", data=data, dry_run=dry)
        old = os.environ.get("ORG_BOT_TOKEN")
        if token:
            os.environ["ORG_BOT_TOKEN"] = token
        else:
            os.environ.pop("ORG_BOT_TOKEN", None)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                res = run(ns, gh=gh, clone_url=clone_url)
        finally:
            if old is None:
                os.environ.pop("ORG_BOT_TOKEN", None)
            else:
                os.environ["ORG_BOT_TOKEN"] = old
        return res, out.getvalue()

    # dry run without a token: a plan, no API write, nothing pushed
    gh = FakeGitHub()
    res, out = go(gh, token=None)
    check("dry run without token", "ORG_BOT_TOKEN is not set" in out and "would open a PR" in out)
    check("dry run: no API call", gh.calls == [])
    heads = sh(
        [
            "git",
            "--git-dir",
            os.path.join(remotes, ORG, "alpha.git"),
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
        ]
    ).stdout
    check("dry run: nothing pushed", heads.split() == ["main"])
    branch = res[0][2]["branch"]
    check(
        "branch name",
        branch.startswith("org-bot/epics-") and len(branch) == len("org-bot/epics-") + 8,
    )
    # with a token: branch pushed, PR opened, title and body as specified
    gh = FakeGitHub()
    res, out = go(gh)
    check("opened", "opened #42" in out and res[0][2]["number"] == 42)
    heads = sh(
        ["git", "--git-dir", os.path.join(remotes, ORG, "alpha.git"), "branch", "--list"]
    ).stdout
    check("branch pushed", branch in heads)
    shown = sh(
        ["git", "--git-dir", os.path.join(remotes, ORG, "alpha.git"), "show", f"{branch}:README.md"]
    ).stdout
    check(
        "pushed change is the epics section",
        "<!-- epics:begin -->" in shown
        and "#3" in shown
        and shown.index("## Epics") < shown.index("## Licence"),
    )
    author = sh(
        [
            "git",
            "--git-dir",
            os.path.join(remotes, ORG, "alpha.git"),
            "log",
            "-1",
            "--format=%an <%ae>",
            branch,
        ]
    ).stdout.strip()
    check("bot identity", author == f"{BOT[0]} <{BOT[1]}>")
    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    check(
        "one PR",
        len(post) == 1
        and post[0][2]["title"] == "docs: refresh the epic list (org-bot)"
        and post[0][2]["head"] == branch
        and post[0][2]["base"] == "main",
    )
    check(
        "body sections",
        all(h in post[0][2]["body"] for h in ("## What & why", "## Verification", "## Record")),
    )
    # the same change already open: nothing written
    gh = FakeGitHub(
        [{"number": 42, "head": {"ref": branch, "repo": {"full_name": f"{ORG}/alpha"}}}]
    )
    res, out = go(gh)
    check(
        "same change: skipped",
        "already proposed in #42" in out and not any(c[0] != "GET" for c in gh.calls),
    )
    # an older bot PR for the task is closed as superseded, its branch deleted
    gh = FakeGitHub(
        [
            {
                "number": 7,
                "head": {"ref": "org-bot/epics-00000000", "repo": {"full_name": f"{ORG}/alpha"}},
            }
        ]
    )
    sh(["git", "--git-dir", os.path.join(remotes, ORG, "alpha.git"), "branch", "-D", branch])
    res, out = go(gh)
    check(
        "superseded closed",
        "closed #7 as superseded" in out
        and ("PATCH", f"repos/{ORG}/alpha/pulls/7", {"state": "closed"}) in gh.calls
        and any(
            c[0] == "DELETE" and c[1].endswith("/refs/heads/org-bot/epics-00000000")
            for c in gh.calls
        ),
    )
    # a PR of another task, or from a fork, is left alone
    gh = FakeGitHub(
        [
            {
                "number": 8,
                "head": {"ref": "org-bot/org-sync-11111111", "repo": {"full_name": f"{ORG}/alpha"}},
            },
            {
                "number": 9,
                "head": {"ref": "org-bot/epics-22222222", "repo": {"full_name": "someone/alpha"}},
            },
        ]
    )
    sh(["git", "--git-dir", os.path.join(remotes, ORG, "alpha.git"), "branch", "-D", branch])
    res, out = go(gh)
    check("other task and forks untouched", not any(c[0] in ("PATCH", "DELETE") for c in gh.calls))
    # an up-to-date repository: nothing at all
    sh(
        [
            "git",
            "--git-dir",
            os.path.join(remotes, ORG, "alpha.git"),
            "update-ref",
            "refs/heads/main",
            branch,
        ]
    )
    gh = FakeGitHub()
    res, out = go(gh)
    check("up to date", "alpha epics: up to date" in out and gh.calls == [])
    # org-sync skips a repository without .github/org-sync.toml
    gh = FakeGitHub()
    res, out = go(gh, task="org-sync")
    check("org-sync skips unadopted repos", res == [] and gh.calls == [])

    # one run, both tasks: each PR carries only its own task's change
    def fake_generate(task, repo, clone, data_, out):
        name = "README.md" if task == "epics" else "SYNCED.md"
        with open(os.path.join(clone, name), "a") as fh:
            fh.write(f"\n{task} change\n")
        return [f"{task} generated"]

    real_generate = globals()["generate"]
    globals()["generate"] = fake_generate
    try:
        gh = FakeGitHub()
        res, out = go(gh, task="all")
    finally:
        globals()["generate"] = real_generate
    branches = {t: r["branch"] for _, t, r in res}
    git_dir = os.path.join(remotes, ORG, "alpha.git")
    sync_files = sh(
        ["git", "--git-dir", git_dir, "diff", "--name-only", "main", branches["org-sync"]]
    ).stdout.split()
    epics_files = sh(
        ["git", "--git-dir", git_dir, "diff", "--name-only", "main", branches["epics"]]
    ).stdout.split()
    check("tasks kept apart", sync_files == ["SYNCED.md"] and epics_files == ["README.md"])
    # a stale bot branch of that name (its PR closed by hand, unrelated history) is overwritten
    git_dir = os.path.join(remotes, ORG, "alpha.git")
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's well-known empty tree
    orphan = sh(
        ["git", "--git-dir", git_dir, "commit-tree", empty_tree, "-m", "stale"], env=env
    ).stdout.strip()
    sh(["git", "--git-dir", git_dir, "update-ref", f"refs/heads/{branches['org-sync']}", orphan])
    globals()["generate"] = fake_generate
    try:
        gh = FakeGitHub()
        res, out = go(gh, task="org-sync")
    finally:
        globals()["generate"] = real_generate
    pushed = sh(["git", "--git-dir", git_dir, "rev-parse", branches["org-sync"]]).stdout.strip()
    check(
        "stale branch overwritten", "opened #42" in out and "FAILED" not in out and pushed != orphan
    )
    # org_sync.py apply: exit 1 with only stdout is owned sections left alone; anything else fails
    check(
        "apply exit codes",
        not apply_failed(0, "")
        and not apply_failed(1, "  \n")
        and apply_failed(1, "Traceback ...")
        and apply_failed(2, ""),
    )
    # the token never reaches an argument list
    e = git_env("s3cret")
    check(
        "token only in env",
        "s3cret" not in e.get("GIT_CONFIG_KEY_0", "")
        and base64.b64decode(e["GIT_CONFIG_VALUE_0"].split()[-1]).decode()
        == "x-access-token:s3cret",
    )
    shutil.rmtree(work, ignore_errors=True)
    for f in failures:
        print(f"FAIL: {f}")
    print(f"org_bot.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
