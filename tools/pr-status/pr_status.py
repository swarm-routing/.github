#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""One compact view of the open PRs across the org's repositories.

Usage:
  pr_status.py list [--repos A,B] [--author LOGIN] [--json]
  pr_status.py threads REPO#N [--all] [--json]
  pr_status.py wait REPO#N [REPO#N ...] [--interval S] [--timeout S] [--json]
  pr_status.py --self-test

`list` prints one line per open PR, then one line per unresolved review
thread under it:

  .github#95 593400c ci=pass(success=3,skipped=1) merge=clean threads=1 · feat(x): title
    Minor · Add the missing failing fixtures. · tools/x.py:58 · 4518902668

- `ci` is the verdict over the head commit's check runs and commit statuses
  (fail > pending > pass; `none` when nothing reported), then the count of
  each conclusion;
- `merge` is GitHub's mergeable_state (`unknown` until GitHub has computed it),
  and `draft` is printed for a draft;
- a thread line is `severity · title · path:line · comment id`. For a
  CodeRabbit comment the severity and the title come from its heading lines
  only: `<details>`, `<!-- -->` and `<picture>` blocks (analysis chains, agent
  prompts) are dropped unread. For anyone else the severity is `@login` and
  the title is the comment's first line. The comment id is the thread's first
  comment, for a reply (`pulls/comments/{id}/replies`).

`threads REPO#N` prints the thread lines of one PR (`--all` adds the resolved
ones, marked). `wait` polls the PRs until no check is pending, then prints
their `list` lines; it exits 2 if `--timeout` passes first.

A REPO is a name in the swarm-routing org or `owner/name`. The org-wide API is
not available to agent sessions, so `--repos` names the repositories (default:
the org's public ones, DEFAULT_REPOS). Review threads come from
`pulls/{n}/ccr/review_threads` (resolved, path, line, comment_ids); where that
endpoint is missing the count prints as `threads=?`. Read-only: every call is
a GET through `gh api`, which authenticates with GH_TOKEN or the gh CLI's own
login (`gh auth token`), so no token is in an argument list. Findings are
printed as data; nothing here acts on their text. Stdlib only.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter

ORG = "swarm-routing"
DEFAULT_REPOS = [
    ".github",
    "skills",
    "AntHocNet",
    "swarm-routing.github.io",
    "ns3-containers",
    "ns3-swarm-core",
    "ns3-tools",
    "benchmarks",
    "ARA",
    "BeeAdHoc",
    "Termite",
    "HOPNET",
]
FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "error"}
SEVERITIES = ("critical", "major", "minor", "trivial", "nitpick", "info")
TITLE_MAX = 100


class Failure(SystemExit):
    pass


class GitHub:
    """GitHub REST through `gh api`, GET only; None for a 404."""

    def get(self, path):
        r = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            if "HTTP 404" in r.stderr:
                return None
            raise Failure(f"gh api {path}: {r.stderr.strip()}")
        return json.loads(r.stdout or "null")

    def paged(self, path):
        sep = "&" if "?" in path else "?"
        out, page = [], 1
        while True:
            got = self.get(f"{path}{sep}per_page=100&page={page}")
            items = got.get("check_runs", []) if isinstance(got, dict) else got or []
            out += items
            if len(items) < 100:
                return out
            page += 1


# --- the parts ---------------------------------------------------------------


def full_repo(name):
    return name if "/" in name else f"{ORG}/{name}"


def short_repo(repo):
    return repo.split("/", 1)[1] if repo.startswith(ORG + "/") else repo


def parse_ref(ref):
    m = re.fullmatch(r"([\w.-]+(?:/[\w.-]+)?)#(\d+)", ref.strip())
    if not m:
        raise Failure(f"pr_status: not REPO#N: {ref!r}")
    return full_repo(m.group(1)), int(m.group(2))


def ci_summary(gh, repo, sha):
    """The verdict and the count of each conclusion over check runs and statuses."""
    counts = Counter()
    for run in gh.paged(f"repos/{repo}/commits/{sha}/check-runs"):
        done = run.get("status") == "completed"
        counts[(run.get("conclusion") or "pending") if done else "pending"] += 1
    status = gh.get(f"repos/{repo}/commits/{sha}/status") or {}
    for s in status.get("statuses", []):
        counts[s.get("state") or "pending"] += 1
    if not counts:
        verdict = "none"
    elif FAILED & set(counts):
        verdict = "fail"
    elif "pending" in counts:
        verdict = "pending"
    else:
        verdict = "pass"
    return {"verdict": verdict, "counts": dict(sorted(counts.items()))}


