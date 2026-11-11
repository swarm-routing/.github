#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Developer Certificate of Origin check for a pull request (swarm-routing/.github#179).

Every commit an outside contributor adds to a PR carries a
``Signed-off-by: Name <email>`` trailer whose email is the commit's author
email (``git commit -s``), which certifies the DCO 1.1 (the ``DCO`` file in
swarm-routing/.github) and records the per-directory licence grant
(CONTRIBUTING "Outside contributions", AntHocNet ADR-0028).

Exempt, since their commits are made by the maintainer's own account or a bot:

- commits whose GitHub author is the PR's author when the PR's
  ``author_association`` is OWNER, MEMBER or COLLABORATOR;
- commits whose GitHub author has write, maintain or admin permission on the
  repository (``repos/{o}/{r}/collaborators/{user}/permission``);
- commits by ``swarm-routing-bot[bot]`` and ``dependabot[bot]``;
- merge commits (an "Update branch" merge brings in main, nothing new).

The commits and their messages come from git (``BASE..HEAD`` in the checkout);
only the GitHub login of each commit's author comes from the REST API
(``pulls/{n}/commits``), with ``GH_TOKEN``. Output: one line per commit, and
on failure the exact commands that fix it.

Usage (in the PR checkout, full history; the commit range comes from the
environment, PR_BASE_SHA and PR_HEAD_SHA, full SHAs, never from arguments):
    PR_BASE_SHA=... PR_HEAD_SHA=... check-dco.py --repo OWNER/REPO --pr N \\
        --pr-author LOGIN --association ASSOC
    check-dco.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

EXEMPT_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
EXEMPT_BOTS = frozenset({"swarm-routing-bot[bot]", "dependabot[bot]"})
EXEMPT_PERMISSIONS = frozenset({"admin", "maintain", "write"})
SIGNOFF = re.compile(r"^Signed-off-by:([^<\n]*)<([^<>\s]+)>[ \t]*$", re.I)
TRAILER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*:")
SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def ident(name: str, email: str) -> str:
    """`Name <email>` compared without case or extra spaces."""
    return f"{' '.join(name.split()).casefold()} <{email.strip().casefold()}>"


def trailer_block(message: str) -> list[str]:
    """The message's trailer lines: its last paragraph, not the subject's, when
    every line of it is `Token: value` or a continuation (leading whitespace)
    of one, as git reads trailers. A Signed-off-by quoted in the body is not
    a trailer."""
    paragraphs = re.split(r"\n[ \t]*\n", message.strip("\n"))
    if len(paragraphs) < 2:
        return []
    lines = paragraphs[-1].split("\n")
    if not TRAILER.match(lines[0]):
        return []
    if all(TRAILER.match(line) or line[:1] in (" ", "\t") for line in lines):
        return lines
    return []


def signoffs(message: str) -> list[str]:
    """The identities of the message's Signed-off-by trailers (see ident)."""
    return [
        ident(m.group(1), m.group(2))
        for m in (SIGNOFF.match(line) for line in trailer_block(message))
        if m
    ]


