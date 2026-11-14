#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A release lock: which released version of another org repository a repository
builds on, checked against the release itself (swarm-routing/ns3-swarm-core#134).

A lock is a `KEY=VALUE` file (`#` comments), the shape of AntHocNet's
`ns3-tools.lock`. Every key but the hashes starts with one prefix, `<P>_`:

    <P>_REPO=swarm-routing/ns3-swarm-core
    <P>_TAG=vX.Y.Z
    <P>_COMMIT=<40 hex: the commit the tag names>
    <P>_VERSION=X.Y.Z
    <P>_SHA256=<64 hex>          one or more `*_SHA256` keys, one per asset used
                                 (`ns3-tools.lock` names them ROUTING_BENCH_SHA256, ...)
    <P>_ASSET=<name>             optional: the asset `<P>_SHA256` is the hash of

`verify` checks the lock against the release: the tag still names the commit
(`git ls-remote`, no token), the version is the tag's, and each `*_SHA256` is the
hash of an asset in the release's `SHA256SUMS` (the asset `<P>_ASSET` names, when
given). `latest` prints the newest published release of the lock's repository
(the highest `vX.Y.Z` tag whose `SHA256SUMS` downloads), so a check can say a
newer release exists. `render` writes a lock for a release, every value read
from it (the commit from git, the hash from `SHA256SUMS`), never typed. Nothing
here clones a repository or reads a token. Stdlib only, one summary line per
result (AntHocNet ADR-0014).

Usage:
  release_lock.py show LOCK
  release_lock.py verify LOCK [--base URL]
  release_lock.py latest LOCK [--base URL]
  release_lock.py render --prefix P --repo OWNER/NAME --tag vX.Y.Z --asset NAME [--base URL]
  release_lock.py --self-test