def strip_html(body):
    """A review comment without its collapsed blocks, HTML comments and images."""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    text = re.sub(r"<picture>.*?</picture>", "", text, flags=re.S | re.I)
    inner = re.compile(r"<details\b(?:(?!<details\b).)*?</details>", re.S | re.I)
    while True:  # innermost first, so nested blocks go whole
        text, n = inner.subn("", text)
        if not n:
            break
    return re.sub(r"<img\b[^>]*>", "", text, flags=re.I)


def clean(s):
    s = re.sub(r"[*_`]", "", s).strip()
    return s if len(s) <= TITLE_MAX else s[: TITLE_MAX - 1] + "…"


def heading(body, login):
    """(severity, title) from a review comment: a bot's heading lines, else the first line."""
    lines = [ln.strip() for ln in strip_html(body).splitlines() if ln.strip()]
    if not lines:
        return (f"@{login}", "")
    if not login.startswith("coderabbitai"):
        return (f"@{login}", clean(lines[0]))
    severity, rest = "-", lines
    first = lines[0]
    tagged = re.search(r"[·|]", first) and not re.fullmatch(r"\*\*[^*]+\*\*", first)
    if tagged or first.startswith("_"):
        parts = [clean(p) for p in re.split(r"[·|]", first) if clean(p)]
        named = [p for p in parts if any(w in p.lower() for w in SEVERITIES)]
        severity = (named or parts or ["-"])[0]
        severity = re.sub(r"^[^\w]+", "", severity) or "-"
        rest = lines[1:]
    bold = [ln for ln in rest if re.fullmatch(r"\*\*[^*]+\*\*", ln)]
    return (severity, clean((bold or rest or [""])[0]))


def threads(gh, repo, number, include_resolved=False):
    """The PR's review threads as dicts, or None where the endpoint is missing."""
    raw = gh.get(f"repos/{repo}/pulls/{number}/ccr/review_threads")
    if raw is None:
        return None
    out = []
    for t in raw:
        if t.get("resolved") and not include_resolved:
            continue
        ids = t.get("comment_ids") or []
        c = gh.get(f"repos/{repo}/pulls/comments/{ids[0]}") if ids else None
        login = ((c or {}).get("user") or {}).get("login", "?")
        sev, title = heading((c or {}).get("body", ""), login)
        out.append(
            {
                "severity": sev,
                "title": title,
                "path": t.get("path"),
                "line": t.get("line"),
                "id": ids[0] if ids else None,
                "replies": max(len(ids) - 1, 0),
                "resolved": bool(t.get("resolved")),
                "outdated": bool(t.get("outdated")),
            }
        )
    return out


def pr_state(gh, repo, number):
    pr = gh.get(f"repos/{repo}/pulls/{number}")
    if pr is None:
        raise Failure(f"pr_status: {short_repo(repo)}#{number} not found")
    sha = pr["head"]["sha"]
    ts = threads(gh, repo, number)
    return {
        "repo": short_repo(repo),
        "number": number,
        "title": pr.get("title", ""),
        "author": (pr.get("user") or {}).get("login"),
        "state": pr.get("state"),
        "draft": bool(pr.get("draft")),
        "head": sha,
        "mergeable": pr.get("mergeable"),
        "mergeable_state": pr.get("mergeable_state") or "unknown",
        "ci": ci_summary(gh, repo, sha),
        "unresolved": None if ts is None else len(ts),
        "threads": ts or [],
    }


def open_prs(gh, repos, author=None):
    out = []
    for name in repos:
        repo = full_repo(name)
        for pr in gh.paged(f"repos/{repo}/pulls?state=open"):
            if author and (pr.get("user") or {}).get("login") != author:
                continue
            out.append(pr_state(gh, repo, pr["number"]))
    return out


# --- output ------------------------------------------------------------------


def thread_line(t):
    where = f"{t['path']}:{t['line']}" if t.get("line") is not None else f"{t['path']}"
    mark = " [resolved]" if t.get("resolved") else ""
    mark += " [outdated]" if t.get("outdated") else ""
    return f"  {t['severity']} · {t['title']} · {where} · {t['id']}{mark}"


