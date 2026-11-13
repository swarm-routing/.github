#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""One compact view of the open PRs across the org's repositories.

Usage:
  pr_status.py list [--repos A,B] [--author LOGIN] [--json]
  pr_status.py threads REPO#N [--all] [--json]
  pr_status.py wait REPO#N [REPO#N ...] [--interval S] [--timeout S] [--review [--review-timeout S]] [--json]
  pr_status.py merge REPO#N [REPO#N ...] [--interval S] [--timeout S] [--review-timeout S] [--update] [--dry-run] [--json]
  pr_status.py queued REPO#N [REPO#N ...] [--json]
  pr_status.py --self-test
  (any command takes --min-rate N, placed before it)

`list` prints one line per open PR, then one line per unresolved review
thread under it:

  .github#95 593400c ci=fail(failure=1,success=3) failed=lint merge=clean threads=1 · feat(x): t
    Minor · Add the missing failing fixtures. · tools/x.py:58 · 4518902668

- `ci` is the verdict over the head commit's check runs and commit statuses
  (fail > pending > pass; `none` when nothing reported), then the count of
  each conclusion and the names of the failed checks. A workflow run on the
  head whose latest attempt ended in `startup_failure` (`actions/runs?head_sha=`)
  creates no check run, so it is read from the runs and counted as failed,
  `failed=<workflow> (startup_failure)`. A check the base branch's rules
  require (`rules/branches/{base}`) that has not reported on the head is
  printed as `missing=<names>` and keeps the verdict `pending`, never `pass`;
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
their `list` lines; it exits 2 if `--timeout` passes first. At the timeout a
PR missing a required check is reported `ci=fail` only when nothing else is
pending on its head; while other checks still run it stays `ci=pending`
(#319). `wait --merged` instead polls until each PR has merged, or stops
at the first that needs a hand: closed unmerged, an unresolved review
thread, a failed required check, auto-merge off (never enabled, or dropped
from the merge queue). One line per PR (`merged`, `stopped: <reason>`,
`timeout: ...`; `--json`: one list at the end); exit 0 when all merged, 1 as
soon as one needs a hand (the rest are not waited for), 2 at the timeout; a
failed read is retried at the next poll (#341). With
`--review` it also waits for CodeRabbit's review (below) and adds a line per
PR, `review: CodeRabbit reviewed` or `warning: no CodeRabbit review yet ...`;
the warning does not change the exit status. Run it before enabling
auto-merge, which does not wait for CodeRabbit (#238).

CodeRabbit's review counts as in once it has posted a review on the PR (on
any commit: it reviews once, when the PR opens) or its `CodeRabbit` check run
on the head has completed (`success`, `neutral`, `skipped`); while that check
run is queued or in progress the review is in progress. It is waited for at
most `--review-timeout` seconds after the PR opened (default 1800; 0: not at
all), then the run goes on with a warning: CodeRabbit is not a required
check, and an absent or failing CodeRabbit never holds a PR.

`gate REPO#N` is that wait as a check of its own (#294): the reusable
`reusable-review-gate.yml` runs it on every PR, so auto-merge and the merge
queue wait for CodeRabbit too. It polls one PR every `--interval` seconds and
prints one line, then exits 0: `reviewed` (as above), `declined: <reason>`
(CodeRabbit said in a comment that it will not review: a skipped review, a
rate limit, a used-up review quota), `draft` (CodeRabbit does not review
drafts; the gate runs again when the PR is marked ready) or `timeout: ...`
once `--timeout` seconds (default 1800) have passed since the PR opened. It
exits non-zero only when it cannot read the PR. It is read-only; the caller
comments on the PR after a `timeout`.

`merge` squash-merges PRs one at a time per repository, in the order given;
repositories run independently of each other. For each PR it polls every
`--interval` seconds, for up to `--timeout` seconds per PR:

- a merged or closed PR is skipped, and the next one in its repository starts;
- a draft, a conflict (`dirty`), a failing check (the latest run of each
  check name, the commit statuses, and a workflow run whose latest attempt
  ended in `startup_failure`) or an unresolved review thread stops
  that PR, and the PRs after it in the same repository are not run;
- a PR GitHub reports `behind` merges as it is when the base branch's rules
  do not require an up-to-date branch (`strict_required_status_checks_policy`
  off, every org profile: CONTRIBUTING "Merge when CI is green"). It is
  updated only when they do, or with `--update` (you judged that `main`
  changed what it touches: a template, a workflow, a required check): then it
  calls `PUT pulls/{n}/update-branch` with `expected_head_sha`, and waits for
  the new head and that head's checks. Since GitHub may report an outdated
  PR `clean` under such rules, `--update` (and a `bot/release` head) also asks
  `compare/{base}...{head}`; a merge refused as "not up to date" (a rule the
  rules endpoint does not show) is updated on the next poll. A behind
  `bot/release` PR is never updated: it stops, since the release `bump` is
  dispatched again instead;
- it waits while a check is pending, or while a check the base branch's rules
  require (`rules/branches/{base}`) has not reported on the head, so it never
  merges while a required check is missing (at the timeout it gives up);
  CodeRabbit's own check run is not counted there, unless a rule requires it;
- it then waits for CodeRabbit's review (above), so the threads the review
  opens are read before the merge; past `--review-timeout` it prints
  `warning: ...; going on without it` once and goes on;
- once every check on the head passed and no thread is open, it merges with
  `merge_method=squash`, `sha=<head>` and the org's squash title
  `"<PR title> (#n)"`, and only then goes on to that repository's next PR,
  which the merge has just put behind.

A merge or update refused by GitHub (403, 405, 422, ...) is reported as
`refused: <message>` and the PR is handed back; a refusal because the head
moved or the branch fell behind (409, "not up to date", "modified") is polled
again, and so is a failed GitHub read (a 502, a rate limit, a network
drop), within the PR's timeout. It never reruns a check and never resolves a
thread. Output is one
line per PR per change of state (`updated`, `waiting: ...`, `warning: ...`, `merged <sha7>`,
`failing: <checks>`, `open threads: N` with the thread lines, `conflict`,
`draft`, `refused: ...`, `timeout`, `not run`); with `--json` those lines go
to stderr and the results to stdout. `--dry-run` reads each PR once and says
what it would do (`would update`, `would merge`, `would wait: ...`) without
writing. Exit status: 0 when every PR merged (or was already merged or
closed), 1 when one stopped, 2 when one timed out.

`queued` says, one line per PR, where it stands in a merge queue. Read-only.

  .github#345 merged 1aed1d1
  .github#346 queued: gh-readonly-queue/main/pr-346-eff0982 CI=in_progress review=success
  .github#347 not queued: open, auto-merge squash by alice
  .github#348 not queued: open, auto-merge none (REST shows none for a queued PR too)
  .github#349 not queued: queue run failed (gh-readonly-queue/main/pr-349-1aed1d1 CI=failure), open, auto-merge none ...

A PR is `queued` when a `merge_group` workflow run exists on a
`gh-readonly-queue/<base>/pr-<n>-<sha>` branch and was created at or after its
current head was pushed (the earliest workflow run on the head, else the head
commit's committer date): a squash queue commit does not name the PR's head,
so its time is what ties it to the head, and a push after queueing takes the
PR out of the queue. The line gives that queue branch and, for each workflow,
its latest run's status, or its conclusion once completed. When one of those
ended in failure (failure, cancelled, timed_out, ...), GitHub has taken the PR
out of the queue: it is `not queued: queue run failed (...)`. A PR taken out
by hand, with no new push and no failed run, still reads `queued`: the runs
are all this read-only command sees (membership itself is GraphQL only). Only
the newest 100 `merge_group` runs of the repository are read. Otherwise the
PR is `not queued`: its state and the auto-merge GitHub's REST API reports (merge
method and who enabled it, or `none`; REST reports none for a PR the queue
holds, so `none` alone never means "not queued"). Exit status 0.

A REPO is a name in the swarm-routing org or `owner/name`. The org-wide API is
not available to agent sessions, so `--repos` names the repositories (default:
the org's public ones, DEFAULT_REPOS). Review threads come from
`pulls/{n}/ccr/review_threads` (resolved, path, line, comment_ids); where that
endpoint is missing the count prints as `threads=?` (and `merge` leaves the
check to the ruleset's thread rule). CodeRabbit's reviews come from
`pulls/{n}/reviews`. `list`, `threads`, `wait`, `gate` and `queued` are read-only
(GET only); `merge` writes only the two PUTs above. Every call goes through
`gh api`, which authenticates with GH_TOKEN or the gh CLI's own login
(`gh auth token`), so no token is in an argument list. Each read checks the
token's `X-RateLimit-Remaining`: below `--min-rate` (default 500) it sleeps
until `X-RateLimit-Reset` when that is at most 10 minutes away, else it
stops with a message (#226). Findings are
printed as data; nothing here acts on their text. Stdlib only.
"""

import argparse
import datetime
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


def split_head(text):
    """`gh api -i` output as (lower-cased headers, body)."""
    lines = text.split("\n")
    headers = {}
    for i, line in enumerate(lines[1:], 1):
        line = line.rstrip("\r")
        if not line:
            return headers, "\n".join(lines[i + 1 :])
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    return headers, ""


class GitHub:
    """GitHub REST through `gh api`: GET (None for a 404), and PUT for `merge`.

    Every GET reads `X-RateLimit-Remaining`/`X-RateLimit-Reset`. Below
    `min_remaining` it sleeps until the reset when that is at most
    RATE_WAIT_MAX seconds away, and otherwise stops with a message, so a
    polling loop never drains the token's quota (swarm-routing/.github#226:
    Zenodo shares the maintainer's)."""

    min_remaining = 500
    RATE_WAIT_MAX = 600

    def rate_sleep(self, s):
        time.sleep(s)

    def rate_clock(self):
        return time.time()

    def note_rate(self, headers):
        try:
            left = int(headers["x-ratelimit-remaining"])
            reset = int(headers.get("x-ratelimit-reset", "0"))
        except (KeyError, ValueError):
            return
        if left >= self.min_remaining:
            return
        wait = max(0, reset - int(self.rate_clock())) + 1
        if wait > self.RATE_WAIT_MAX:
            raise Failure(
                f"pr_status: rate limit low: {left} requests left (below --min-rate "
                f"{self.min_remaining}), resets in {wait} s; stopping rather than draining it"
            )
        print(
            f"rate limit low: {left} left (below {self.min_remaining}); sleeping {wait} s until reset",
            file=sys.stderr,
        )
        self.rate_sleep(wait)

    def get(self, path):
        r = subprocess.run(
            ["gh", "api", "-i", "-H", "Accept: application/vnd.github+json", path],
            capture_output=True,
            text=True,
        )
        headers, body = split_head(r.stdout or "")
        if r.returncode != 0:
            if "HTTP 404" in r.stderr:
                return None
            raise Failure(f"gh api {path}: {r.stderr.strip()}")
        self.note_rate(headers)
        return json.loads(body or "null")

    def put(self, path, fields):
        """(True, response) or (False, "HTTP <code>: <message>"); never raises on a refusal."""
        cmd = ["gh", "api", "-X", "PUT", "-H", "Accept: application/vnd.github+json", path]
        for k, v in fields.items():
            cmd += ["-f", f"{k}={v}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return True, json.loads(r.stdout or "null")
        code = re.search(r"HTTP (\d+)", r.stderr)
        try:
            msg = json.loads(r.stdout).get("message")
        except (ValueError, AttributeError):
            msg = None
        msg = msg or r.stderr.strip() or "gh api failed"
        return False, (f"HTTP {code.group(1)}: " if code else "") + msg

    def paged(self, path, required=False):
        sep = "&" if "?" in path else "?"
        out, page = [], 1
        while True:
            got = self.get(f"{path}{sep}per_page=100&page={page}")
            if got is None and required:
                # a mistyped or invisible repository is not "no open PRs"
                raise Failure(f"pr_status: {path.split('?')[0]} not found (404)")
            if isinstance(got, dict):
                items = got.get("check_runs") or got.get("workflow_runs") or []
            else:
                items = got or []
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


def startup_failures(gh, repo, sha):
    """The workflows whose latest run on the head ended in `startup_failure`.

    Such a run creates no check run, so the check-runs list alone reads it as
    absent (#169)."""
    latest = {}
    for run in gh.paged(f"repos/{repo}/actions/runs?head_sha={sha}"):
        wf = run.get("workflow_id") or run.get("name") or run.get("id")
        key = (run.get("created_at") or "", run.get("id") or 0)
        if wf not in latest or key >= latest[wf][0]:
            latest[wf] = (key, run)
    return sorted(
        f"{run.get('name') or run.get('path') or '?'} (startup_failure)"
        for _, run in latest.values()
        if run.get("conclusion") == "startup_failure"
    )


def ci_summary(gh, repo, sha, required=frozenset(), skip_coderabbit=False):
    """The verdict, the count of each conclusion, the failed checks' names and
    the required checks that have not reported on the head. With
    `skip_coderabbit`, CodeRabbit's own check run is left out unless required
    (`wait --review` waits for the review separately)."""
    counts, failed, seen = Counter(), [], set()
    for run in gh.paged(f"repos/{repo}/commits/{sha}/check-runs"):
        if skip_coderabbit and is_coderabbit(run) and run.get("name") not in required:
            continue
        done = run.get("status") == "completed"
        state = (run.get("conclusion") or "pending") if done else "pending"
        counts[state] += 1
        seen.add(run.get("name"))
        if state in FAILED:
            failed.append(run.get("name") or "?")
    status = gh.get(f"repos/{repo}/commits/{sha}/status") or {}
    for s in status.get("statuses", []):
        counts[s.get("state") or "pending"] += 1
        seen.add(s.get("context"))
        if s.get("state") in FAILED:
            failed.append(s.get("context") or "?")
    for name in startup_failures(gh, repo, sha):
        counts["startup_failure"] += 1
        failed.append(name)
    missing = sorted(set(required) - seen)
    if FAILED & set(counts):
        verdict = "fail"
    elif "pending" in counts or missing:
        verdict = "pending"
    elif not counts:
        verdict = "none"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "counts": dict(sorted(counts.items())),
        "failed": sorted(failed),
        "missing": missing,
    }


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


def plain(s):
    """Text from PR authors and commenters, without control characters (escape sequences)."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(s))


def clean(s):
    s = plain(s)
    # Markdown emphasis and code marks only, so `pr_status.py` and `self_test()` keep their underscores
    s = re.sub(r"\*\*|`|(?<!\w)_|_(?!\w)", "", s).strip()
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


def pr_state(gh, repo, number, cache=None, skip_coderabbit=False):
    pr = gh.get(f"repos/{repo}/pulls/{number}")
    if pr is None:
        raise Failure(f"pr_status: {short_repo(repo)}#{number} not found")
    sha = pr["head"]["sha"]
    base = (pr.get("base") or {}).get("ref") or "main"
    required = required_checks(gh, repo, base, {} if cache is None else cache)
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
        "created_at": pr.get("created_at"),
        "ci": ci_summary(gh, repo, sha, required, skip_coderabbit),
        "unresolved": None if ts is None else len(ts),
        "threads": ts or [],
    }


def open_prs(gh, repos, author=None):
    out, cache = [], {}
    for name in repos:
        repo = full_repo(name)
        for pr in gh.paged(f"repos/{repo}/pulls?state=open", required=True):
            if author and (pr.get("user") or {}).get("login") != author:
                continue
            out.append(pr_state(gh, repo, pr["number"], cache))
    return out


# --- output ------------------------------------------------------------------


def thread_line(t):
    path = plain(t["path"])  # not clean(): `__init__.py` keeps its underscores
    where = f"{path}:{t['line']}" if t.get("line") is not None else path
    mark = " [resolved]" if t.get("resolved") else ""
    mark += " [outdated]" if t.get("outdated") else ""
    return f"  {t['severity']} · {t['title']} · {where} · {t['id']}{mark}"


def pr_lines(p):
    c = p["ci"]
    counts = ",".join(f"{k}={v}" for k, v in c["counts"].items())
    ci = f"ci={c['verdict']}" + (f"({counts})" if counts else "")
    ci += f" failed={','.join(c['failed'])}" if c["failed"] else ""
    ci += f" missing={','.join(c['missing'])}" if c.get("missing") else ""
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


def merged_poll(gh, repo, n, cache):
    """None while a PR is on its way to merging, else (result, head, detail) (#341)."""
    pr = gh.get(f"repos/{repo}/pulls/{n}")
    if pr is None:
        raise LookupError(f"pr_status: {short_repo(repo)}#{n} not found")
    head = pr["head"]["sha"]
    if pr.get("merged") or pr.get("merged_at"):
        return "merged", head, ""
    if pr.get("state") == "closed":
        return "stopped", head, "closed unmerged"
    ts = threads(gh, repo, n)
    if ts:
        return (
            "stopped",
            head,
            f"{len(ts)} unresolved thread(s), first: {thread_line(ts[0]).strip()}",
        )
    base = (pr.get("base") or {}).get("ref") or "main"
    required = required_checks(gh, repo, base, cache)
    failed = [c for c in head_checks(gh, repo, head, required)["failed"] if c in required]
    if failed:
        return "stopped", head, f"required check failed: {', '.join(failed)}"
    # a queued PR reads auto_merge null; its merge group's branch,
    # gh-readonly-queue/<base>/pr-<n>-<sha>, shows it is still in the queue.
    # The branch, not queue_runs(): it exists from the moment the group forms,
    # before any merge_group run does (`queued` reads the runs, #347).
    queued = gh.get(f"repos/{repo}/git/matching-refs/heads/gh-readonly-queue/{base}/pr-{n}-")
    if not pr.get("auto_merge") and not queued:
        # The queue deletes its branch as it merges: a PR read just before the
        # merge has no branch any more. Read it again before calling it off.
        again = gh.get(f"repos/{repo}/pulls/{n}") or {}
        if again.get("merged") or again.get("merged_at"):
            return "merged", (again.get("head") or {}).get("sha") or head, ""
        return "stopped", head, "auto-merge off (never enabled, or dropped from the merge queue)"
    return None


def cmd_wait_merged(args, gh, sleep=time.sleep, clock=time.monotonic):
    """Poll until every PR merged (0); stop at the first that needs a hand (1);
    2 at the timeout. --json prints one list of results at the end."""
    refs = [(full_repo(r), n) for r, n in (parse_ref(x) for x in args.refs)]
    as_json = getattr(args, "json", False)
    results, cache, start = {}, {}, clock()

    def report(repo, n, result, head="", detail=""):
        results[(repo, n)] = {
            "repo": short_repo(repo),
            "number": n,
            "head": head,
            "result": result,
            "detail": detail,
        }
        if not as_json:
            sha = f" {head[:7]}" if head else ""
            tail = "" if result == "merged" else f": {detail}"
            print(f"{short_repo(repo)}#{n}{sha} {result}{tail}", flush=True)

    def finish(rc):
        if as_json:
            print(json.dumps([results[k] for k in refs if k in results], indent=1))
        return rc

    while True:
        for repo, n in refs:
            if (repo, n) in results:
                continue
            try:
                got = merged_poll(gh, repo, n, cache)
            except LookupError as e:
                raise Failure(str(e)) from None
            except Failure as e:  # a 502 or a rate limit: read again next poll
                print(f"retrying after a failed read: {e}", file=sys.stderr)
                got = None
            if got:
                report(repo, n, *got)
                if got[0] == "stopped":  # one needs a hand: stop now, the rest are not waited for
                    return finish(1)
        if len(results) == len(refs):
            return finish(0)
        if clock() - start >= args.timeout:
            for repo, n in refs:
                if (repo, n) not in results:
                    report(repo, n, "timeout", detail=f"not merged after {args.timeout:g}s")
            return finish(2)
        sleep(args.interval)


def cmd_wait(args, gh, sleep=time.sleep, clock=time.monotonic, wall=time.time):
    refs = [parse_ref(r) for r in args.refs]
    if getattr(args, "merged", False):
        return cmd_wait_merged(args, gh, sleep=sleep, clock=clock)
    review_wait = getattr(args, "review_timeout", 0) if getattr(args, "review", False) else 0
    start, cache = clock(), {}
    while True:
        prs = [pr_state(gh, repo, n, cache, review_wait > 0) for repo, n in refs]
        pending = [p for p in prs if p["ci"]["verdict"] == "pending"]
        unreviewed = []
        for p in prs if review_wait > 0 else []:
            repo = full_repo(p["repo"])
            p["review"] = coderabbit_review(gh, repo, p["number"], p["head"])
            p["review_age"] = pr_age(p, wall, clock() - start)
            if p["review"] == "reviewed":  # the threads the review opened, read after it
                ts = threads(gh, repo, p["number"])
                p["unresolved"], p["threads"] = (None if ts is None else len(ts)), ts or []
            if p["review"] != "reviewed" and p["review_age"] < review_wait:
                unreviewed.append(p)
        if not (pending or unreviewed) or clock() - start >= args.timeout:
            break
        sleep(args.interval)
    # a required check that never reported, with nothing else running, is a failure
    for p in pending:
        if p["ci"]["missing"] and "pending" not in p["ci"]["counts"]:
            p["ci"]["verdict"] = "fail"
    lines = [ln for p in prs for ln in pr_lines(p)]
    for p in prs if review_wait > 0 else []:
        if p["review"] == "reviewed":
            lines.append(f"{p['repo']}#{p['number']} review: CodeRabbit reviewed")
        else:  # a warning, not a failure: CodeRabbit may be absent or down (#238)
            lines.append(
                f"{p['repo']}#{p['number']} warning: {REVIEW_WAIT[p['review']]} "
                f"{p['review_age']:.0f}s after the PR opened"
            )
    if pending:
        lines.append(f"timeout: {len(pending)} still pending after {args.timeout:g}s")
    emit(prs, lines, args.json)
    return 2 if pending else 0


# --- merge: wait for green, squash-merge one at a time (update when needed) ---

RETRY = re.compile(r"up to date|modified|behind", re.I)
UPDATE_FIRST = re.compile(r"not up to date", re.I)


def branch_rules(gh, repo, base, cache):
    """(required check names, strict) of the base branch's rules, cached per repo
    and branch; strict: a rule requires the branch to be up to date before merging."""
    key = (repo, base)
    if key not in cache:
        names, strict = set(), False
        for rule in gh.get(f"repos/{repo}/rules/branches/{base}") or []:
            if rule.get("type") == "required_status_checks":
                params = rule.get("parameters") or {}
                names |= {c.get("context") for c in params.get("required_status_checks") or []}
                strict = strict or bool(params.get("strict_required_status_checks_policy"))
        cache[key] = (names - {None}, strict)
    return cache[key]


def required_checks(gh, repo, base, cache):
    """The check names the base branch's rules require (cached per repo and branch)."""
    return branch_rules(gh, repo, base, cache)[0]


def head_checks(gh, repo, sha, required):
    """{failed, pending} names on the head: the latest run per check name, the
    commit statuses, and a required check that has not reported counts as pending."""
    latest = {}
    for run in gh.paged(f"repos/{repo}/commits/{sha}/check-runs"):
        name = run.get("name") or f"#{run.get('id')}"
        if is_coderabbit(run) and name not in required:
            continue  # the review, not CI: coderabbit_review() waits for it, with its own time-out
        key = (run.get("started_at") or "", run.get("id") or 0)
        if name not in latest or key >= latest[name][0]:
            latest[name] = (key, run)
    seen, failed, pending = set(), [], []
    for name, (_, run) in latest.items():
        seen.add(name)
        if run.get("status") != "completed":
            pending.append(name)
        elif run.get("conclusion") in FAILED:
            failed.append(name)
    for st in (gh.get(f"repos/{repo}/commits/{sha}/status") or {}).get("statuses", []):
        name = st.get("context") or "?"
        seen.add(name)
        if st.get("state") in FAILED:
            failed.append(name)
        elif st.get("state") == "pending":
            pending.append(name)
    pending += [f"{name} (not reported)" for name in sorted(required - seen)]
    failed += startup_failures(gh, repo, sha)
    return {"failed": sorted(failed), "pending": sorted(pending)}


def is_coderabbit(run):
    """CodeRabbit's own check run (`CodeRabbit`, app `coderabbitai`)."""
    slug = ((run.get("app") or {}).get("slug") or "").lower()
    return run.get("name") == "CodeRabbit" or slug.startswith("coderabbit")


def coderabbit_review(gh, repo, number, sha, since=""):
    """`reviewed`, `reviewing` or `none`: whether CodeRabbit has had its say on the PR.

    `reviewed` when it posted a review (on any commit: it reviews once when the
    PR opens, #37) or its check run on the head completed (`success`,
    `neutral`, `skipped`: done, or nothing to review by its settings);
    `reviewing` while that check run is queued or in progress; `none` before
    it has started, or where CodeRabbit is not installed or is down. With
    `since` (ISO time, the gate's last `ready_for_review`), a check run that
    started before it is left out: a run skipped while the PR was a draft is
    not the review (#294)."""
    for r in gh.paged(f"repos/{repo}/pulls/{number}/reviews"):
        if ((r.get("user") or {}).get("login") or "").startswith("coderabbitai"):
            return "reviewed"
    runs = [
        r
        for r in gh.paged(f"repos/{repo}/commits/{sha}/check-runs")
        if is_coderabbit(r) and (r.get("started_at") or "") >= since
    ]
    if any(r.get("status") != "completed" for r in runs):
        return "reviewing"
    if any(r.get("conclusion") in ("success", "neutral", "skipped") for r in runs):
        return "reviewed"
    return "none"


def pr_age(pr, wall, elapsed):
    """Seconds since the PR was opened (at least `elapsed`, the time spent polling it)."""
    opened = pr.get("created_at")
    if not opened:
        return elapsed
    t = datetime.datetime.fromisoformat(opened.replace("Z", "+00:00")).timestamp()
    return max(elapsed, wall() - t)


REVIEW_WAIT = {"reviewing": "CodeRabbit review in progress", "none": "no CodeRabbit review yet"}

# What CodeRabbit writes when it will not review a PR (#294): a skipped review
# (draft, ignored paths or branches, auto review off), a rate limit, a used-up
# review allowance. Matched on its comments' visible text only.
DECLINED = re.compile(
    r"review(?:s)? (?:skipped|paused)|rate limit(?:ed| exceeded)?\b"
    r"|used (?:up )?all (?:of )?(?:the |your |its )?(?:\d+ )?(?:included )?reviews"
    r"|auto reviews? (?:is |are )?disabled",
    re.I,
)


def last_ready(gh, repo, number):
    """When the PR last became ready for review ("" if never): a decline from
    before it belongs to the draft, not to the current review attempt."""
    times = [
        e.get("created_at") or ""
        for e in gh.paged(f"repos/{repo}/issues/{number}/events")
        if e.get("event") == "ready_for_review"
    ]
    return max(times, default="")


def coderabbit_declined(gh, repo, number, since=""):
    """CodeRabbit's own words for not reviewing the PR, or "" (#294). Only a
    comment written or edited at or after `since` (ISO time) counts."""
    for c in gh.paged(f"repos/{repo}/issues/{number}/comments"):
        if not ((c.get("user") or {}).get("login") or "").startswith("coderabbitai"):
            continue
        if (c.get("updated_at") or c.get("created_at") or "") < since:
            continue
        m = DECLINED.search(plain(strip_html(c.get("body") or "")))
        if m:
            return clean(m.group(0))
    return ""


def gate_poll(gh, repo, n, args, wall, elapsed):
    """One look at the PR: (the line to print, or None to poll again; the PR's
    age). Raises Failure when a read fails (the caller retries), LookupError
    when the PR is missing."""
    pr = gh.get(f"repos/{repo}/pulls/{n}")
    if pr is None:
        raise LookupError(f"pr_status: {short_repo(repo)}#{n} not found")
    if pr.get("draft"):
        return "draft: CodeRabbit does not review drafts; the gate runs again when it is ready", 0
    ready = last_ready(gh, repo, n)
    if coderabbit_review(gh, repo, n, pr["head"]["sha"], ready) == "reviewed":
        return "reviewed: CodeRabbit reviewed", 0
    why = coderabbit_declined(gh, repo, n, ready)
    if why:
        return f"declined: {why}", 0
    age = pr_age(pr, wall, elapsed)
    if age >= args.timeout:
        return f"timeout: no CodeRabbit review {age:.0f}s after the PR opened", age
    return None, age


def cmd_gate(args, gh, sleep=time.sleep, clock=time.monotonic, wall=time.time):
    """Wait for CodeRabbit on one PR, then print one line and exit 0 (#294).

    A failed GitHub read (a 502, a rate limit) is retried at the next poll, so a
    passing blip never turns the required check red; if reads keep failing
    until the time-out, the gate passes as a timeout. A missing PR fails."""
    repo, n = parse_ref(args.ref)
    repo, start = full_repo(repo), clock()
    while True:
        elapsed = clock() - start
        try:
            line, age = gate_poll(gh, repo, n, args, wall, elapsed)
        except LookupError as e:
            raise Failure(str(e)) from None
        except Failure as e:
            print(f"retrying after a failed read: {e}", file=sys.stderr)
            line, age = None, elapsed
            if elapsed >= args.timeout:
                line = f"timeout: GitHub reads kept failing for {elapsed:.0f}s"
        if line:
            print(line)
            return 0
        sleep(max(1.0, min(args.interval, args.timeout - age)))


class Job:
    """One PR's progress through `merge`."""

    def __init__(self, repo, number):
        self.repo, self.number = repo, number
        self.sha, self.title, self.start, self.updated_from = "", "", None, None
        self.last, self.events, self.result, self.detail = None, [], None, ""
        self.review_warned = False

    def ref(self):
        return f"{short_repo(self.repo)}#{self.number}"

    def say(self, key, text, out):
        if key != self.last:
            self.last = key
            self.events.append(text)
            out(f"{self.ref()} {self.sha[:7] or '-'} {text}")


def merge_step(gh, job, dry_run, cache, out, review_wait=0, age=lambda pr: 0, update=False):
    """One poll of one PR: (result, text) once it is done with, None to poll again."""
    repo, n = job.repo, job.number
    pr = gh.get(f"repos/{repo}/pulls/{n}")
    if pr is None:
        return ("stopped", "not found")
    job.sha, job.title = pr["head"]["sha"], pr.get("title", "")
    if pr.get("merged"):
        return ("skipped", "already merged")
    if pr.get("state") != "open":
        return ("skipped", "closed")
    if pr.get("draft"):
        return ("stopped", "draft")
    if job.updated_from == job.sha:
        job.say("head", "waiting: the new head after the update", out)
        return None
    state = pr.get("mergeable_state") or "unknown"
    if state == "dirty":
        return ("stopped", "conflict")
    base = (pr.get("base") or {}).get("ref") or "main"
    required, strict = branch_rules(gh, repo, base, cache)
    ci = head_checks(gh, repo, job.sha, required)
    if ci["failed"]:
        return ("stopped", "failing: " + ", ".join(ci["failed"]))
    release = (pr.get("head") or {}).get("ref") == "bot/release"
    outdated = state == "behind"
    if not outdated and (update or release):
        # under rules that do not require an up-to-date branch GitHub may report an
        # outdated PR `clean`: ask the comparison with the base instead
        cmp = gh.get(f"repos/{repo}/compare/{base}...{job.sha}") or {}
        outdated = (cmp.get("behind_by") or 0) > 0
    if outdated and release:
        return ("stopped", "behind: dispatch the release bump again")
    if outdated and (strict or update):
        if dry_run:
            return ("dry", "would update")
        ok, got = gh.put(f"repos/{repo}/pulls/{n}/update-branch", {"expected_head_sha": job.sha})
        if not ok:
            return ("stopped", f"refused: {plain(got)}")
        job.updated_from = job.sha
        job.say(f"updated {job.sha}", "updated", out)
        return None
    if ci["pending"]:
        names = ", ".join(ci["pending"][:3]) + (", ..." if len(ci["pending"]) > 3 else "")
        text = f"{len(ci['pending'])} pending ({names})"
        if dry_run:
            return ("dry", f"would wait: {text}")
        text = f"waiting: {text}"
        job.say("ci", text, out)
        return None
    if review_wait > 0 and not job.review_warned:
        # before the threads: the review is what opens them (#238)
        cr = coderabbit_review(gh, repo, n, job.sha)
        if cr != "reviewed":
            waited = age(pr)
            if waited < review_wait:
                if dry_run:
                    return ("dry", f"would wait: {REVIEW_WAIT[cr]}")
                job.say("review", f"waiting: {REVIEW_WAIT[cr]}", out)
                return None
            job.review_warned = True
            job.say(
                "review-late",
                f"warning: {REVIEW_WAIT[cr]} {waited:.0f}s after the PR opened "
                f"(--review-timeout {review_wait:g}); going on without it",
                out,
            )
    ts = threads(gh, repo, n)
    if ts:
        return ("stopped", "\n".join([f"open threads: {len(ts)}"] + [thread_line(t) for t in ts]))
    if state == "unknown":
        if dry_run:
            return ("dry", "would wait: mergeable state unknown")
        job.say("unknown", "waiting: mergeable state unknown", out)
        return None
    if dry_run:
        return ("dry", "would merge")
    fields = {"merge_method": "squash", "sha": job.sha, "commit_title": f"{job.title} (#{n})"}
    ok, got = gh.put(f"repos/{repo}/pulls/{n}/merge", fields)
    if ok:
        return ("merged", f"merged {((got or {}).get('sha') or '')[:7]}".rstrip())
    if UPDATE_FIRST.search(got):
        # an up-to-date branch is required after all (a rule the rules endpoint
        # did not show, such as a legacy branch protection): update on the next poll
        cache[(repo, base)] = (required, True)
        job.say(f"retry {job.sha}", f"waiting: merge not accepted yet ({plain(got)})", out)
        return None
    if got.startswith("HTTP 409") or RETRY.search(got):
        job.say(f"retry {job.sha}", f"waiting: merge not accepted yet ({plain(got)})", out)
        return None
    return ("stopped", f"refused: {plain(got)}")


def cmd_merge(args, gh, sleep=time.sleep, clock=time.monotonic, wall=time.time):
    def out(line):
        print(line, file=sys.stderr if args.json else sys.stdout, flush=True)

    queues = {}
    for ref in args.refs:
        repo, n = parse_ref(ref)
        queues.setdefault(repo, []).append(Job(repo, n))
    jobs = [j for q in queues.values() for j in q]
    cache = {}
    while True:
        for q in queues.values():
            while q:
                job = q[0]
                if job.start is None:
                    job.start = clock()
                try:
                    res = merge_step(
                        gh,
                        job,
                        args.dry_run,
                        cache,
                        out,
                        review_wait=args.review_timeout,
                        age=lambda pr, job=job: pr_age(pr, wall, clock() - job.start),
                        update=args.update,
                    )
                except Failure as e:
                    if args.dry_run:  # a dry run reads each PR once
                        raise
                    # a transient API error (502, rate limit, network): poll again,
                    # bounded by the PR's --timeout, rather than end every repository's run
                    job.say("error", f"waiting: {plain(e.code)}", out)
                    res = None
                if res is None and clock() - job.start >= args.timeout:
                    res = ("timeout", f"timeout after {args.timeout:g}s")
                if res is None:
                    break
                job.result, job.detail = res
                job.last = None
                job.say("done", job.detail, out)
                q.pop(0)
                if job.result in ("stopped", "timeout") and not args.dry_run:
                    for rest in q:
                        rest.result, rest.detail = "not run", f"not run: {job.ref()} {job.result}"
                        out(f"{rest.ref()} - {rest.detail}")
                    q.clear()
        if not any(queues.values()):
            break
        sleep(args.interval)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "repo": short_repo(j.repo),
                        "number": j.number,
                        "head": j.sha,
                        "result": j.result,
                        "detail": j.detail,
                        "events": j.events,
                    }
                    for j in jobs
                ],
                indent=1,
            )
        )
    results = {j.result for j in jobs}
    if results & {"stopped", "not run"}:
        return 1
    return 2 if "timeout" in results else 0


REVIEW_HELP = (
    "seconds after the PR opened to wait for CodeRabbit's review, then go on with a "
    "warning (default %(default)s; 0: do not wait)"
)


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument(
        "--min-rate",
        type=int,
        default=GitHub.min_remaining,
        help="back off when fewer API requests than this remain (default %(default)s)",
    )
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
    w.add_argument(
        "--review",
        action="store_true",
        help="also wait for CodeRabbit's review (before enabling auto-merge)",
    )
    w.add_argument("--review-timeout", type=float, default=1800, help=REVIEW_HELP)
    w.add_argument("--json", action="store_true")
    w.add_argument(
        "--merged",
        action="store_true",
        help="poll until each PR merged, or stop when one needs a hand (#341)",
    )
    g = sub.add_parser("gate", help="wait for CodeRabbit on one PR (the review-gate check)")
    g.add_argument("ref", metavar="REPO#N")
    g.add_argument("--interval", type=float, default=30)
    g.add_argument(
        "--timeout",
        type=float,
        default=1800,
        help="seconds after the PR opened to wait (default %(default)s)",
    )
    m = sub.add_parser("merge", help="wait for green, squash-merge in order")
    m.add_argument("refs", nargs="+", metavar="REPO#N")
    m.add_argument(
        "--update",
        action="store_true",
        help="update a behind PR first even where the rules do not require it",
    )
    m.add_argument("--interval", type=float, default=60)
    m.add_argument("--timeout", type=float, default=7200, help="seconds per PR")
    m.add_argument("--review-timeout", type=float, default=1800, help=REVIEW_HELP)
    m.add_argument("--dry-run", action="store_true", help="read once, say what it would do")
    m.add_argument("--json", action="store_true")
    qd = sub.add_parser("queued", help="merged, in the merge queue, or neither (read-only)")
    qd.add_argument("refs", nargs="+", metavar="REPO#N")
    qd.add_argument("--json", action="store_true")
    return p


def head_pushed_at(gh, repo, sha):
    """When the head reached GitHub: its earliest workflow run, else its committer date."""
    runs = gh.get(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100") or {}
    times = [r["created_at"] for r in runs.get("workflow_runs") or [] if r.get("created_at")]
    if times:
        return min(times)
    commit = gh.get(f"repos/{repo}/commits/{sha}") or {}
    return ((commit.get("commit") or {}).get("committer") or {}).get("date") or ""


def queue_runs(gh, repo, base, number, since, cache):
    """The newest queue branch's runs for the PR created at or after `since`, latest per workflow."""
    if repo not in cache:
        got = gh.get(f"repos/{repo}/actions/runs?event=merge_group&per_page=100") or {}
        cache[repo] = got.get("workflow_runs") or []
    prefix = f"gh-readonly-queue/{base}/pr-{number}-"
    runs = [
        r
        for r in cache[repo]
        if (r.get("head_branch") or "").startswith(prefix) and (r.get("created_at") or "") >= since
    ]
    if not runs:
        return None, {}
    newest = max(runs, key=lambda r: (r.get("created_at") or "", r.get("id") or 0))
    branch, latest = newest["head_branch"], {}
    for r in sorted(runs, key=lambda r: (r.get("created_at") or "", r.get("id") or 0)):
        if r["head_branch"] == branch:
            latest[r.get("name") or str(r.get("workflow_id"))] = r
    return branch, latest


def cmd_queued(args, gh):
    results, lines, cache = [], [], {}
    for ref in args.refs:
        repo, n = parse_ref(ref)
        name = f"{short_repo(repo)}#{n}"
        pr = gh.get(f"repos/{repo}/pulls/{n}")
        if pr is None:
            raise Failure(f"pr_status: {name} not found")
        res = {"pr": name, "state": pr.get("state")}
        if pr.get("merged") or pr.get("merged_at"):
            sha = (pr.get("merge_commit_sha") or "")[:7]
            res.update(status="merged", merge_commit=pr.get("merge_commit_sha"))
            lines.append(f"{name} merged {sha}".rstrip())
            results.append(res)
            continue
        base, head = pr["base"]["ref"], pr["head"]["sha"]
        branch, runs = (None, {})
        if pr.get("state") == "open":
            since = head_pushed_at(gh, repo, head)
            branch, runs = queue_runs(gh, repo, base, n, since, cache)
        states = {}
        if branch:
            states = {
                k: (r.get("conclusion") or "?")
                if r.get("status") == "completed"
                else r.get("status")
                for k, r in sorted(runs.items())
            }
            short = branch.rsplit("-", 1)
            shown = f"{short[0]}-{short[1][:7]}" if len(short) == 2 else branch
            shown = f"{shown} " + " ".join(f"{k}={v}" for k, v in states.items())
        failed = any(
            r.get("status") == "completed" and r.get("conclusion") in FAILED for r in runs.values()
        )
        if branch and not failed:
            res.update(status="queued", branch=branch, runs=states)
            lines.append(f"{name} queued: {shown}")
        else:
            am = pr.get("auto_merge")
            if am:
                who = (am.get("enabled_by") or {}).get("login") or "?"
                auto = f"auto-merge {(am.get('merge_method') or '?').lower()} by {who}"
            else:
                auto = "auto-merge none (REST shows none for a queued PR too)"
            res.update(status="not queued", auto_merge=am)
            why = ""
            if branch:  # a failed queue run: GitHub took the PR out of the queue
                res.update(branch=branch, runs=states, queue_run_failed=True)
                why = f"queue run failed ({shown}), "
            lines.append(f"{name} not queued: {why}{pr.get('state')}, {auto}")
        results.append(res)
    emit(results, lines, args.json)
    return 0


def main(argv=None, gh=None):
    p = parser()
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        p.error("a command is required")
    gh = gh or GitHub()
    gh.min_remaining = args.min_rate
    cmds = {
        "list": cmd_list,
        "threads": cmd_threads,
        "wait": cmd_wait,
        "gate": cmd_gate,
        "merge": cmd_merge,
        "queued": cmd_queued,
    }
    return cmds[args.cmd](args, gh)


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
                {"name": "lint", "status": "completed", "conclusion": "failure"},
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


OK_RUN = {"name": "ci", "status": "completed", "conclusion": "success"}
CR_REVIEW = {"user": {"login": "coderabbitai[bot]"}, "state": "COMMENTED", "commit_id": "0" * 40}


class SimGitHub(GitHub):
    """A fake GitHub that changes state: update-branch moves the head, a merge
    closes the PR and puts the repository's other open PRs behind."""

    def __init__(
        self,
        prs,
        checks=None,
        threads=None,
        required=None,
        refuse=None,
        runs=None,
        strict=(),
        legacy=(),
        reviews=None,
    ):
        self.prs = {}
        for (repo, n), fields in prs.items():
            pr = {"number": n, "title": f"feat: pr {n}", "state": "open", "merged": False}
            pr.update(draft=False, mergeable_state="clean", base={"ref": "main"})
            pr.update(fields)
            pr["head"] = {"sha": fields.get("sha", f"{n:x}" * 40)[:40]}
            self.prs[(repo, n)] = pr
        self.checks = checks or {}  # sha -> list of runs, or a callable returning one
        self.thr = threads or {}
        self.required = required or {}
        self.refuse = refuse or {}  # (repo, n) -> "HTTP 405: ..."
        self.runs = runs or {}  # sha -> workflow runs
        self.strict = set(strict)  # repos whose rules require an up-to-date branch
        self.legacy = set(legacy)  # repos that require it without the rules showing it
        self.reviews = reviews or {}  # (repo, n) -> reviews; default: CodeRabbit has reviewed
        self.calls, self.puts, self.updates = [], [], 0

    def get(self, path):
        self.calls.append(path)
        m = re.fullmatch(r"repos/swarm-routing/([\w.-]+)/(.*)", path)
        repo, rest = m.groups()
        if m := re.fullmatch(r"pulls/(\d+)", rest):
            pr = self.prs.get((repo, int(m.group(1))))
            return json.loads(json.dumps(pr)) if pr else None
        if m := re.fullmatch(r"commits/(\w+)/check-runs\?.*", rest):
            runs = self.checks.get(m.group(1), [OK_RUN])
            return {"check_runs": runs() if callable(runs) else runs}
        if re.fullmatch(r"commits/\w+/status", rest):
            return {"state": "success", "statuses": []}
        if m := re.fullmatch(r"actions/runs\?head_sha=(\w+)&.*", rest):
            return {"workflow_runs": self.runs.get(m.group(1), [])}
        if m := re.fullmatch(r"pulls/(\d+)/reviews\?.*", rest):
            got = self.reviews.get((repo, int(m.group(1))), [CR_REVIEW])
            return got() if callable(got) else got
        if m := re.fullmatch(r"pulls/(\d+)/ccr/review_threads", rest):
            return self.thr.get((repo, int(m.group(1))), [])
        if re.fullmatch(r"pulls/comments/\d+", rest):
            return {"user": {"login": "coderabbitai[bot]"}, "body": CR_OLD}
        if m := re.fullmatch(r"compare/main\.\.\.(\w+)", rest):
            prs = [p for (r, _), p in self.prs.items() if r == repo]
            pr = next(p for p in prs if p["head"]["sha"] == m.group(1))
            return {
                "behind_by": int(pr["mergeable_state"] == "behind" or pr.get("outdated", False))
            }
        if rest == "rules/branches/main":
            names = self.required.get(repo, [])
            params = {"required_status_checks": [{"context": c} for c in names]}
            params["strict_required_status_checks_policy"] = repo in self.strict
            return [{"type": "deletion"}, {"type": "required_status_checks", "parameters": params}]
        return None

    def put(self, path, fields):
        self.puts.append((path, dict(fields)))
        repo, n, what = re.fullmatch(
            r"repos/swarm-routing/([\w.-]+)/pulls/(\d+)/(.*)", path
        ).groups()
        pr = self.prs[(repo, int(n))]
        if (repo, int(n)) in self.refuse:
            return False, self.refuse[(repo, int(n))]
        if what == "update-branch":
            assert fields["expected_head_sha"] == pr["head"]["sha"]
            self.updates += 1
            pr["head"]["sha"] = f"{9 - self.updates}{n}" * 20
            pr["mergeable_state"] = "clean"
            pr["outdated"] = False
            return True, {"message": "Updating pull request branch."}
        if fields["sha"] != pr["head"]["sha"]:
            return False, "HTTP 409: Head branch was modified."
        if pr["mergeable_state"] == "behind" and repo in self.strict | self.legacy:
            return False, "HTTP 405: Head branch is not up to date with the base branch."
        pr.update(state="closed", merged=True)
        for (r, _), other in self.prs.items():
            if r == repo and other["state"] == "open":
                other["mergeable_state"] = "behind"
        return True, {"sha": "e" * 40, "merged": True}


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
    check(
        "identifiers keep their underscores",
        clean("Fix `pr_status.py` in _self_test()_") == "Fix pr_status.py in self_test()",
    )
    check("control characters are dropped", "\x1b" not in clean("a\x1b[31mred\x07b"))
    check("a path keeps its underscores", plain("pkg/__init__.py\x1b") == "pkg/__init__.py ")
    stripped = strip_html(CR_BODY)
    check("details stripped", "IGNORED" not in stripped and "details>" not in stripped)
    check("comments, pictures stripped", "<!--" not in stripped and "<picture>" not in stripped)
    check(
        "human comment",
        heading("\nPlease rename this.\nMore.", "carol") == ("@carol", "Please rename this."),
    )
    check("long title cut", len(heading("x" * 500, "dave")[1]) == TITLE_MAX)

    # queued: merged, in the queue for the current head, a stale queue run, auto-merge
    q = "repos/swarm-routing/alpha"
    qpr = {"state": "open", "merged": False, "base": {"ref": "main"}, "auto_merge": None}
    qrun = {"event": "merge_group", "status": "completed", "conclusion": "success"}
    qdata = {
        f"{q}/pulls/7": dict(qpr, state="closed", merged=True, merge_commit_sha="c" * 40),
        f"{q}/pulls/8": dict(qpr, head={"sha": "8" * 40}),
        f"{q}/pulls/9": dict(qpr, head={"sha": "9" * 40}),
        f"{q}/pulls/10": dict(
            qpr,
            head={"sha": "a1" * 20},
            auto_merge={"merge_method": "squash", "enabled_by": {"login": "alice"}},
        ),
        f"{q}/actions/runs?head_sha={'8' * 40}&per_page=100": {
            "workflow_runs": [{"created_at": "2026-11-12T10:05:00Z"}]
        },
        f"{q}/actions/runs?head_sha={'9' * 40}&per_page=100": {
            "workflow_runs": [{"created_at": "2026-11-12T11:00:00Z"}]
        },
        f"{q}/actions/runs?head_sha={'a1' * 20}&per_page=100": {"workflow_runs": []},
        f"{q}/pulls/11": dict(qpr, head={"sha": "b1" * 20}),
        f"{q}/actions/runs?head_sha={'b1' * 20}&per_page=100": {
            "workflow_runs": [{"created_at": "2026-11-12T10:00:00Z"}]
        },
        f"{q}/commits/{'a1' * 20}": {"commit": {"committer": {"date": "2026-11-12T09:00:00Z"}}},
        f"{q}/actions/runs?event=merge_group&per_page=100": {
            "workflow_runs": [
                # pr-8: an older queue entry (failed), then the current one
                dict(
                    qrun,
                    id=1,
                    name="CI",
                    conclusion="failure",
                    created_at="2026-11-12T10:10:00Z",
                    head_branch="gh-readonly-queue/main/pr-8-" + "1" * 40,
                ),
                dict(
                    qrun,
                    id=2,
                    name="CI",
                    status="in_progress",
                    conclusion=None,
                    created_at="2026-11-12T10:20:00Z",
                    head_branch="gh-readonly-queue/main/pr-8-" + "2" * 40,
                ),
                dict(
                    qrun,
                    id=3,
                    name="review",
                    created_at="2026-11-12T10:20:01Z",
                    head_branch="gh-readonly-queue/main/pr-8-" + "2" * 40,
                ),
                # pr-9: queued before its head was pushed, so not for this head
                dict(
                    qrun,
                    id=4,
                    name="CI",
                    created_at="2026-11-12T10:30:00Z",
                    head_branch="gh-readonly-queue/main/pr-9-" + "3" * 40,
                ),
                # pr-80 shares the prefix digits, never pr-8's
                dict(
                    qrun,
                    id=5,
                    name="CI",
                    created_at="2026-11-12T10:40:00Z",
                    head_branch="gh-readonly-queue/main/pr-80-" + "4" * 40,
                ),
                # pr-11: queued after its head was pushed, then its queue CI failed (dequeued)
                dict(
                    qrun,
                    id=6,
                    name="CI",
                    conclusion="failure",
                    created_at="2026-11-12T10:50:00Z",
                    head_branch="gh-readonly-queue/main/pr-11-" + "5" * 40,
                ),
                dict(
                    qrun,
                    id=7,
                    name="review",
                    created_at="2026-11-12T10:50:01Z",
                    head_branch="gh-readonly-queue/main/pr-11-" + "5" * 40,
                ),
            ]
        },
    }
    rc, out, gh = run(["queued", "alpha#7", "alpha#8", "alpha#9", "alpha#10", "alpha#11"], qdata)
    check(
        "queued: one line per PR",
        rc == 0
        and out.splitlines()
        == [
            "alpha#7 merged ccccccc",
            "alpha#8 queued: gh-readonly-queue/main/pr-8-2222222 CI=in_progress review=success",
            "alpha#9 not queued: open, auto-merge none (REST shows none for a queued PR too)",
            "alpha#10 not queued: open, auto-merge squash by alice",
            "alpha#11 not queued: queue run failed (gh-readonly-queue/main/pr-11-5555555 "
            "CI=failure review=success), open, auto-merge none (REST shows none for a queued "
            "PR too)",
        ],
    )
    check(
        "queued: read only, the queue runs read once",
        all(not c.startswith("-") for c in gh.calls)
        and gh.calls.count(f"{q}/actions/runs?event=merge_group&per_page=100") == 1,
    )
    rc, out, gh = run(["queued", "alpha#8", "--json"], qdata)
    got = json.loads(out)
    check(
        "queued --json",
        got[0]["status"] == "queued"
        and got[0]["runs"] == {"CI": "in_progress", "review": "success"},
    )
    rc, out, gh = run(["queued", "alpha#11", "--json"], qdata)
    got = json.loads(out)
    check(
        "queued --json: a failed queue run",
        got[0]["status"] == "not queued"
        and got[0]["queue_run_failed"] is True
        and got[0]["runs"]["CI"] == "failure",
    )

    # list: CI states, a resolved and an unresolved thread, the 404 endpoint
    rc, out, gh = run(["list", "--repos", "alpha"])
    lines = out.splitlines()
    check("list rc", rc == 0)
    check(
        "pr line",
        lines[0]
        == "alpha#5 aaaaaaa ci=fail(failure=1,skipped=1,success=3) failed=lint merge=clean threads=3 · feat(x): a change",
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
        and js[0]["ci"]
        == {
            "verdict": "fail",
            "counts": {"failure": 1, "skipped": 1, "success": 3},
            "failed": ["lint"],
            "missing": [],
        }
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

    # #167's state: every workflow ended in startup_failure, so no check run exists
    # and the three required checks are absent; a re-run that started is not a failure
    sha = "a" * 40
    data = fixture()
    data[f"repos/swarm-routing/alpha/commits/{sha}/check-runs?per_page=100&page=1"] = {
        "check_runs": []
    }
    data[f"repos/swarm-routing/alpha/commits/{sha}/status"] = {"state": "pending", "statuses": []}
    required = ["lint", "python / python", "title / title"]
    data["repos/swarm-routing/alpha/rules/branches/main"] = [
        {"type": "deletion"},
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": c} for c in required]},
        },
    ]
    sf = {"status": "completed", "conclusion": "startup_failure"}
    data[f"repos/swarm-routing/alpha/actions/runs?head_sha={sha}&per_page=100&page=1"] = {
        "total_count": 4,
        "workflow_runs": [
            dict(sf, id=1, workflow_id=10, name="CI", created_at="2026-11-01T00:00:00Z"),
            dict(sf, id=2, workflow_id=20, name="PR title", created_at="2026-11-01T00:00:00Z"),
            dict(sf, id=3, workflow_id=30, name="Docs", created_at="2026-11-01T00:00:00Z"),
            {
                "id": 4,
                "workflow_id": 30,
                "name": "Docs",
                "status": "in_progress",
                "conclusion": None,
                "created_at": "2026-11-02T00:00:00Z",
            },
        ],
    }
    rc, out, _ = run(["list", "--repos", "alpha"], data=data)
    check(
        "a startup failure and missing required checks are not a pass",
        out.splitlines()[0]
        == "alpha#5 aaaaaaa ci=fail(startup_failure=2) failed=CI (startup_failure),"
        "PR title (startup_failure) missing=lint,python / python,title / title "
        "merge=clean threads=3 · feat(x): a change",
    )
    data[f"repos/swarm-routing/alpha/actions/runs?head_sha={sha}&per_page=100&page=1"] = {
        "workflow_runs": []
    }
    data[f"repos/swarm-routing/alpha/commits/{sha}/check-runs?per_page=100&page=1"] = {
        "check_runs": [{"name": "lint", "status": "completed", "conclusion": "success"}]
    }
    rc, out, _ = run(["list", "--repos", "alpha"], data=data)
    check(
        "a missing required check keeps the verdict pending",
        out.splitlines()[0].startswith(
            "alpha#5 aaaaaaa ci=pending(success=1) missing=python / python,title / title "
        ),
    )
    now = [0.0]

    def tick(s):
        now[0] += s

    rc, out, _ = run(["wait", "alpha#5"], data=data, sleep=tick, clock=lambda: now[0], timeout=3)
    check(
        "wait: a required check still missing at the timeout fails",
        rc == 2
        and out.splitlines()[0].startswith("alpha#5 aaaaaaa ci=fail(success=1) missing=")
        and "timeout: 1 still pending after 3s" in out,
    )
    data[f"repos/swarm-routing/alpha/commits/{sha}/check-runs?per_page=100&page=1"] = {
        "check_runs": [
            {"name": "lint", "status": "completed", "conclusion": "success"},
            {"name": "build", "status": "in_progress", "conclusion": None},
        ]
    }
    now[0] = 0.0
    rc, out, _ = run(["wait", "alpha#5"], data=data, sleep=tick, clock=lambda: now[0], timeout=3)
    check(
        "wait: a missing required check while others still run stays pending at the timeout",
        rc == 2
        and out.splitlines()[0].startswith(
            "alpha#5 aaaaaaa ci=pending(pending=1,success=1) missing="
        )
        and "timeout: 1 still pending after 3s" in out,
    )
    data[f"repos/swarm-routing/alpha/commits/{sha}/check-runs?per_page=100&page=1"] = {
        "check_runs": [{"name": "lint", "status": "completed", "conclusion": "success"}]
    }

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
        run(["list", "--repos", "no-such-repo"])
        check("a missing repository fails instead of listing no PRs", False)
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

    # merge: a simulated GitHub whose state moves with each update and merge
    def merge(refs, gh, *flags, timeout=600):
        now = [0.0]

        def tick(s):
            now[0] += s

        argv = ["merge", *refs, "--interval", "60", "--timeout", str(timeout), *flags]
        ns = parser().parse_args(argv)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cmd_merge(ns, gh, sleep=tick, clock=lambda: now[0])
        return rc, out.getvalue(), err.getvalue()

    def pending_then(sha, polls):
        seen = []

        def runs():
            seen.append(1)
            return [OK_RUN] if len(seen) > polls else [{"name": "ci", "status": "in_progress"}]

        return {sha: runs}

    # rules require an up-to-date branch: behind -> update -> wait for the new head -> merged
    gh = SimGitHub({("alpha", 1): {"mergeable_state": "behind"}}, strict={"alpha"})
    gh.checks = pending_then("81" * 20, 2)
    rc, out, _ = merge(["alpha#1"], gh)
    check(
        "merge: behind, update, merged",
        rc == 0
        and out.splitlines()
        == [
            "alpha#1 1111111 updated",
            "alpha#1 8181818 waiting: 1 pending (ci)",
            "alpha#1 8181818 merged eeeeeee",
        ],
    )
    check(
        "merge: update then squash with sha and title",
        gh.puts
        == [
            ("repos/swarm-routing/alpha/pulls/1/update-branch", {"expected_head_sha": "1" * 40}),
            (
                "repos/swarm-routing/alpha/pulls/1/merge",
                {"merge_method": "squash", "sha": "81" * 20, "commit_title": "feat: pr 1 (#1)"},
            ),
        ],
    )

    # two PRs in sequence: the second falls behind after the first merges
    gh = SimGitHub({("alpha", 2): {}, ("alpha", 3): {}}, strict={"alpha"})
    rc, out, _ = merge(["alpha#2", "alpha#3"], gh)
    merges = [p for p, f in gh.puts if p.endswith("/merge")]
    check(
        "merge: sequential order",
        rc == 0
        and merges
        == ["repos/swarm-routing/alpha/pulls/2/merge", "repos/swarm-routing/alpha/pulls/3/merge"]
        and out.splitlines()
        == [
            "alpha#2 2222222 merged eeeeeee",
            "alpha#3 3333333 updated",
            "alpha#3 8383838 merged eeeeeee",
        ],
    )

    # stops: failing check, open thread, conflict, draft, refused merge
    gh = SimGitHub({("alpha", 4): {}, ("alpha", 5): {}})
    gh.checks = {
        "4" * 40: [
            {"name": "lint", "status": "completed", "conclusion": "failure"},
            dict(OK_RUN, name="test"),
        ]
    }
    rc, out, _ = merge(["alpha#4", "alpha#5"], gh)
    check(
        "merge: failing check stops the repository",
        rc == 1
        and not gh.puts
        and out.splitlines()
        == ["alpha#4 4444444 failing: lint", "alpha#5 - not run: alpha#4 stopped"],
    )
    gh = SimGitHub({("alpha", 6): {}})
    gh.thr = {("alpha", 6): [{"resolved": False, "path": "x.py", "line": 3, "comment_ids": [7]}]}
    rc, out, _ = merge(["alpha#6"], gh)
    check(
        "merge: open thread",
        rc == 1
        and not gh.puts
        and out.splitlines()
        == ["alpha#6 6666666 open threads: 1", "  Major · Guard the empty list. · x.py:3 · 7"],
    )
    gh = SimGitHub({("alpha", 7): {"mergeable_state": "dirty"}, ("alpha", 8): {"draft": True}})
    rc, out, _ = merge(["alpha#7"], gh)
    check("merge: conflict", rc == 1 and out == "alpha#7 7777777 conflict\n" and not gh.puts)
    rc, out, _ = merge(["alpha#8"], gh)
    check("merge: draft", rc == 1 and out == "alpha#8 8888888 draft\n" and not gh.puts)
    gh = SimGitHub(
        {("alpha", 9): {}}, refuse={("alpha", 9): "HTTP 405: Repository rule violations"}
    )
    rc, out, _ = merge(["alpha#9"], gh)
    check(
        "merge: refused is handed back",
        rc == 1 and out == "alpha#9 9999999 refused: HTTP 405: Repository rule violations\n",
    )

    # skipped: already merged, closed; a required check that never reports times out
    gh = SimGitHub(
        {("alpha", 10): {"merged": True, "state": "closed"}, ("alpha", 11): {"state": "closed"}}
    )
    rc, out, _ = merge(["alpha#10", "alpha#11"], gh)
    check(
        "merge: already merged and closed are skipped",
        rc == 0
        and not gh.puts
        and out.splitlines() == ["alpha#10 aaaaaaa already merged", "alpha#11 bbbbbbb closed"],
    )
    gh = SimGitHub({("alpha", 12): {}}, required={"alpha": ["ci", "gate"]})
    rc, out, _ = merge(["alpha#12"], gh, timeout=180)
    check(
        "merge: an unreported required check is pending until the timeout",
        rc == 2
        and not gh.puts
        and out.splitlines()
        == [
            "alpha#12 ccccccc waiting: 1 pending (gate (not reported))",
            "alpha#12 ccccccc timeout after 180s",
        ],
    )

    # a workflow that never started: no check run, but the merge refuses it
    gh = SimGitHub(
        {("alpha", 17): {}},
        runs={
            "11" * 20: [{"id": 1, "workflow_id": 1, "name": "CI", "conclusion": "startup_failure"}]
        },
    )
    rc, out, _ = merge(["alpha#17"], gh)
    check(
        "merge: a startup failure stops the PR",
        rc == 1 and not gh.puts and out == "alpha#17 1111111 failing: CI (startup_failure)\n",
    )

    # a failed read (a 502) is polled again, not the end of the run
    gh = SimGitHub({("alpha", 16): {}})
    flaky = [1]
    real_get = gh.get

    def get_once_502(path):
        if flaky and path.endswith("/pulls/16"):
            flaky.pop()
            raise Failure("gh api repos/swarm-routing/alpha/pulls/16: HTTP 502")
        return real_get(path)

    gh.get = get_once_502
    rc, out, _ = merge(["alpha#16"], gh)
    check(
        "merge: a transient read error is polled again",
        rc == 0
        and out.splitlines()
        == [
            "alpha#16 - waiting: gh api repos/swarm-routing/alpha/pulls/16: HTTP 502",
            "alpha#16 1010101 merged eeeeeee",
        ],
    )

    # the latest run of a name counts, so a re-run that passed is green
    gh = SimGitHub({("alpha", 13): {}})
    gh.checks = {
        "d" * 40: [
            {
                "id": 1,
                "name": "ci",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "1",
            },
            {
                "id": 2,
                "name": "ci",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2",
            },
        ]
    }
    rc, out, _ = merge(["alpha#13"], gh)
    check("merge: latest run per name", rc == 0 and out == "alpha#13 ddddddd merged eeeeeee\n")

    # repositories are independent: a stop in one does not hold the other back
    gh = SimGitHub({("alpha", 14): {"mergeable_state": "dirty"}, ("beta", 15): {}})
    rc, out, _ = merge(["alpha#14", "beta#15"], gh)
    check(
        "merge: repositories independent",
        rc == 1 and "beta#15 fffffff merged eeeeeee" in out and "alpha#14 eeeeeee conflict" in out,
    )

    # rules that do not require an up-to-date branch (every org profile, #205): a
    # behind PR merges as it is, in sequence, with no update
    gh = SimGitHub({("alpha", 2): {}, ("alpha", 3): {}})
    rc, out, _ = merge(["alpha#2", "alpha#3"], gh)
    check(
        "merge: behind merges as it is when the rules allow it",
        rc == 0
        and gh.updates == 0
        and [p for p, _ in gh.puts]
        == ["repos/swarm-routing/alpha/pulls/2/merge", "repos/swarm-routing/alpha/pulls/3/merge"]
        and out.splitlines()
        == ["alpha#2 2222222 merged eeeeeee", "alpha#3 3333333 merged eeeeeee"],
    )
    # --update: main changed what the PR touches, so it is updated first all the same
    gh = SimGitHub({("alpha", 1): {"mergeable_state": "behind"}})
    rc, out, _ = merge(["alpha#1"], gh, "--update")
    check(
        "merge: --update updates a behind PR the rules would merge",
        rc == 0
        and gh.updates == 1
        and out.splitlines() == ["alpha#1 1111111 updated", "alpha#1 8181818 merged eeeeeee"],
    )
    # a behind bot/release PR is never updated: the bump is dispatched again
    for strict in ((), {"alpha"}):
        gh = SimGitHub({("alpha", 1): {"mergeable_state": "behind"}}, strict=strict)
        gh.prs[("alpha", 1)]["head"]["ref"] = "bot/release"
        rc, out, _ = merge(["alpha#1"], gh, "--update")
        check(
            f"merge: behind bot/release stops (strict={bool(strict)})",
            rc == 1
            and not gh.puts
            and out == "alpha#1 1111111 behind: dispatch the release bump again\n",
        )

    # GitHub may report an outdated PR `clean` under non-strict rules: --update and a
    # bot/release head ask the comparison with the base
    gh = SimGitHub({("alpha", 1): {"outdated": True}})
    rc, out, _ = merge(["alpha#1"], gh, "--update")
    check(
        "merge: --update updates an outdated PR GitHub reports clean",
        rc == 0
        and gh.updates == 1
        and out.splitlines() == ["alpha#1 1111111 updated", "alpha#1 8181818 merged eeeeeee"],
    )
    gh = SimGitHub({("alpha", 1): {"outdated": True}})
    gh.prs[("alpha", 1)]["head"]["ref"] = "bot/release"
    rc, out, _ = merge(["alpha#1"], gh)
    check(
        "merge: an outdated bot/release PR reported clean stops",
        rc == 1
        and not gh.puts
        and out == "alpha#1 1111111 behind: dispatch the release bump again\n",
    )
    gh = SimGitHub({("alpha", 1): {"outdated": True}})
    rc, out, _ = merge(["alpha#1"], gh)
    check(
        "merge: an outdated PR merges as it is without --update",
        rc == 0 and gh.updates == 0 and out == "alpha#1 1111111 merged eeeeeee\n",
    )
    # a refusal as "not up to date" (strict without the rules showing it): update, merge
    gh = SimGitHub({("alpha", 1): {"mergeable_state": "behind"}}, legacy={"alpha"})
    rc, out, _ = merge(["alpha#1"], gh)
    check(
        "merge: refused as not up to date, then updated and merged",
        rc == 0
        and gh.updates == 1
        and out.splitlines()[-2:] == ["alpha#1 1111111 updated", "alpha#1 8181818 merged eeeeeee"],
    )

    # CodeRabbit's review comes before the merge (#238): wait for it, check the
    # threads it opened, and go on with a warning when it never comes
    def review_after(polls, then=None):
        seen = []

        def reviews():
            seen.append(1)
            return [CR_REVIEW] if len(seen) > polls else (then or [])

        return reviews

    gh = SimGitHub({("alpha", 20): {"sha": "20" * 20}}, reviews={("alpha", 20): review_after(2)})
    rc, out, _ = merge(["alpha#20"], gh)
    check(
        "merge: waits for CodeRabbit's review, then merges",
        rc == 0
        and out.splitlines()
        == [
            "alpha#20 2020202 waiting: no CodeRabbit review yet",
            "alpha#20 2020202 merged eeeeeee",
        ],
    )
    gh = SimGitHub({("alpha", 21): {"sha": "21" * 20}})
    seen = []

    def review_once():
        seen.append(1)
        return [CR_REVIEW] if len(seen) > 1 else []

    gh.reviews = {("alpha", 21): review_once}
    real_get = gh.get

    def get_threads(path):  # the review opens a thread
        if path.endswith("/pulls/21/ccr/review_threads") and len(seen) > 1:
            return [{"resolved": False, "path": "x.py", "line": 3, "comment_ids": [7]}]
        return real_get(path)

    gh.get = get_threads
    rc, out, _ = merge(["alpha#21"], gh)
    check(
        "merge: the threads the review opened stop the merge",
        rc == 1
        and not gh.puts
        and out.splitlines()
        == [
            "alpha#21 2121212 waiting: no CodeRabbit review yet",
            "alpha#21 2121212 open threads: 1",
            "  Major · Guard the empty list. · x.py:3 · 7",
        ],
    )
    cr_run = {"name": "CodeRabbit", "app": {"slug": "coderabbitai"}}
    reviewing = [dict(cr_run, status="in_progress"), OK_RUN]
    finished = [dict(cr_run, status="completed", conclusion="skipped"), OK_RUN]
    gh = SimGitHub({("alpha", 22): {"sha": "22" * 20}}, reviews={("alpha", 22): []})
    polls = []

    def cr_then_done():
        polls.append(1)
        return finished if len(polls) > 4 else reviewing

    gh.checks = {"22" * 20: cr_then_done}
    rc, out, _ = merge(["alpha#22"], gh)
    check(
        "merge: CodeRabbit's running check is the review, not a pending CI check",
        rc == 0
        and out.splitlines()
        == [
            "alpha#22 2222222 waiting: CodeRabbit review in progress",
            "alpha#22 2222222 merged eeeeeee",
        ],
    )
    gh = SimGitHub({("alpha", 23): {"sha": "23" * 20}}, reviews={("alpha", 23): []})
    rc, out, _ = merge(["alpha#23"], gh, "--review-timeout", "120")
    check(
        "merge: no review by the review time-out: a warning, then the merge",
        rc == 0
        and out.splitlines()
        == [
            "alpha#23 2323232 waiting: no CodeRabbit review yet",
            "alpha#23 2323232 warning: no CodeRabbit review yet 120s after the PR opened "
            "(--review-timeout 120); going on without it",
            "alpha#23 2323232 merged eeeeeee",
        ],
    )
    gh = SimGitHub(
        {("alpha", 24): {"sha": "24" * 20, "created_at": "2026-01-01T00:00:00Z"}},
        reviews={("alpha", 24): []},
    )
    gh.checks = {"24" * 20: [dict(cr_run, status="completed", conclusion="cancelled"), OK_RUN]}
    rc, out, _ = merge(["alpha#24"], gh)
    check(
        "merge: an old PR CodeRabbit never reviewed is not held, a cancelled review is no failure",
        rc == 0
        and len(out.splitlines()) == 2
        and "warning: no CodeRabbit review yet" in out.splitlines()[0]
        and out.splitlines()[1] == "alpha#24 2424242 merged eeeeeee",
    )
    gh = SimGitHub({("alpha", 25): {"sha": "25" * 20}}, reviews={("alpha", 25): []})
    rc, out, _ = merge(["alpha#25"], gh, "--review-timeout", "0")
    check(
        "merge: --review-timeout 0 does not wait",
        rc == 0 and out == "alpha#25 2525252 merged eeeeeee\n",
    )
    rc, out, _ = merge(
        ["alpha#25"],
        SimGitHub({("alpha", 25): {"sha": "25" * 20}}, reviews={("alpha", 25): []}),
        "--dry-run",
    )
    check(
        "merge: dry run before the review",
        rc == 0 and out == "alpha#25 2525252 would wait: no CodeRabbit review yet\n",
    )

    # wait --review: until CodeRabbit has reviewed, a warning (exit 0) when it never does
    def wait_review(gh, ref, timeout=600, review_timeout=300):
        now = [0.0]

        def tick(s):
            now[0] += s

        ns = parser().parse_args(
            ["wait", ref, "--review", "--interval", "60", "--timeout", str(timeout)]
            + ["--review-timeout", str(review_timeout)]
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_wait(ns, gh, sleep=tick, clock=lambda: now[0])
        return rc, out.getvalue(), now[0]

    gh = SimGitHub({("alpha", 26): {"sha": "26" * 20}}, reviews={("alpha", 26): review_after(3)})
    rc, out, waited = wait_review(gh, "alpha#26")
    check(
        "wait --review: until CodeRabbit reviewed",
        rc == 0
        and waited == 180
        and out.splitlines()[-1] == "alpha#26 review: CodeRabbit reviewed",
    )
    gh = SimGitHub({("alpha", 27): {"sha": "27" * 20}}, reviews={("alpha", 27): []})
    rc, out, waited = wait_review(gh, "alpha#27")
    check(
        "wait --review: a warning, not a failure, at the review time-out",
        rc == 0
        and waited == 300
        and out.splitlines()[-1]
        == "alpha#27 warning: no CodeRabbit review yet 300s after the PR opened",
    )

    gh = SimGitHub({("alpha", 28): {"sha": "28" * 20}}, reviews={("alpha", 28): []})
    gh.checks = {"28" * 20: reviewing}
    rc, out, waited = wait_review(gh, "alpha#28", review_timeout=120)
    check(
        "wait --review: an optional CodeRabbit run still going is not pending CI",
        rc == 0
        and waited == 120
        and "ci=pass(success=1)" in out
        and out.splitlines()[-1].startswith("alpha#28 warning: CodeRabbit review in progress"),
    )
    gh = SimGitHub({("alpha", 29): {"sha": "29" * 20}})
    reads = []
    real_get29 = gh.get

    def thread_on_second_read(path):  # the review lands between pr_state's read and its own
        if path.endswith("/pulls/29/ccr/review_threads"):
            reads.append(1)
            if len(reads) > 1:
                return [{"resolved": False, "path": "x.py", "line": 3, "comment_ids": [7]}]
            return []
        return real_get29(path)

    gh.get = thread_on_second_read
    rc, out, _ = wait_review(gh, "alpha#29")
    check(
        "wait --review: the threads are read again after the review",
        rc == 0 and "threads=1" in out and "Guard the empty list." in out,
    )

    # --dry-run writes nothing; --json puts the events on stderr and results on stdout
    gh = SimGitHub(
        {("alpha", 1): {"mergeable_state": "behind"}, ("alpha", 2): {}}, strict={"alpha"}
    )
    rc, out, _ = merge(["alpha#1", "alpha#2"], gh, "--dry-run")
    check(
        "merge: dry run",
        rc == 0
        and not gh.puts
        and out.splitlines() == ["alpha#1 1111111 would update", "alpha#2 2222222 would merge"],
    )
    gh = SimGitHub({("alpha", 3): {}}, required={"alpha": ["gate"]})
    rc, out, _ = merge(["alpha#3"], gh, "--dry-run")
    check(
        "merge: dry run while pending",
        rc == 0 and out == "alpha#3 3333333 would wait: 1 pending (gate (not reported))\n",
    )
    gh = SimGitHub({("alpha", 2): {}})
    rc, out, err = merge(["alpha#2"], gh, "--json")
    js = json.loads(out)
    check(
        "merge: json",
        rc == 0
        and err == "alpha#2 2222222 merged eeeeeee\n"
        and js
        == [
            {
                "repo": "alpha",
                "number": 2,
                "head": "2" * 40,
                "result": "merged",
                "detail": "merged eeeeeee",
                "events": ["merged eeeeeee"],
            }
        ],
    )

    # the rate limit: a fake `gh api -i` response with X-RateLimit-* headers
    head = "HTTP/1.1 200 OK\r\nX-Ratelimit-Remaining: {}\r\nX-Ratelimit-Reset: {}\r\n\r\n[1]"
    check(
        "split_head",
        split_head(head.format(7, 9))
        == ({"x-ratelimit-remaining": "7", "x-ratelimit-reset": "9"}, "[1]"),
    )

    class RateGitHub(GitHub):
        def __init__(self, left, reset):
            self.out, self.slept = head.format(left, reset), []
            self.rate_sleep = self.slept.append
            self.rate_clock = lambda: 1000

    import unittest.mock as um

    def rate_get(left, reset, min_rate=500):
        gh = RateGitHub(left, reset)
        gh.min_remaining = min_rate
        done = subprocess.CompletedProcess([], 0, stdout=gh.out, stderr="")
        err = io.StringIO()
        with um.patch.object(subprocess, "run", return_value=done), contextlib.redirect_stderr(err):
            try:
                return gh.get("x"), gh.slept, None
            except Failure as e:
                return None, gh.slept, str(e)

    # gate (#294): reviewed, declined, draft, timeout, and waiting until the review lands
    def gate(prfields, reviews, comments=(), checks=None, age=0, timeout=1800, events=()):
        data = {}
        pr = {"number": 7, "head": {"sha": "a" * 40}, "created_at": "2026-11-12T00:00:00Z"}
        pr.update(prfields)
        data["repos/swarm-routing/ARA/pulls/7"] = pr
        rv = list(reviews)
        data["repos/swarm-routing/ARA/pulls/7/reviews?per_page=100&page=1"] = lambda: (
            rv.pop(0) if len(rv) > 1 else rv[0]
        )
        data["repos/swarm-routing/ARA/commits/" + "a" * 40 + "/check-runs?per_page=100&page=1"] = {
            "check_runs": checks or []
        }
        data["repos/swarm-routing/ARA/issues/7/comments?per_page=100&page=1"] = list(comments)
        data["repos/swarm-routing/ARA/issues/7/events?per_page=100&page=1"] = list(events)
        gh, slept = FakeGitHub(data), []
        t0 = datetime.datetime(2026, 11, 12, tzinfo=datetime.timezone.utc).timestamp()
        out = io.StringIO()
        args = parser().parse_args(["gate", "ARA#7", "--timeout", str(timeout), "--interval", "30"])
        clock = iter(range(0, 100000, 30))
        with contextlib.redirect_stdout(out):
            rc = cmd_gate(
                args, gh, sleep=slept.append, clock=lambda: next(clock), wall=lambda: t0 + age
            )
        return rc, out.getvalue().strip(), slept

    cr_comment = {"user": {"login": "coderabbitai[bot]"}, "body": ""}
    rc, out, slept = gate({}, [[CR_REVIEW]])
    check(
        "gate: reviewed passes at once",
        rc == 0 and out == "reviewed: CodeRabbit reviewed" and slept == [],
    )
    rc, out, slept = gate({}, [[], [], [CR_REVIEW]])
    check("gate: waits until the review lands", out.startswith("reviewed") and len(slept) == 2)
    rc, out, _ = gate(
        {},
        [[]],
        comments=[dict(cr_comment, body="> [!IMPORTANT]\n> ## Review skipped\n> Draft detected.")],
    )
    check("gate: a skipped review passes with the reason", out == "declined: Review skipped")
    rc, out, _ = gate(
        {},
        [[]],
        comments=[dict(cr_comment, body="You have used all 10 included reviews this month.")],
    )
    check(
        "gate: a used-up quota passes with the reason",
        out.startswith("declined: used all 10 included reviews"),
    )
    rc, out, _ = gate(
        {}, [[]], comments=[{"user": {"login": "dave"}, "body": "rate limit exceeded"}], age=2000
    )
    check("gate: another author's words do not count", out.startswith("timeout"))
    rc, out, _ = gate({}, [[]], age=2000)
    check(
        "gate: past the time-out passes with timeout",
        rc == 0 and out.startswith("timeout: no CodeRabbit review"),
    )
    rc, out, slept = gate({}, [[]], age=1790)
    check("gate: sleeps only up to the time-out", slept and abs(slept[0] - 10.0) < 1e-9)
    stale = dict(
        cr_comment, body="## Review skipped\nDraft detected.", updated_at="2026-11-12T00:01:00Z"
    )
    ready = [{"event": "ready_for_review", "created_at": "2026-11-12T00:05:00Z"}]
    rc, out, _ = gate({}, [[]], comments=[stale], events=ready, age=2000)
    check("gate: a decline from before ready_for_review does not count", out.startswith("timeout"))
    rc, out, _ = gate({}, [[]], comments=[stale])
    check("gate: a decline with no ready_for_review after it counts", out.startswith("declined"))
    draft_run = {"name": "CodeRabbit", "status": "completed", "conclusion": "skipped"}
    draft_run["started_at"] = "2026-11-12T00:01:00Z"
    rc, out, _ = gate({}, [[]], checks=[draft_run], events=ready, age=2000)
    check(
        "gate: a check run from before ready_for_review is not the review",
        out.startswith("timeout"),
    )
    rc, out, _ = gate(
        {}, [[]], checks=[dict(draft_run, started_at="2026-11-12T00:06:00Z")], events=ready
    )
    check("gate: a check run after ready_for_review counts", out.startswith("reviewed"))
    rc, out, _ = gate({"draft": True}, [[]])
    check("gate: a draft passes", out.startswith("draft:"))
    rc, out, _ = gate(
        {}, [[]], checks=[{"name": "CodeRabbit", "status": "completed", "conclusion": "skipped"}]
    )
    check("gate: CodeRabbit's completed check counts as reviewed", out.startswith("reviewed"))

    class FlakyGitHub(FakeGitHub):
        def __init__(self, data, fails):
            super().__init__(data)
            self.fails = fails

        def get(self, path):
            if self.fails:
                self.fails -= 1
                raise Failure("gh api: HTTP 502")
            return super().get(path)

    def gate_flaky(fails, timeout):
        data = {
            "repos/swarm-routing/ARA/pulls/7": {"number": 7, "head": {"sha": "b" * 40}},
            "repos/swarm-routing/ARA/pulls/7/reviews?per_page=100&page=1": [CR_REVIEW],
        }
        slept, out, err = [], io.StringIO(), io.StringIO()
        clock = iter(range(0, 100000, 30))
        args = parser().parse_args(["gate", "ARA#7", "--timeout", str(timeout)])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cmd_gate(
                args, FlakyGitHub(data, fails), sleep=slept.append, clock=lambda: next(clock)
            )
        return rc, out.getvalue().strip(), len(slept)

    rc, out, polls = gate_flaky(2, 1800)
    check(
        "gate: a failed read is retried, not a red check",
        rc == 0 and out.startswith("reviewed") and polls == 2,
    )
    rc, out, _ = gate_flaky(10**6, 60)
    check(
        "gate: reads failing until the time-out pass as a timeout",
        rc == 0 and out.startswith("timeout: GitHub reads kept failing"),
    )
    gh_missing = FakeGitHub({})
    try:
        cmd_gate(parser().parse_args(["gate", "ARA#7"]), gh_missing, sleep=lambda s: None)
        check("gate: a missing PR fails", False)
    except Failure:
        check("gate: a missing PR fails", True)

    # wait --merged (#341): merged, closed, a thread, a red required check, auto-merge off, timeout
    def landed(
        pr_seq, runs=(OK_RUN,), threads_=(), timeout=100, missing=False, extra=(), in_queue=False
    ):
        sha = "c" * 40
        prs = iter(pr_seq)
        last = {}

        def next_pr():
            last["pr"] = next(prs, last.get("pr"))
            return None if missing else dict({"head": {"sha": sha}, "state": "open"}, **last["pr"])

        data = {
            "repos/swarm-routing/beta/pulls/9": next_pr,
            "repos/swarm-routing/beta/pulls/9/ccr/review_threads": list(threads_),
            "repos/swarm-routing/beta/pulls/comments/700": {
                "user": {"login": "coderabbitai[bot]"},
                "body": CR_BODY,
            },
            "repos/swarm-routing/beta/rules/branches/main": [
                {
                    "type": "required_status_checks",
                    "parameters": {"required_status_checks": [{"context": "ci"}]},
                }
            ],
            f"repos/swarm-routing/beta/commits/{sha}/check-runs?per_page=100&page=1": {
                "check_runs": list(runs)
            },
            f"repos/swarm-routing/beta/commits/{sha}/status": {"statuses": []},
            f"repos/swarm-routing/beta/actions/runs?head_sha={sha}&per_page=100&page=1": {
                "workflow_runs": []
            },
        }
        now = [0.0]
        data["repos/swarm-routing/beta/git/matching-refs/heads/gh-readonly-queue/main/pr-9-"] = (
            lambda: [{"ref": "refs/heads/gh-readonly-queue/main/pr-9-abc"}] if in_queue else []
        )
        data["repos/swarm-routing/beta/pulls/10"] = {
            "head": {"sha": sha},
            "state": "open",
            "auto_merge": {"merge_method": "squash"},
        }
        data["repos/swarm-routing/beta/pulls/10/ccr/review_threads"] = []
        ns = parser().parse_args(["wait", "--merged", *extra, "beta#9", "--timeout", str(timeout)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = cmd_wait(
                    ns,
                    FakeGitHub(data),
                    sleep=lambda x: now.__setitem__(0, now[0] + x),
                    clock=lambda: now[0],
                )
            except Failure:
                rc = "failure"
        return rc, out.getvalue()

    queued = {"auto_merge": {"merge_method": "squash"}}
    rc, out = landed([queued, queued, dict(queued, merged=True)])
    check(
        "wait --merged: waits while queued, then merged",
        rc == 0 and out == "beta#9 ccccccc merged\n",
    )
    rc, out = landed([{"state": "closed"}])
    check("wait --merged: closed unmerged stops", rc == 1 and "stopped: closed unmerged" in out)
    rc, out = landed(
        [queued], threads_=[{"resolved": False, "path": "b.py", "line": 58, "comment_ids": [700]}]
    )
    check(
        "wait --merged: an unresolved thread stops, naming it",
        rc == 1
        and "1 unresolved thread(s), first: Minor · Add the missing failing fixtures." in out,
    )
    rc, out = landed([queued], runs=[dict(OK_RUN, conclusion="failure")])
    check(
        "wait --merged: a red required check stops", rc == 1 and "required check failed: ci" in out
    )
    rc, out = landed(
        [queued], runs=[OK_RUN, {"name": "sonar", "status": "completed", "conclusion": "failure"}]
    )
    check("…a red report-only check does not", rc == 2 and "timeout: not merged" in out)
    rc, out = landed([queued, {}])
    check(
        "wait --merged: auto-merge off (dropped from the queue) stops",
        rc == 1 and "auto-merge off" in out,
    )
    rc, out = landed([queued], timeout=60)
    check(
        "wait --merged: the timeout exits 2",
        rc == 2 and "beta#9 timeout: not merged after 60s" in out,
    )
    rc, out = landed([{}, {}, {"merged": True}], in_queue=True)
    check(
        "wait --merged: in the merge queue (auto_merge reads null there) it keeps waiting",
        rc == 0 and out.endswith("merged\n"),
    )
    rc, out = landed([{}, {"merged": True, "head": {"sha": "d" * 40}}])
    check(
        "wait --merged: merged between the PR read and the queue read is merged, not stopped, "
        "with the head that merged",
        rc == 0 and out == "beta#9 ddddddd merged\n",
    )
    rc, out = landed([queued], missing=True)
    check("wait --merged: a missing PR fails", rc == "failure")
    rc, out = landed([{"state": "closed"}], extra=["beta#10"])
    check(
        "wait --merged: one PR stopped while another is pending returns 1 at once",
        rc == 1 and "beta#9 ccccccc stopped: closed unmerged" in out and "beta#10" not in out,
    )
    rc, out = landed([dict(queued, merged=True)], extra=["--json"])
    got = json.loads(out)
    check(
        "wait --merged --json: merged as one list",
        rc == 0
        and got
        == [{"repo": "beta", "number": 9, "head": "c" * 40, "result": "merged", "detail": ""}],
    )
    rc, out = landed([{"state": "closed"}], extra=["--json"])
    check(
        "wait --merged --json: stopped",
        rc == 1
        and json.loads(out)[0]["result"] == "stopped"
        and json.loads(out)[0]["detail"] == "closed unmerged",
    )
    rc, out = landed([queued], timeout=60, extra=["--json"])
    check(
        "wait --merged --json: timeout",
        rc == 2 and json.loads(out)[0]["result"] == "timeout",
    )

    got, slept, err = rate_get(4000, 1100)
    check("rate: plenty left, no wait", got == [1] and slept == [] and err is None)
    got, slept, err = rate_get(100, 1100)
    check("rate: low, sleeps until the reset", got == [1] and slept == [101] and err is None)
    got, slept, err = rate_get(100, 5000)
    check("rate: low, reset far off: stops", err and "100 requests left" in err and slept == [])
    got, slept, err = rate_get(100, 1100, min_rate=50)
    check("rate: --min-rate lowers the threshold", slept == [] and err is None)
    check(
        "rate: --min-rate parses", parser().parse_args(["--min-rate", "50", "list"]).min_rate == 50
    )

    for f in failures:
        print(f"FAIL: {f}")
    print(f"pr_status.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