`--base` (default https://github.com) is where `<base>/<repo>.git` and
`<base>/<repo>/releases/download/<tag>/<asset>` live; the self-test passes a
`file://` tree.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

GITHUB = "https://github.com"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
FIELDS = ("REPO", "TAG", "COMMIT", "VERSION")


class LockError(Exception):
    pass


def parse_text(text, name="lock"):
    """(prefix, values) from a lock's text; LockError names what is wrong."""
    values = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            raise LockError(f"{name}:{n}: not KEY=VALUE: {raw!r}")
        if key in values:
            raise LockError(f"{name}:{n}: {key} given twice")
        values[key] = value
    repos = [k for k in values if k.endswith("_REPO")]
    if len(repos) != 1:
        raise LockError(f"{name}: want exactly one *_REPO key, found {len(repos)}")
    prefix = repos[0][: -len("_REPO")]
    stray = [k for k in values if not k.startswith(prefix + "_") and not k.endswith("_SHA256")]
    if stray:
        raise LockError(f"{name}: keys outside the prefix {prefix}_: {', '.join(stray)}")
    missing = [f"{prefix}_{f}" for f in FIELDS if f"{prefix}_{f}" not in values]
    if missing:
        raise LockError(f"{name}: missing {', '.join(missing)}")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", values[f"{prefix}_REPO"]):
        raise LockError(f"{name}: {prefix}_REPO is not owner/name")
    tag, version = values[f"{prefix}_TAG"], values[f"{prefix}_VERSION"]
    if not SEMVER.match(tag):
        raise LockError(f"{name}: {prefix}_TAG {tag} is not vX.Y.Z")
    if tag != f"v{version}":
        raise LockError(f"{name}: {prefix}_VERSION {version} is not the tag's ({tag})")
    if not HEX40.match(values[f"{prefix}_COMMIT"]):
        raise LockError(f"{name}: {prefix}_COMMIT is not a 40-character commit")
    shas = sha_keys(prefix, values)
    if not shas:
        raise LockError(f"{name}: no *_SHA256 key")
    if f"{prefix}_ASSET" in values and f"{prefix}_SHA256" not in values:
        raise LockError(f"{name}: {prefix}_ASSET needs {prefix}_SHA256, its hash")
    for k in shas:
        if not HEX64.match(values[k]):
            raise LockError(f"{name}: {k} is not a 64-character sha256")
    return prefix, values


def parse(path):
    """A lock file below the current directory (a relative path only: the lock is
    read from the repository it pins, never from elsewhere)."""
    here = os.path.realpath(os.getcwd())
    full = os.path.realpath(os.path.join(here, path))
    if os.path.isabs(path) or not full.startswith(here + os.sep):
        raise LockError(f"{path}: give the lock as a path below the current directory")
    with open(full, encoding="utf-8") as f:
        return parse_text(f.read(), os.path.basename(full))


def sha_keys(prefix, values):
    return sorted(k for k in values if k.endswith("_SHA256"))


REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ASSET_NAME = re.compile(r"^[A-Za-z0-9_.+-]+$")


def checked_base(base):
    """GitHub, or a file:// tree (the self-tests); nothing else is fetched from."""
    base = base.rstrip("/")
    if base != GITHUB and not base.startswith("file:///"):
        raise LockError(f"--base {base}: only {GITHUB} or a file:// tree")
    return base


def checked_repo(repo):
    if not REPO.match(repo) or ".." in repo:
        raise LockError(f"{repo}: not owner/name")
    return repo


def git_url(base, repo):
    return f"{checked_base(base)}/{checked_repo(repo)}.git"


def download_url(base, repo, tag, asset):
    if not SEMVER.match(tag) or not ASSET_NAME.match(asset):
        raise LockError(f"{tag}/{asset}: not a release tag and asset name")
    return f"{checked_base(base)}/{checked_repo(repo)}/releases/download/{tag}/{asset}"


def tags(base, repo):
    """{tag: commit} for the repository's tags, annotated tags peeled (git ls-remote)."""
    r = subprocess.run(
        ["git", "ls-remote", "--tags", "--", git_url(base, repo)], capture_output=True, text=True
    )
    if r.returncode:
        raise LockError(f"git ls-remote {git_url(base, repo)}: {r.stderr.strip()}")
    out, peeled = {}, {}
    for line in r.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/") :]
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            out[name] = sha
    out.update(peeled)
    return out


def sha256sums(base, repo, tag):
    """{asset: sha256} from the release's SHA256SUMS, or None when it has none."""
    url = download_url(base, repo, tag, "SHA256SUMS")
    try:
        with urllib.request.urlopen(url, timeout=60) as r:  # GitHub or file:// only
            text = r.read().decode("utf-8")
    except (urllib.error.URLError, OSError):
        return None
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and HEX64.match(parts[0]):
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def version_key(tag):
    m = SEMVER.match(tag)
    return tuple(int(x) for x in m.groups()) if m else None


def verify(prefix, values, base=GITHUB):
    """Problems with the lock against its release (empty: it verifies)."""
    repo, tag, commit = (values[f"{prefix}_{f}"] for f in ("REPO", "TAG", "COMMIT"))
    problems = []
    named = tags(base, repo).get(tag)
    if named is None:
        problems.append(f"{repo} has no tag {tag}")
    elif named != commit:
        problems.append(f"{repo} tag {tag} names {named}, the lock says {commit}")
    sums = sha256sums(base, repo, tag)
    if sums is None:
        return problems + [f"{repo} release {tag} has no SHA256SUMS asset"]
    by_hash = {}
    for asset, h in sums.items():
        by_hash.setdefault(h, []).append(asset)
    asset = values.get(f"{prefix}_ASSET")
    for k in sha_keys(prefix, values):
        h = values[k]
        if k == f"{prefix}_SHA256" and asset:
            if sums.get(asset) != h:
                problems.append(
                    f"{k}: {asset} in {tag}'s SHA256SUMS is {sums.get(asset, 'absent')}, "
                    f"the lock says {h}"
                )
        elif h not in by_hash:
            problems.append(f"{k}: {h} is no asset's sha256 in {tag}'s SHA256SUMS")
    return problems


def latest(base, repo):
    """(tag, commit) of the newest published release (highest vX.Y.Z with a SHA256SUMS)."""
    found = tags(base, repo)
    for tag in sorted((t for t in found if version_key(t)), key=version_key, reverse=True):
        if sha256sums(base, repo, tag) is not None:
            return tag, found[tag]
    return None, None


def render(prefix, repo, tag, asset_template, base=GITHUB, header=""):
    """A lock's text for a release, every value read from it. `asset_template` may
    hold `{version}`."""
    m = SEMVER.match(tag)
    if not m:
        raise LockError(f"{tag} is not vX.Y.Z")
    version = tag[1:]
    commit = tags(base, repo).get(tag)
    if commit is None:
        raise LockError(f"{repo} has no tag {tag}")
    sums = sha256sums(base, repo, tag)
    if sums is None:
        raise LockError(f"{repo} release {tag} has no SHA256SUMS asset")
    asset = asset_template.format(version=version)
    if asset not in sums:
        raise LockError(f"{repo} release {tag}: no {asset} in SHA256SUMS")
    lines = [
        f"{prefix}_REPO={repo}",
        f"{prefix}_TAG={tag}",
        f"{prefix}_COMMIT={commit}",
        f"{prefix}_VERSION={version}",
        f"{prefix}_ASSET={asset}",
        f"{prefix}_SHA256={sums[asset]}",
    ]
    return header + "\n".join(lines) + "\n"


# --- self-test: a file:// tree with a git repository and release assets ------------


def make_release(root, repo, tag, assets, env):
    """Tag the fixture repository's HEAD as `tag` (annotated) and publish SHA256SUMS."""
    import hashlib

    git_dir = os.path.join(root, repo + ".git")
    subprocess.run(["git", "-C", git_dir, "tag", "-a", tag, "-m", tag], check=True, env=env)
    d = os.path.join(root, repo, "releases", "download", tag)
    os.makedirs(d, exist_ok=True)
    lines = []
    for name, data in assets.items():
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    with open(os.path.join(d, "SHA256SUMS"), "w") as f:
        f.write("\n".join(lines) + "\n")
    head = subprocess.run(
        ["git", "-C", git_dir, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return head, dict(line.split()[::-1] for line in lines)


def fixture_repo(root, repo, env):
    """A repository at <root>/<repo>.git with one commit; returns a function that
    adds a commit."""
    git_dir = os.path.join(root, repo + ".git")
    os.makedirs(git_dir)
    subprocess.run(["git", "init", "-q", "-b", "main", git_dir], check=True, env=env)

    def commit(msg):
        with open(os.path.join(git_dir, "f.txt"), "a") as f:
            f.write(msg + "\n")
        subprocess.run(["git", "-C", git_dir, "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", git_dir, "commit", "-q", "-m", msg], check=True, env=env)

    commit("one")
    return commit


def self_test():
    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    env = dict(os.environ)
    for k in ("GIT_AUTHOR", "GIT_COMMITTER"):
        env[f"{k}_NAME"], env[f"{k}_EMAIL"] = "t", "t@t"
    with tempfile.TemporaryDirectory() as t:
        base = "file://" + t
        repo = "org/lib"
        commit = fixture_repo(t, repo, env)
        c1, s1 = make_release(t, repo, "v0.1.0", {"lib-0.1.0.tar.gz": b"one"}, env)
        commit("two")
        c2, s2 = make_release(
            t, repo, "v0.2.0", {"lib-0.2.0.tar.gz": b"two", "lib-0.2.0.whl": b"w"}, env
        )
        commit("three")
        subprocess.run(  # a tag with no release assets yet: not a published release
            ["git", "-C", os.path.join(t, repo + ".git"), "tag", "v0.3.0"], check=True, env=env
        )

        text = render("LIB", repo, "v0.1.0", "lib-{version}.tar.gz", base, "# a lock\n")
        prefix, values = parse_text(text)
        check(
            "render reads the commit and the hash",
            prefix == "LIB"
            and values["LIB_COMMIT"] == c1
            and values["LIB_SHA256"] == s1["lib-0.1.0.tar.gz"]
            and values["LIB_ASSET"] == "lib-0.1.0.tar.gz",
        )
        check("a rendered lock verifies", verify(prefix, values, base) == [])
        check("latest skips a tag with no SHA256SUMS", latest(base, repo) == ("v0.2.0", c2))

        bad = dict(values, LIB_COMMIT=c2)
        check(
            "a tag that names another commit",
            any("names " + c1 in p for p in verify(prefix, bad, base)),
        )
        bad = dict(values, LIB_SHA256="0" * 64)
        check(
            "a hash that is not the asset's",
            any("lib-0.1.0.tar.gz in v0.1.0's SHA256SUMS" in p for p in verify(prefix, bad, base)),
        )
        # the ns3-tools.lock shape: several *_SHA256 keys, some outside the prefix, no *_ASSET
        multi = (
            f"NT_REPO={repo}\nNT_TAG=v0.2.0\nNT_COMMIT={c2}\nNT_VERSION=0.2.0\n"
            f"NT_SHA256={s2['lib-0.2.0.tar.gz']}\nOTHER_KEY=x\n"
        )
        try:
            parse_text(multi)
            stray = False
        except LockError as e:
            stray = "outside the prefix" in str(e)
        check("keys outside the prefix are refused", stray)
        multi = (
            f"NT_REPO={repo}\nNT_TAG=v0.2.0\nNT_COMMIT={c2}\nNT_VERSION=0.2.0\n"
            f"TAR_SHA256={s2['lib-0.2.0.tar.gz']}\nNT_WHEEL_SHA256={s2['lib-0.2.0.whl']}\n"
        )
        p2, v2 = parse_text(multi)
        check("several hashes, each an asset's: verifies", verify(p2, v2, base) == [])
        v2["NT_WHEEL_SHA256"] = "f" * 64
        check(
            "several hashes, one unknown",
            any("NT_WHEEL_SHA256" in p for p in verify(p2, v2, base)),
        )
        for broken, why in (
            ("X_REPO=a/b\n", "missing"),
            (text.replace("v0.1.0", "v0.1"), "not vX.Y.Z"),
            (text.replace("LIB_VERSION=0.1.0", "LIB_VERSION=0.1.1"), "is not the tag's"),
            (text.replace(c1, c1[:39]), "40-character"),
            (text + "LIB_TAG=v0.1.0\n", "given twice"),
            (text + "nonsense\n", "not KEY=VALUE"),
            (text.replace("LIB_SHA256=", "LIB_OTHER_SHA256="), "needs LIB_SHA256"),
        ):
            try:
                parse_text(broken)
                got = ""
            except LockError as e:
                got = str(e)
            check(f"parse refuses: {why}", why in got)
        try:
            render("LIB", repo, "v0.3.0", "lib-{version}.tar.gz", base)
            got = ""
        except LockError as e:
            got = str(e)
        check("render refuses a release with no SHA256SUMS", "no SHA256SUMS" in got)
        for bad_base in ("http://example.com", "https://evil.example"):
            try:
                tags(bad_base, repo)
                got = ""
            except LockError as e:
                got = str(e)
            check(f"only GitHub or file:// is fetched from: {bad_base}", "only" in got)
        try:
            tags(base, "--upload-pack=x/y")
            got = ""
        except LockError as e:
            got = str(e)
        check("a repository that is not owner/name", "not owner/name" in got)
        try:
            parse("/etc/passwd")
            got = ""
        except LockError as e:
            got = str(e)
        check("a lock outside the current directory is refused", "below the current" in got)
        check(
            "verify a tag that does not exist",
            verify(prefix, dict(values, LIB_TAG="v9.9.9", LIB_VERSION="9.9.9"), base)[0].endswith(
                "no tag v9.9.9"
            ),
        )

    for f in failures:
        print(f"FAIL: {f}")
    print(f"release_lock.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    for name in ("show", "verify", "latest"):
        s = sub.add_parser(name)
        s.add_argument("lock")
        s.add_argument("--base", default=GITHUB)
    r = sub.add_parser("render")
    for opt in ("--prefix", "--repo", "--tag", "--asset"):
        r.add_argument(opt, required=True)
    r.add_argument("--base", default=GITHUB)
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    try:
        if a.cmd == "render":
            sys.stdout.write(render(a.prefix, a.repo, a.tag, a.asset, a.base))
            return 0
        if a.cmd not in ("show", "verify", "latest"):
            p.error("a command, or --self-test")
        prefix, values = parse(a.lock)
        repo, tag = values[f"{prefix}_REPO"], values[f"{prefix}_TAG"]
        if a.cmd == "show":
            print(f"{a.lock}: {repo} {tag} ({values[f'{prefix}_COMMIT']})")
            return 0
        if a.cmd == "verify":
            problems = verify(prefix, values, a.base)
            for x in problems:
                print(f"FAIL {x}")
            print(
                f"{a.lock}: {repo} {tag}: "
                + ("verifies" if not problems else f"{len(problems)} problem(s)")
            )
            return 1 if problems else 0
        newest, commit = latest(a.base, repo)
        if newest is None:
            print(f"{a.lock}: {repo} has no published release")
            return 1
        newer = version_key(newest) > version_key(tag)
        print(
            f"{a.lock}: {repo} locked {tag}, newest release {newest} ({commit[:7]})"
            + (": a newer release exists" if newer else ": current")
        )
        return 0
    except (LockError, OSError) as e:
        print(f"FAIL {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