def pr_lines(p):
    c = p["ci"]
    counts = ",".join(f"{k}={v}" for k, v in c["counts"].items())
    ci = f"ci={c['verdict']}" + (f"({counts})" if counts else "")
    th = "?" if p["unresolved"] is None else p["unresolved"]
    draft = " draft" if p["draft"] else ""
    title = clean(p["title"])
    head = f"{p['repo']}#{p['number']} {p['head'][:7]} {ci} merge={p['mergeable_state']}{draft}"
    return [f"{head} threads={th} · {title}"] + [thread_line(t) for t in p["threads"]]


def emit(obj, lines, as_json):
    if as_json:
        print(json.dumps(obj, indent=1))
    else:
        for ln in lines:
            print(ln)


def cmd_list(args, gh):
    repos = [r.strip() for r in args.repos.split(",") if r.strip()] if args.repos else DEFAULT_REPOS
    prs = open_prs(gh, repos, args.author)
    lines = [ln for p in prs for ln in pr_lines(p)]
    emit(prs, lines or ["no open PRs"], args.json)
    return 0


def cmd_threads(args, gh):
    repo, number = parse_ref(args.ref)
    ts = threads(gh, repo, number, include_resolved=args.all)
    if ts is None:
        raise Failure(f"pr_status: no review threads endpoint for {short_repo(repo)}#{number}")
    emit(ts, [thread_line(t).strip() for t in ts] or ["no unresolved threads"], args.json)
    return 0


def cmd_wait(args, gh, sleep=time.sleep, clock=time.monotonic):
    refs = [parse_ref(r) for r in args.refs]
    start = clock()
    while True:
        prs = [pr_state(gh, repo, n) for repo, n in refs]
        pending = [p for p in prs if p["ci"]["verdict"] == "pending"]
        if not pending or clock() - start >= args.timeout:
            break
        sleep(args.interval)
    lines = [ln for p in prs for ln in pr_lines(p)]
    if pending:
        lines.append(f"timeout: {len(pending)} still pending after {args.timeout:g}s")
    emit(prs, lines, args.json)
    return 2 if pending else 0