def git_commits(base: str, head: str) -> list[dict]:
    """sha, author name, author email, parent count and message of BASE..HEAD."""
    for sha in (base, head):
        if not SHA.match(sha):
            raise ValueError(f"not a full commit SHA: {sha!r}")
    fmt = "%H%x1f%an%x1f%ae%x1f%P%x1f%B%x1e"
    out = subprocess.run(
        ["git", "log", "--reverse", f"--format={fmt}", "--end-of-options", f"{base}..{head}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, name, email, parents, message = rec.split("\x1f", 4)
        commits.append(
            {
                "sha": sha,
                "name": name,
                "email": email,
                "parents": len(parents.split()),
                "message": message,
            }
        )
    return commits


def api_get(path: str):
    req = urllib.request.Request(f"{API}/{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pr_logins(repo: str, pr: int, get=api_get) -> dict[str, str]:
    """sha -> the GitHub login of its author (absent when GitHub knows none)."""
    out, page = {}, 1
    while True:
        batch = get(f"repos/{repo}/pulls/{pr}/commits?per_page=100&page={page}")
        for c in batch:
            if c.get("author") and c["author"].get("login"):
                out[c["sha"]] = c["author"]["login"]
        if len(batch) < 100:
            return out
        page += 1


def permission_lookup(repo: str, get=api_get):
    cache = {}

    def has_write(login: str) -> bool:
        if login not in cache:
            try:
                perm = get(f"repos/{repo}/collaborators/{login}/permission").get("permission")
            except (urllib.error.URLError, OSError, ValueError):
                perm = None  # unknown: not exempt, the contributor signs off
            cache[login] = perm in EXEMPT_PERMISSIONS
        return cache[login]

    return has_write


def verdicts(commits, logins, pr_author, association, has_write) -> list[tuple[str, dict, str]]:
    """(status, commit, why) per commit; status is ok, exempt or FAIL."""
    out = []
    for c in commits:
        login = logins.get(c["sha"], "")
        if c["parents"] > 1:
            out.append(("exempt", c, "merge commit"))
        elif login in EXEMPT_BOTS:
            out.append(("exempt", c, f"bot {login}"))
        elif login and login == pr_author and association in EXEMPT_ASSOCIATIONS:
            out.append(("exempt", c, f"{login} is {association}"))
        elif login and has_write(login):
            out.append(("exempt", c, f"{login} has write access"))
        elif ident(c["name"], c["email"]) in signoffs(c["message"]):
            out.append(("ok", c, f"Signed-off-by {c['name']} <{c['email']}>"))
        elif signoffs(c["message"]):
            out.append(
                (
                    "FAIL",
                    c,
                    f"Signed-off-by {', '.join(signoffs(c['message']))} does not match "
                    f"the author {c['name']} <{c['email']}>",
                )
            )
        else:
            out.append(("FAIL", c, f"no Signed-off-by: {c['name']} <{c['email']}>"))
    return out


HOW_TO_FIX = """\
How to fix (CONTRIBUTING "Outside contributions"): sign off every commit with
the same name and email as its author, which certifies the Developer
Certificate of Origin 1.1 (https://developercertificate.org/):

  git commit --amend -s --no-edit            # only the last commit
  git rebase --signoff HEAD~{n}              # all {n} commits of this PR
  git push --force-with-lease

`--signoff` signs as you (the committer): it fixes only commits you
authored. A commit someone else authored needs that author's own sign-off.

If the author email itself is wrong, set it first (git config user.email
<you@example.org>), then `git rebase --exec 'git commit --amend --no-edit
--reset-author -s' HEAD~{n}`. Use `git commit -s` from now on."""


def report(rows) -> int:
    for status, c, why in rows:
        subject = c["message"].split("\n", 1)[0][:72]
        print(f"{status:6} {c['sha'][:12]} {subject} ({why})")
    bad = [r for r in rows if r[0] == "FAIL"]
    print(f"{len(rows)} commit(s); {len(bad)} without a matching Signed-off-by")
    if bad:
        for _, c, why in bad:
            print(f"::error::commit {c['sha'][:12]}: {why}")
        print(HOW_TO_FIX.format(n=len(rows)))
        return 1
    return 0


def self_test() -> int:
    def commit(sha, email, message, parents=1, name="Ada"):
        return {"sha": sha, "name": name, "email": email, "parents": parents, "message": message}

    commits = [
        commit("a1", "ada@x.org", "feat: a\n\nSigned-off-by:  ada  <ADA@x.org>\n"),
        commit("b2", "ada@x.org", "fix: b\n"),
        commit("c3", "ada@x.org", "fix: c\n\nSigned-off-by: Bob <bob@x.org>\n"),
        commit("d4", "m@x.org", "chore: maintainer\n"),
        commit("e5", "bot@x.org", "chore: bot\n"),
        commit("f6", "d@x.org", "chore(deps): bump\n"),
        commit("g7", "ada@x.org", "Merge branch 'main'\n", parents=2),
        commit("h8", "w@x.org", "fix: a writer pushed to the fork\n"),
        commit("i9", "nologin@x.org", "fix: no GitHub user\n"),
        commit("j0", "ada@x.org", "fix: d\n\nSigned-off-by: Bob <ada@x.org>\n"),
        # quoted in the body, not a trailer
        commit("k1", "ada@x.org", "fix: e\n\nSigned-off-by: Ada <ada@x.org>\nmore body text\n"),
        commit("l2", "ada@x.org", "fix: f\n\nSigned-off-by: Ada <ada@x.org>\n\nthe end\n"),
        commit("m3", "ada@x.org", "Signed-off-by: Ada <ada@x.org>\n"),
        # in the trailer block, among other trailers and a continuation line
        commit(
            "n4",
            "ada@x.org",
            "fix: g\n\nbody\n\nCo-Authored-By: Bob\n <bob@x.org>\n"
            "Signed-off-by: Ada <ada@x.org>\nClaude-Session: https://x\n",
        ),
    ]
    logins = {
        "a1": "ada",
        "b2": "ada",
        "c3": "ada",
        "d4": "maint",
        "e5": "swarm-routing-bot[bot]",
        "f6": "dependabot[bot]",
        "g7": "ada",
        "h8": "writer",
    }
    perms = {"writer": "write", "ada": "read"}
    calls = []

    def has_write(login):
        calls.append(login)
        return perms.get(login) in EXEMPT_PERMISSIONS

    want = {
        "a1": "ok",
        "b2": "FAIL",
        "c3": "FAIL",
        "d4": "FAIL",  # maint opened nothing and has no write access here
        "e5": "exempt",
        "f6": "exempt",
        "g7": "exempt",
        "h8": "exempt",
        "i9": "FAIL",
        "j0": "FAIL",  # the right email under another name
        "k1": "FAIL",
        "l2": "FAIL",
        "m3": "FAIL",
        "n4": "ok",
    }
    fails = 0
    for bad in ("--output=/tmp/x", "HEAD", "abc"):
        try:
            git_commits(bad, "0" * 40)
            fails += 1
            print(f"SELF-TEST FAIL (accepted {bad!r} as a SHA)")
        except ValueError:
            pass
    got = {c["sha"]: s for s, c, _ in verdicts(commits, logins, "ada", "NONE", has_write)}
    if got != want:
        fails += 1
        print(f"SELF-TEST FAIL (outside PR): {got}")
    # the same commits in a PR the maintainer opened: their own commit is exempt
    got = {c["sha"]: s for s, c, _ in verdicts(commits, logins, "maint", "OWNER", has_write)}
    if got["d4"] != "exempt" or got["b2"] != "FAIL":
        fails += 1
        print(f"SELF-TEST FAIL (member PR): {got}")
    # an outside PR's author is never exempt by association alone
    got = {c["sha"]: s for s, c, _ in verdicts(commits, logins, "ada", "CONTRIBUTOR", has_write)}
    if got["b2"] != "FAIL":
        fails += 1
        print(f"SELF-TEST FAIL (contributor association): {got}")
    # pagination and a commit without a GitHub author
    pages = {
        1: [{"sha": f"s{i}", "author": {"login": "ada"}} for i in range(100)],
        2: [{"sha": "t", "author": None}],
    }
    got = pr_logins("o/r", 1, lambda p: pages[int(p.rsplit("=", 1)[1])])
    if len(got) != 100 or "t" in got:
        fails += 1
        print(f"SELF-TEST FAIL (pagination): {len(got)}")
    # a failed permission lookup is not an exemption, and is asked once

    def boom(path):
        raise urllib.error.HTTPError(path, 403, "forbidden", None, None)

    hw = permission_lookup("o/r", boom)
    if hw("x") or hw("x"):
        fails += 1
        print("SELF-TEST FAIL (permission lookup error exempted)")
    # the report fails and prints the fix
    rows = verdicts(commits[:2], logins, "ada", "NONE", lambda _: False)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = report(rows)
    if rc != 1 or "git rebase --signoff HEAD~2" not in buf.getvalue():
        fails += 1
        print(f"SELF-TEST FAIL (report): rc={rc}")
    if report([]) != 0:
        fails += 1
    # git: a real two-commit history, one signed
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

        def git(*a):
            return subprocess.run(
                ["git", "-C", d, "-c", "user.name=Ada", "-c", "user.email=ada@x.org", *a],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            ).stdout.strip()

        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "base")
        base = git("rev-parse", "HEAD")
        git("commit", "-q", "--allow-empty", "-s", "-m", "feat: signed")
        git("commit", "-q", "--allow-empty", "-m", "fix: unsigned")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            cs = git_commits(base, git("rev-parse", "HEAD"))
        finally:
            os.chdir(cwd)
        st = [s for s, _, _ in verdicts(cs, {}, "ada", "NONE", lambda _: False)]
        if st != ["ok", "FAIL"]:
            fails += 1
            print(f"SELF-TEST FAIL (git): {st}")
    print("self-test:", "PASS" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--repo")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--pr-author", default="")
    ap.add_argument("--association", default="NONE")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    base, head = os.environ.get("PR_BASE_SHA", ""), os.environ.get("PR_HEAD_SHA", "")
    if not (a.repo and a.pr and base and head):
        ap.error("--repo, --pr and the PR_BASE_SHA and PR_HEAD_SHA variables are required")
    commits = git_commits(base, head)
    logins = pr_logins(a.repo, a.pr)
    rows = verdicts(commits, logins, a.pr_author, a.association, permission_lookup(a.repo))
    return report(rows)


if __name__ == "__main__":
    sys.exit(main())
