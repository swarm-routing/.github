#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Self-test for reusable-release.yml's `route` step (#943): the step's own
`run:` script, read from the workflow, runs under bash against a fake `gh`
(a canned GitHub API) and a fake push payload. Exits non-zero on the first
failure; no pytest dependency.

Covered: a merge queue's batched push whose head is not the bump commit
releases the bump commit; an ordinary push is a no-op; a bump-looking commit
from another branch is not released; mode publish releases a merged bump
commit and refuses a malformed sha, a commit off the default branch, a
commit that is not a bump, a version already out, and resumes a tag on the
same commit with no release; mode release by dispatch and the other modes
keep the run's own commit."""

import json
import os
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, "..", "..", ".github", "workflows", "reusable-release.yml")
REPO = "swarm-routing/fixture"
BASE = "main"
BUMP = "b" * 40  # the merged bump PR
HEAD = "c" * 40  # another PR, merged in the same batch on top of it
OTHER = "d" * 40  # a commit that is no bump
OFF = "e" * 40  # a bump-looking commit off the default branch
TITLE = "chore(release): bump version 1.0.0 to 1.1.0"

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
assert args and args[0] == "api", args
path, jq, i = None, None, 1
while i < len(args):
    a = args[i]
    if a == "--jq":
        jq = args[i + 1]; i += 2
    elif a in ("-X", "-H", "-f", "-F", "--method"):
        i += 2
    elif a.startswith("-"):
        i += 1
    else:
        path = a; i += 1
api = json.load(open(os.environ["FAKE_API"]))
if path not in api:
    print(f"gh: Not Found (HTTP 404) {path}", file=sys.stderr)
    sys.exit(1)
body = json.dumps(api[path])
if jq is None:
    print(body)
else:
    sys.exit(subprocess.run(["jq", "-r", jq], input=body, text=True).returncode)