def main(argv=None, gh=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("list", help="open PRs, one line each, plus their unresolved threads")
    a.add_argument("--repos", default="", help="comma-separated names (default: DEFAULT_REPOS)")
    a.add_argument("--author", default="", help="only PRs opened by this login")
    a.add_argument("--json", action="store_true")
    t = sub.add_parser("threads", help="one PR's unresolved review threads")
    t.add_argument("ref", metavar="REPO#N")
    t.add_argument("--all", action="store_true", help="include resolved threads")
    t.add_argument("--json", action="store_true")
    w = sub.add_parser("wait", help="poll until no check is pending, then list")
    w.add_argument("refs", nargs="+", metavar="REPO#N")
    w.add_argument("--interval", type=float, default=30)
    w.add_argument("--timeout", type=float, default=1800)
    w.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        p.error("a command is required")
    gh = gh or GitHub()
    return {"list": cmd_list, "threads": cmd_threads, "wait": cmd_wait}[args.cmd](args, gh)


# --- self-test: a fake GitHub serving recorded API shapes ---------------------

CR_BODY = """<!-- coderabbit-ai-generated:v1 -->

**<picture><img src="https://example.invalid/amber.svg" alt=""></picture> Minor** \
· **Functional Correctness** · **Quick win**

**Add the missing failing fixtures.**

`self_test()` has no failing fixture for a missing README. Long explanation follows.

<details>
<summary><picture><img src="https://example.invalid/bot.svg"></picture> Prompt for AI Agents</summary>
<details><summary>nested</summary>

```
IGNORED-PROMPT-TEXT
```

</details>
</details>

<!-- cr-comment:v1:abc -->
"""

CR_OLD = """_⚠️ Potential issue_ | _🟠 Major_

**Guard the empty list.**

<details><summary>🧩 Analysis chain</summary>IGNORED-ANALYSIS</details>
"""


def fixture():
    pr = {
        "number": 5,
        "title": "feat(x): a change",
        "user": {"login": "alice"},
        "state": "open",
        "draft": False,
        "head": {"sha": "a" * 40},
        "mergeable": True,
        "mergeable_state": "clean",
    }
    return {
        "repos/swarm-routing/alpha/pulls?state=open&per_page=100&page=1": [
            {"number": 5, "user": {"login": "alice"}},
            {"number": 6, "user": {"login": "bob"}},
        ],
        "repos/swarm-routing/alpha/pulls/5": pr,
        "repos/swarm-routing/alpha/pulls/6": dict(
            pr, number=6, title="wip", user={"login": "bob"}, draft=True, head={"sha": "b" * 40}
        ),
        f"repos/swarm-routing/alpha/commits/{'a' * 40}/check-runs?per_page=100&page=1": {
            "check_runs": [
                {"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "skipped"},
                {"status": "completed", "conclusion": "failure"},
            ]
        },
        f"repos/swarm-routing/alpha/commits/{'a' * 40}/status": {
            "state": "success",
            "statuses": [{"context": "ext", "state": "success"}],
        },
        f"repos/swarm-routing/alpha/commits/{'b' * 40}/check-runs?per_page=100&page=1": {
            "check_runs": [{"status": "in_progress", "conclusion": None}]
        },
        f"repos/swarm-routing/alpha/commits/{'b' * 40}/status": {
            "state": "pending",
            "statuses": [],
        },
        "repos/swarm-routing/alpha/pulls/5/ccr/review_threads": [
            {"resolved": True, "path": "a.py", "line": 1, "comment_ids": [100]},
            {"resolved": False, "path": "b.py", "line": 58, "comment_ids": [101, 102]},
            {"resolved": False, "path": "c.py", "line": 7, "comment_ids": [103]},
            {
                "resolved": False,
                "outdated": True,
                "path": "d.md",
                "line": None,
                "comment_ids": [104],
            },
        ],
        "repos/swarm-routing/alpha/pulls/comments/100": {
            "user": {"login": "coderabbitai[bot]"},
            "body": "**Old.**",
        },
        "repos/swarm-routing/alpha/pulls/comments/101": {
            "user": {"login": "coderabbitai[bot]"},
            "body": CR_BODY,
        },
        "repos/swarm-routing/alpha/pulls/comments/103": {
            "user": {"login": "coderabbitai[bot]"},
            "body": CR_OLD,
        },
        "repos/swarm-routing/alpha/pulls/comments/104": {
            "user": {"login": "carol"},
            "body": "\nPlease rename this.\nSecond line.",
        },
        # pulls/6/ccr/review_threads is absent: a 404, so threads=?
    }


class FakeGitHub(GitHub):
    def __init__(self, data):
        self.data, self.calls = data, []

    def get(self, path):
        self.calls.append(path)
        got = self.data.get(path)
        return got() if callable(got) else got


def self_test():
    import contextlib
    import io

    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    def run(argv, data=None, **kw):
        gh = FakeGitHub(data or fixture())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if argv[0] == "wait":
                ns = argparse.Namespace(refs=argv[1:], interval=1, timeout=kw.get("timeout", 10))
                ns.json = False
                rc = cmd_wait(ns, gh, sleep=kw["sleep"], clock=kw["clock"])
            else:
                rc = main(argv, gh=gh)
        return rc, out.getvalue(), gh

    # the CodeRabbit heading alone: severity and title, nothing from the collapsed blocks
    check(
        "heading new",
        heading(CR_BODY, "coderabbitai[bot]") == ("Minor", "Add the missing failing fixtures."),
    )
    check("heading old", heading(CR_OLD, "coderabbitai[bot]") == ("Major", "Guard the empty list."))
    stripped = strip_html(CR_BODY)
    check("details stripped", "IGNORED" not in stripped and "details>" not in stripped)
    check("comments, pictures stripped", "<!--" not in stripped and "<picture>" not in stripped)
    check(
        "human comment",
        heading("\nPlease rename this.\nMore.", "carol") == ("@carol", "Please rename this."),
    )
    check("long title cut", len(heading("x" * 500, "dave")[1]) == TITLE_MAX)

    # list: CI states, a resolved and an unresolved thread, the 404 endpoint
    rc, out, gh = run(["list", "--repos", "alpha"])
    lines = out.splitlines()
    check("list rc", rc == 0)
    check(
        "pr line",
        lines[0]
        == "alpha#5 aaaaaaa ci=fail(failure=1,skipped=1,success=3) merge=clean threads=3 · feat(x): a change",
    )
    check(
        "unresolved thread line",
        lines[1] == "  Minor · Add the missing failing fixtures. · b.py:58 · 101",
    )
    check("old-format thread line", lines[2] == "  Major · Guard the empty list. · c.py:7 · 103")
    check(
        "human, outdated, no line",
        lines[3] == "  @carol · Please rename this. · d.md · 104 [outdated]",
    )
    check("resolved thread hidden", "Old" not in out and "pulls/comments/100" not in gh.calls)
    check(
        "pending, draft, no thread endpoint",
        lines[4].startswith(
            "alpha#6 bbbbbbb ci=pending(pending=1) merge=clean draft threads=? · wip"
        ),
    )
    check("one line per PR and per finding", len(lines) == 5)
    check("bodies not printed", "IGNORED" not in out and "explanation" not in out)
    check("read only", all(not c.startswith("-") for c in gh.calls))

    rc, out, _ = run(["list", "--repos", "alpha", "--author", "bob"])
    check("author filter", out.startswith("alpha#6 ") and len(out.splitlines()) == 1)

    rc, out, _ = run(["list", "--repos", "alpha", "--json"])
    js = json.loads(out)
    check(
        "json",
        [p["number"] for p in js] == [5, 6]
        and js[0]["ci"] == {"verdict": "fail", "counts": {"failure": 1, "skipped": 1, "success": 3}}
        and js[0]["unresolved"] == 3
        and js[0]["threads"][0]["replies"] == 1
        and js[1]["unresolved"] is None,
    )

    # CI with nothing reported, and a clean pass
    data = fixture()
    data[f"repos/swarm-routing/alpha/commits/{'a' * 40}/check-runs?per_page=100&page=1"] = {
        "check_runs": []
    }
    data[f"repos/swarm-routing/alpha/commits/{'a' * 40}/status"] = {
        "state": "pending",
        "statuses": [],
    }
    check(
        "ci none",
        ci_summary(FakeGitHub(data), "swarm-routing/alpha", "a" * 40)["verdict"] == "none",
    )
    data[f"repos/swarm-routing/alpha/commits/{'a' * 40}/check-runs?per_page=100&page=1"] = {
        "check_runs": [{"status": "completed", "conclusion": "success"}]
    }
    check(
        "ci pass",
        ci_summary(FakeGitHub(data), "swarm-routing/alpha", "a" * 40)["verdict"] == "pass",
    )

    # threads: unresolved only, --all marks the resolved one; at most 3 lines per thread
    rc, out, _ = run(["threads", "alpha#5"])
    check(
        "threads",
        rc == 0
        and out.splitlines()[0] == "Minor · Add the missing failing fixtures. · b.py:58 · 101",
    )
    check("threads: one line each", len(out.splitlines()) == 3)
    rc, out, _ = run(["threads", "swarm-routing/alpha#5", "--all"])
    check("threads --all", "Old. · a.py:1 · 100 [resolved]" in out and len(out.splitlines()) == 4)
    try:
        run(["threads", "alpha"])
        check("bad ref refused", False)
    except Failure:
        pass
    try:
        run(["threads", "alpha#6"])
        check("missing endpoint refused", False)
    except Failure:
        pass

    # wait: polls while pending, then lists; times out with exit 2
    data = fixture()
    key = f"repos/swarm-routing/alpha/commits/{'b' * 40}/check-runs?per_page=100&page=1"
    polls = []

    def later():
        polls.append(1)
        done = {"status": "completed", "conclusion": "success"}
        return {"check_runs": [done if len(polls) > 2 else {"status": "queued"}]}

    data[key] = later
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    rc, out, _ = run(["wait", "alpha#6"], data=data, sleep=sleep, clock=lambda: now[0])
    check("wait done", rc == 0 and len(slept) == 2 and "ci=pass(success=1)" in out)
    data[key] = {"check_runs": [{"status": "queued"}]}
    now[0], slept[:] = 0.0, []
    rc, out, _ = run(
        ["wait", "alpha#6", "alpha#5"], data=data, sleep=sleep, clock=lambda: now[0], timeout=3
    )
    check(
        "wait timeout", rc == 2 and "timeout: 1 still pending after 3s" in out and len(slept) == 3
    )

    for f in failures:
        print(f"FAIL: {f}")
    print(f"pr_status.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
