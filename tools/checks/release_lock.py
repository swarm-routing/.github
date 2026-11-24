#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A release lock: which released version of another org repository a repository
builds on, checked against the release itself (swarm-routing/swarm-adapter-ns3#134).

A lock is a `KEY=VALUE` file (`#` comments), the shape of AntHocNet's
`ns3-tools.lock`. Every key but the hashes starts with one prefix, `<P>_`:

    <P>_REPO=swarm-routing/swarm-adapter-ns3
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
from it (the commit from git, the hash from `SHA256SUMS`), never typed. `bump`
moves an existing lock to the newest release (org-bot's `release-lock` task,
swarm-routing/.github#478): every line but the release's own values is kept, and
each `*_SHA256` follows its asset, found by its hash in the locked release's
`SHA256SUMS` and named the same in the new one with the version moved
(`routing-bench-0.2.0.tar.gz` -> `routing-bench-0.3.0.tar.gz`); an asset the new
release no longer has under that name (renamed or dropped) is refused, for a
person to bump with the consumer's code that names it. A lock naming a
repository by its name before the 2026-11-22 renames (`RENAMED`,
swarm-routing/.github#672) still verifies, read from the new name, and a bump
writes the new name. A lock whose releases continue in another repository
(`MOVED`: swarm-core's, from swarm-routing/swarm-adapter-ns3 to
swarm-routing/swarm-core, swarm-routing/.github#691) moves there with `latest`
and `bump` once the successor has a release, which counts as newer whatever
its version, so a lock never goes back across the move. A lock on
swarm-adapter-ns3 with `swarm-core.lock` beside it (AntHocNet's
`swarm-adapter-ns3.lock`, swarm-routing/AntHocNet#1218) does not take the newest
release: `bump` moves it to the adapter release whose own `swarm-core.lock` names
the repository's swarm-core tag (check-swarm-core-pin.py's `adapter_for`, which
fetches each adapter tag shallow), and holds it while none does. Nothing
else here fetches a repository, and nothing reads a token. Stdlib only, one summary line per
result (AntHocNet ADR-0014).

Usage:
  release_lock.py show LOCK
  release_lock.py verify LOCK [--base URL]
  release_lock.py latest LOCK [--base URL]
  release_lock.py bump LOCK [--base URL] [--write]
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
# org repositories renamed on 2026-11-22 (swarm-routing/.github#672): GitHub
# redirects their old names for git and release downloads, but a lock is read
# from, and bumped to, the new name
RENAMED = {
    "swarm-routing/ns3-swarm-core": "swarm-routing/swarm-adapter-ns3",
    "swarm-routing/ns3-containers": "swarm-routing/sim-containers",
    "swarm-routing/ns3-tools": "swarm-routing/sim-tools",
}


# a lock whose releases continue in another repository (swarm-routing/.github#691):
# swarm-core released from swarm-routing/swarm-adapter-ns3 up to v1.0.0, from its
# own repository since. Keyed by the lock's prefix too: swarm-adapter-ns3 keeps
# releasing its ns-3 module, which a SWARM_CORE lock does not follow.
MOVED = {("SWARM_CORE", "swarm-routing/swarm-adapter-ns3"): "swarm-routing/swarm-core"}
ADAPTER = "swarm-routing/swarm-adapter-ns3"


def canonical(repo):
    """The repository's current name (`RENAMED`), or `repo` itself."""
    return RENAMED.get(repo, repo)


def next_release(base, prefix, repo):
    """(repo, tag, commit) of the newest published release a lock with `prefix` on
    `repo` can move to: its successor's (`MOVED`) once that has one, which counts
    as newer than any release of the old repository (a lock never goes back across
    the move), else `repo`'s own; (repo, None, None) when there is none."""
    repo = canonical(repo)
    later = MOVED.get((prefix, repo))
    if later:
        tag, commit = latest(base, later)
        if tag:
            return later, tag, commit
    tag, commit = latest(base, repo)
    return repo, tag, commit


def is_newer(repo, tag, new_repo, new_tag):
    """True when `new_repo`'s `new_tag` is past the lock's `repo` `tag`: a release
    of another repository is (`next_release` only returns a successor's), else the
    higher version."""
    if canonical(new_repo) != canonical(repo):
        return True
    return version_key(new_tag) > version_key(tag)


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


def lock_path(path):
    """The real path of a lock below the current directory (a relative path only: the
    lock is read from, and bump writes, the repository it pins, never elsewhere)."""
    here = os.path.realpath(os.getcwd())
    full = os.path.realpath(os.path.join(here, path))
    if os.path.isabs(path) or not full.startswith(here + os.sep):
        raise LockError(f"{path}: give the lock as a path below the current directory")
    return full


def parse(path):
    """A lock file below the current directory (lock_path)."""
    full = lock_path(path)
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
    repo = canonical(repo)
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


def bump(text, base=GITHUB, name="lock", target=None):
    """(new text, old tag, new tag, new commit) moving the lock `text` to the newest
    release, or to `target`, a tag of the lock's own repository (adapter_target),
    or (None, old tag, old tag, old commit) when it is current. Comments, key
    order and every other line stay; LockError when an asset cannot be followed."""
    prefix, values = parse_text(text, name)
    repo, tag = canonical(values[f"{prefix}_REPO"]), values[f"{prefix}_TAG"]
    if target:
        new_repo, newest, commit = repo, target, tags(base, repo).get(target)
        if commit is None:
            raise LockError(f"{name}: {repo} has no tag {target}")
        if target == tag and repo == values[f"{prefix}_REPO"]:
            return None, tag, tag, values[f"{prefix}_COMMIT"]
    else:
        new_repo, newest, commit = next_release(base, prefix, repo)
        if newest is None:
            raise LockError(f"{name}: {repo} has no published release")
        if not is_newer(repo, tag, new_repo, newest):
            return None, tag, tag, values[f"{prefix}_COMMIT"]
    old_ver, new_ver = tag[1:], newest[1:]
    old_sums, new_sums = sha256sums(base, repo, tag), sha256sums(base, new_repo, newest)
    if old_sums is None:
        raise LockError(f"{name}: {repo} release {tag} has no SHA256SUMS asset")
    by_hash = {}
    for a, h in old_sums.items():
        by_hash.setdefault(h, []).append(a)
    new = {
        # a renamed repository's new name (#672), or its successor's (#691)
        f"{prefix}_REPO": new_repo,
        f"{prefix}_TAG": newest,
        f"{prefix}_COMMIT": commit,
        f"{prefix}_VERSION": new_ver,
    }
    asset_key = f"{prefix}_ASSET"
    for k in sha_keys(prefix, values):
        old = values[asset_key] if k == f"{prefix}_SHA256" and asset_key in values else None
        if old is None:
            named = by_hash.get(values[k], [])
            if not named:
                raise LockError(f"{name}: {k} is no asset's sha256 in {tag}'s SHA256SUMS")
            if len(named) > 1:  # identical contents: which one the consumer fetches is unknown
                raise LockError(
                    f"{name}: {k} is the sha256 of {', '.join(sorted(named))} in {tag}: "
                    "ambiguous; bump this lock by hand"
                )
            old = named[0]
        if old_ver not in old:
            raise LockError(f"{name}: {k}'s asset {old} does not carry the version {old_ver}")
        moved = old.replace(old_ver, new_ver)
        if moved not in new_sums:
            raise LockError(
                f"{name}: {new_repo} {newest} has no {moved} ({k}, {old} in {tag}): the asset "
                "was renamed or dropped; bump this lock by hand, with the code that names it"
            )
        new[k] = new_sums[moved]
        if k == f"{prefix}_SHA256" and asset_key in values:
            new[asset_key] = moved
    lines = []
    for raw in text.splitlines(keepends=True):
        key = raw.split("=", 1)[0].strip()
        if "=" in raw and not raw.lstrip().startswith("#") and key in new:
            eol = "\n" if raw.endswith("\n") else ""
            raw = f"{raw[: len(raw) - len(raw.lstrip())]}{key}={new[key]}{eol}"
        lines.append(raw)
    out = "".join(lines)
    p2, v2 = parse_text(out, name)
    problems = verify(p2, v2, base)
    if problems:
        raise LockError(f"{name}: the bumped lock does not verify: {'; '.join(problems)}")
    return out, tag, newest, commit


def adapter_target(full, prefix, values, base=GITHUB):
    """For a lock on swarm-adapter-ns3 with swarm-core.lock beside it (AntHocNet's
    `swarm-adapter-ns3.lock`, swarm-routing/AntHocNet#1218): (True, tag) of the
    adapter release whose own swarm-core.lock names the same swarm-core release
    (check-swarm-core-pin.py's adapter_for, the ns-3 dependency's rule), tag None
    while none ships it; (False, None) for any other lock, which takes the newest
    release. Read from the adapter's tags, never typed."""
    core_lock = os.path.join(os.path.dirname(full), "swarm-core.lock")
    if canonical(values[f"{prefix}_REPO"]) != ADAPTER or not os.path.isfile(core_lock):
        return False, None
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "check_swarm_core_pin", os.path.join(here, "check-swarm-core-pin.py")
    )
    pin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pin)
    with open(core_lock, encoding="utf-8") as f:
        p, v = parse_text(f.read(), "swarm-core.lock")
    if canonical(v[f"{p}_REPO"]) != pin.CORE_REPO:
        return False, None  # swarm-core not yet on its own repository (#691)
    return True, pin.adapter_for(base, v[f"{p}_TAG"])[0]


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

        # bump (#478): the ns3-tools.lock shape follows each asset to the new release
        multi = (
            f"# header\nNT_REPO={repo}\nNT_TAG=v0.1.0\nNT_COMMIT={c1}\nNT_VERSION=0.1.0\n"
            f"TAR_SHA256={s1['lib-0.1.0.tar.gz']}\n"
        )
        out, old, newest, ncommit = bump(multi, base)
        check(
            "bump: comments kept, every release value and hash read from the new release",
            out.startswith("# header\nNT_REPO=")
            and (old, newest, ncommit) == ("v0.1.0", "v0.2.0", c2)
            and f"TAR_SHA256={s2['lib-0.2.0.tar.gz']}\n" in out
            and "NT_VERSION=0.2.0\n" in out
            and verify(*parse_text(out), base) == [],
        )
        out2, *_ = bump(text, base)  # the swarm-core.lock shape: <P>_ASSET moves too
        check(
            "bump: <P>_ASSET and <P>_SHA256 move together",
            "LIB_ASSET=lib-0.2.0.tar.gz\n" in out2
            and f"LIB_SHA256={s2['lib-0.2.0.tar.gz']}\n" in out2,
        )
        check("bump: a current lock is left", bump(out, base)[0] is None)
        twins = "dup/lib"
        more = fixture_repo(t, twins, env)
        make_release(
            t, twins, "v1.0.0", {"a-1.0.0.tar.gz": b"same", "b-1.0.0.tar.gz": b"same"}, env
        )
        more("two")
        make_release(t, twins, "v1.1.0", {"a-1.1.0.tar.gz": b"x", "b-1.1.0.tar.gz": b"y"}, env)
        twin = render("D", twins, "v1.0.0", "a-{version}.tar.gz", base).replace("D_ASSET=", "#")
        try:
            bump(twin, base)
            got = ""
        except LockError as e:
            got = str(e)
        check("bump: a hash two assets share is refused, not guessed (#481)", "ambiguous" in got)
        commit("four")
        make_release(t, repo, "v0.4.0", {"lib-renamed-0.4.0.tar.gz": b"four"}, env)
        try:
            bump(out, base)
            got = ""
        except LockError as e:
            got = str(e)
        check("bump: a renamed asset is refused, for a person", "renamed or dropped" in got)

        # a repository renamed on 2026-11-22 (#672): the lock's old name verifies,
        # read from the new one, and a bump writes the new name
        old_name, new_name = "swarm-routing/ns3-tools", "swarm-routing/sim-tools"
        moved = fixture_repo(t, new_name, env)
        r1, _ = make_release(t, new_name, "v1.0.0", {"x-1.0.0.tar.gz": b"a"}, env)
        moved("two")
        r2, _ = make_release(t, new_name, "v1.1.0", {"x-1.1.0.tar.gz": b"b"}, env)
        legacy = render("NT", new_name, "v1.0.0", "x-{version}.tar.gz", base).replace(
            f"NT_REPO={new_name}", f"NT_REPO={old_name}"
        )
        check("a renamed repository's old name verifies", verify(*parse_text(legacy), base) == [])
        out, _, newest, _ = bump(legacy, base)
        check(
            "bump: a renamed repository's lock moves to its new name",
            f"NT_REPO={new_name}\n" in out and newest == "v1.1.0" and f"NT_COMMIT={r2}" in out,
        )

        # swarm-core's releases moved to their own repository (#691): a SWARM_CORE
        # lock on swarm-adapter-ns3 v1.0.0, under its old name, moves to the first
        # swarm-core release even when its version is lower; another prefix stays
        adapter, core = "swarm-routing/swarm-adapter-ns3", "swarm-routing/swarm-core"
        fixture_repo(t, adapter, env)
        a1, _ = make_release(t, adapter, "v1.0.0", {"swarm-core-1.0.0.tar.gz": b"v1"}, env)
        more_core = fixture_repo(t, core, env)
        v1 = render("SWARM_CORE", adapter, "v1.0.0", "swarm-core-{version}.tar.gz", base)
        v1 = v1.replace(f"_REPO={adapter}", "_REPO=swarm-routing/ns3-swarm-core")
        check(
            "moved: no successor release yet, the lock is current",
            bump(v1, base)[0] is None
            and next_release(base, "SWARM_CORE", adapter) == (adapter, "v1.0.0", a1),
        )
        more_core("two")
        k1, _ = make_release(t, core, "v0.9.0", {"swarm-core-0.9.0.tar.gz": b"v09"}, env)
        out, old, newest, ncommit = bump(v1, base)
        check(
            "moved: the first swarm-core release is newer than swarm-adapter-ns3 v1.0.0",
            out is not None
            and (old, newest, ncommit) == ("v1.0.0", "v0.9.0", k1)
            and f"SWARM_CORE_REPO={core}\n" in out
            and "SWARM_CORE_ASSET=swarm-core-0.9.0.tar.gz\n" in out
            and verify(*parse_text(out), base) == [],
        )
        check("moved: then current, never back", bump(out, base)[0] is None)
        other = v1.replace("SWARM_CORE_", "ADAPTER_")
        check(
            "moved: a lock with another prefix keeps its repository",
            bump(other, base)[0] is None and is_newer(adapter, "v1.0.0", core, "v0.1.0"),
        )

        # an adapter lock beside swarm-core.lock (AntHocNet, swarm-routing/AntHocNet#1218)
        # moves to the adapter release built on the locked swarm-core release, not
        # the newest adapter release
        import contextlib
        import io

        a_git = os.path.join(t, adapter + ".git")

        def adapter_release(tag, core_tag):
            with open(os.path.join(a_git, "swarm-core.lock"), "w", encoding="utf-8") as f:
                f.write(render("SWARM_CORE", core, core_tag, "swarm-core-{version}.tar.gz", base))
            with open(os.path.join(a_git, "f.txt"), "a") as f:
                f.write(tag + "\n")
            subprocess.run(["git", "-C", a_git, "add", "-A"], check=True, env=env)
            subprocess.run(["git", "-C", a_git, "commit", "-q", "-m", tag], check=True, env=env)
            v = tag[1:]
            return make_release(t, adapter, tag, {f"swarm-core-{v}.tar.gz": tag.encode()}, env)[0]

        more_core("three")
        make_release(t, core, "v0.9.1", {"swarm-core-0.9.1.tar.gz": b"v091"}, env)
        a11 = adapter_release("v1.1.0", "v0.9.0")
        adapter_release("v1.2.0", "v0.9.1")
        consumer = os.path.join(t, "consumer")
        os.makedirs(consumer)
        a_lock = render("ADAPTER", adapter, "v1.0.0", "swarm-core-{version}.tar.gz", base)
        for name_, text_ in (
            ("swarm-core.lock", out),  # swarm-core v0.9.0, from the moved check above
            ("swarm-adapter-ns3.lock", a_lock),
        ):
            with open(os.path.join(consumer, name_), "w", encoding="utf-8") as f:
                f.write(text_)

        def run_bump():
            here, buf = os.getcwd(), io.StringIO()
            os.chdir(consumer)
            try:
                with contextlib.redirect_stdout(buf):
                    rc = main(["bump", "swarm-adapter-ns3.lock", "--write", "--base", base])
            finally:
                os.chdir(here)
            with open(os.path.join(consumer, "swarm-adapter-ns3.lock"), encoding="utf-8") as f:
                return rc, buf.getvalue(), f.read()

        rc, said, got = run_bump()
        check(
            "adapter lock: follows swarm-core.lock's tag, not the newest adapter release",
            rc == 0
            and "ADAPTER_TAG=v1.1.0\n" in got
            and f"ADAPTER_COMMIT={a11}\n" in got
            and "lock-target: swarm-adapter-ns3.lock@v1.1.0" in said,
        )
        check("adapter lock: then current", "current" in run_bump()[1])
        more_core("four")
        make_release(t, core, "v0.9.2", {"swarm-core-0.9.2.tar.gz": b"v092"}, env)
        with open(os.path.join(consumer, "swarm-core.lock"), "w", encoding="utf-8") as f:
            f.write(render("SWARM_CORE", core, "v0.9.2", "swarm-core-{version}.tar.gz", base))
        rc, said, got = run_bump()
        check(
            "adapter lock: no adapter release ships swarm-core's tag, the lock is held",
            rc == 0 and "held" in said and "ADAPTER_TAG=v1.1.0\n" in got,
        )
        os.remove(os.path.join(consumer, "swarm-core.lock"))
        rc, said, got = run_bump()
        check(
            "adapter lock: without swarm-core.lock, the newest release",
            rc == 0 and "ADAPTER_TAG=v1.2.0\n" in got,
        )

    for f in failures:
        print(f"FAIL: {f}")
    print(f"release_lock.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    for name in ("show", "verify", "latest", "bump"):
        s = sub.add_parser(name)
        s.add_argument("lock")
        s.add_argument("--base", default=GITHUB)
        if name == "bump":
            s.add_argument("--write", action="store_true", help="write the lock in place")
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
        if a.cmd not in ("show", "verify", "latest", "bump"):
            p.error("a command, or --self-test")
        prefix, values = parse(a.lock)
        if a.cmd == "bump":
            full = lock_path(a.lock)
            follows, target = adapter_target(full, prefix, values, a.base)
            if follows and not target:
                print(
                    f"{a.lock}: {values[f'{prefix}_REPO']} {values[f'{prefix}_TAG']}: held, "
                    "no adapter release ships swarm-core.lock's swarm-core release"
                )
                return 0
            with open(full, encoding="utf-8") as f:
                out, old, newest, commit = bump(f.read(), a.base, os.path.basename(full), target)
            if out is None:
                print(f"{a.lock}: {values[f'{prefix}_REPO']} {old}: current")
                return 0
            if a.write:
                with open(full, "w", encoding="utf-8") as f:
                    f.write(out)
            print(
                f"{a.lock}: {values[f'{prefix}_REPO']} {old} -> {newest} ({commit[:7]})"
                + ("" if a.write else " (not written: --write)")
            )
            print(f"lock-target: {a.lock}@{newest}")
            return 0
        repo, tag = canonical(values[f"{prefix}_REPO"]), values[f"{prefix}_TAG"]
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
        new_repo, newest, commit = next_release(a.base, prefix, repo)
        if newest is None:
            print(f"{a.lock}: {repo} has no published release")
            return 1
        newer = is_newer(repo, tag, new_repo, newest)
        where = "" if new_repo == repo else f" in {new_repo}"
        print(
            f"{a.lock}: {repo} locked {tag}, newest release {newest}{where} ({commit[:7]})"
            + (": a newer release exists" if newer else ": current")
        )
        return 0
    except (LockError, OSError) as e:
        print(f"FAIL {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