"""


def route_script():
    wf = yaml.safe_load(open(WORKFLOW))
    steps = wf["jobs"]["route"]["steps"]
    return next(s["run"] for s in steps if s.get("id") == "route")


def pr(sha, head_ref, title=TITLE, head_repo=REPO):
    return {
        "merged_at": "2026-11-25T10:00:00Z",
        "merge_commit_sha": sha,
        "base": {"ref": BASE},
        "head": {"ref": head_ref, "repo": {"full_name": head_repo}},
        "title": title,
        "html_url": f"https://github.com/{REPO}/pull/1",
    }


def api(extra=None):
    r = f"repos/{REPO}"
    a = {
        r: {"default_branch": BASE},
        f"{r}/commits/{BUMP}/pulls": [pr(BUMP, "bot/release")],
        f"{r}/commits/{HEAD}/pulls": [pr(HEAD, "feature", title="feat: other (#2)")],
        f"{r}/commits/{OTHER}/pulls": [pr(OTHER, "feature", title="fix: something (#3)")],
        f"{r}/commits/{OFF}/pulls": [pr(OFF, "evil", head_repo="someone/fork")],
        f"{r}/compare/{BUMP}...{BASE}": {"status": "ahead"},
        f"{r}/compare/{HEAD}...{BASE}": {"status": "identical"},
        f"{r}/compare/{OTHER}...{BASE}": {"status": "ahead"},
        f"{r}/commits/{BUMP}": {"sha": BUMP, "commit": {"message": TITLE + " (#1)\n\nbody"}},
        f"{r}/commits/{OTHER}": {"sha": OTHER, "commit": {"message": "fix: something (#3)"}},
        f"{r}/git/matching-refs/tags/v1.1.0": [],
    }
    a.update(extra or {})
    return a


def push_event(*commits):
    return {
        "commits": [{"id": c, "message": m} for c, m in commits],
        "head_commit": {"id": commits[-1][0]},
    }


def run(tmp, *, event="push", payload=None, mode="", sha_in="", fake=None, github_sha=HEAD):
    with open(os.path.join(tmp, "api.json"), "w") as f:
        json.dump(api(fake), f)
    with open(os.path.join(tmp, "event.json"), "w") as f:
        json.dump(payload or {}, f)
    out = os.path.join(tmp, "out")
    open(out, "w").close()
    env = {
        "PATH": f"{tmp}/bin:{os.environ['PATH']}",
        "FAKE_API": os.path.join(tmp, "api.json"),
        "GH_TOKEN": "fake",
        "MODE_IN": mode,
        "DRY_RUN": "false",
        "INCREMENT": "",
        "EVENT": event,
        "TAG_IN": "",
        "SHA_IN": sha_in,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_REF": f"refs/heads/{BASE}",
        "GITHUB_SHA": github_sha,
        "GITHUB_EVENT_PATH": os.path.join(tmp, "event.json"),
        "GITHUB_OUTPUT": out,
        "RUNNER_TEMP": tmp,
    }
    # as GitHub runs a `run:` step: bash -e -o pipefail
    p = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", os.path.join(tmp, "route.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    outputs = dict(ln.split("=", 1) for ln in open(out).read().splitlines() if "=" in ln)
    return p.returncode, outputs, p.stdout + p.stderr


def main():
    failures = []

    def check(name, cond, log=""):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)
            print(log)

    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "bin"))
        gh = os.path.join(tmp, "bin", "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH)
        os.chmod(gh, 0o755)
        with open(os.path.join(tmp, "route.sh"), "w") as f:
            f.write(route_script())

        batch = push_event((BUMP, TITLE + " (#1)"), (HEAD, "feat: other (#2)"))
        rc, o, log = run(tmp, payload=batch)
        check(
            "batched push: the bump commit below the head is released",
            rc == 0
            and o.get("mode") == "release"
            and o.get("sha") == BUMP
            and o.get("version") == "1.1.0",
            log,
        )
        check(
            "batched push: says the head is not the release", "below this push's head" in log, log
        )

        rc, o, log = run(tmp, payload=push_event((BUMP, TITLE + " (#1)")), github_sha=BUMP)
        check(
            "push of the bump alone: released as before",
            rc == 0 and o.get("mode") == "release" and o.get("sha") == BUMP,
            log,
        )

        rc, o, log = run(tmp, payload=push_event((OTHER, "fix: something (#3)")), github_sha=OTHER)
        check(
            "ordinary push: a no-op",
            rc == 0 and o.get("mode") == "none" and o.get("sha") == OTHER and "version" not in o,
            log,
        )

        rc, o, log = run(tmp, payload=push_event((OFF, TITLE), (OTHER, "fix: x")), github_sha=OTHER)
        check(
            "a bump message from another branch: not released",
            rc == 0 and o.get("mode") == "none",
            log,
        )

        off_base = {f"repos/{REPO}/compare/{BUMP}...{BASE}": {"status": "diverged"}}
        rc, o, log = run(tmp, payload=batch, fake=off_base)
        check(
            "push: a bump commit off the default branch is refused",
            rc != 0 and "is not on main" in log,
            log,
        )

        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in=BUMP)
        check(
            "publish: a merged bump commit is released by hand",
            rc == 0
            and o.get("mode") == "release"
            and o.get("sha") == BUMP
            and o.get("version") == "1.1.0",
            log,
        )

        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in="fbb8cc6")
        check("publish: a short sha is refused", rc != 0 and "full 40-hex" in log, log)

        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in="")
        check("publish: no sha is refused", rc != 0 and "mode publish needs sha" in log, log)

        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in=OTHER)
        check(
            "publish: a commit that is no bump PR's merge is refused",
            rc != 0 and "nothing to release" in log,
            log,
        )

        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in=BUMP, fake=off_base)
        check(
            "publish: a commit off the default branch is refused",
            rc != 0 and "is not on main" in log,
            log,
        )

        bad_msg = {
            f"repos/{REPO}/commits/{BUMP}": {
                "sha": BUMP,
                "commit": {"message": "Merge pull request #1"},
            }
        }
        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in=BUMP, fake=bad_msg)
        check(
            "publish: a commit whose message is no bump is refused",
            rc != 0 and "is not a release bump" in log,
            log,
        )

        tag = {
            f"repos/{REPO}/git/matching-refs/tags/v1.1.0": [
                {"ref": "refs/tags/v1.1.0", "object": {"sha": "f" * 40}}
            ],
            f"repos/{REPO}/commits/v1.1.0": {"sha": BUMP},
        }
        rc, o, log = run(
            tmp,
            event="workflow_dispatch",
            mode="publish",
            sha_in=BUMP,
            fake={**tag, f"repos/{REPO}/releases/tags/v1.1.0": {"id": 1}},
        )
        check(
            "publish: a version already released is refused",
            rc != 0 and "exists already" in log,
            log,
        )

        rc, o, log = run(
            tmp,
            event="workflow_dispatch",
            mode="publish",
            sha_in=BUMP,
            fake={**tag, f"repos/{REPO}/commits/v1.1.0": {"sha": OTHER}},
        )
        check(
            "publish: a tag on another commit is refused", rc != 0 and "exists already" in log, log
        )

        rc, o, log = run(tmp, event="workflow_dispatch", mode="publish", sha_in=BUMP, fake=tag)
        check(
            "publish: a tag on this commit with no release resumes",
            rc == 0
            and o.get("mode") == "release"
            and o.get("sha") == BUMP
            and "publish resumes" in log,
            log,
        )

        rc, o, log = run(tmp, event="workflow_dispatch", mode="release", github_sha=BUMP)
        check(
            "release by dispatch: the run's own commit, as before",
            rc == 0 and o.get("mode") == "release" and o.get("sha") == BUMP,
            log,
        )

        rc, o, log = run(tmp, event="workflow_dispatch", mode="release", github_sha=HEAD)
        check("release by dispatch of a non-bump commit: refused, as before", rc != 0, log)

        rc, o, log = run(tmp, event="workflow_dispatch", mode="bump", sha_in=BUMP)
        check(
            "bump: sha is ignored, the run's own commit",
            rc == 0
            and o.get("mode") == "bump"
            and o.get("sha") == HEAD
            and "applies to mode publish only" in log,
            log,
        )

    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("\nall route checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
