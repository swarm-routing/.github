#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Move a release image's rolling tags: latest-<profile>, and latest for optimized.

    rolling_tags.py move --repo ghcr.io/<owner>/<pkg> --tag v1.2.0 --profile optimized
                         [--digest sha256:...] [--verify-signature] [--summary FILE]
    rolling_tags.py --self-test

reusable-ns3-image.yml runs `move` after a release image's signature
verifies, with the pushed digest (#373, epic #370). The same command repairs a
release whose rolling-tag step failed: without --digest it reads the digest of
the immutable version tag <tag>-<profile>, so nothing is rebuilt and the
version tag is never touched; --verify-signature checks that digest's cosign
signature against reusable-ns3-image.yml's identity first.

The rules:
- only a release version (vX.Y.Z or X.Y.Z) moves them; a campaign tag
  (<commit7>-<base7>) or a pre-release (v1.3.0-rc1) moves nothing (exit 0);
- never back: the release a rolling tag holds is read from its
  org.opencontainers.image.version label and compared numerically; a newer
  one stays where it is;
- fail closed: only a tag the registry reports missing is new; any other
  error, or a tag whose version label is not a version, stops (exit 1);
- a carbon copy: `imagetools create --prefer-index=false`, then the copy's
  digest must be the source's;
- each registry call is retried twice on a transient error (not on "not
  found").
"""

import argparse
import json
import re
import subprocess
import sys
import time

RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")
MISSING = re.compile(r"not found|manifest unknown|name unknown", re.I)
LABEL = "org.opencontainers.image.version"
IDENTITY = (
    r"^https://github\.com/swarm-routing/\.github/\.github/workflows/reusable-ns3-image\.yml@"
)
ISSUER = "https://token.actions.githubusercontent.com"
DELAYS = (5, 20)  # seconds before the 2nd and 3rd attempt


class Missing(RuntimeError):
    """The registry says the tag does not exist."""


def run(cmd):
    """(returncode, stdout + stderr) of a command."""
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout + p.stderr


def call(cmd, runner, sleep):
    """stdout of `cmd`; Missing when the registry says not found; retried on any other error."""
    out = ""
    for i in range(len(DELAYS) + 1):
        rc, out = runner(cmd)
        if rc == 0:
            return out
        if MISSING.search(out):
            raise Missing(out.strip())
        if i < len(DELAYS):
            sleep(DELAYS[i])
    raise RuntimeError(f"{' '.join(cmd)}: {out.strip()}")


def version(s):
    m = VERSION.match(s or "")
    return tuple(map(int, m.groups())) if m else None


def held(ref, runner, sleep):
    """The release `ref` holds (its version label), or None when the tag is missing."""
    try:
        out = call(["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Image}}"],
                   runner, sleep)  # fmt: skip
    except Missing:
        return None
    img = json.loads(out)
    if "config" not in img:  # an index: one config per platform
        img = img.get("linux/amd64") or next(iter(img.values()))
    v = (img["config"].get("Labels") or {}).get(LABEL, "")
    if not version(v):
        raise RuntimeError(f"{ref} exists but its release cannot be read ({LABEL}={v!r})")
    return v


def digest_of(ref, runner, sleep):
    out = call(["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"],
               runner, sleep)  # fmt: skip
    return json.loads(out)["digest"]


def move(repo, tag, profile, digest=None, verify=False, runner=run, sleep=time.sleep, log=print):
    """Move the rolling tags of release `tag`; returns the tags moved."""
    if not RELEASE.match(tag):
        log(f"no rolling tags: '{tag}' is not a release version")
        return []
    if digest is None:  # a repair: the immutable version tag's digest
        digest = digest_of(f"{repo}:{tag}-{profile}", runner, sleep)
    if verify:
        call(["cosign", "verify", "--certificate-identity-regexp", IDENTITY,
              "--certificate-oidc-issuer", ISSUER, f"{repo}@{digest}"], runner, sleep)  # fmt: skip
    targets = [f"latest-{profile}"] + (["latest"] if profile == "optimized" else [])
    moved = []
    for t in targets:
        cur = held(f"{repo}:{t}", runner, sleep)
        if cur is not None and version(tag) < version(cur):
            log(f"::notice::{repo}:{t} holds {cur}, newer than {tag}: not moved back")
            continue
        call(["docker", "buildx", "imagetools", "create", "--prefer-index=false",
              "-t", f"{repo}:{t}", f"{repo}@{digest}"], runner, sleep)  # fmt: skip
        got = digest_of(f"{repo}:{t}", runner, sleep)
        if got != digest:
            raise RuntimeError(f"{repo}:{t} is {got}, the source is {digest}")
        moved.append(t)
    return moved


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    m = sub.add_parser("move", help="move latest-<profile> (and latest) to a release's digest")
    m.add_argument("--repo", required=True, help="ghcr.io/<owner>/<package>")
    m.add_argument("--tag", required=True, help="the release version, e.g. v1.2.0")
    m.add_argument("--profile", required=True)
    m.add_argument("--digest", help="default: the digest of <repo>:<tag>-<profile> (a repair)")
    m.add_argument("--verify-signature", action="store_true", help="cosign verify the digest first")
    m.add_argument("--summary", help="append a line naming the moved tags (GITHUB_STEP_SUMMARY)")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "move":
        p.error("a command is required: move")
    try:
        moved = move(a.repo, a.tag, a.profile, a.digest, a.verify_signature)
    except (RuntimeError, KeyError, ValueError) as e:
        print(f"::error::{e}; the rolling tags were not moved", file=sys.stderr)
        return 1
    print(f"moved: {' '.join(moved) or 'none'}")
    if moved and a.summary:
        with open(a.summary, "a") as f:
            f.write(f"rolling tags `{' '.join(moved)}` -> {a.repo} ({a.tag}-{a.profile})\n")
    return 0


# --- self-test -----------------------------------------------------------------


class FakeRegistry:
    """`docker buildx imagetools` and `cosign verify` against a dict of tags."""

    def __init__(self, tags=None, failures=0, broken=False, bad_copy=False, signed=True):
        self.tags = dict(tags or {})  # tag -> (digest, version label)
        self.failures = failures  # transient errors before each call succeeds
        self.broken = broken  # every inspection fails (not "not found")
        self.bad_copy = bad_copy
        self.signed = signed
        self.calls = []
        self._left = {}

    def __call__(self, cmd):
        self.calls.append(cmd)
        key = " ".join(cmd)
        left = self._left.setdefault(key, self.failures)
        if left:
            self._left[key] = left - 1
            return 1, "ERROR: 502 Bad Gateway"
        if cmd[0] == "cosign":
            return (0, "ok") if self.signed else (1, "ERROR: no matching signatures")
        if cmd[3] == "create":
            if cmd[4] != "--prefer-index=false":
                return 9, "create without --prefer-index=false"
            tag, src = cmd[6].rsplit(":", 1)[1], cmd[7].split("@", 1)[1]
            label = next((v for d, v in self.tags.values() if d == src), "")
            self.tags[tag] = ("sha256:other" if self.bad_copy else src, label)
            return 0, ""
        if self.broken:
            return 1, "ERROR: 502 Bad Gateway"
        tag = cmd[4].rsplit(":", 1)[1] if "@" not in cmd[4] else None
        if tag not in self.tags:
            return 1, f"ERROR: {cmd[4]}: not found"
        d, v = self.tags[tag]
        if cmd[6] == "{{json .Manifest}}":
            return 0, json.dumps({"digest": d})
        return 0, json.dumps({"config": {"Labels": {LABEL: v} if v is not None else {}}})


def self_test():
    failures = 0

    def case(name, cond, detail=""):
        nonlocal failures
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
        failures += not cond

    repo, new = "ghcr.io/o/x", "sha256:new"

    def go(reg, tag="v1.0.0", profile="optimized", digest=new, verify=False):
        logs = []
        try:
            moved = move(repo, tag, profile, digest, verify, reg, lambda s: None, logs.append)
            return moved, logs, None
        except RuntimeError as e:
            return None, logs, str(e)

    pushed = {"v1.0.0-optimized": (new, "v1.0.0-optimized")}
    moved, _, _ = go(FakeRegistry(pushed))
    case(
        "first release, optimized: latest-optimized and latest",
        moved == ["latest-optimized", "latest"],
        moved,
    )
    moved, _, _ = go(FakeRegistry(pushed), profile="debug")
    case("first release, debug: latest-debug only", moved == ["latest-debug"], moved)
    older = {
        "latest-optimized": ("sha256:a", "v1.1.0-optimized"),
        "latest": ("sha256:a", "v1.1.0-optimized"),
    }
    moved, _, _ = go(FakeRegistry(older), tag="v1.2.0")
    case("a newer release moves both", moved == ["latest-optimized", "latest"], moved)
    moved, _, _ = go(FakeRegistry(older), tag="v1.1.0")
    case(
        "the same release again moves them (idempotent)",
        moved == ["latest-optimized", "latest"],
        moved,
    )
    moved, logs, _ = go(FakeRegistry(older), tag="v1.0.5")
    case(
        "an older release never moves them back",
        moved == [] and "not moved back" in logs[0],
        (moved, logs),
    )
    moved, _, _ = go(
        FakeRegistry({"latest-debug": ("sha256:a", "v1.9.0-debug")}), tag="v1.10.0", profile="debug"
    )
    case("v1.10.0 is newer than v1.9.0 (numeric)", moved == ["latest-debug"], moved)
    moved, _, _ = go(
        FakeRegistry({"latest-debug": ("sha256:a", "v1.9.9-debug")}), tag="2.0.0", profile="debug"
    )
    case("a version without v", moved == ["latest-debug"], moved)
    for tag in ("abc1234-{base7}", "v1.3.0-rc1", "latest"):
        reg = FakeRegistry()
        moved, logs, _ = go(reg, tag=tag)
        case(
            f"'{tag}' moves nothing",
            moved == [] and not reg.calls and "not a release" in logs[0],
            logs,
        )
    _, _, err = go(FakeRegistry(pushed, broken=True), tag="v1.3.0", profile="debug")
    case("a registry that keeps failing stops it (fail closed)", err and "502" in err, err)
    reg = FakeRegistry({"latest-debug": ("sha256:a", "v1.4.0-debug")}, failures=2)
    moved, _, err = go(reg, tag="v1.3.0", profile="debug")
    case(
        "a transient error is retried, then the comparison holds",
        moved == [] and err is None,
        (moved, err),
    )
    _, _, err = go(FakeRegistry({"latest-debug": ("sha256:a", "")}), tag="v1.3.0", profile="debug")
    case("a tag with no version label stops it", err and "cannot be read" in err, err)
    _, _, err = go(FakeRegistry(pushed, bad_copy=True))
    case("a copy with another digest stops it", err and "the source is" in err, err)
    reg = FakeRegistry({"v1.2.0-optimized": ("sha256:rel", "v1.2.0-optimized")})
    moved, _, _ = go(reg, tag="v1.2.0", digest=None, verify=True)
    case("repair: the version tag's digest, signature verified, both moved",
         moved == ["latest-optimized", "latest"] and reg.tags["latest"][0] == "sha256:rel"
         and any(c[0] == "cosign" for c in reg.calls), (moved, reg.tags))  # fmt: skip
    case("repair never writes the version tag",
         all(not (c[3:4] == ["create"] and c[6].endswith(":v1.2.0-optimized")) for c in reg.calls if c[0] == "docker"),
         reg.calls)  # fmt: skip
    reg = FakeRegistry({"v1.2.0-optimized": ("sha256:rel", "v1.2.0-optimized")}, signed=False)
    _, _, err = go(reg, tag="v1.2.0", digest=None, verify=True)
    case("repair: an unsigned digest is refused", err and "no matching signatures" in err, err)
    _, _, err = go(FakeRegistry(), tag="v9.9.9", digest=None)
    case("repair: a version tag that does not exist stops it", err is not None, err)
    print(f"\n{'all ok' if not failures else f'{failures} failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
