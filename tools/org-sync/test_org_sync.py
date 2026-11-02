#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Self-test for org_sync.py against throwaway fixture repos. Exits non-zero on
the first failure; no pytest dependency."""

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org_sync  # noqa: E402

ORG = org_sync.ORG


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = org_sync.main(list(argv))
    return rc, out.getvalue()


def fresh():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "remote", "add", "origin", "https://github.com/swarm-routing/demo"], check=True)
    return d


def edit(d, path, old, new):
    p = os.path.join(d, path)
    text = open(p).read()
    assert old in text, (path, old)
    open(p, "w").write(text.replace(old, new, 1))


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print(f"ok    {msg}")


# 1. init on an empty repo creates everything, and check is then clean.
for kind in org_sync.KINDS:
    d = fresh()
    rc, _ = run("init", d, "--kind", kind, "--dual", "tools/")
    check(rc == 0, f"init --kind {kind} succeeds")
    check(run("check", d)[0] == 0, f"check is clean right after init ({kind})")
    mk = open(os.path.join(d, "Makefile")).read()
    for t in org_sync.MAKE_TARGETS:
        assert f"\n{t}:" in mk, (kind, t)
    check(not re.search(r"@[A-Z_]+@", mk), f"no unrendered @PLACEHOLDER@ in the {kind} Makefile")

d = fresh()
run("init", d, "--kind", "python", "--dual", "")

# 2. An edit inside a managed section is drift; apply restores it.
edit(d, "AGENTS.md", "9. **Nothing shipped", "9. **Something shipped")
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#org-rules" in out, "an edit inside a managed section fails check, naming it")
run("apply", d)
check(run("check", d)[0] == 0, "apply restores the managed section")

# 3. Repo text outside the markers survives apply.
edit(d, "AGENTS.md", "## What this repo is\n", "## What this repo is\n\nLOCAL NOTE\n")
run("apply", d)
check("LOCAL NOTE" in open(os.path.join(d, "AGENTS.md")).read(), "text outside the markers survives apply")

# 4. The Makefile is the repo's: its recipes may change, its target names may not.
edit(d, "Makefile", "python3 -m pytest -q", "python3 -m unittest")
check(run("check", d)[0] == 0, "changing a Makefile recipe is not drift")
edit(d, "Makefile", "\nshell:", "\nsh:")
rc, out = run("check", d)
check(rc == 1 and "missing standard target(s): shell" in out, "a missing standard target fails check")
edit(d, "Makefile", "\nsh:", "\nshell:")

# 5. An existing repo without markers: identical sections are adopted, a
#    diverged one is a conflict that apply leaves alone until forced.
d = fresh()
os.makedirs(os.path.join(d, ".github"))
open(os.path.join(d, ".github/org-sync.toml"), "w").write('kind = "data"\n')
for f in ("AGENTS.md", "CLAUDE.md", "README.md"):
    open(os.path.join(d, f), "w").write(open(os.path.join(ORG, f)).read())
rc, out = run("plan", d)
check("adopt     AGENTS.md#org-rules" in out and "adopt     CLAUDE.md#org" in out,
      "unmarked org sections identical to the templates are adopted")
check("adopt     README.md#badges" in out, "the badge row is inserted after the title")
edit(d, "AGENTS.md", "7. **Keep bounded structures bounded**", "7. **Keep bounded things bounded**")
rc, out = run("apply", d)
check(rc == 1 and "conflict  AGENTS.md#org-rules" in out, "a diverged unmarked section is a conflict")
check("Keep bounded things bounded" in open(os.path.join(d, "AGENTS.md")).read(), "apply leaves a conflict untouched")
rc, out = run("conflicts", d)
check("-7. **Keep bounded things bounded**" in out, "conflicts prints the hunk")
run("apply", d, "--force", "AGENTS.md#org-rules")
check(run("check", d)[0] == 0, "apply --force resolves it")

# 6. The JSON item merges only the org's keys.
p = os.path.join(d, ".claude/settings.json")
open(p, "w").write('{"permissions": {"allow": ["Bash(ls)"]}}\n')
run("apply", d)
text = open(p).read()
check('"Bash(ls)"' in text and "org-repo@swarm-routing" in text, "settings.json keeps the repo's keys and gains the org's")

# 7. A no-change update reads well under the 2 KB budget (skills#2).
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for c in (["plan", "--json", d], ["apply", d], ["conflicts", d], ["check", d]):
        org_sync.main(c)
check(len(buf.getvalue()) < 2048, f"a no-change update prints {len(buf.getvalue())} bytes (< 2048)")

print("org-sync self-test: OK")
