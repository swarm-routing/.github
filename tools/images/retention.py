#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Delete a -dev package's versions after 2 days, never one that committed data pins.

    retention.py pinned --org swarm-routing [--out FILE]
    retention.py sweep --org swarm-routing --package anthocnet-dev [--days 2] [--apply]
                       [--summary FILE]
    retention.py --self-test

Development images live in packages named `<repo>-dev` (epic #370, #371) and
are deleted after 2 days by a job of the owning repository's main pipeline
(reusable-dev-image-cleanup.yml), unless committed data pins them.

`pinned` lists what committed data pins: every `sha256:<64 hex>` and every
`ghcr.io/<org>/<package>:<tag>` in the tracked text files of the default
branch of every public, unarchived, non-fork repository of the org, and of
the head of every open pull request of <org>/benchmarks (`git grep -I` on a
shallow clone; binary files are skipped). It prints counts per package; --out
writes the whole list as JSON.

`sweep` runs `pinned` itself, then reads the package's versions and deletes
(with --apply; a dry run otherwise) every version that is
- tagged, and not only with signature tags (`sha256-<hex>`, `sha256-<hex>.sig`,
  `.att`, ...: a cosign signature, an attestation or a referrers index),
- created more than --days days ago,
- not the package's newest image (GHCR refuses to delete the last tagged
  version), and
- not pinned: neither its digest nor any of its tags is in the list;
then the signature versions of each image it deleted, and those whose image
is no longer in the package (left by an earlier sweep whose second delete
failed). The signatures of a kept image are kept.

