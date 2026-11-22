#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Open the refresh PRs that keep every org repository in step with this one.

Usage:
  org_bot.py run [--task epics|org-sync|zenodo|swarm-core-pin|release-lock|release-rebuild|release-aftercare|bestpractices|release|hourly|all]
                 [--repos A,B] [--dry-run]
  org_bot.py --self-test

Seven tasks, each a generator or check this repository already has, run on a fresh clone
of each public repository (listed by `epics.py fetch`: the org listing, or
ROADMAP.md#epics where that listing is forbidden; the run prints which):

  epics     tools/epics/epics.py: the README's `## Epics` section, and in
            .github also ROADMAP.md#epics and the profile's open epics.
  org-sync  tools/org-sync/org_sync.py apply, in each repository with a
            .github/org-sync.toml. Sections the repository owns
            (`org_sync.py conflicts`) are never forced; the PR lists them,
            and the seeds the repository edited that differ from today's
            render (`org_sync.py seeds`), for information: the bot never
            changes an edited seed. A seed still exactly as the pinned
            templates rendered it is reseeded in the PR (`apply
            --reseed-untouched`, #615). The references to this repository's
            workflows and actions move with the lock's commit; in .github
            itself `org_sync.py refs` pins its own (ADR-0004, #716).
  zenodo    tools/zenodo/zenodo.py record --write, in each repository with a
            CITATION.cff: when Zenodo holds a concept for its releases (a
            record linking the newest tag) and CITATION.cff's `doi:` or
            org-sync's `zenodo_concept` does not name it yet (a first
            release made it), it writes them, then `org_sync.py apply`
            renders the README DOI badge and the citing section, so no DOI
            is typed by hand (#232). A concept named two ways fails that
            repository, for the maintainer. Zenodo is only read.

  swarm-core-pin  tools/checks/check-swarm-core-pin.py --bump, in each
            repository whose core/CMakeLists.txt pins swarm-core: when
            swarm-core main changed core/ since the pin, the old commit
            becomes main's on the pin lines only (#208; never in recorded
            results, docs or campaign plans, #407). Its PR lives on one branch,
            org-bot/swarm-core-pin, and is updated in place (pushed again, its
            body rewritten) when swarm-core moves on before it merges.
            With vcpkg.json (#489, vcpkg mode) the same PR also moves the
            swarm-core override and the swarm-routing/vcpkg-registry
            baseline, once the registry's main holds the new release (until
            its port PR merges the task proposes nothing).
            ORG_BOT_SWARM_CORE overrides swarm-core's URL,
            ORG_BOT_VCPKG_REGISTRY the registry's.
  release-lock  tools/checks/release_lock.py bump --write, in each repository
            with a root `<name>.lock` other than swarm-core.lock (that one is
            swarm-core-pin's, as its pin lines move with it) that
            release_lock.py parses, AntHocNet's ns3-tools.lock today (#478):
            when the repository the lock names has a newer release, the lock
            is moved to it, every value read from the release (the tag's
            commit, each asset's sha256 from its SHA256SUMS, the asset found
            by its hash in the locked release and named the same with the
            version moved); an asset the new release renamed or dropped fails
            that repository, for a person. Its PR lives on
            org-bot/release-lock, updated in place, and runs the consumer's
            CI like any PR: the merge queue lands it only when that CI is
            green, so a release that changes the consumer's outputs waits for
            a person. A lock that an open PR not from org-bot already changes
            (a hand bump) is left alone. A PR whose branch is behind its base
            and red is rebuilt on the base at the next run. Hourly (with
            `release`), daily (`all`) and on each org-release event.
            ORG_BOT_RELEASES overrides where releases are read from.

  release-aftercare  what a release leaves to record, once the bump PR merged
            (#465, #430, #428): for each repository whose newest GitHub
            release is younger than ORG_BOT_AFTERCARE_DAYS (default 14),
            tools/zenodo/zenodo.py shipped --write (docs/roadmap.md's shipped
            block, each release with its Zenodo version DOI, a release joining
            it only once Zenodo has archived it; CONTRIBUTING.md's version-DOI
            rows where it keeps them), and in .github `zenodo.py table
            CONTRIBUTING.md --write` (the archived-releases table). Every DOI
            is read from Zenodo, never typed. The PR gets auto-merge as any
            bot PR. Then tools/release/release_check.py after runs for that
            release, and what it still finds (WARN and FAIL lines) is posted
            as one comment, updated in place, on the site's
            `[release-sync] <name> <tag>` issue.
  bestpractices  the Go tool `bestpractices answers <clone> --slug swarm-routing/<repo>
            --write` (cmd/bestpractices, run from the ci-tools image's binary,
            ORG_BOT_BESTPRACTICES names it), in every public repository: the
            OpenSSF Best Practices answers its files show, as `.bestpractices.json`
            at the top level, regenerated so the weekly `bestpractices` check
            proposes them on bestpractices.dev (one Save per project, the site has
            no write API; #531, swarm-routing/AntHocNet#790). A PR only when the
            file changes; the newer PR supersedes an older one. Daily (`all`),
            and for one repository on its `bestpractices` repository_dispatch,
            sent by that repository's org-managed bestpractices-evidence.yml when
            a push to main touches the files the answers read.
  release-rebuild  no clone, the API only (#430): a repository whose open
            `bot/release` PR is behind its base gets its release caller (the
            workflow that calls reusable-release.yml) dispatched with mode
            `bump` again, as CONTRIBUTING's rule says, with the `increment`
            the PR was opened with (its body's `release-increment` line), so
            the PR is rebuilt on the new tip. Only the inputs the caller's
            `on: workflow_dispatch: inputs:` declares are sent. Never a first
            bump: only a PR the maintainer asked for is rebuilt; never while a
            run of that workflow is queued or running; never with a guessed
            increment (a PR whose body records none is left to a person).
  `release` runs both release tasks and release-lock (org-bot.yml, hourly,
  and for one repository on its `org-release` repository_dispatch, #479); `hourly`
  runs those and org-sync (the hourly schedule, so a deferred refresh lands, #505); `all`
  runs epics, org-sync, zenodo, swarm-core-pin, release-lock and bestpractices.

  org-sync and swarm-core-pin never leave two PRs that each fail the other's
  required check (#429: on 2026-11-14 every protocol repository held a pin
  bump red on `check / org-sync` and a template refresh red on `swarm-core /
  pin`). When either task changes a repository, the other generator runs on
  the same clone too; if it also changes something, both changes go in one PR
  on org-bot/swarm-core-pin (the pin task's fixed branch, updated in place),
  and the bot's open org-sync PR there is closed as superseded. A repository
  where only one of them changes anything gets that task's PR as before.
  release-lock carries the org-sync change the same way (its PR is never red on
  `check / org-sync`), but leaves the org-sync PR open: no check fails because
  a lock is behind, so the lock PR blocks nothing, and a lock bump red in the
  consumer's CI must never hold the template refresh back. Whichever lands
  first, the other's copy of those files is then no change.

Fan-out in bounded batches (#505): the refresh tasks that touch every
repository at once (epics, org-sync, bestpractices) open at most
ORG_BOT_BATCH new PRs (default 4) before a pause of ORG_BOT_BATCH_PAUSE
seconds (default 120, so the batch's runs reach the queue), then wait while
the org holds more than ORG_BOT_QUEUE_LIMIT queued workflow runs (default 10,
read from every public repository's `actions/runs?status=queued`). The run
waits ORG_BOT_BATCH_WAIT seconds at most (default 1800) in all; past that,
the PRs it has not opened are deferred, each named on its own line, and the
next run (hourly for org-sync, daily for the rest) proposes them. On
2026-11-16 22 refresh PRs opened at once held a release's publish job queued
for 19 minutes behind them. Updates in place and the release-driven tasks
(swarm-core-pin, release-lock, release-aftercare) are never held back.
ORG_BOT_BATCH=0 turns the throttle off.

When a run changes files, the bot opens one PR per repository and task:
- the branch is `org-bot/<task>-<hash of the change>`;
- the title is a lowercase Conventional Commit;
- the body says what was generated, from which run.

If that exact change is already open as a PR, nothing new is opened. An older
bot PR for the same task is closed as superseded, with a pointer to the new
one, so a repository has at most one open bot PR per task. CI runs on the PR
because it is opened with a personal or app token, not the workflow's own
GITHUB_TOKEN.

Where the base branch has a merge queue (a `merge_queue` rule, read from
`rules/branches/<base>`; repo-settings `merge_queue = true`, #128), the bot
enables auto-merge on its own PR (GraphQL `enablePullRequestAutoMerge`, the
REST API has none), so the PR enters the queue once its checks are green and
lands with no hand step (#178). Only on the PRs it opens from its `org-bot/`
branches, never on anyone else's. A repository without a merge queue is
logged and left to a person or an agent to merge when CI is green; so is a PR
whose auto-merge GitHub refuses (the line says why; the run goes on).

The token comes from ORG_BOT_TOKEN, never from the command line: the org
GitHub App's installation token when the workflow can make one (#21), else a
fine-grained token on the swarm-routing org with Contents, Pull requests,
Workflows (org-sync renders a workflow file), Actions (release-rebuild's
dispatch) and Issues (release-aftercare's comment) read and write. Commits are made
as ORG_BOT_GIT_NAME <ORG_BOT_GIT_EMAIL> when both are set (the App's
`<slug>[bot]` identity), else as github-actions[bot]. Without a token every
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
import time
import re
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EPICS = os.path.join(ROOT, "tools", "epics", "epics.py")
ORG_SYNC = os.path.join(ROOT, "tools", "org-sync", "org_sync.py")
ZENODO = os.path.join(ROOT, "tools", "zenodo", "zenodo.py")
PIN = os.path.join(ROOT, "tools", "checks", "check-swarm-core-pin.py")
LOCK_TOOL = os.path.join(ROOT, "tools", "checks", "release_lock.py")
RELEASE_CHECK = os.path.join(ROOT, "tools", "release", "release_check.py")
# the Go tool's binary (cmd/bestpractices), copied out of the ci-tools image by org-bot.yml
BESTPRACTICES = os.environ.get("ORG_BOT_BESTPRACTICES", "bestpractices")
SITE = (
    "swarm-routing.github.io"  # the site repository, where each release's [release-sync] issue is
)
AFTERCARE_MARK = "<!-- org-bot:release-aftercare -->"
# swarm-core's git URL for the swarm-core-pin task (a local path in the self-test)
SWARM_CORE = os.environ.get(
    "ORG_BOT_SWARM_CORE", "https://github.com/swarm-routing/swarm-adapter-ns3.git"
)
# where the task reads swarm-core's tags and release assets for a repository with a
# release lock, swarm-core.lock (swarm-routing/swarm-adapter-ns3#134; a file:// tree in
# the self-test)
SWARM_CORE_RELEASES = os.environ.get("ORG_BOT_SWARM_CORE_RELEASES", "https://github.com")
# the vcpkg registry the swarm-core-pin task moves a vcpkg-mode baseline to (#489)
VCPKG_REGISTRY = os.environ.get(
    "ORG_BOT_VCPKG_REGISTRY", "https://github.com/swarm-routing/vcpkg-registry.git"
)
# where the release-lock task reads every other lock's releases (#478)
RELEASES = os.environ.get("ORG_BOT_RELEASES", "https://github.com")
# the lock swarm-core-pin owns: its pin lines move with it
SWARM_CORE_LOCK = "swarm-core.lock"
# tasks whose PR lives on one branch, updated in place when the change moves on
FIXED_BRANCH = {"swarm-core-pin", "release-lock"}
# tasks whose PRs would each fail the other's required check: carried in one PR (#429)
PAIRED = {"org-sync": "swarm-core-pin", "swarm-core-pin": "org-sync"}
# a task that carries its partner's change too, leaving the partner's PR open (#478)
CARRY = {"release-lock": "org-sync"}
FANOUT = {"epics", "org-sync", "bestpractices"}  # throttled in batches (#505)
FAILED_RUN = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
ORG = "swarm-routing"
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
REUSABLE_RELEASE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?uses:[ \t]*swarm-routing/\.github/\.github/workflows/reusable-release\.yml@",
    re.M,
)
AUTO_MERGE = (
    "mutation($pr: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $pr}) "
    "{ clientMutationId } }"
)

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
    "swarm-core-pin": {
        "title": "chore(core): bump the swarm-core pin (org-bot)",
        "what": "This repository's swarm-core pin is behind, so its `swarm-core / pin` check "
        "fails on every PR until the pin follows (#208): with a commit pin, swarm-core "
        "`main` changed `core/`; with a release lock (`swarm-core.lock`, "
        "swarm-routing/swarm-adapter-ns3#134), a newer swarm-core release is out, and "
        "nothing happens between releases. Rewritten by swarm-routing/.github "
        "`tools/checks/check-swarm-core-pin.py --bump`: the old commit or tag becomes the "
        "new one on the pin lines only (`SWARM_CORE_REF` in `core/CMakeLists.txt` and the "
        "`Makefile`, or the lock written from the release, every value read from it; the "
        "workflows' `core-deps` and ns-3 dependency lines); recorded results, docs and "
        "campaign plans are never touched (#407). This repository's core tests and ns-3 "
        "suite run on this PR; when swarm-core moves again before it merges, the bot "
        "updates this PR in place.",
    },
    "release-lock": {
        "title": "chore(deps): bump the release locks (org-bot)",
        "what": "A repository this one locks by release (a root `<name>.lock` other than "
        "`swarm-core.lock`) published a newer release (#478). Moved by swarm-routing/.github "
        "`tools/checks/release_lock.py bump --write`: the tag, the commit it names, the "
        "version and each asset's sha256 are read from the new release (an asset is found by "
        "its hash in the locked release's `SHA256SUMS` and named the same in the new one, the "
        "version moved), never typed; every other line of the lock stays. This repository's "
        "CI judges the new release on this PR: where it changes an output a gate compares, "
        "the PR stays red and waits for a person (never merged around the gate). When the "
        "dependency releases again before this merges, the bot updates this PR in place.",
    },
    "release-aftercare": {
        "title": "docs: record the released versions and their zenodo dois (org-bot)",
        "what": "A release of this repository (or, in .github, of any org repository) is "
        "published and archived on Zenodo, and its record here is behind (#465, #430, #428). "
        "Written by swarm-routing/.github `tools/zenodo/zenodo.py shipped --write` "
        "(`docs/roadmap.md`'s shipped block; `CONTRIBUTING.md`'s version-DOI rows where it "
        "keeps them) or, in .github, `zenodo.py table CONTRIBUTING.md --write`; every DOI is "
        "the one Zenodo returned, never typed, and a release joins only once Zenodo has it.",
    },
    "bestpractices": {
        "title": "chore: regenerate .bestpractices.json (org-bot)",
        "what": "The OpenSSF Best Practices answers this repository's files show changed. "
        "Regenerated with swarm-routing/.github's `bestpractices answers . --write` "
        "(cmd/bestpractices): every passing criterion the repository gives evidence for, "
        "each justified by its full URL on `main`; owner-only criteria stay `?`. Once this "
        "merges, the weekly `bestpractices` check puts the proposal link for what "
        "bestpractices.dev lacks in the repository's `[bestpractices]` issue: the "
        "maintainer opens it, reviews and presses Save (the site has no write API).",
    },
    "zenodo": {
        "title": "docs: record the zenodo concept doi (org-bot)",
        "what": "Zenodo holds a concept for this repository's releases that CITATION.cff "
        "or `.github/org-sync.toml` does not name yet. Written by swarm-routing/.github "
        "`tools/zenodo/zenodo.py record --write` from the record Zenodo returned (never "
        "typed), then `tools/org-sync/org_sync.py apply` rendered the README DOI badge; "
        "the apply also carries any other template drift of this repository.",
    },
}


class Failure(SystemExit):
    pass


class Throttle:
    """Bounded batches for the fan-out tasks (#505): `admit()` before each new
    fan-out PR; after every `batch` of them, pause, then wait while the org's
    queue holds more than `limit` queued runs, `budget` seconds in all."""

    def __init__(self, gh, repos, sleep=time.sleep, clock=time.monotonic):
        env = os.environ.get
        self.gh, self.repos, self.sleep, self.clock = gh, list(repos), sleep, clock
        self.batch = int(env("ORG_BOT_BATCH") or 4)
        self.pause = float(env("ORG_BOT_BATCH_PAUSE") or 120)
        self.limit = int(env("ORG_BOT_QUEUE_LIMIT") or 10)
        self.budget = float(env("ORG_BOT_BATCH_WAIT") or 1800)
        self.opened = self.waited = 0
        self.spent = 0.0
        self.closed = ""  # why later fan-out PRs are deferred, once the budget is spent

    def queued(self):
        n = 0
        for repo in self.repos:
            try:
                got = self.gh.api(
                    "GET", f"repos/{ORG}/{repo}/actions/runs?status=queued&per_page=1"
                )
            except Failure:
                continue  # one unreadable repository never stops the fan-out
            n += int(got.get("total_count") or 0) if isinstance(got, dict) else 0
        return n

    def _sleep(self, seconds):
        start = self.clock()
        self.sleep(seconds)
        self.spent += self.clock() - start

    def admit(self):
        """None to go ahead, else why this PR is deferred."""
        if self.batch <= 0:
            return None
        if self.closed:
            return self.closed
        if self.opened and self.opened % self.batch == 0 and self.waited != self.opened:
            self.waited = self.opened
            self._sleep(min(self.pause, max(0.0, self.budget - self.spent)))
            while True:
                q = self.queued()
                if q <= self.limit:
                    print(
                        f"org-bot: batch of {self.batch} opened; {q} runs queued in the org, next batch"
                    )
                    break
                if self.spent >= self.budget:
                    self.closed = (
                        f"deferred: {q} runs queued in the org after {self.spent / 60:.0f} min of "
                        f"waiting (limit {self.limit}, #505); the next run proposes it"
                    )
                    return self.closed
                self._sleep(min(60.0, self.budget - self.spent))
        return None

    def done(self):
        self.opened += 1


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

    def graphql(self, query, **variables):
        cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
        for k, v in variables.items():
            cmd += ["-f", f"{k}={v}"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
        if r.returncode != 0:
            raise Failure(f"gh api graphql: {r.stderr.strip() or r.stdout.strip()}")
        return json.loads(r.stdout) if r.stdout.strip() else {}


def identity():
    """(name, email) to commit as: the App's bot when both are given, else BOT."""
    name, email = os.environ.get("ORG_BOT_GIT_NAME"), os.environ.get("ORG_BOT_GIT_EMAIL")
    return (name, email) if name and email else BOT


def git_env(token):
    name, email = identity()
    env = dict(
        os.environ,
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=email,
        GIT_COMMITTER_NAME=name,
        GIT_COMMITTER_EMAIL=email,
    )
    if token:
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {cred}",
        )
    return env


# org_sync.py apply's template pin (#586): which swarm-routing/.github commit
# rendered a change is not part of the change, so a new commit here that
# renders the same text keeps the open refresh PR instead of replacing it
ORG_SYNC_LOCK = ".github/org-sync.lock"
LOCK_COMMIT = re.compile(r'^([+-]?commit = ")[0-9a-f]{40}"', re.M)


def branch_for(task, diff):
    if task in FIXED_BRANCH:
        return f"org-bot/{task}"
    diff = LOCK_COMMIT.sub(r'\1<pin>"', diff)
    return f"org-bot/{task}-{hashlib.sha256(diff.encode()).hexdigest()[:8]}"


def branch_has(clone, branch, env):
    """True when the PR branch already holds every file this run changed, as
    generated: main may have gained a file that names the old pin since the
    branch was pushed, and then the branch needs the refresh too (#208)."""
    if sh(
        ["git", "-C", clone, "fetch", "-q", "--depth", "1", "origin", branch], env=env, check=False
    ).returncode:
        return False
    changed = sh(["git", "-C", clone, "diff", "--name-only"], env=env).stdout.split()
    changed += sh(
        ["git", "-C", clone, "ls-files", "--others", "--exclude-standard"], env=env
    ).stdout.split()
    for path in changed:
        theirs = sh(["git", "-C", clone, "show", f"FETCH_HEAD:{path}"], env=env, check=False)
        if path == ORG_SYNC_LOCK and not theirs.returncode:
            continue  # an older template pin with the same render (#586)
        with open(os.path.join(clone, path), encoding="utf-8", errors="replace") as fh:
            if theirs.returncode or theirs.stdout != fh.read():
                return False
    return True


def pin_target(notes):
    """What a fixed-branch PR moves to: the `pin-target: <sha>` line check-swarm-core-pin.py
    --bump printed, or release_lock.py bump's `lock-target: <lock>@<tag>` lines, or None."""
    got = []
    for note in notes:
        for line in (note or "").splitlines():
            if line.startswith(("pin-target:", "lock-target:")):
                got.append(line.split(":", 1)[1].strip())
    return " ".join(got) or None


def lock_files(clone):
    """The root locks the release-lock task moves: `<name>.lock` files release_lock.py
    parses, swarm-core.lock (swarm-core-pin's) and other formats (protocols.lock) left out."""
    sys.path.insert(0, os.path.dirname(LOCK_TOOL))
    import release_lock

    found = []
    for name in sorted(os.listdir(clone)):
        path = os.path.join(clone, name)
        if not name.endswith(".lock") or name == SWARM_CORE_LOCK or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                release_lock.parse_text(fh.read(), name)
        except (release_lock.LockError, UnicodeDecodeError):
            continue
        found.append(name)
    return found


def may_lock(gh, full):
    """False when the repository's root lists no `<name>.lock` but swarm-core.lock, so the
    release-lock task need not clone it; True when it does or the listing is unreadable."""
    try:
        entries = gh.api("GET", f"repos/{full}/contents")
    except Failure:
        return True
    if not isinstance(entries, list):
        return True
    return any(
        e.get("name", "").endswith(".lock") and e.get("name") != SWARM_CORE_LOCK
        for e in entries
        if isinstance(e, dict)
    )


def pages(gh, path, limit=10):
    """Every item of a paged list (100 a page, at most `limit` pages; GitHub lists a
    PR's first 3000 files)."""
    items = []
    for page in range(1, limit + 1):
        got = gh.api("GET", f"{path}&page={page}") or []
        if not isinstance(got, list):
            break
        items += got
        if len(got) < 100:
            break
    return items


def held_locks(gh, full, locks):
    """{lock: why} for each lock an open PR not from org-bot already changes (a hand
    bump, #478): the task leaves those alone rather than open a competing PR."""
    held = {}
    prs = pages(gh, f"repos/{full}/pulls?state=open&per_page=100")
    if len(prs) >= 1000:  # the list may go on: fail closed, never a competing PR
        return {lock: "1000+ open PRs, not all read" for lock in locks}
    for p in prs:
        if p["head"]["ref"].startswith("org-bot/"):
            continue
        files = pages(gh, f"repos/{full}/pulls/{p['number']}/files?per_page=100", 30)
        if len(files) >= 3000:  # GitHub lists a PR's first 3000 files: it may change a lock
            for lock in locks:
                held.setdefault(lock, f"#{p['number']} changes 3000+ files, not all listed")
        for f in files:
            name = f.get("filename") if isinstance(f, dict) else None
            if name in locks and name not in held:
                held[name] = f"#{p['number']} changes it ({p.get('title') or ''})"
    return held


def stale_red(gh, full, base, pr):
    """The bot's fixed-branch PR is behind `base` and a check failed on its head: rebuilt
    on the base, so a red that main fixed since (a template, a gate) is not kept."""
    branch = pr["head"]["ref"]
    try:
        cmp = gh.api("GET", f"repos/{full}/compare/{base}...{branch}") or {}
        if not cmp.get("behind_by"):
            return False
        sha = pr["head"].get("sha") or branch
        runs = gh.api("GET", f"repos/{full}/commits/{sha}/check-runs?per_page=100") or {}
    except Failure:
        return False
    return any(r.get("conclusion") in FAILED_RUN for r in runs.get("check_runs") or [])


def apply_failed(returncode, stderr):
    """org_sync.py apply: 0 is clean, 1 with a quiet stderr is owned sections left alone."""
    return returncode > 1 or (returncode == 1 and bool(stderr.strip()))


def generate(task, repo, clone, data, out, skip=None):
    """Run the task's generator in `clone`; return the lines it printed. `skip`
    (release-lock): {lock: why} for locks left alone."""
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
    elif task == "swarm-core-pin":
        cmake = os.path.join(clone, "core", "CMakeLists.txt")
        if not os.path.exists(cmake):
            return None
        with open(cmake) as fh:
            text = fh.read()
        locked = os.path.exists(os.path.join(clone, SWARM_CORE_LOCK))
        if "SWARM_CORE_REF" not in text and "swarm-core.lock" not in text and not locked:
            return None  # no swarm-core pin in this repository
        r = sh(
            [sys.executable, "-I", PIN, "--bump", "--swarm-core", SWARM_CORE]
            + ["--releases", SWARM_CORE_RELEASES, "--registry", VCPKG_REGISTRY],
            cwd=clone,
            check=False,
        )
        if r.returncode:
            raise Failure(f"check-swarm-core-pin.py --bump: {r.stdout.strip() or r.stderr.strip()}")
        out.append(r.stdout.strip())
        return out
    elif task == "release-lock":
        locks = lock_files(clone)
        if not locks:
            return None
        for lock in locks:
            if lock in (skip or {}):
                out.append(f"{lock}: left alone, {skip[lock]}")
                print(f"{repo} release-lock: {lock} left alone, {skip[lock]}")
                continue
            r = sh(
                [sys.executable, "-I", LOCK_TOOL, "bump", lock, "--write", "--base", RELEASES],
                cwd=clone,
                check=False,
            )
            if r.returncode:
                raise Failure(
                    f"release_lock.py bump {lock}: {r.stdout.strip() or r.stderr.strip()}"
                )
            out.append(r.stdout.strip())
        return out
    elif task == "release-aftercare":
        if repo == ".github":
            cmd = [sys.executable, "-I", ZENODO, "table", os.path.join(clone, "CONTRIBUTING.md")]
        else:
            if not os.path.exists(os.path.join(clone, "CITATION.cff")):
                return None
            cmd = [sys.executable, "-I", ZENODO, "shipped", "--repo", f"{ORG}/{repo}"]
            cmd += ["--checkout", clone]
        r = sh(cmd + ["--write"], check=False)
        if r.returncode:
            raise Failure(f"zenodo.py: {r.stderr.strip() or r.stdout.strip()}")
        out.append(r.stdout.strip())
        return out
    elif task == "bestpractices":
        r = sh(
            [BESTPRACTICES, "answers", clone, "--slug", f"{ORG}/{repo}", "--write"],
            check=False,
        )
        if r.returncode:
            raise Failure(f"bestpractices answers: {r.stderr.strip() or r.stdout.strip()}")
        # intent-to-add: a new file's content is in `git diff`, so the branch name
        # (a hash of the diff) changes with it and a changed file is a new PR
        sh(["git", "-C", clone, "add", "-N", ".bestpractices.json"])
        # its stderr: the file written, then the count by status
        out.append(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "")
        return out
    elif task == "zenodo":
        if not os.path.exists(os.path.join(clone, "CITATION.cff")):
            return None
        r = sh(
            [sys.executable, "-I", ZENODO, "record", "--repo", f"{ORG}/{repo}"]
            + ["--checkout", clone, "--write"],
            check=False,
        )
        if r.returncode:
            raise Failure(f"zenodo.py record: {r.stderr.strip() or r.stdout.strip()}")
        out.append(r.stdout.strip())
        changed = sh(["git", "-C", clone, "status", "--porcelain"]).stdout.strip()
        if not changed or not os.path.exists(os.path.join(clone, ".github", "org-sync.toml")):
            return out
        cmds = [[sys.executable, "-I", ORG_SYNC, "apply", clone]]  # the badge, the citing section
    else:
        if not os.path.exists(os.path.join(clone, ".github", "org-sync.toml")):
            return None
        # orphan blocks (#235) go too, and a seed the repository never edited takes
        # today's render (#615): both proposed in this reviewed PR
        cmds = [
            [sys.executable, "-I", ORG_SYNC, "apply", clone, "--prune-orphans"]
            + ["--reseed-untouched"]
        ]
        if repo == ".github":
            # its reusable workflows call its own actions and workflows: pinned
            # by commit too, at the newest commit that changed them (#716)
            cmds.append([sys.executable, "-I", ORG_SYNC, "refs", clone])
    for c in cmds:
        # org_sync.py apply exits 1 when sections the repository owns differ (it
        # leaves them and lists them on stdout); only a crash writes to stderr.
        r = sh(c, check=task == "epics")
        if task != "epics" and apply_failed(r.returncode, r.stderr):
            raise Failure(f"org_sync.py apply: {r.stderr.strip() or r.stdout.strip()}")
        out.append(r.stdout.strip())
    if task == "org-sync":
        r = sh([sys.executable, "-I", ORG_SYNC, "conflicts", clone], check=False)
        if r.stdout.strip():
            out.append("conflicts left to the repository:\n" + r.stdout.strip())
        # a seed the repository edited is its own: listed for information, never
        # changed (#91, #615); the untouched ones were reseeded by apply above
        r = sh([sys.executable, "-I", ORG_SYNC, "seeds", clone], check=False)
        differ = [ln for ln in r.stdout.splitlines() if ln.startswith(("differs", "missing"))]
        if differ:
            out.append(
                "seeds the repository edited, differing from today's render (its own, not "
                "changed here; `org_sync.py reseed FILE` takes the template):\n" + "\n".join(differ)
            )
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
        "superseded. Where `main` has a merge queue, auto-merge is on and it lands once "
        "green; elsewhere merge it when CI is green.",
    ]
    return "\n".join(lines)


def queue(gh, full, base, pr):
    """Auto-merge for the bot's own PR `pr` where `base` has a merge queue, so it
    enters the queue once green; the note to print."""
    if not pr["head"]["ref"].startswith("org-bot/"):  # never anyone else's PR
        raise Failure(f"#{pr['number']}: not an org-bot branch, auto-merge left alone")
    if pr.get("auto_merge"):
        return "auto-merge already on"
    ref = urllib.parse.quote(base, safe="")
    try:
        rules = gh.api("GET", f"repos/{full}/rules/branches/{ref}?per_page=100")
    except Failure as e:
        return f"merge queue unknown ({e}): merge by hand once green"
    if not any(r.get("type") == "merge_queue" for r in rules):
        return f"no merge queue on {base}: merge by hand once green"
    try:
        gh.graphql(AUTO_MERGE, pr=pr["node_id"])
    except Failure as e:
        return f"auto-merge NOT enabled ({e}): merge by hand once green"
    return "auto-merge on: enters the merge queue once green"


def supersede(gh, full, olds, number):
    """Close the bot's older PRs `olds` as superseded by #number, deleting their branches."""
    for old in olds:
        gh.api(
            "POST",
            f"repos/{full}/issues/{old['number']}/comments",
            {"body": f"Superseded by #{number}, which carries the newer generated change."},
        )
        gh.api("PATCH", f"repos/{full}/pulls/{old['number']}", {"state": "closed"})
        delete_branch(gh, full, old["head"]["ref"])


def delete_branch(gh, full, branch):
    """Delete a bot branch; one already gone (its PR merged and the branch was
    auto-deleted between the listing and now, as two runs racing on an epic
    burst can make it) is not a failure (#572)."""
    try:
        gh.api("DELETE", f"repos/{full}/git/refs/heads/{branch}")
    except Failure as e:
        if "Reference does not exist" not in str(e):
            raise


def close_stale(gh, repo, task, notes, dry_run):
    """Nothing to bump (every lock current, or held by a hand PR): an open bot PR on the
    task's fixed branch carries a bump that must not merge beside the hand PR, so it is
    closed (#478)."""
    full = f"{ORG}/{repo}"
    branch = branch_for(task, "")
    held = [n for n in notes if n and " left alone, " in n]
    if dry_run:
        print(f"{repo} {task}: up to date")
        return None
    mine = [
        p
        for p in pages(gh, f"repos/{full}/pulls?state=open&per_page=100")
        if p["head"]["ref"] == branch and p["head"].get("repo", {}).get("full_name", full) == full
    ]
    for p in mine:
        why = "; ".join(held) or "every lock is already on its newest release"
        gh.api(
            "POST",
            f"repos/{full}/issues/{p['number']}/comments",
            {"body": f"Closed by org-bot: nothing left for it to bump ({why})."},
        )
        gh.api("PATCH", f"repos/{full}/pulls/{p['number']}", {"state": "closed"})
        delete_branch(gh, full, branch)
    print(f"{repo} {task}: up to date{closed_note(mine).replace('superseded', 'stale')}")
    return {"number": None, "closed": [p["number"] for p in mine]} if mine else None


def branch_only(clone, branch, env):
    """The fetched PR branch changes no file beyond this run's change: a lock dropped
    from the bump (held by a hand PR since) makes the branch stale (#478)."""
    if sh(
        ["git", "-C", clone, "fetch", "-q", "--depth", "1", "origin", branch], env=env, check=False
    ).returncode:
        return False
    theirs = set(
        sh(["git", "-C", clone, "diff", "--name-only", "HEAD", "FETCH_HEAD"]).stdout.split()
    )
    ours = set(sh(["git", "-C", clone, "diff", "--name-only"]).stdout.split())
    ours |= set(
        sh(["git", "-C", clone, "ls-files", "--others", "--exclude-standard"]).stdout.split()
    )
    return theirs <= ours


def propose(gh, repo, task, clone, notes, env, dry_run, run_url, also=(), throttle=None):
    """One PR for the change in `clone`, unless the same change is already open.
    `also`: other tasks whose open bot PRs this one carries, closed as superseded (#429).
    `throttle`: a new fan-out PR waits for its batch, or is deferred (#505)."""
    diff = sh(["git", "-C", clone, "diff"]).stdout
    status = sh(["git", "-C", clone, "status", "--porcelain"]).stdout
    if not status.strip():
        if task == "release-lock":
            return close_stale(gh, repo, task, notes, dry_run)
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
        if (p["head"]["ref"].startswith(f"org-bot/{task}-") or p["head"]["ref"] == branch)
        and p["head"].get("repo", {}).get("full_name", full) == full
    ]
    same = [p for p in mine if p["head"]["ref"] == branch]
    carried = [
        p
        for p in open_prs
        if any(p["head"]["ref"].startswith(f"org-bot/{t}") for t in also)
        and p["head"].get("repo", {}).get("full_name", full) == full
    ]
    target = pin_target(notes) if task in FIXED_BRANCH else None
    if target and not same and task == "swarm-core-pin":
        # someone already opened a bump to this commit by hand: no duplicate (#208)
        hand = [
            p
            for p in open_prs
            if p not in mine
            and "swarm-core pin" in (p.get("title") or "")
            and target[:7] in (p.get("title") or "") + (p.get("body") or "")
        ]
        if hand:
            print(f"{repo} {task}: already proposed by hand in #{hand[0]['number']}")
            return {"number": hand[0]["number"], "branch": None, "hand": True}
    base = gh.api("GET", f"repos/{full}")["default_branch"]
    if same and task in FIXED_BRANCH:
        # one PR per repository, refreshed in place (#208): unchanged when it
        # already carries this target, else the branch is pushed again
        if (
            target
            and target in (same[0].get("body") or "")
            and branch_has(clone, branch, env)
            and not (
                task == "release-lock"
                and (not branch_only(clone, branch, env) or stale_red(gh, full, base, same[0]))
            )
        ):
            supersede(gh, full, carried, same[0]["number"])
            note = queue(gh, full, base, same[0])
            print(
                f"{repo} {task}: already proposed in #{same[0]['number']}{closed_note(carried)}; {note}"
            )
            return {"number": same[0]["number"], "branch": branch, "queue": note}
        number = same[0]["number"]
        sh(["git", "-C", clone, "checkout", "-q", "-b", branch], env=env)
        sh(["git", "-C", clone, "add", "-A"], env=env)
        msg = f"{TASKS[task]['title']}\n\nGenerated by swarm-routing/.github tools/org-bot ({run_url or 'local run'})."
        sh(["git", "-C", clone, "commit", "-q", "-m", msg], env=env)
        sh(["git", "-C", clone, "push", "-q", "origin", f"+HEAD:refs/heads/{branch}"], env=env)
        gh.api(
            "PATCH",
            f"repos/{full}/pulls/{number}",
            {"title": TASKS[task]["title"], "body": pr_body(task, notes, run_url)},
        )
        supersede(gh, full, carried, number)
        note = queue(gh, full, base, same[0])
        print(f"{repo} {task}: updated #{number} on {branch}{closed_note(carried)}; {note}")
        return {"number": number, "branch": branch, "queue": note, "updated": True}
    if same:
        note = queue(gh, full, base, same[0])
        print(f"{repo} {task}: already proposed in #{same[0]['number']}; {note}")
        return {"number": same[0]["number"], "branch": branch, "queue": note}
    if throttle is not None and task in FANOUT:
        why = throttle.admit()
        if why:
            print(f"{repo} {task}: {why}")
            return {"branch": branch, "deferred": True}
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
    if throttle is not None and task in FANOUT:
        throttle.done()
    supersede(gh, full, mine + carried, pr["number"])
    closed = closed_note(mine + carried)
    note = queue(gh, full, base, {**pr, "head": {"ref": branch}})
    print(f"{repo} {task}: opened #{pr['number']} from {branch}{closed}; {note}")
    return {"number": pr["number"], "branch": branch, "queue": note}


def newest_release(gh, full):
    """(tag, published) of the newest published, non-prerelease release, or None."""
    rels = gh.api("GET", f"repos/{full}/releases?per_page=20") or []
    rels = [
        r for r in rels if not r.get("draft") and not r.get("prerelease") and r.get("published_at")
    ]
    if not rels:
        return None
    r = max(rels, key=lambda r: r["published_at"])
    return r["tag_name"], r["published_at"]


def recent(published, days, now=None):
    import datetime

    now = now or datetime.datetime.now(datetime.timezone.utc)
    when = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
    return (now - when).total_seconds() < days * 86400


def leftovers(gh, repo, tag, pr, dry_run, run_url):
    """release_check.py after's WARN and FAIL lines, posted on the site's release-sync issue."""
    r = sh(
        [sys.executable, "-I", RELEASE_CHECK, "after", f"{ORG}/{repo}", "--tag", tag],
        env=gh.env,
        check=False,
    )
    left = [
        ln
        for ln in r.stdout.splitlines()
        if ln.startswith(("WARN", "FAIL")) and "see above" not in ln
    ]
    if r.returncode > 1:
        left.append(f"FAIL  release_check.py after: {(r.stderr.strip() or 'crashed')[:300]}")
    mine = ""
    if pr and pr.get("number"):
        mine = f"\nThe record (roadmap shipped, DOI rows): {ORG}/{repo}#{pr['number']}, auto-merge where the repository has a merge queue.\n"
    body = "\n".join(
        [
            AFTERCARE_MARK,
            f"### Release aftercare: {repo} {tag}",
            "",
            f"`tools/release/release_check.py after {ORG}/{repo} --tag {tag}`, run by org-bot's "
            f"`release-aftercare` task ({run_url or 'a local run'}); updated in place each hour "
            "while the release is recent.",
            "",
            *([f"- `{ln}`" for ln in left] or ["Nothing left: every check passed."]),
            mine,
        ]
    )
    want = f"[release-sync] {repo} {tag}"
    hit = []
    for page in range(1, 11):  # newest first; PRs share the listing, so page on
        issues = (
            gh.api(
                "GET",
                f"repos/{ORG}/{SITE}/issues?state=all&sort=created&direction=desc"
                f"&per_page=100&page={page}",
            )
            or []
        )
        hit = [
            i for i in issues if (i.get("title") or "").strip() == want and "pull_request" not in i
        ]
        if hit or len(issues) < 100:
            break
    if not hit:
        print(f"{repo} release-aftercare: {len(left)} left; no '{want}' issue yet")
        return {"left": left, "issue": None}
    n = hit[0]["number"]
    comments = gh.api("GET", f"repos/{ORG}/{SITE}/issues/{n}/comments?per_page=100") or []
    old = [c for c in comments if AFTERCARE_MARK in (c.get("body") or "")]
    if old and old[0]["body"].strip() == body.strip():
        print(f"{repo} release-aftercare: {len(left)} left, {SITE}#{n} already says so")
    elif dry_run:
        print(
            f"{repo} release-aftercare: {len(left)} left; would {'update' if old else 'post'} on {SITE}#{n}"
        )
    elif old:
        gh.api("PATCH", f"repos/{ORG}/{SITE}/issues/comments/{old[0]['id']}", {"body": body})
        print(f"{repo} release-aftercare: {len(left)} left; updated the comment on {SITE}#{n}")
    else:
        gh.api("POST", f"repos/{ORG}/{SITE}/issues/{n}/comments", {"body": body})
        print(f"{repo} release-aftercare: {len(left)} left; posted on {SITE}#{n}")
    return {"left": left, "issue": n}


def dispatch_inputs(text):
    """The input names under `on: workflow_dispatch: inputs:`, read by indentation."""
    lines, names = text.splitlines(), []

    def ind(ln):
        return len(ln) - len(ln.lstrip(" "))

    for i, ln in enumerate(lines):
        if ln.strip() not in ("workflow_dispatch:", "workflow_dispatch: {}"):
            continue
        base = ind(ln)
        for k in range(i + 1, len(lines)):
            if not lines[k].strip() or lines[k].lstrip().startswith("#"):
                continue
            if ind(lines[k]) <= base:
                break
            if lines[k].strip() == "inputs:":
                at = ind(lines[k])
                for m in range(k + 1, len(lines)):
                    t = lines[m]
                    if not t.strip() or t.lstrip().startswith("#"):
                        continue
                    if ind(t) <= at:
                        break
                    hit = re.match(r"^ *([A-Za-z0-9_-]+):", t)
                    if hit and (not names or ind(t) == names[0][1]):
                        names.append((hit.group(1), ind(t)))
                break
        break
    return {n for n, _ in names}


INCREMENT_MARK = re.compile(r"<!-- release-increment: (auto|PATCH|MINOR|MAJOR) -->")


def rebuild(gh, repo, dry_run):
    """Dispatch bump again where the open bot/release PR is behind its base (#430)."""
    full = f"{ORG}/{repo}"
    pulls = gh.api("GET", f"repos/{full}/pulls?state=open&head={ORG}:bot/release&per_page=10") or []
    pulls = [p for p in pulls if p["head"]["ref"] == "bot/release"]
    if not pulls:
        return None
    pr = pulls[0]
    base = pr["base"]["ref"]
    behind = (gh.api("GET", f"repos/{full}/compare/{base}...bot/release") or {}).get("behind_by", 0)
    if not behind:
        print(f"{repo} release-rebuild: bump PR #{pr['number']} is on {base}")
        return {"number": pr["number"], "behind": 0}
    caller, text = None, ""
    for entry in gh.api("GET", f"repos/{full}/contents/.github/workflows?ref={base}") or []:
        if not entry.get("name", "").endswith((".yml", ".yaml")):
            continue
        got = gh.api("GET", f"repos/{full}/contents/{entry['path']}?ref={base}") or {}
        body = base64.b64decode(got.get("content", "")).decode("utf-8", "replace")
        if REUSABLE_RELEASE.search(body):
            caller, text = entry["name"], body
            break
    if not caller:
        print(
            f"{repo} release-rebuild: #{pr['number']} is {behind} behind, no reusable-release caller: dispatch bump by hand"
        )
        return {"number": pr["number"], "behind": behind, "caller": None}
    # an active run on any page: one status-filtered count per active status
    for status in ("queued", "in_progress", "waiting", "requested", "pending"):
        runs = (
            gh.api(
                "GET", f"repos/{full}/actions/workflows/{caller}/runs?status={status}&per_page=1"
            )
            or {}
        )
        if runs.get("total_count") or runs.get("workflow_runs"):
            print(
                f"{repo} release-rebuild: #{pr['number']} is {behind} behind; a {caller} run is still {status}"
            )
            return {"number": pr["number"], "behind": behind, "caller": caller, "busy": True}
    declared = dispatch_inputs(text)
    inputs = {}
    if "mode" in declared:
        inputs["mode"] = "bump"
    if "increment" in declared:
        m = INCREMENT_MARK.search(pr.get("body") or "")
        if not m:  # opened before the marker: the size asked for is unknown, so never guessed
            print(
                f"{repo} release-rebuild: #{pr['number']} is {behind} behind, and its body records "
                "no release-increment: dispatch bump by hand with the increment it was opened with"
            )
            return {"number": pr["number"], "behind": behind, "caller": caller, "unknown": True}
        inputs["increment"] = m.group(1)
    what = f"{caller} mode bump" + (
        f", increment {inputs['increment']}" if "increment" in inputs else ""
    )
    if dry_run:
        print(
            f"{repo} release-rebuild: #{pr['number']} is {behind} behind {base}; would dispatch {what}"
        )
        return {"number": pr["number"], "behind": behind, "caller": caller, "dry_run": True}
    gh.api(
        "POST",
        f"repos/{full}/actions/workflows/{caller}/dispatches",
        {"ref": base, "inputs": inputs},
    )
    print(f"{repo} release-rebuild: #{pr['number']} is {behind} behind {base}; dispatched {what}")
    return {"number": pr["number"], "behind": behind, "caller": caller, "inputs": inputs}


def closed_note(prs):
    return f"; closed {', '.join('#' + str(o['number']) for o in prs)} as superseded" if prs else ""


def snapshot(clone):
    """The clone's working-tree change, to tell whether a generator changed anything."""
    return (
        sh(["git", "-C", clone, "diff"]).stdout
        + sh(["git", "-C", clone, "status", "--porcelain"]).stdout
    )


def pair(task, repo, clone, data, notes):
    """#429: after `task` changed the clone, run its partner on the same clone. Returns
    (task to propose under, notes, tasks whose open PRs this one carries)."""
    partner = PAIRED.get(task) or CARRY.get(task)
    if not partner or not snapshot(clone).strip():
        return task, notes, ()
    before = snapshot(clone)
    # the tree as the task left it, so a partner that fails half-way is undone
    # exactly, the task's own change kept
    sh(["git", "-C", clone, "add", "-A"])
    tree = sh(["git", "-C", clone, "write-tree"]).stdout.strip()
    sh(["git", "-C", clone, "reset", "-q"])
    try:
        extra = generate(partner, repo, clone, data, [])
    except Failure as e:  # the partner's own run reports it; this PR goes on alone
        sh(["git", "-C", clone, "read-tree", tree])
        sh(["git", "-C", clone, "checkout-index", "-a", "-f"])
        sh(["git", "-C", clone, "clean", "-qfd"])
        sh(["git", "-C", clone, "reset", "-q"])
        return task, notes + [f"{partner} not carried: {e}"], ()
    if extra is None or snapshot(clone) == before:
        return task, notes, ()
    if task in CARRY:
        head = (
            f"This PR also carries the {partner} change, so `check / org-sync` does not hold "
            f"it; the {partner} PR stays open, and whichever lands first leaves the other's "
            "copy of those files no change (#478):"
        )
        return task, notes + [head] + extra, ()
    head = (
        f"This PR also carries the {partner} change (#429), so neither required check "
        "(`check / org-sync`, `swarm-core / pin`) holds it:"
    )
    notes = notes + [head] + extra
    # one PR on the pin task's fixed branch, updated in place; the open org-sync PR closes
    return "swarm-core-pin", notes, ("org-sync",)


def run(args, gh=None, clone_url=None):
    token = os.environ.get("ORG_BOT_TOKEN") or None
    dry_run = args.dry_run or not token
    if not token and not args.dry_run:
        print("org-bot: ORG_BOT_TOKEN is not set; dry run")
    gh = gh or GitHub(token)
    clone_url = clone_url or "https://github.com/{org}/{repo}.git"
    groups = {
        "all": ["epics", "org-sync", "zenodo", "swarm-core-pin", "release-lock", "bestpractices"],
        "release": ["release-rebuild", "release-aftercare", "release-lock"],
        # the hourly run: the release tasks, and org-sync, so a refresh the
        # throttle deferred lands within the hour (#505)
        "hourly": ["release-rebuild", "release-aftercare", "release-lock", "org-sync"],
    }
    tasks = groups.get(args.task, [args.task])
    days = float(os.environ.get("ORG_BOT_AFTERCARE_DAYS") or 14)
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        )
    work = tempfile.mkdtemp(prefix="org-bot-")
    data = os.path.join(work, "epics.json")
    # A run with the epics task fetches every public repository's epics:
    # .github's ROADMAP and profile list them all, so a run limited by --repos
    # must not regenerate them from part of the data (it would delete the other
    # repositories' sections). org-sync reads no epic data, so an org-sync-only
    # run fetches just the repositories it touches.
    if args.data:
        shutil.copy(args.data, data)
    else:
        fetch = [sys.executable, "-I", EPICS, "fetch", "--out", data]
        if args.repos and "epics" not in tasks:
            fetch += ["--repos", args.repos]
        # epics.py says on stderr where the repository list came from (the org
        # listing, or ROADMAP.md#epics where that listing is forbidden, #175)
        source = sh(fetch, env=gh.env).stderr.strip()
        if source:
            print(f"org-bot: {source}")
    repos = [r["name"] for r in json.load(open(data))["repos"]]  # public, not archived, not forks
    throttle = None if dry_run else Throttle(gh, repos)  # the whole org's queue (#505)
    if args.repos:
        wanted = [n.strip() for n in args.repos.split(",") if n.strip()]
        unknown = sorted(set(wanted) - set(repos))
        if unknown:
            # not named: a private repository's name never reaches the public log (#622)
            raise Failure(
                f"org-bot: {len(unknown)} named repositories are not public org repositories "
                "(a typo, or a private, archived or forked one)"
            )
        repos = [r for r in repos if r in wanted]
    env = git_env(None if dry_run else token)
    results, failed = [], []
    released = {}  # repo -> its recent release's tag, for release-aftercare
    if "release-aftercare" in tasks:
        for repo in repos:
            try:
                got = newest_release(gh, f"{ORG}/{repo}") if repo != ".github" else None
            except Failure as e:
                print(f"{repo} release-aftercare: releases unreadable ({e})")
                continue
            if got and recent(got[1], days):
                released[repo] = got[0]
        if released and ".github" in repos:
            released[".github"] = None  # the org's archived-releases table
        print(
            f"org-bot: release-aftercare: releases younger than {days:g} days: "
            + (", ".join(f"{r} {t}" for r, t in released.items() if t) or "none")
        )
    for repo in repos:
        clone = os.path.join(work, repo)
        try:
            if "release-rebuild" in tasks:
                results.append((repo, "release-rebuild", rebuild(gh, repo, dry_run)))
            mine = [
                t
                for t in tasks
                if t != "release-rebuild"
                and (t != "release-aftercare" or repo in released)
                and (t != "release-lock" or may_lock(gh, f"{ORG}/{repo}"))
            ]
            if not mine:
                continue
            sh(
                ["git", "clone", "-q", "--depth", "1", clone_url.format(org=ORG, repo=repo), clone],
                env=env,
            )
            base_sha = sh(["git", "-C", clone, "rev-parse", "HEAD"], env=env).stdout.strip()
            for task in mine:
                # every task starts from the cloned commit, never from the last task's
                sh(["git", "-C", clone, "checkout", "-q", "--", "."], env=env)
                sh(["git", "-C", clone, "clean", "-qfd"], env=env)
                sh(["git", "-C", clone, "checkout", "-q", "--detach", base_sha], env=env)
                if task == "release-lock" and lock_files(clone):
                    held = held_locks(gh, f"{ORG}/{repo}", lock_files(clone))
                    notes = generate(task, repo, clone, data, [], skip=held)
                else:
                    notes = generate(task, repo, clone, data, [])
                if notes is None:
                    continue
                as_task, notes, also = pair(task, repo, clone, data, notes)
                pr = propose(gh, repo, as_task, clone, notes, env, dry_run, run_url, also, throttle)
                results.append((repo, task, pr))
                if task == "release-aftercare" and released.get(repo):
                    results.append(
                        (
                            repo,
                            "release-leftovers",
                            leftovers(gh, repo, released[repo], pr, dry_run, run_url),
                        )
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
    r.add_argument(
        "--task",
        choices=[
            "epics",
            "org-sync",
            "zenodo",
            "swarm-core-pin",
            "release-lock",
            "release-rebuild",
            "release-aftercare",
            "bestpractices",
            "release",
            "hourly",
            "all",
        ],
        default="all",
    )
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

    # the template pin (#586): a refresh rendered from a newer commit with the
    # same text is the same branch; a different text is not
    lock_diff = (
        '--- a/.github/org-sync.lock\n+++ b/.github/org-sync.lock\n-commit = "{}"\n+commit = "{}"\n'
    )
    same_a = branch_for("org-sync", lock_diff.format("a" * 40, "b" * 40) + "+text\n")
    same_b = branch_for("org-sync", lock_diff.format("a" * 40, "c" * 40) + "+text\n")
    other = branch_for("org-sync", lock_diff.format("a" * 40, "c" * 40) + "+other\n")
    check("the template pin is not part of the branch name", same_a == same_b != other)

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

        def __init__(self, open_prs=(), merge_queue=False, refuse=False, gone=()):
            self.calls, self.open = [], list(open_prs)
            self.merge_queue, self.refuse, self.gone = merge_queue, refuse, set(gone)

        def api(self, method, path, body=None):
            self.calls.append((method, path, body))
            if method == "DELETE" and path.rsplit("/heads/", 1)[-1] in self.gone:
                raise Failure(f"gh api DELETE {path}: gh: Reference does not exist (HTTP 422)")
            if method == "GET" and "/pulls?" in path:
                return self.open
            if method == "GET" and "/rules/branches/main?" in path:
                rules = [{"type": "pull_request"}, {"type": "required_status_checks"}]
                return rules + ([{"type": "merge_queue"}] if self.merge_queue else [])
            if method == "GET":
                return {"default_branch": "main"}
            if method == "POST" and path.endswith("/pulls"):
                return {"number": 42, "node_id": "PR_42"}
            return {}

        def graphql(self, query, **variables):
            self.calls.append(("GRAPHQL", query, variables))
            if self.refuse:
                raise Failure("gh api graphql: Auto merge is not allowed for this repository")
            return {"data": {"enablePullRequestAutoMerge": {"clientMutationId": None}}}

        def auto_merged(self):
            return [c[2]["pr"] for c in self.calls if c[0] == "GRAPHQL" and "AutoMerge" in c[1]]

    clone_url = "file://" + remotes + "/{org}/{repo}.git"

    def go(gh, dry=False, token="tok", task="epics", repos="", data=data):
        ns = argparse.Namespace(task=task, repos=repos, data=data, dry_run=dry)
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
    # the App's identity when the workflow passes both halves, never just one
    app = ("swarm-routing-bot[bot]", "1+swarm-routing-bot[bot]@users.noreply.github.com")
    saved = {k: os.environ.pop(k, None) for k in ("ORG_BOT_GIT_NAME", "ORG_BOT_GIT_EMAIL")}
    try:
        os.environ["ORG_BOT_GIT_NAME"] = app[0]
        half = git_env(None)
        os.environ["ORG_BOT_GIT_EMAIL"] = app[1]
        full_id = git_env(None)
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    check(
        "app identity",
        (half["GIT_AUTHOR_NAME"], half["GIT_AUTHOR_EMAIL"]) == BOT
        and (full_id["GIT_AUTHOR_NAME"], full_id["GIT_COMMITTER_EMAIL"]) == app,
    )
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
    check("no merge queue: auto-merge not touched", gh.auto_merged() == [])
    check("no merge queue: logged", "opened #42" in out and "no merge queue on main" in out)
    # the superseded PR's branch already gone (merged and auto-deleted meanwhile, #572):
    # not a failure, the new PR still opens
    gh = FakeGitHub(
        [
            {
                "number": 7,
                "head": {"ref": "org-bot/epics-00000000", "repo": {"full_name": f"{ORG}/alpha"}},
            }
        ],
        gone={"org-bot/epics-00000000"},
    )
    sh(["git", "--git-dir", os.path.join(remotes, ORG, "alpha.git"), "branch", "-D", branch])
    res, out = go(gh)
    check(
        "superseded branch already gone: no failure",
        "closed #7 as superseded" in out and "opened #42" in out and "FAILED" not in out,
    )
    # a merge queue on main: the new PR gets auto-merge, the older one is superseded
    gh = FakeGitHub(
        [
            {
                "number": 7,
                "node_id": "PR_7",
                "head": {"ref": "org-bot/epics-00000000", "repo": {"full_name": f"{ORG}/alpha"}},
            }
        ],
        merge_queue=True,
    )
    sh(["git", "--git-dir", os.path.join(remotes, ORG, "alpha.git"), "branch", "-D", branch])
    res, out = go(gh)
    check(
        "merge queue: auto-merge on the new PR only, the older one closed",
        gh.auto_merged() == ["PR_42"]
        and "closed #7 as superseded; auto-merge on" in out
        and ("PATCH", f"repos/{ORG}/alpha/pulls/7", {"state": "closed"}) in gh.calls,
    )
    # the same change already open: auto-merge enabled once, never twice
    open_pr = {
        "number": 42,
        "node_id": "PR_42",
        "head": {"ref": branch, "repo": {"full_name": f"{ORG}/alpha"}},
    }
    gh = FakeGitHub([open_pr], merge_queue=True)
    res, out = go(gh)
    check(
        "same change, queue: auto-merge enabled",
        gh.auto_merged() == ["PR_42"] and "already proposed in #42; auto-merge on" in out,
    )
    gh = FakeGitHub([dict(open_pr, auto_merge={"merge_method": "squash"})], merge_queue=True)
    res, out = go(gh)
    check(
        "same change, auto-merge already on: nothing written",
        gh.auto_merged() == [] and "auto-merge already on" in out,
    )
    # GitHub refuses auto-merge: logged, the run goes on
    gh = FakeGitHub([open_pr], merge_queue=True, refuse=True)
    res, out = go(gh)
    check(
        "auto-merge refused: logged, not a failure",
        "auto-merge NOT enabled" in out and "FAILED" not in out and res,
    )
    # only the bot's own branches
    try:
        queue(
            FakeGitHub(merge_queue=True), f"{ORG}/alpha", "main", dict(open_pr, head={"ref": "x"})
        )
        check("someone else's PR refused", False)
    except Failure:
        pass
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

    # --repos limits the repositories proposed to, never the epic data the
    # generators read: .github's ROADMAP lists every repository (2026-11-09,
    # a --repos run opened a ROADMAP PR deleting every other section)
    make_repo("beta", stale)
    wide = os.path.join(work, "wide.json")
    with open(data) as fh:
        both = json.load(fh)
    both["repos"].append(
        {"name": "beta", "url": "https://github.com/swarm-routing/beta", "epics": [epic]}
    )
    with open(wide, "w") as fh:
        json.dump(both, fh)
    seen = []

    def spy_generate(task, repo, clone, data_, out):
        with open(data_) as fh:
            seen.append((repo, sorted(r["name"] for r in json.load(fh)["repos"])))
        return None

    globals()["generate"] = spy_generate
    try:
        res, out = go(FakeGitHub(), repos="beta", data=wide)
        unknown = False
        try:  # a private repository is not in the data: refused, never named (#622)
            go(FakeGitHub(), repos="secret-lib", data=wide)
        except Failure as e:
            unknown = "secret-lib" not in str(e) and "1 named repositories" in str(e)
    finally:
        globals()["generate"] = real_generate
    check("--repos picks the repositories", [r for r, _ in seen] == ["beta"])
    check("--repos keeps every repository's data", seen and seen[0][1] == ["alpha", "beta"])
    check("--repos rejects an unknown name without naming it", unknown)

    # and the API path itself: with no --data, the epics fetch gets no --repos
    # filter (the bug), while an org-sync-only run fetches only its repositories
    fetches = []
    real_sh = globals()["sh"]

    def fake_sh(cmd, cwd=None, env=None, check=True):
        if len(cmd) > 3 and cmd[2] == EPICS and cmd[3] == "fetch":
            fetches.append(cmd)
            shutil.copy(wide, cmd[cmd.index("--out") + 1])
            return subprocess.CompletedProcess(cmd, 0, "", "epics: repositories from X (2)")
        return real_sh(cmd, cwd=cwd, env=env, check=check)

    globals()["sh"], globals()["generate"] = fake_sh, spy_generate
    try:
        _, fetched = go(FakeGitHub(), repos="beta", data="")
        go(FakeGitHub(), repos="beta", data="", task="org-sync")
    finally:
        globals()["sh"], globals()["generate"] = real_sh, real_generate
    check("epics fetch is never limited by --repos", fetches and "--repos" not in fetches[0])
    check("the repository source is printed", "org-bot: epics: repositories from X (2)" in fetched)
    check(
        "org-sync-only fetch is limited to its repositories",
        len(fetches) == 2 and fetches[1][-2:] == ["--repos", "beta"],
    )
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
    # a settings-only org-sync.toml (no kind, tools/repo-settings): org_sync.py changes
    # nothing there, so the repository reads up to date and gets no PR
    settings_only = os.path.join(work, "settings-only")
    os.makedirs(os.path.join(settings_only, ".github"))
    with open(os.path.join(settings_only, ".github", "org-sync.toml"), "w") as fh:
        fh.write('[settings]\ndescription = "x"\n')
    notes = generate("org-sync", "settings-only", settings_only, data, [])
    check(
        "org-sync leaves a settings-only config alone",
        sorted(os.listdir(settings_only)) == [".github"]
        and any("settings only" in n for n in notes),
    )
    # .github itself (settings only) gets its own references pinned (#716): `refs`
    # at the newest commit of this checkout that changed a reusable workflow or action
    dotgithub = os.path.join(work, "dotgithub")
    os.makedirs(os.path.join(dotgithub, ".github", "workflows"))
    with open(os.path.join(dotgithub, ".github", "org-sync.toml"), "w") as fh:
        fh.write('[settings]\ndescription = "x"\n')
    inner = os.path.join(dotgithub, ".github", "workflows", "reusable-x.yml")
    with open(inner, "w") as fh:
        fh.write(
            "on:\n  workflow_call:\njobs:\n  x:\n    uses: swarm-routing/.github/.github/actions/bot-token@main\n"
        )
    notes = generate("org-sync", ".github", dotgithub, data, [])
    with open(inner) as fh:
        check(
            ".github's own references pinned by commit",
            re.search(r"bot-token@[0-9a-f]{40} # main", fh.read()) is not None
            and any("update    .github/workflows/reusable-x.yml" in n for n in notes),
        )
    # org-sync notes list the seeds that differ, for information, and leave them alone
    adopted = os.path.join(work, "adopted")
    os.makedirs(adopted)
    sh(["git", "-C", adopted, "init", "-q"])
    sh([sys.executable, "-I", ORG_SYNC, "init", adopted, "--kind", "data", "--title", "demo"])
    cfg = os.path.join(adopted, ".github", "org-sync.toml")
    with open(cfg) as fh:
        text = fh.read()
    with open(cfg, "w") as fh:
        fh.write(text.replace('kind = "data"\n', 'kind = "data"\nposture = "a dataset"\n'))
    with open(os.path.join(adopted, "SECURITY.md")) as fh:
        before = fh.read()
    with open(os.path.join(adopted, "AGENTS.md"), "a") as fh:
        fh.write("\n<!-- org-sync:begin stale -->\nold\n<!-- org-sync:end stale -->\n")
    notes = generate("org-sync", "adopted", adopted, data, [])
    with open(os.path.join(adopted, "AGENTS.md")) as fh:
        check(
            "org-sync removes an orphan block (#235)",
            "org-sync:begin stale" not in fh.read()
            and any("removed   AGENTS.md#stale (orphan)" in n for n in notes),
        )
    with open(os.path.join(adopted, "SECURITY.md")) as fh:
        after = fh.read()
    check(
        "org-sync notes list differing seeds, unchanged",
        any("differs   SECURITY.md (2 lines)" in n for n in notes) and before == after,
    )
    # zenodo (#232): record writes the concept Zenodo holds, apply renders the badge; a
    # repository without CITATION.cff is skipped, and a refused record fails that repository
    src = os.path.join(work, "src", "gamma")
    os.makedirs(src)
    sh(["git", "init", "-q", "-b", "main", src], env=env)
    sh([sys.executable, "-I", ORG_SYNC, "init", src, "--kind", "data", "--title", "gamma"])
    cfg = os.path.join(src, ".github", "org-sync.toml")
    with open(cfg) as fh:
        text = fh.read()
    with open(cfg, "w") as fh:
        fh.write(text.replace('kind = "data"\n', 'kind = "data"\ncitation = true\n'))
    sh([sys.executable, "-I", ORG_SYNC, "apply", src], check=False)
    sh(["git", "-C", src, "add", "-A"], env=env)
    sh(["git", "-C", src, "commit", "-q", "-m", "init"], env=env)
    sh(["git", "clone", "-q", "--bare", src, os.path.join(remotes, ORG, "gamma.git")], env=env)
    zdata = os.path.join(work, "zdata.json")
    with open(zdata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": n, "epics": []} for n in ("alpha", "gamma")]}, fh)
    records = []

    def zenodo_sh(answer):
        def fake(cmd, cwd=None, env=None, check=True):
            if len(cmd) > 3 and cmd[2] == ZENODO:
                records.append(cmd)
                clone = cmd[cmd.index("--checkout") + 1]
                if answer:
                    return subprocess.CompletedProcess(cmd, 1, "", answer)
                p = os.path.join(clone, ".github", "org-sync.toml")
                with open(p) as fh:
                    t = fh.read()
                with open(p, "w") as fh:
                    fh.write(
                        t.replace('kind = "data"\n', 'kind = "data"\nzenodo_concept = "500"\n')
                    )
                with open(os.path.join(clone, "CITATION.cff"), "a") as fh:
                    fh.write('doi: "10.5281/zenodo.500"\n')
                return subprocess.CompletedProcess(cmd, 0, "R: concept 500 written", "")
            return real_sh(cmd, cwd=cwd, env=env, check=check)

        return fake

    globals()["sh"] = zenodo_sh("")
    try:
        gh = FakeGitHub()
        res, out = go(gh, task="zenodo", data=zdata)
    finally:
        globals()["sh"] = real_sh
    zbranch = res[0][2]["branch"] if res else ""
    git_dir = os.path.join(remotes, ORG, "gamma.git")
    readme = sh(["git", "--git-dir", git_dir, "show", f"{zbranch}:README.md"], check=False).stdout
    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    check(
        "zenodo: record, then apply renders the badge, one PR",
        [r[0] for r in res] == ["gamma"]
        and len(records) == 1
        and records[0][-5:] == ["--repo", f"{ORG}/gamma", "--checkout", records[0][-2], "--write"]
        and "zenodo.org/badge/DOI/10.5281/zenodo.500.svg" in readme
        and post
        and post[0][2]["title"] == "docs: record the zenodo concept doi (org-bot)"
        and "concept 500 written" in post[0][2]["body"],
    )
    globals()["sh"] = zenodo_sh("org/gamma: the concept is named two ways")
    try:
        go(FakeGitHub(), task="zenodo", data=zdata)
        refused = None
    except Failure as e:
        refused = str(e)
    finally:
        globals()["sh"] = real_sh
    check("zenodo: a refused record fails the repository", refused and "gamma" in refused)
    # bestpractices: the Go tool writes .bestpractices.json (a fake binary here); a
    # changed file is one PR, an unchanged one none, and a failure fails the repository
    fake_bp = os.path.join(work, "fake-bestpractices")
    with open(fake_bp, "w") as fh:
        fh.write(
            "#!/bin/sh\n"
            '[ "$1" = answers ] && [ "$3" = --slug ] && [ "$5" = --write ] || exit 2\n'
            '[ -n "$BP_FAIL" ] && { echo "boom" >&2; exit 1; }\n'
            'printf \'{\\n  "build_status": "Met"\\n}\\n\' > "$2/.bestpractices.json"\n'
            'echo "bestpractices: wrote $2/.bestpractices.json" >&2\n'
            'echo "bestpractices: Met 1" >&2\n'
        )
    os.chmod(fake_bp, 0o700)  # owner only
    global BESTPRACTICES
    real_bp, BESTPRACTICES = BESTPRACTICES, fake_bp
    try:
        gh = FakeGitHub()
        res, out = go(gh, task="bestpractices", repos="gamma", data=zdata)
        post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
        bbranch = res[0][2]["branch"] if res and res[0][2] else ""
        written = sh(
            ["git", "--git-dir", git_dir, "show", f"{bbranch}:.bestpractices.json"], check=False
        ).stdout
        check(
            "bestpractices: the file written by the tool, one PR",
            [r[0] for r in res] == ["gamma"]
            and bbranch.startswith("org-bot/bestpractices-")
            and written == '{\n  "build_status": "Met"\n}\n'
            and len(post) == 1
            and post[0][2]["title"] == "chore: regenerate .bestpractices.json (org-bot)"
            and "Met 1" in post[0][2]["body"],
        )
        sh(["git", "--git-dir", git_dir, "update-ref", "refs/heads/main", bbranch])
        gh = FakeGitHub()
        res, out = go(gh, task="bestpractices", repos="gamma", data=zdata)
        check(
            "bestpractices: unchanged, no PR",
            "gamma bestpractices: up to date" in out
            and not [c for c in gh.calls if c[0] == "POST"],
        )
        os.environ["BP_FAIL"] = "1"
        try:
            go(FakeGitHub(), task="bestpractices", repos="gamma", data=zdata)
            refused = None
        except Failure as e:
            refused = str(e)
        finally:
            os.environ.pop("BP_FAIL", None)
        check("bestpractices: a failing tool fails the repository", refused and "gamma" in refused)
    finally:
        BESTPRACTICES = real_bp
    # swarm-core-pin (#208): a stale pin gets one PR on org-bot/swarm-core-pin, a current
    # one none, a repository with no pin is skipped, and a second swarm-core move
    # updates that same PR (branch pushed again, body rewritten)
    sc = os.path.join(work, "swarm-core")
    os.makedirs(os.path.join(sc, "core"))

    def sc_commit(text, msg):
        with open(os.path.join(sc, "core", "a.h"), "w") as fh:
            fh.write(text)
        sh(["git", "-C", sc, "add", "-A"], env=env)
        sh(["git", "-C", sc, "commit", "-q", "-m", msg], env=env)
        return sh(["git", "-C", sc, "rev-parse", "HEAD"]).stdout.strip()

    sh(["git", "init", "-q", "-b", "main", sc], env=env)
    old = sc_commit("int a;\n", "core a")

    def pinned_repo(name, pin):
        src = os.path.join(work, "src", name)
        files = {
            "core/CMakeLists.txt": f'set(SWARM_CORE_REF "{pin}" CACHE STRING "swarm-core")\n',
            "Makefile": f"SWARM_CORE_REF ?= {pin}\n",
            ".github/workflows/licence.yml": f"  core-deps: swarm-routing/ns3-swarm-core@{pin}:core\n",
        }
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(src, rel)), exist_ok=True)
            with open(os.path.join(src, rel), "w") as fh:
                fh.write(text)
        sh(["git", "init", "-q", "-b", "main", src], env=env)
        sh(["git", "-C", src, "add", "-A"], env=env)
        sh(["git", "-C", src, "commit", "-q", "-m", "init"], env=env)
        sh(
            ["git", "clone", "-q", "--bare", src, os.path.join(remotes, ORG, name + ".git")],
            env=env,
        )

    pinned_repo("delta", old)
    new = sc_commit("int a, b;\n", "core b")
    pinned_repo("eps", new)
    pdata = os.path.join(work, "pdata.json")
    with open(pdata, "w") as fh:
        json.dump(
            {"org": ORG, "repos": [{"name": n, "epics": []} for n in ("alpha", "delta", "eps")]},
            fh,
        )
    globals()["SWARM_CORE"] = sc
    gh = FakeGitHub()
    res, out = go(gh, task="swarm-core-pin", data=pdata)
    git_dir = os.path.join(remotes, ORG, "delta.git")
    shown = sh(
        ["git", "--git-dir", git_dir, "show", "org-bot/swarm-core-pin:Makefile"], check=False
    ).stdout
    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    check(
        "swarm-core-pin: a stale pin gets one PR on the fixed branch, a current one none",
        [r[0] for r in res] == ["delta", "eps"]
        and res[0][2]["branch"] == "org-bot/swarm-core-pin"
        and "eps swarm-core-pin: up to date" in out
        and new in shown
        and len(post) == 1
        and post[0][2]["title"] == "chore(core): bump the swarm-core pin (org-bot)"
        and f"pin-target: {new}" in post[0][2]["body"]
        and "core b" in post[0][2]["body"],
    )
    newer = sc_commit("int a, b, c;\n", "core c")
    open_pr = {
        "number": 42,
        "node_id": "PR_42",
        "head": {"ref": "org-bot/swarm-core-pin", "repo": {"full_name": f"{ORG}/delta"}},
        "body": f"pin-target: {new}",
    }
    gh = FakeGitHub(open_prs=[open_pr])
    res, out = go(gh, task="swarm-core-pin", repos="delta", data=pdata)
    shown = sh(["git", "--git-dir", git_dir, "show", "org-bot/swarm-core-pin:Makefile"]).stdout
    patch = [c for c in gh.calls if c[0] == "PATCH" and c[1].endswith("/pulls/42")]
    check(
        "swarm-core-pin: a second move updates the same PR",
        "updated #42" in out
        and newer in shown
        and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
        and patch
        and f"pin-target: {newer}" in patch[0][2]["body"],
    )
    gh = FakeGitHub(open_prs=[{**open_pr, "body": f"pin-target: {newer}"}])
    res, out = go(gh, task="swarm-core-pin", repos="delta", data=pdata)
    check(
        "swarm-core-pin: the same target is left alone",
        "already proposed in #42" in out and not [c for c in gh.calls if c[0] in ("POST", "PATCH")],
    )
    # main gains a file naming the old pin while the PR is open: same target,
    # but the branch lacks that file's bump, so it is refreshed (CodeRabbit, #359)
    extra = os.path.join(work, "delta-extra")
    sh(["git", "clone", "-q", os.path.join(remotes, ORG, "delta.git"), extra], env=env)
    os.makedirs(os.path.join(extra, ".github", "workflows"), exist_ok=True)
    with open(os.path.join(extra, ".github", "workflows", "bench.yml"), "w") as fh:
        fh.write(f"        swarm-core=swarm-routing/ns3-swarm-core@{old}\n")
    sh(["git", "-C", extra, "add", "-A"], env=env)
    sh(["git", "-C", extra, "commit", "-q", "-m", "bench"], env=env)
    sh(["git", "-C", extra, "push", "-q", "origin", "HEAD:main"], env=env)
    gh = FakeGitHub(open_prs=[{**open_pr, "body": f"pin-target: {newer}"}])
    res, out = go(gh, task="swarm-core-pin", repos="delta", data=pdata)
    bench = sh(
        ["git", "--git-dir", git_dir, "show", "org-bot/swarm-core-pin:.github/workflows/bench.yml"],
        check=False,
    ).stdout
    check(
        "swarm-core-pin: a new file naming the old pin refreshes the PR, same target",
        "updated #42" in out and newer in bench,
    )
    hand_pr = {
        "number": 7,
        "head": {"ref": "claude/bump", "repo": {"full_name": f"{ORG}/delta"}},
        "title": f"chore(core): bump the swarm-core pin to {newer[:7]}",
        "body": "",
    }
    gh = FakeGitHub(open_prs=[hand_pr])
    res, out = go(gh, task="swarm-core-pin", repos="delta", data=pdata)
    check(
        "swarm-core-pin: a hand-opened bump to the same commit gets no duplicate",
        "already proposed by hand in #7" in out
        and not [c for c in gh.calls if c[0] in ("POST", "PATCH")],
    )
    # #429: the 2026-11-14 deadlock. A stale pin and drifted templates in one repository,
    # with the bot's two open PRs (the pin bump red on `check / org-sync`, the refresh red
    # on `swarm-core / pin`): either task now carries both changes in one PR on
    # org-bot/swarm-core-pin and closes the org-sync PR; one change alone keeps its own PR
    pinned_repo("theta", old)
    pinned_repo("iota", newer)
    tdata = os.path.join(work, "tdata.json")
    with open(tdata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": n, "epics": []} for n in ("theta", "iota")]}, fh)

    def drift_generate(task, repo, clone, data_, out):
        if task != "org-sync":
            return real_generate(task, repo, clone, data_, out)
        with open(os.path.join(clone, "SYNCED.md"), "w") as fh:
            fh.write("templates\n")
        return ["org-sync generated"]

    git_dir = os.path.join(remotes, ORG, "theta.git")
    pin_pr = {
        "number": 50,
        "node_id": "PR_50",
        "head": {"ref": "org-bot/swarm-core-pin", "repo": {"full_name": f"{ORG}/theta"}},
        "body": f"pin-target: {newer}",
    }
    sync_pr = {
        "number": 51,
        "node_id": "PR_51",
        "head": {"ref": "org-bot/org-sync-0badf00d", "repo": {"full_name": f"{ORG}/theta"}},
        "body": "",
    }
    sh(
        ["git", "--git-dir", git_dir, "update-ref", "refs/heads/org-bot/swarm-core-pin", "main"],
        env=env,
    )
    for task in ("org-sync", "swarm-core-pin"):
        globals()["generate"] = drift_generate
        try:
            gh = FakeGitHub(open_prs=[pin_pr, sync_pr])
            res, out = go(gh, task=task, repos="theta", data=tdata)
        finally:
            globals()["generate"] = real_generate
        files = sh(
            ["git", "--git-dir", git_dir, "diff", "--name-only", "main", "org-bot/swarm-core-pin"],
            check=False,
        ).stdout.split()
        closed = [c for c in gh.calls if c[0] == "PATCH" and c[1].endswith("/pulls/51")]
        body = [c for c in gh.calls if c[0] == "PATCH" and c[1].endswith("/pulls/50")]
        check(
            f"#429 deadlock, {task} run: one PR carries the pin bump and the templates",
            res
            and res[0][2]["branch"] == "org-bot/swarm-core-pin"
            and res[0][2]["number"] == 50
            and sorted(files)
            == [".github/workflows/licence.yml", "Makefile", "SYNCED.md", "core/CMakeLists.txt"]
            and closed
            and closed[0][2] == {"state": "closed"}
            and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")],
        )
        check(
            f"#429 deadlock, {task} run: the PR body says it carries both",
            task == "swarm-core-pin"
            and not body  # the org-sync run already pushed it
            or (
                body
                and "(#429)" in body[0][2]["body"]
                and f"pin-target: {newer}" in body[0][2]["body"]
            ),
        )

    def half_generate(task, repo, clone, data_, out):
        if task == "org-sync":  # the task itself: a new file and an edit
            with open(os.path.join(clone, "SYNCED.md"), "w") as fh:
                fh.write("templates\n")
            with open(os.path.join(clone, "Makefile"), "a") as fh:
                fh.write("# synced\n")
            return ["org-sync generated"]
        with open(os.path.join(clone, "HALF.md"), "w") as fh:  # the partner fails half-way
            fh.write("partial\n")
        with open(os.path.join(clone, "core", "CMakeLists.txt"), "a") as fh:
            fh.write("# partial\n")
        raise Failure("check-swarm-core-pin.py --bump: refused")

    globals()["generate"] = half_generate
    try:
        gh = FakeGitHub()
        res, out = go(gh, task="org-sync", repos="iota", data=tdata)
    finally:
        globals()["generate"] = real_generate
    ibranch = res[0][2]["branch"] if res else ""
    ifiles = sh(
        [
            "git",
            "--git-dir",
            os.path.join(remotes, ORG, "iota.git"),
            "diff",
            "--name-only",
            "main",
            ibranch,
        ],
        check=False,
    ).stdout.split()
    check(
        "#429: a partner that fails half-way is undone, the task's own change kept",
        ibranch.startswith("org-bot/org-sync-") and sorted(ifiles) == ["Makefile", "SYNCED.md"],
    )
    globals()["generate"] = drift_generate
    try:
        gh = FakeGitHub()
        res, out = go(gh, task="org-sync", repos="iota", data=tdata)
    finally:
        globals()["generate"] = real_generate
    check(
        "#429: a current pin leaves the template refresh its own PR",
        res
        and res[0][2]["branch"].startswith("org-bot/org-sync-")
        and not [c for c in gh.calls if c[0] == "PATCH"],
    )
    # swarm-core-pin on a release lock (swarm-routing/swarm-adapter-ns3#134): a lock behind
    # the newest release gets the PR, a current one none, and none between releases
    sys.path.insert(0, os.path.dirname(PIN))
    import release_lock

    rel = os.path.join(work, "releases")
    sc_repo = "swarm-routing/swarm-adapter-ns3"
    sc_more = release_lock.fixture_repo(rel, sc_repo, env)
    release_lock.make_release(rel, sc_repo, "v0.3.0", {"swarm-core-0.3.0.tar.gz": b"3"}, env)
    rbase = "file://" + rel

    # the vcpkg registry a vcpkg-mode consumer's baseline moves to (#489)
    vreg = os.path.join(work, "vcpkg-registry")
    sh(["git", "init", "-q", "-b", "main", vreg], env=env)

    def vreg_port(version):
        os.makedirs(os.path.join(vreg, "versions"), exist_ok=True)
        with open(os.path.join(vreg, "versions", "baseline.json"), "w") as fh:
            json.dump({"default": {"swarm-core": {"baseline": version, "port-version": 0}}}, fh)
        sh(["git", "-C", vreg, "add", "-A"], env=env)
        sh(["git", "-C", vreg, "commit", "-q", "-m", version], env=env)
        return sh(["git", "-C", vreg, "rev-parse", "HEAD"], env=env).stdout.strip()

    v3_base = vreg_port("0.3.0")
    globals()["VCPKG_REGISTRY"] = vreg

    def locked_repo(name, vcpkg=False):
        src = os.path.join(work, "src", name)
        lock = release_lock.render(
            "SWARM_CORE", sc_repo, "v0.3.0", "swarm-core-{version}.tar.gz", rbase
        )
        files = {
            "swarm-core.lock": lock,
            "core/CMakeLists.txt": "file(STRINGS ../swarm-core.lock lock)\n",
            "Makefile": "SWARM_CORE_REF ?= v0.3.0\n",
            ".github/workflows/licence.yml": "  core-deps: swarm-routing/ns3-swarm-core@v0.3.0:core\n",
        }
        if vcpkg:  # core/ takes swarm-core through vcpkg; the lock records the ns-3 tag
            files["core/CMakeLists.txt"] = "find_package(swarm-core CONFIG REQUIRED)\n"
            files["vcpkg.json"] = json.dumps(
                {
                    "dependencies": ["swarm-core"],
                    "overrides": [{"name": "swarm-core", "version": "0.3.0", "port-version": 0}],
                },
                indent=2,
            )
            files["vcpkg-configuration.json"] = json.dumps(
                {
                    "registries": [
                        {
                            "kind": "git",
                            "repository": "https://github.com/swarm-routing/vcpkg-registry",
                            "baseline": v3_base,
                            "packages": ["swarm-core"],
                        }
                    ]
                },
                indent=2,
            )
        for rel_, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(src, rel_)), exist_ok=True)
            with open(os.path.join(src, rel_), "w") as fh:
                fh.write(text)
        sh(["git", "init", "-q", "-b", "main", src], env=env)
        sh(["git", "-C", src, "add", "-A"], env=env)
        sh(["git", "-C", src, "commit", "-q", "-m", "init"], env=env)
        sh(
            ["git", "clone", "-q", "--bare", src, os.path.join(remotes, ORG, name + ".git")],
            env=env,
        )

    locked_repo("zeta")
    locked_repo("zeta-vcpkg", vcpkg=True)
    ldata = os.path.join(work, "ldata.json")
    with open(ldata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": "zeta", "epics": []}]}, fh)
    vdata = os.path.join(work, "vdata.json")
    with open(vdata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": "zeta-vcpkg", "epics": []}]}, fh)
    globals()["SWARM_CORE_RELEASES"] = rbase
    sc_more("main moves, no release")
    gh = FakeGitHub()
    res, out = go(gh, task="swarm-core-pin", data=ldata)
    check(
        "swarm-core-pin, lock: no PR between releases, however main moves",
        "zeta swarm-core-pin: up to date" in out
        and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")],
    )
    _, v4 = release_lock.make_release(
        rel, sc_repo, "v0.4.0", {"swarm-core-0.4.0.tar.gz": b"4"}, env
    )
    gh = FakeGitHub()
    res, out = go(gh, task="swarm-core-pin", data=ldata)
    lock_shown = sh(
        [
            "git",
            "--git-dir",
            os.path.join(remotes, ORG, "zeta.git"),
            "show",
            "org-bot/swarm-core-pin:swarm-core.lock",
        ],
        check=False,
    ).stdout
    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    check(
        "swarm-core-pin, lock: a new release gets one PR with the lock read from it",
        len(post) == 1
        and "SWARM_CORE_TAG=v0.4.0" in lock_shown
        and v4["swarm-core-0.4.0.tar.gz"] in lock_shown
        and "pin-target:" in post[0][2]["body"]
        and "v0.4.0" in post[0][2]["body"],
    )
    # vcpkg mode (#489): no PR until the registry's main holds the release, then one PR
    # that moves the lock, the override and the registry baseline together
    gh = FakeGitHub()
    res, out = go(gh, task="swarm-core-pin", data=vdata)
    check(
        "swarm-core-pin, vcpkg: a release the registry lacks yet gets no PR",
        "zeta-vcpkg swarm-core-pin: up to date" in out
        and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")],
    )
    v4_base = vreg_port("0.4.0")
    gh = FakeGitHub()
    res, out = go(gh, task="swarm-core-pin", data=vdata)

    def zv(path):
        return sh(
            [
                "git",
                "--git-dir",
                os.path.join(remotes, ORG, "zeta-vcpkg.git"),
                "show",
                f"org-bot/swarm-core-pin:{path}",
            ],
            check=False,
        ).stdout

    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    check(
        "swarm-core-pin, vcpkg: once the registry has it, one PR moves lock, override and baseline",
        len(post) == 1
        and "SWARM_CORE_TAG=v0.4.0" in zv("swarm-core.lock")
        and '"version": "0.4.0"' in zv("vcpkg.json")
        and v4_base in zv("vcpkg-configuration.json"),
    )

    # release-rebuild (#430): a behind bot/release PR gets its caller dispatched with mode bump
    # and the increment the PR was opened with; never when current, busy, or in a dry run
    class RouteGitHub(FakeGitHub):
        def __init__(self, routes, **kw):
            super().__init__(**kw)
            self.routes = routes

        def api(self, method, path, body=None):
            if method == "GET" and path in self.routes:
                self.calls.append((method, path, body))
                return self.routes[path]
            return super().api(method, path, body)

    caller = (
        "on:\n  workflow_dispatch:\n    inputs:\n      mode: { type: choice, options: [dry-run, bump] }\n"
        "      increment: { type: choice, options: [auto, PATCH, MINOR, MAJOR] }\njobs:\n  release:\n"
        "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main\n"
    )
    full = f"{ORG}/lam"
    rroutes = {
        f"repos/{full}/pulls?state=open&head={ORG}:bot/release&per_page=10": [
            {
                "number": 9,
                "head": {"ref": "bot/release"},
                "base": {"ref": "main"},
                "body": "x\n<!-- release-increment: MAJOR -->\n",
            }
        ],
        f"repos/{full}/compare/main...bot/release": {"behind_by": 3},
        f"repos/{full}/contents/.github/workflows?ref=main": [
            {"name": "ci.yml", "path": ".github/workflows/ci.yml"},
            {"name": "release.yml", "path": ".github/workflows/release.yml"},
        ],
        f"repos/{full}/contents/.github/workflows/ci.yml?ref=main": {
            "content": base64.b64encode(b"jobs: {}\n").decode()
        },
        f"repos/{full}/contents/.github/workflows/release.yml?ref=main": {
            "content": base64.b64encode(caller.encode()).decode()
        },
        **{
            f"repos/{full}/actions/workflows/release.yml/runs?status={st_}&per_page=1": {
                "total_count": 0,
                "workflow_runs": [],
            }
            for st_ in ("queued", "in_progress", "waiting", "requested", "pending")
        },
    }

    def rb(routes, dry=False):
        gh = RouteGitHub(routes)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            got = rebuild(gh, "lam", dry)
        posts = [c for c in gh.calls if c[0] == "POST"]
        return got, posts, out.getvalue()

    got, posts, out = rb(rroutes)
    check(
        "release-rebuild: a behind bump PR dispatches its caller with mode bump and its increment",
        posts
        == [
            (
                "POST",
                f"repos/{full}/actions/workflows/release.yml/dispatches",
                {"ref": "main", "inputs": {"mode": "bump", "increment": "MAJOR"}},
            )
        ]
        and "3 behind" in out,
    )
    got, posts, out = rb(rroutes, dry=True)
    check("release-rebuild: a dry run dispatches nothing", not posts and "would dispatch" in out)
    pr9 = rroutes[f"repos/{full}/pulls?state=open&head={ORG}:bot/release&per_page=10"][0]
    got, posts, out = rb({**rroutes, f"repos/{full}/compare/main...bot/release": {"behind_by": 0}})
    check("release-rebuild: a current bump PR is left alone", not posts and got["behind"] == 0)
    busy = {"total_count": 1, "workflow_runs": [{"id": 2, "status": "in_progress"}]}
    got, posts, out = rb(
        {
            **rroutes,
            f"repos/{full}/actions/workflows/release.yml/runs?status=in_progress&per_page=1": busy,
        }
    )
    check(
        "release-rebuild: never while a dispatch still runs (status-filtered, any page)",
        not posts and "still in_progress" in out,
    )
    got, posts, out = rb(
        {
            **rroutes,
            f"repos/{full}/pulls?state=open&head={ORG}:bot/release&per_page=10": [
                {**pr9, "body": "opened before the marker"}
            ],
        }
    )
    check(
        "release-rebuild: no recorded increment, no guess: dispatch by hand",
        not posts and "dispatch bump by hand" in out and got.get("unknown"),
    )
    plain = (
        "on:\n  workflow_dispatch:\njobs:\n  r:\n"
        "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main\n"
        "    with:\n      mode: bump\n      increment: ''\n"
    )
    got, posts, out = rb(
        {
            **rroutes,
            f"repos/{full}/pulls?state=open&head={ORG}:bot/release&per_page=10": [
                {**pr9, "body": ""}
            ],
            f"repos/{full}/contents/.github/workflows/release.yml?ref=main": {
                "content": base64.b64encode(plain.encode()).decode()
            },
        }
    )
    check(
        "release-rebuild: only the inputs the caller declares (a job's with: is none)",
        posts and posts[0][2] == {"ref": "main", "inputs": {}},
    )
    got, posts, out = rb(
        {**rroutes, f"repos/{full}/pulls?state=open&head={ORG}:bot/release&per_page=10": []}
    )
    check("release-rebuild: no bump PR, nothing", got is None and not posts)
    got, posts, out = rb({**rroutes, f"repos/{full}/contents/.github/workflows?ref=main": []})
    check(
        "release-rebuild: no reusable-release caller says so, dispatches nothing",
        not posts and "by hand" in out,
    )
    # release-aftercare (#465): a recent release gets its record PR and the leftovers on
    # the site's release-sync issue; an old one is not even cloned
    src = os.path.join(work, "src", "mu")
    os.makedirs(os.path.join(src, "docs"))
    for rel_, text in (
        ("CITATION.cff", "title: mu\n"),
        ("docs/roadmap.md", "| v0.2.0 | planned |\n"),
    ):
        with open(os.path.join(src, rel_), "w") as fh:
            fh.write(text)
    sh(["git", "init", "-q", "-b", "main", src], env=env)
    sh(["git", "-C", src, "add", "-A"], env=env)
    sh(["git", "-C", src, "commit", "-q", "-m", "init"], env=env)
    sh(["git", "clone", "-q", "--bare", src, os.path.join(remotes, ORG, "mu.git")], env=env)
    adata = os.path.join(work, "adata.json")
    with open(adata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": "mu", "epics": []}]}, fh)
    import datetime

    fresh = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    calls = []

    def after_sh(cmd, cwd=None, env=None, check=True):
        if len(cmd) > 3 and cmd[2] == ZENODO:
            calls.append(cmd[3])
            root = cmd[cmd.index("--checkout") + 1]
            with open(os.path.join(root, "docs", "roadmap.md"), "a") as fh:
                fh.write("- **v0.2.0** shipped (DOI from Zenodo)\n")
            return subprocess.CompletedProcess(cmd, 0, "org/mu docs/roadmap.md: writes", "")
        if len(cmd) > 3 and cmd[2] == RELEASE_CHECK:
            calls.append(cmd[3])
            text = "OK    release: v0.2.0 published\nWARN  vcpkg: open PR\nFAIL  see above\n"
            return subprocess.CompletedProcess(cmd, 1, text, "")
        return real_sh(cmd, cwd=cwd, env=env, check=check)

    aroutes = {
        f"repos/{ORG}/mu/releases?per_page=20": [
            {"tag_name": "v0.2.0", "published_at": fresh},
            {"tag_name": "v0.1.0", "published_at": "2026-01-01T00:00:00Z"},
        ],
        f"repos/{ORG}/{SITE}/issues?state=all&sort=created&direction=desc&per_page=100&page=1": [
            {"number": 1000 + k, "title": f"other {k}"} for k in range(100)
        ],
        f"repos/{ORG}/{SITE}/issues?state=all&sort=created&direction=desc&per_page=100&page=2": [
            {"number": 77, "title": "[release-sync] mu v0.2.0"}
        ],
        f"repos/{ORG}/{SITE}/issues/77/comments?per_page=100": [],
    }
    globals()["sh"] = after_sh
    try:
        gh = RouteGitHub(aroutes, merge_queue=True)
        res, out = go(gh, task="release-aftercare", data=adata)
    finally:
        globals()["sh"] = real_sh
    road = (
        sh(
            [
                "git",
                "--git-dir",
                os.path.join(remotes, ORG, "mu.git"),
                "show",
                f"{res[0][2]['branch']}:docs/roadmap.md",
            ],
            check=False,
        ).stdout
        if res and res[0][2]
        else ""
    )
    posted = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/issues/77/comments")]
    check(
        "release-aftercare: a recent release gets its record PR with auto-merge",
        calls[:1] == ["shipped"]
        and res[0][2]["branch"].startswith("org-bot/release-aftercare-")
        and "v0.2.0** shipped" in road
        and gh.auto_merged() == ["PR_42"],
    )
    check(
        "release-aftercare: the leftovers posted on the site's release-sync issue (page 2)",
        "after" in calls
        and posted
        and AFTERCARE_MARK in posted[0][2]["body"]
        and "- `WARN  vcpkg: open PR`" in posted[0][2]["body"]
        and "see above" not in posted[0][2]["body"]
        and "swarm-routing/mu#42" in posted[0][2]["body"],
    )
    body = posted[0][2]["body"] if posted else ""
    aroutes[f"repos/{ORG}/{SITE}/issues/77/comments?per_page=100"] = [{"id": 5, "body": body}]
    globals()["sh"] = after_sh
    try:
        gh = RouteGitHub(
            aroutes,
            open_prs=[
                {
                    "number": 42,
                    "node_id": "PR_42",
                    "auto_merge": {},
                    "head": {"ref": res[0][2]["branch"], "repo": {"full_name": f"{ORG}/mu"}},
                }
            ],
        )
        res2, out = go(gh, task="release-aftercare", data=adata)
    finally:
        globals()["sh"] = real_sh
    check(
        "release-aftercare: a second run changes nothing",
        "already proposed in #42" in out
        and "already says so" in out
        and not [c for c in gh.calls if c[0] in ("POST", "PATCH")],
    )
    aroutes[f"repos/{ORG}/mu/releases?per_page=20"] = [
        {"tag_name": "v0.2.0", "published_at": "2026-01-01T00:00:00Z"}
    ]
    calls.clear()
    globals()["sh"] = after_sh
    try:
        gh = RouteGitHub(aroutes)
        res3, out = go(gh, task="release-aftercare", data=adata)
    finally:
        globals()["sh"] = real_sh
    check(
        "release-aftercare: an old release is left alone",
        res3 == [] and calls == [] and "none" in out,
    )
    seen_cmd = []

    def table_sh(cmd, cwd=None, env=None, check=True):
        seen_cmd.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "CONTRIBUTING.md: wrote 1 row(s)", "")

    globals()["sh"] = table_sh
    try:
        notes = generate("release-aftercare", ".github", "/x", data, [])
    finally:
        globals()["sh"] = real_sh
    check(
        "release-aftercare: in .github, the archived-releases table",
        seen_cmd
        and seen_cmd[0][2:] == [ZENODO, "table", "/x/CONTRIBUTING.md", "--write"]
        and notes,
    )
    # release-lock (#478): every other root lock follows its dependency's releases, one PR
    # on org-bot/release-lock; a hand PR on the lock, a renamed asset, a carried org-sync
    nt_repo = "swarm-routing/sim-tools"
    nt_more = release_lock.fixture_repo(rel, nt_repo, env)
    _, n1 = release_lock.make_release(
        rel, nt_repo, "v0.1.0", {"routing-bench-0.1.0.tar.gz": b"rb1", "nt-0.1.0.whl": b"w1"}, env
    )
    globals()["RELEASES"] = rbase
    nt_tags = release_lock.tags(rbase, nt_repo)
    nt_lock = (
        "# the ns3-tools release this repository builds on\n"
        f"NS3_TOOLS_REPO={nt_repo}\nNS3_TOOLS_TAG=v0.1.0\n"
        f"NS3_TOOLS_COMMIT={nt_tags['v0.1.0']}\nNS3_TOOLS_VERSION=0.1.0\n"
        f"ROUTING_BENCH_SHA256={n1['routing-bench-0.1.0.tar.gz']}\n"
        f"NS3_TOOL_WHEEL_SHA256={n1['nt-0.1.0.whl']}\n"
    )
    protocols = "anthocnet https://github.com/x/y 0123 v1.0.0\n"  # not a release lock

    def lock_repo(name):
        src = os.path.join(work, "src", name)
        os.makedirs(src)
        for fn, text in (("ns3-tools.lock", nt_lock), ("protocols.lock", protocols)):
            with open(os.path.join(src, fn), "w") as fh:
                fh.write(text)
        sh(["git", "init", "-q", "-b", "main", src], env=env)
        sh(["git", "-C", src, "add", "-A"], env=env)
        sh(["git", "-C", src, "commit", "-q", "-m", "init"], env=env)
        sh(
            ["git", "clone", "-q", "--bare", src, os.path.join(remotes, ORG, name + ".git")],
            env=env,
        )

    def shown(name, path, ref="org-bot/release-lock"):
        return sh(
            [
                "git",
                "--git-dir",
                os.path.join(remotes, ORG, name + ".git"),
                "show",
                f"{ref}:{path}",
            ],
            check=False,
        ).stdout

    lock_repo("nu")
    ndata = os.path.join(work, "ndata.json")
    with open(ndata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": "nu", "epics": []}]}, fh)
    gh = FakeGitHub()
    res, out = go(gh, task="release-lock", data=ndata)
    check(
        "release-lock: a current lock gets no PR, a lock of another format is skipped",
        "nu release-lock: up to date" in out
        and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")],
    )
    nt_more("two")
    _, n2 = release_lock.make_release(
        rel, nt_repo, "v0.2.0", {"routing-bench-0.2.0.tar.gz": b"rb2", "nt-0.2.0.whl": b"w2"}, env
    )
    gh = RouteGitHub({f"repos/{ORG}/nu/releases?per_page=20": []}, merge_queue=True)
    res, out = go(gh, task="release", data=ndata)  # the hourly group carries release-lock
    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    got = shown("nu", "ns3-tools.lock")
    check(
        "release-lock: a new release gets one auto-merge PR, every value read from it",
        len(post) == 1
        and post[0][2]["head"] == "org-bot/release-lock"
        and post[0][2]["title"].startswith("chore(deps):")
        and "lock-target: ns3-tools.lock@v0.2.0" in post[0][2]["body"]
        and got.startswith("# the ns3-tools release")
        and "NS3_TOOLS_TAG=v0.2.0\n" in got
        and f"ROUTING_BENCH_SHA256={n2['routing-bench-0.2.0.tar.gz']}" in got
        and f"NS3_TOOL_WHEEL_SHA256={n2['nt-0.2.0.whl']}" in got
        and shown("nu", "protocols.lock") == protocols
        and gh.auto_merged() == ["PR_42"],
    )
    bot_pr = {
        "number": 42,
        "node_id": "PR_42",
        "title": TASKS["release-lock"]["title"],
        "body": post[0][2]["body"],
        "head": {"ref": "org-bot/release-lock", "sha": "f00d", "repo": {"full_name": f"{ORG}/nu"}},
        "auto_merge": {"merge_method": "squash"},
    }
    gh = FakeGitHub([bot_pr])
    res, out = go(gh, task="release-lock", data=ndata)
    check(
        "release-lock: the same target is left alone",
        "already proposed in #42" in out and not [c for c in gh.calls if c[0] in ("POST", "PATCH")],
    )
    extra = os.path.join(work, "nu-extra")  # the branch carries more than this run's change
    sh(
        [
            "git",
            "clone",
            "-q",
            "-b",
            "org-bot/release-lock",
            os.path.join(remotes, ORG, "nu.git"),
            extra,
        ],
        env=env,
    )
    with open(os.path.join(extra, "other.lock"), "w") as fh:
        fh.write("dropped from the bump since\n")
    sh(["git", "-C", extra, "add", "-A"], env=env)
    sh(["git", "-C", extra, "commit", "-q", "-m", "x"], env=env)
    sh(["git", "-C", extra, "push", "-q", "origin", "HEAD:org-bot/release-lock"], env=env)
    gh = FakeGitHub([bot_pr])
    res, out = go(gh, task="release-lock", data=ndata)
    check(
        "release-lock: a branch with a file beyond this run's change is rebuilt (#481)",
        "updated #42 on org-bot/release-lock" in out and not shown("nu", "other.lock"),
    )
    red = {
        f"repos/{ORG}/nu/compare/main...org-bot/release-lock": {"behind_by": 3},
        f"repos/{ORG}/nu/commits/f00d/check-runs?per_page=100": {
            "check_runs": [{"name": "CI gate", "conclusion": "failure"}]
        },
    }
    gh = RouteGitHub(red, open_prs=[bot_pr])
    res, out = go(gh, task="release-lock", data=ndata)
    check(
        "release-lock: behind its base and red, the PR is rebuilt on the base",
        "updated #42 on org-bot/release-lock" in out,
    )
    red[f"repos/{ORG}/nu/commits/f00d/check-runs?per_page=100"] = {
        "check_runs": [{"name": "CI gate", "conclusion": "success"}]
    }
    gh = RouteGitHub(red, open_prs=[bot_pr])
    res, out = go(gh, task="release-lock", data=ndata)
    check("release-lock: behind but green, left to the queue", "already proposed in #42" in out)
    lock_repo("xi")  # a hand bump is open: no competing PR (#478)
    xdata = os.path.join(work, "xdata.json")
    with open(xdata, "w") as fh:
        json.dump({"org": ORG, "repos": [{"name": "xi", "epics": []}]}, fh)
    hand = {
        "number": 7,
        "title": "chore(deps): pin ns3-tools v0.2.0",
        "body": "",
        "head": {"ref": "claude/ns3-tools", "repo": {"full_name": f"{ORG}/xi"}},
    }
    gh = RouteGitHub(
        {f"repos/{ORG}/xi/pulls/7/files?per_page=100&page=1": [{"filename": "ns3-tools.lock"}]},
        open_prs=[hand],
    )
    res, out = go(gh, task="release-lock", data=xdata)
    check(
        "release-lock: a lock an open hand PR changes is left alone",
        "xi release-lock: up to date" in out
        and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")],
    )
    big = {
        f"repos/{ORG}/xi/pulls/7/files?per_page=100&page={n}": [
            {"filename": f"f{n}-{i}"} for i in range(100)
        ]
        for n in range(1, 31)
    }
    gh = RouteGitHub(big, open_prs=[hand])
    res, out = go(gh, task="release-lock", data=xdata)
    check(
        "release-lock: a hand PR whose file list may be truncated holds the lock (fail closed)",
        "3000+ files" in out
        and not [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")],
    )
    xbot = dict(bot_pr, head={**bot_pr["head"], "repo": {"full_name": f"{ORG}/xi"}})
    gh = RouteGitHub(
        {f"repos/{ORG}/xi/pulls/7/files?per_page=100&page=1": [{"filename": "ns3-tools.lock"}]},
        open_prs=[hand, xbot],
    )
    res, out = go(gh, task="release-lock", data=xdata)
    check(
        "release-lock: the bot's open bump closes once a hand PR holds the lock (#481)",
        ("PATCH", f"repos/{ORG}/xi/pulls/42", {"state": "closed"}) in gh.calls
        and "closed #42 as stale" in out,
    )
    # #429-style carry: drifted templates ride along, the org-sync PR stays open
    sync_pr = {
        "number": 5,
        "title": TASKS["org-sync"]["title"],
        "body": "",
        "head": {"ref": "org-bot/org-sync-abcd1234", "repo": {"full_name": f"{ORG}/xi"}},
    }

    def sync_generate(task, repo, clone, data_, out, skip=None):
        if task == "org-sync":
            with open(os.path.join(clone, "SYNCED.md"), "w") as fh:
                fh.write("templates\n")
            return ["org-sync generated"]
        return real_generate(task, repo, clone, data_, out, skip=skip)

    globals()["generate"] = sync_generate
    try:
        gh = FakeGitHub([sync_pr])
        res, out = go(gh, task="release-lock", data=xdata)
    finally:
        globals()["generate"] = real_generate
    post = [c for c in gh.calls if c[0] == "POST" and c[1].endswith("/pulls")]
    check(
        "release-lock: carries the org-sync change and leaves the org-sync PR open",
        len(post) == 1
        and shown("xi", "SYNCED.md") == "templates\n"
        and "NS3_TOOLS_TAG=v0.2.0" in shown("xi", "ns3-tools.lock")
        and not [c for c in gh.calls if c[0] == "PATCH" and c[1].endswith("/pulls/5")]
        and "also carries the org-sync change" in post[0][2]["body"],
    )
    nt_more("three")  # the wheel renamed: a person bumps it, with the code that names it
    release_lock.make_release(
        rel, nt_repo, "v0.3.0", {"routing-bench-0.3.0.tar.gz": b"rb3", "nt2-0.3.0.whl": b"w3"}, env
    )
    gh = FakeGitHub([bot_pr])
    try:
        res, out = go(gh, task="release-lock", data=ndata)
        refused = ""
    except Failure as e:
        refused = str(e)
    check("release-lock: a renamed asset fails that repository", "1 repositories failed" in refused)
    # org_sync.py apply: exit 1 with only stdout is owned sections left alone; anything else fails
    check(
        "apply exit codes",
        not apply_failed(0, "")
        and not apply_failed(1, "  \n")
        and apply_failed(1, "Traceback ...")
        and apply_failed(2, ""),
    )

    # the fan-out throttle (#505): batches, a pause, a wait on the org's queue, a budget
    class QueueGitHub:
        def __init__(self, counts):
            self.counts, self.calls = list(counts), []

        def api(self, method, path, body=None):
            self.calls.append(path)
            return {"total_count": self.counts.pop(0) if self.counts else 0}

    now = [0.0]
    naps = []

    def nap(s):
        naps.append(s)
        now[0] += s

    saved = {
        k: os.environ.pop(k, None)
        for k in (
            "ORG_BOT_BATCH",
            "ORG_BOT_BATCH_PAUSE",
            "ORG_BOT_QUEUE_LIMIT",
            "ORG_BOT_BATCH_WAIT",
        )
    }
    try:
        os.environ.update(
            ORG_BOT_BATCH="2",
            ORG_BOT_BATCH_PAUSE="100",
            ORG_BOT_QUEUE_LIMIT="5",
            ORG_BOT_BATCH_WAIT="300",
        )
        # one repository: the queue reads 9, then 3 -> one extra minute, then the next batch
        qgh = QueueGitHub([9, 3])
        th = Throttle(qgh, ["alpha"], sleep=nap, clock=lambda: now[0])
        got = []
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(4):
                why = th.admit()
                got.append(why)
                if not why:
                    th.done()
        check(
            "throttle: two at once, then pause and wait for the queue",
            got == [None, None, None, None]
            and naps == [100, 60]
            and qgh.calls == [f"repos/{ORG}/alpha/actions/runs?status=queued&per_page=1"] * 2,
        )
        # a queue that never drains: deferred once the budget is spent, and every later one too
        naps.clear()
        now[0] = 0.0
        th = Throttle(QueueGitHub([50] * 20), ["alpha"], sleep=nap, clock=lambda: now[0])
        got = []
        for _ in range(4):
            why = th.admit()
            got.append(why)
            if not why:
                th.done()
        check(
            "throttle: deferred past the budget",
            got[:2] == [None, None]
            and got[2]
            and "deferred: 50 runs queued" in got[2]
            and got[3] == got[2]
            and sum(naps) == 300,
        )
        # ORG_BOT_BATCH=0: off, no API call
        os.environ["ORG_BOT_BATCH"] = "0"
        qgh = QueueGitHub([])
        th = Throttle(qgh, ["alpha"], sleep=nap, clock=lambda: now[0])
        check("throttle off", all(th.admit() is None for _ in range(9)) and qgh.calls == [])
        # propose: a deferred fan-out PR pushes nothing and opens nothing; a pin update is never held
        os.environ["ORG_BOT_BATCH"] = "1"
        th = Throttle(QueueGitHub([99] * 9), ["alpha"], sleep=nap, clock=lambda: now[0])
        th.opened, th.closed = 1, "deferred: test (#505)"
        gh = FakeGitHub()
        tclone = os.path.join(work, "throttle-clone")
        sh(["git", "clone", "-q", clone_url.format(org=ORG, repo="alpha"), tclone], env=env)
        with open(os.path.join(tclone, "README.md"), "a") as fh:
            fh.write("drift\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = propose(gh, "alpha", "org-sync", tclone, [], env, False, "", (), th)
        check(
            "propose: deferred, nothing written",
            got.get("deferred")
            and "deferred: test" in out.getvalue()
            and not [c for c in gh.calls if c[0] != "GET"],
        )
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
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