It never touches an untagged version (the children and attestations of tagged
images, swarm-routing/ns3-containers#36), a package whose name does not end in
`-dev`, or `ns3-dev`, which keeps the frozen official base images (epic #370,
constraint 2; ns3-containers sweeps its own candidates by their tag pattern).
It fails closed: if any repository or pull request cannot be read, nothing is
deleted. A failed delete exits 1, except GHCR's refusal to delete a last
version; a version already gone counts as deleted. Each GitHub call is retried
twice on a transient error (not on a 4xx).
"""

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

PR_REPOS = ("benchmarks",)  # whose open pull requests' heads also pin
FROZEN = ("ns3-dev",)  # ends in -dev, but holds the frozen official images
ACCESSORY = re.compile(r"^sha256-([0-9a-f]{64})(\..+)?$")
LAST = re.compile(r"last (tagged )?version", re.I)
CLIENT = re.compile(r"HTTP 4\d\d")
GONE = re.compile(r"HTTP 404")
ORG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
DELAYS = (5, 20)  # seconds before the 2nd and 3rd attempt


class Refused(Exception):
    """Not a package this tool may sweep."""


def run(cmd):
    """(returncode, stdout) of a command, or (returncode, stdout + stderr) when it fails."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # a missing repo never waits for a password
    p = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    return p.returncode, p.stdout if p.returncode == 0 else p.stdout + p.stderr


def call(cmd, runner, sleep, ok=(0,)):
    """stdout of `cmd` (rc in `ok`); retried on a transient error, never on a 4xx."""
    out = ""
    for i in range(len(DELAYS) + 1):
        rc, out = runner(cmd)
        if rc in ok:
            return out
        if CLIENT.search(out) or i == len(DELAYS):
            break
        sleep(DELAYS[i])
    raise RuntimeError(f"{' '.join(cmd)}: {out.strip()}")


def lines(out):
    return [json.loads(x) for x in out.splitlines() if x.strip()]


def patterns(org):
    """The git grep pattern (POSIX ERE) and its Python twin for one match."""
    grep = (
        rf"ghcr\.io/{org}/[a-z0-9._/-]+(:[a-z0-9_][a-z0-9_.-]*)?(@sha256:[0-9a-f]{{64}})?"
        r"|sha256:[0-9a-f]{64}"
    )
    ref = re.compile(
        rf"ghcr\.io/{org}/([a-z0-9._/-]+)(?::([a-z0-9_][a-z0-9_.-]*))?(?:@(sha256:[0-9a-f]{{64}}))?$",
        re.I,
    )
    return grep, ref


class Pins:
    def __init__(self):
        self.digests = set()  # sha256:<hex>, whichever package names it
        self.tags = {}  # package -> tags
        self.named = {}  # package -> digests named with it (for the counts)
        self.sources = []  # repo or repo#pr scanned

    def add(self, match, ref):
        m = ref.match(match)
        if not m:  # a bare digest
            self.digests.add(match.lower())
            return
        pkg, tag, digest = m.group(1).lower().rstrip("."), m.group(2), m.group(3)
        if tag:
            # `...:v1.0.` at the end of a sentence: keep both readings
            self.tags.setdefault(pkg, set()).update({tag, tag.rstrip(".-")} - {""})
        if digest:
            self.digests.add(digest.lower())
            self.named.setdefault(pkg, set()).add(digest.lower())

    def pins(self, pkg, version):
        return version["name"].lower() in self.digests or bool(
            set(version["tags"]) & self.tags.get(pkg, set())
        )

    def as_json(self):
        return {
            "sources": self.sources,
            "digests": sorted(self.digests),
            "tags": {p: sorted(t) for p, t in sorted(self.tags.items())},
        }

    def summary(self):
        repos = [s for s in self.sources if "#" not in s]
        out = [
            f"scanned {len(repos)} default branches and {len(self.sources) - len(repos)} "
            f"open pull request heads: {len(self.digests)} digests, "
            f"{sum(map(len, self.tags.values()))} tags pinned"
        ]
        for p in sorted(set(self.tags) | set(self.named)):
            out.append(
                f"  {p}: {len(self.named.get(p, ()))} digests, {len(self.tags.get(p, ()))} tags"
            )
        return "\n".join(out)


def grep(d, rev, org, pins, runner, sleep):
    pattern, ref = patterns(org)
    out = call(["git", "-C", d, "grep", "-I", "-h", "-o", "-i", "-E", "-e", pattern, rev, "--"],
               runner, sleep, ok=(0, 1))  # fmt: skip
    for m in out.split():
        pins.add(m, ref)


def pinned(org, runner=run, sleep=time.sleep, base="https://github.com", log=print):
    """Pins of every public repository's default branch and every open benchmarks PR head."""
    if not ORG.match(org):
        raise RuntimeError(f"not an organization name: {org!r}")
    repos = lines(call(["gh", "api", "--paginate", f"orgs/{org}/repos?type=public&per_page=100",
                        "--jq", ".[] | {name, private, archived, fork}"], runner, sleep))  # fmt: skip
    names = sorted(r["name"] for r in repos if not (r["private"] or r["archived"] or r["fork"]))
    for r in PR_REPOS:
        if r not in names:  # its manifests would go unread: fail closed
            raise RuntimeError(f"{org}/{r} is not among the org's public repositories")
    pins = Pins()
    with tempfile.TemporaryDirectory(prefix="retention-") as tmp:
        for name in names:
            d = os.path.join(tmp, name)
            call(["git", "clone", "--depth", "1", "--quiet", f"{base}/{org}/{name}.git", d],
                 runner, sleep)  # fmt: skip
            if runner(["git", "-C", d, "rev-parse", "--verify", "--quiet", "HEAD"])[0] != 0:
                log(f"{org}/{name}: empty repository, nothing to read")
                shutil.rmtree(d)
                continue
            grep(d, "HEAD", org, pins, runner, sleep)
            pins.sources.append(name)
            if name in PR_REPOS:
                prs = call(["gh", "api", "--paginate", f"repos/{org}/{name}/pulls?state=open&per_page=100",
                            "--jq", ".[].number"], runner, sleep).split()  # fmt: skip
                for n in sorted(map(int, prs)):
                    call(["git", "-C", d, "fetch", "--depth", "1", "--quiet", "origin",
                          f"pull/{n}/head"], runner, sleep)  # fmt: skip
                    grep(d, "FETCH_HEAD", org, pins, runner, sleep)
                    pins.sources.append(f"{name}#{n}")
            shutil.rmtree(d)
    if not pins.sources:
        raise RuntimeError(f"no repository of {org} could be read")
    return pins


def when(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def plan(pkg, versions, pins, cutoff):
    """(images to delete, accessories to delete by subject digest, orphans, kept counts)."""
    images, accessories = [], {}
    for v in versions:
        if not v["tags"]:
            continue
        subjects = {m.group(1) for m in map(ACCESSORY.match, v["tags"]) if m}
        if len(subjects) == 1 and all(ACCESSORY.match(t) for t in v["tags"]):
            accessories.setdefault("sha256:" + subjects.pop(), []).append(v)
        else:
            images.append(v)
    by_age = sorted(versions, key=lambda v: (when(v["created_at"]), v["id"]))
    newest_image = max(images, key=lambda v: (when(v["created_at"]), v["id"]), default=None)
    newest = {by_age[-1]["id"]} if by_age else set()
    if newest_image:
        newest.add(newest_image["id"])
    kept = {"pinned": 0, "younger": 0, "untagged": 0, "newest": 0}
    kept["untagged"] = sum(1 for v in versions if not v["tags"])
    delete = []
    for v in images:
        if pins.pins(pkg, v):
            kept["pinned"] += 1
        elif when(v["created_at"]) >= cutoff:
            kept["younger"] += 1
        elif v["id"] in newest:
            kept["newest"] += 1
        else:
            delete.append(v)
    present = {v["name"].lower() for v in versions}
    orphans = [
        a
        for subject, acc in accessories.items()
        if subject not in present
        for a in acc
        if when(a["created_at"]) < cutoff and a["id"] not in newest and not pins.pins(pkg, a)
    ]
    signed = {
        v["name"].lower(): [
            a for a in accessories.get(v["name"].lower(), [])
            if a["id"] not in newest and not pins.pins(pkg, a)
        ]
        for v in delete
    }  # fmt: skip
    return delete, signed, orphans, kept


def describe(v):
    return f"{v['id']} {v['name'][:19]} {','.join(v['tags']) or '-'} {v['created_at']}"


def sweep(org, pkg, days=2, apply=False, runner=run, sleep=time.sleep, now=None,
          base="https://github.com", log=print):  # fmt: skip
    """Delete (or list, without apply) what goes; returns (summary line, failures)."""
    if not pkg.endswith("-dev") or pkg in FROZEN:
        raise Refused(
            f"refused: '{pkg}' is not a development package (only <repo>-dev; "
            f"{', '.join(FROZEN)} keeps frozen official images)"
        )
    path = f"/orgs/{org}/packages/container/{pkg}/versions"
    try:
        out = call(["gh", "api", "--paginate", f"{path}?per_page=100",
                    "--jq", ".[] | {id, name, created_at, tags: .metadata.container.tags}"],
                   runner, sleep)  # fmt: skip
    except RuntimeError as e:
        if not GONE.search(str(e)):
            raise
        log(
            f"::warning::no package {org}/{pkg} (nothing pushed yet, or no access): nothing to sweep"
        )
        return f"`{pkg}`: no package, nothing swept", 0
    versions = lines(out)
    pins = pinned(org, runner, sleep, base, log)
    log(pins.summary())
    for v in versions:
        v["tags"] = v.get("tags") or []
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=days)
    delete, signed, orphans, kept = plan(pkg, versions, pins, cutoff)
    verb = "deleted" if apply else "would delete"
    done = {"images": 0, "signatures": 0}
    failures = 0

    def remove(v, kind):
        nonlocal failures
        if not apply:
            log(f"{verb} {kind} {describe(v)}")
            done["images" if kind == "image" else "signatures"] += 1
            return True
        try:
            call(["gh", "api", "-X", "DELETE", f"{path}/{v['id']}"], runner, sleep)
        except RuntimeError as e:
            if GONE.search(str(e)):  # another sweep was first
                log(f"already gone: {describe(v)}")
                return True
            if LAST.search(str(e)):
                log(f"::notice::GHCR keeps its last version: {describe(v)}")
                return False
            log(f"::error::{kind} {describe(v)}: {e}")
            failures += 1
            return False
        log(f"{verb} {kind} {describe(v)}")
        done["images" if kind == "image" else "signatures"] += 1
        return True

    for v in delete:
        if remove(v, "image"):  # its signatures go only once the image is gone
            for a in signed[v["name"].lower()]:
                remove(a, "signature")
    for a in orphans:
        remove(a, "signature")
    line = (
        f"`{pkg}`: {verb} {done['images']} images and {done['signatures']} signature or "
        f"attestation versions created before {cutoff:%Y-%m-%d %H:%M} UTC; kept "
        f"{kept['pinned']} pinned, {kept['younger']} younger, {kept['untagged']} untagged, "
        f"{kept['newest']} newest; {failures} failed"
    )
    return line, failures


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    q = sub.add_parser("pinned", help="list the digests and tags committed files pin")
    q.add_argument("--org", required=True)
    q.add_argument("--out", help="write the whole list as JSON")
    s = sub.add_parser("sweep", help="delete a -dev package's unpinned versions older than --days")
    s.add_argument("--org", required=True)
    s.add_argument("--package", required=True, help="<repo>-dev")
    s.add_argument("--days", type=float, default=2)
    s.add_argument("--apply", action="store_true", help="delete; without it, a dry run")
    s.add_argument("--summary", help="append the result line (GITHUB_STEP_SUMMARY)")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    try:
        if a.cmd == "pinned":
            pins = pinned(a.org)
            print(pins.summary())
            if a.out:
                with open(a.out, "w") as f:
                    json.dump(pins.as_json(), f, indent=1)
                    f.write("\n")
            return 0
        if a.cmd == "sweep":
            line, failures = sweep(a.org, a.package, a.days, a.apply)
            print(line)
            if a.summary:
                with open(a.summary, "a") as f:
                    f.write(line + "\n")
            return 1 if failures else 0
    except Refused as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2
    except (RuntimeError, KeyError, ValueError) as e:  # a JSON or date that does not parse
        print(f"::error::{e}; nothing (more) was deleted", file=sys.stderr)
        return 1
    p.error("a command is required: pinned or sweep")


# --- self-test -----------------------------------------------------------------

NOW = dt.datetime(2026, 11, 13, 12, 0, tzinfo=dt.timezone.utc)


def h(n):
    return f"{n:064x}"


def ago(days):
    return (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGitHub:
    """`gh api` against dicts; git runs for real, on local file:// remotes."""

    def __init__(self, repos, prs, packages, fail=(), last=(), vanished=(), transient=0):
        self.repos = repos  # [{name, private, archived, fork}]
        self.prs = prs  # open pull request numbers of benchmarks
        self.packages = packages  # name -> [versions]
        self.fail = set(fail)  # ids whose delete keeps failing (HTTP 500)
        self.last = set(last)  # ids GHCR refuses as its last version
        self.vanished = set(vanished)  # ids listed but already deleted (HTTP 404)
        self.transient = transient  # 502s before the repository list answers
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "git":
            return run(cmd)
        if "DELETE" in cmd:
            pkg, vid = cmd[-1].split("/")[-3], int(cmd[-1].split("/")[-1])
            if vid in self.fail:
                return 1, "gh: Internal Server Error (HTTP 500)"
            if vid in self.last:
                return 1, ("gh: You cannot delete the last tagged version of a package. "
                           "You must delete the package instead. (HTTP 400)")  # fmt: skip
            if vid in self.vanished:
                return 1, "gh: Not Found (HTTP 404)"
            self.packages[pkg] = [v for v in self.packages[pkg] if v["id"] != vid]
            return 0, ""
        url = cmd[3]
        if "/repos?" in url:
            if self.transient:
                self.transient -= 1
                return 1, "gh: Bad Gateway (HTTP 502)"
            return 0, "\n".join(json.dumps(r) for r in self.repos)
        if "/pulls?" in url:
            return 0, "\n".join(map(str, self.prs))
        pkg = url.split("/")[-2]
        if pkg not in self.packages:
            return 1, "gh: Not Found (HTTP 404)"
        return 0, "\n".join(
            json.dumps({**v, "tags": v["tags"] or None}) for v in self.packages[pkg]
        )

    def attempted(self):
        return {int(c[-1].split("/")[-1]) for c in self.calls if "DELETE" in c}

    def left(self, pkg):
        return {v["id"] for v in self.packages[pkg]}


def git(*args, cwd=None):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-c", "init.defaultBranch=main", *args], cwd=cwd, check=True,
                   capture_output=True)  # fmt: skip


def remote(root, name, files, pr=None):
    """A bare remote root/o/<name>.git with `files` on main (None: empty); `pr`: (n, files)."""
    work, bare = os.path.join(root, "work", name), os.path.join(root, "o", f"{name}.git")
    os.makedirs(work)
    git("init", "-q", work)
    git("init", "-q", "--bare", bare)
    for ref, batch in ((("refs/heads/main", files),) if files else ()) + ((pr,) if pr else ()):
        for path, body in batch.items():
            os.makedirs(os.path.dirname(os.path.join(work, path)), exist_ok=True)
            with open(os.path.join(work, path), "wb") as f:
                f.write(body if isinstance(body, bytes) else body.encode())
        git("add", "-A", cwd=work)
        git("commit", "-qm", ref, cwd=work)
        git("push", "-q", bare, f"HEAD:{ref}", cwd=work)


def self_test():
    failures = 0

    def case(name, cond, detail=""):
        nonlocal failures
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
        failures += not cond

    pinned_d, pr_d, old_d, young_d = (f"sha256:{h(n)}" for n in (1, 2, 3, 4))
    root = tempfile.mkdtemp(prefix="retention-test-")
    try:
        remote(root, "benchmarks", {
            "runs/r/manifest.json": json.dumps({"campaign_image": f"ghcr.io/o/x-dev@{pinned_d}"}),
            "runs/r/cells/a.txt": f"##PROV## base=ghcr.io/o/ns3-dev:3.48-optimized-abcdef0@sha256:{h(9)}\n",
        }, pr=("refs/pull/7/head", {"runs/s.json": f'{{"image": "ghcr.io/O/x-dev:pr-tag@{pr_d}"}}'}))  # fmt: skip
        remote(root, "ARA", {
            "tools/bench/campaigns/anchor.yaml": "# runs on ghcr.io/o/x-dev:pinned-tag.\n",
            "data/blob.bin": b"\x00\x01" + f"sha256:{h(77)}".encode(),
        })  # fmt: skip
        remote(root, "empty", None)
        remote(root, "old", {"plan/p.yaml": f"image: ghcr.io/o/x-dev@sha256:{h(66)}\n"})
        base = "file://" + root
        repo = {"private": False, "archived": False, "fork": False}
        repos = [
            {**repo, "name": "benchmarks"},
            {**repo, "name": "ARA"},
            {**repo, "name": "empty"},
            {**repo, "name": "old", "archived": True},
            {**repo, "name": "forked", "fork": True},
            {**repo, "name": "papers", "private": True},
        ]

        def package():
            return [
                {"id": 1, "name": pinned_d, "tags": ["c1-b1-optimized"], "created_at": ago(10)},
                {"id": 2, "name": f"sha256:{h(11)}", "tags": ["pinned-tag"], "created_at": ago(9)},
                {"id": 3, "name": old_d, "tags": ["old-unpinned"], "created_at": ago(5)},
                {"id": 4, "name": f"sha256:{h(12)}", "tags": [f"sha256-{h(3)}.sig"], "created_at": ago(5)},
                {"id": 5, "name": f"sha256:{h(13)}", "tags": [f"sha256-{h(3)}"], "created_at": ago(5)},
                {"id": 6, "name": f"sha256:{h(14)}", "tags": [f"sha256-{h(1)}.sig"], "created_at": ago(10)},
                {"id": 7, "name": young_d, "tags": ["young"], "created_at": ago(1)},
                {"id": 8, "name": f"sha256:{h(15)}", "tags": [], "created_at": ago(30)},
                {"id": 9, "name": pr_d, "tags": ["pr-tag"], "created_at": ago(10)},
                {"id": 10, "name": f"sha256:{h(16)}", "tags": [f"sha256-{h(5)}.sig"], "created_at": ago(6)},
                {"id": 11, "name": f"sha256:{h(66)}", "tags": ["archived-only"], "created_at": ago(8)},
                {"id": 12, "name": f"sha256:{h(17)}", "tags": [f"sha256-{h(4)}.att"], "created_at": ago(1)},
            ]  # fmt: skip

        def go(pkg="x-dev", apply=True, repos=repos, prs=(7,), packages=None, **kw):
            gh = FakeGitHub(repos, list(prs), packages or {"x-dev": package()}, **kw)
            logs = []
            try:
                line, failed = sweep("o", pkg, 2, apply, gh, lambda s: None, NOW, base, logs.append)
                return gh, line, failed, logs, None
            except (RuntimeError, Refused) as e:
                return gh, None, None, logs, str(e)

        pins = pinned("o", FakeGitHub(repos, [7], {}), lambda s: None, base, lambda s: None)
        case("pinned: every public default branch and the open benchmarks PR head",
             pins.sources == ["ARA", "benchmarks", "benchmarks#7"], pins.sources)  # fmt: skip
        case("pinned: the digests of a manifest, a ##PROV## line and a PR head",
             {pinned_d, pr_d, f"sha256:{h(9)}"} <= pins.digests, pins.digests)  # fmt: skip
        case("pinned: tags, the one at a sentence's end without its full stop too",
             {"pinned-tag", "pr-tag"} <= pins.tags.get("x-dev", set())
             and "3.48-optimized-abcdef0" in pins.tags.get("ns3-dev", set()), pins.tags)  # fmt: skip
        case("pinned: a binary file and an archived repository are not read",
             not {f"sha256:{h(77)}", f"sha256:{h(66)}"} & pins.digests, pins.digests)  # fmt: skip
        case("pinned: counts per package",
             "x-dev: 2 digests, 3 tags" in pins.summary() and "ns3-dev: 1 digests" in pins.summary(),
             pins.summary())  # fmt: skip

        gh, line, failed, logs, err = go()
        gone = {v["id"] for v in package()} - gh.left("x-dev")
        clones = [c[-2] for c in gh.calls if c[:2] == ["git", "clone"]]
        case("only public, unarchived, non-fork repositories are cloned",
             sorted(c.rsplit("/", 1)[-1] for c in clones) == ["ARA.git", "benchmarks.git", "empty.git"],
             clones)  # fmt: skip
        case("a pinned digest is kept, with its signature", not {1, 6} & gone, gone)
        case("a pinned tag is kept", 2 not in gone, gone)
        case("an open benchmarks PR's pin is kept", 9 not in gone, gone)
        case("an unpinned image older than 2 days goes, with its .sig and referrers versions",
             {3, 4, 5} <= gone, gone)  # fmt: skip
        case("a younger image is kept, with its attestation", not {7, 12} & gone, gone)
        case("an untagged version is kept", 8 not in gone, gone)
        case("an old signature whose image is no longer there goes", 10 in gone, gone)
        case("an image only an archived repository names goes", 11 in gone, gone)
        order = [int(c[-1].rsplit("/", 1)[1]) for c in gh.calls if "DELETE" in c]
        case("an image goes before its signatures", order.index(3) < order.index(4), order)
        case("the summary line",
             line and "deleted 2 images and 3 signature" in line
             and "kept 3 pinned, 1 younger, 1 untagged, 0 newest; 0 failed" in line
             and failed == 0, line)  # fmt: skip

        gh, line, failed, logs, err = go(apply=False)
        case("a dry run deletes nothing and lists what would go",
             not gh.attempted() and sum("would delete" in x for x in logs) == 5
             and "would delete 2 images" in line, (gh.attempted(), logs, line))  # fmt: skip

        newest = [
            {"id": 20, "name": f"sha256:{h(20)}", "tags": ["a"], "created_at": ago(5)},
            {"id": 21, "name": f"sha256:{h(21)}", "tags": ["b"], "created_at": ago(4)},
            {"id": 22, "name": f"sha256:{h(22)}", "tags": [f"sha256-{h(21)}.sig"], "created_at": ago(4)},
            {"id": 23, "name": f"sha256:{h(23)}", "tags": [], "created_at": ago(3)},
        ]  # fmt: skip
        gh, line, failed, _, _ = go("y-dev", packages={"y-dev": newest})
        case("the newest image is kept, with its signature, even when it is old",
             gh.left("y-dev") == {21, 22, 23} and "1 newest" in line and failed == 0, line)  # fmt: skip

        for pkg in ("ns3-tools-ns3-campaign", "anthocnet-ns3", "ns3-dev"):
            gh, _, _, _, err = go(pkg)
            case(f"'{pkg}' is refused and never read",
                 err and "refused" in err and not gh.calls, (err, gh.calls))  # fmt: skip
        with contextlib.redirect_stderr(io.StringIO()):
            rc = main(["sweep", "--org", "o", "--package", "ns3-tools-ns3"])
        case("main exits 2 on a refused package, before any call", rc == 2, rc)

        gh, line, failed, logs, err = go(fail={3}, last={11})
        case("a failed delete is counted (main exits 1)", failed == 1 and "1 failed" in line, line)
        case("the signatures of an image whose delete failed are not even tried",
             not {4, 5} & gh.attempted() and 3 in gh.left("x-dev"), gh.attempted())  # fmt: skip
        case("GHCR refusing its last version is no failure",
             11 in gh.left("x-dev") and any("last version" in x for x in logs), logs)  # fmt: skip
        gh, line, failed, logs, err = go(vanished={3})
        case("a version already gone counts as deleted, and its signatures follow",
             failed == 0 and {4, 5} <= gh.attempted(), (line, gh.attempted()))  # fmt: skip

        gh, line, failed, logs, err = go("z-dev")
        case("a package not pushed yet: a warning, nothing cloned or deleted",
             failed == 0 and "no package" in line and not any(c[0] == "git" for c in gh.calls),
             (line, logs))  # fmt: skip
        gh, line, failed, _, err = go(transient=2)
        case("a transient API error is retried", err is None and failed == 0, err)
        for name, kw, needle in (
            ("an API that keeps failing", {"transient": 3}, "502"),
            ("a repository that cannot be cloned",
             {"repos": [*repos, {**repo, "name": "missing"}]}, "missing"),
            ("benchmarks missing from the list",
             {"repos": [r for r in repos if r["name"] != "benchmarks"]}, "benchmarks"),
            ("an open PR whose head cannot be fetched", {"prs": (7, 8)}, "pull/8/head"),
        ):  # fmt: skip
            gh, _, _, _, err = go(**kw)
            case(f"fail closed: {name} stops it before any delete",
                 err and needle in err and not gh.attempted(), (err, gh.attempted()))  # fmt: skip
    finally:
        shutil.rmtree(root)
    print(f"\n{'all ok' if not failures else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
