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
    subprocess.run(
        ["git", "-C", d, "remote", "add", "origin", "https://github.com/swarm-routing/demo"],
        check=True,
    )
    return d


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def edit(d, path, old, new):
    p = os.path.join(d, path)
    text = read(p)
    assert old in text, (path, old)
    write(p, text.replace(old, new, 1))


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
    mk = read(os.path.join(d, "Makefile"))
    for t in org_sync.MAKE_TARGETS:
        assert f"\n{t}:" in mk, (kind, t)
    check(not re.search(r"@[A-Z_]+@", mk), f"no unrendered @PLACEHOLDER@ in the {kind} Makefile")

    lic = re.search(r"SPDX-License-Identifier: (.*)", mk).group(1)
    check(lic == "GPL-2.0-only", f"a partly dual repo's Makefile is GPL-2.0-only ({kind})")
    if kind == "protocol":
        check("if [ -d ns3 ]" in mk, "a protocol repo's build/test wait for ns3/")

# single dual-licensed files keep no trailing slash; directories get one
check(org_sync.dual_root("test/run.sh") == "test/run.sh", "a dual file root stays a file")
check(
    org_sync.dual_root("./tools") == "tools/" and org_sync.dual_root(".github/") == ".github/",
    "a dual directory root ends in /",
)

d = fresh()
run("init", d, "--kind", "python", "--dual", "")
check(
    "SPDX-License-Identifier: MIT OR GPL-2.0-only" in read(os.path.join(d, "Makefile")),
    "a fully dual repo's Makefile is dual",
)

# 2. An edit inside a managed section is drift; apply restores it.
edit(d, "AGENTS.md", "9. **Nothing shipped", "9. **Something shipped")
rc, out = run("check", d)
check(
    rc == 1 and "AGENTS.md#org-rules" in out,
    "an edit inside a managed section fails check, naming it",
)
run("apply", d)
check(run("check", d)[0] == 0, "apply restores the managed section")

# 3. Repo text outside the markers survives apply.
edit(d, "AGENTS.md", "## What this repo is\n", "## What this repo is\n\nLOCAL NOTE\n")
run("apply", d)
check("LOCAL NOTE" in read(os.path.join(d, "AGENTS.md")), "text outside the markers survives apply")

# 4. The Makefile is the repo's: its recipes may change, its target names may not.
edit(d, "Makefile", "python3 -m pytest -q", "python3 -m unittest")
check(run("check", d)[0] == 0, "changing a Makefile recipe is not drift")
edit(d, "Makefile", "\nshell:", "\nsh:")
rc, out = run("check", d)
check(
    rc == 1 and "missing standard target(s): shell" in out, "a missing standard target fails check"
)
edit(d, "Makefile", "\nsh:", "\nshell:")

# 5. An existing repo without markers: identical sections are adopted, a
#    diverged one is a conflict that apply leaves alone until forced.
d = fresh()
os.makedirs(os.path.join(d, ".github"))
write(os.path.join(d, ".github/org-sync.toml"), 'kind = "data"\n')
for f in ("AGENTS.md", "CLAUDE.md", "README.md"):
    write(os.path.join(d, f), read(os.path.join(ORG, f)))
rc, out = run("plan", d)
check(
    "adopt     AGENTS.md#org-rules" in out and "adopt     CLAUDE.md#org" in out,
    "unmarked org sections identical to the templates are adopted",
)
check("adopt     README.md#badges" in out, "the badge row is inserted after the title")
edit(d, "AGENTS.md", "7. **Keep bounded structures bounded**", "7. **Keep bounded things bounded**")
rc, out = run("apply", d)
check(
    rc == 1 and "conflict  AGENTS.md#org-rules" in out, "a diverged unmarked section is a conflict"
)
check(
    "Keep bounded things bounded" in read(os.path.join(d, "AGENTS.md")),
    "apply leaves a conflict untouched",
)
rc, out = run("conflicts", d)
check("-7. **Keep bounded things bounded**" in out, "conflicts prints the hunk")
run("apply", d, "--force", "AGENTS.md#org-rules")
check(run("check", d)[0] == 0, "apply --force resolves it")
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "<!-- org-sync:begin skills -->\n## Agent skills" in agents
    and agents.index("## Agent skills") < agents.index("## Where to look"),
    "the skills section is inserted before the repository's own Where-to-look table",
)
edit(
    d,
    "AGENTS.md",
    agents[agents.index("<!-- org-sync:begin skills -->") :].split("## Where to look")[0],
    "",
)
edit(
    d, "AGENTS.md", "<!-- org-sync:end git-workflow -->\n\n", "<!-- org-sync:end git-workflow -->\n"
)
check(
    "<!-- org-sync:end git-workflow -->\n## Where to look" in read(os.path.join(d, "AGENTS.md")),
    "fixture: no blank line",
)
run("apply", d)
check(
    "## Agent skills" in read(os.path.join(d, "AGENTS.md")) and run("check", d)[0] == 0,
    "the skills section is inserted when the heading has no blank line before it",
)

# 6. The JSON item merges only the org's keys.
p = os.path.join(d, ".claude/settings.json")
write(p, '{"permissions": {"allow": ["Bash(ls)"]}}\n')
run("apply", d)
text = read(p)
check(
    '"Bash(ls)"' in text and "swarm-routing@swarm-routing" in text,
    "settings.json keeps the repo's keys and gains the org's",
)
write(
    p,
    '{"enabledPlugins": {"org-repo@swarm-routing": true, "tool@elsewhere": true},'
    ' "permissions": {"allow": ["Bash(ls)"]}}\n',
)
run("apply", d)
text = read(p)
check(
    "org-repo@swarm-routing" not in text
    and "swarm-routing@swarm-routing" in text
    and "tool@elsewhere" in text
    and '"Bash(ls)"' in text,
    "a plugin the org marketplace no longer ships is dropped; others are kept",
)
check(run("check", d)[0] == 0, "settings.json in sync after the rename")


# 7. Header-check flags: dual roots normalized, the core include check whenever core/ is dual.
def ha(dual):
    return org_sync.header_args({"dual": dual})


check(
    ha(["./tools", "core"]) == "--dual tools/ --dual core/ --core core/",
    "dual roots are normalized to Git-relative prefixes",
)
check(
    ha([""]) == "--dual '' --core core/",
    "a whole-repo dual licence still gets the core include check",
)
check(ha(["tools/"]) == "--dual tools/", "no core check when core/ is not dual")

# 8. A multi-line recipe renders one tab-indented line per command (no `make -n` side effects).
mk = org_sync.render_makefile(
    {"kind": "container", "dual": ["tools/"], "title": "demo", "repo": "demo"}
)
check(
    "\t$(MAKE) build\n\ttest/run.sh local/" in mk,
    "the container test recipe builds and tests on separate lines",
)

# 9. A no-change update reads well under the 2 KB budget (skills#2).
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for c in (["plan", "--json", d], ["apply", d], ["conflicts", d], ["check", d]):
        org_sync.main(c)
check(len(buf.getvalue()) < 2048, f"a no-change update prints {len(buf.getvalue())} bytes (< 2048)")

# 10. YAML sections use `#` markers: the org's CodeRabbit settings are managed,
# the repository's own path_instructions between them survive apply.
cr = os.path.join(d, ".coderabbit.yaml")
text = read(cr)
check(
    "# org-sync:begin coderabbit-head\n" in text and "# org-sync:end coderabbit-tail\n" in text,
    "a YAML file gets `#` section markers",
)
check("auto_incremental_review: false" in text, "the org's review budget is in the managed head")
own = '    - path: "src/**"\n      instructions: >-\n        LOCAL RULE\n'
edit(
    d,
    ".coderabbit.yaml",
    "# org-sync:begin coderabbit-tail\n",
    own + "# org-sync:begin coderabbit-tail\n",
)
edit(d, ".coderabbit.yaml", "auto_incremental_review: false", "auto_incremental_review: true")
rc, out = run("check", d)
check(rc == 1 and ".coderabbit.yaml#coderabbit-head" in out, "an edit in the YAML head is drift")
run("apply", d)
text = read(cr)
check(
    run("check", d)[0] == 0 and "LOCAL RULE" in text and "auto_incremental_review: false" in text,
    "apply restores the YAML head and keeps the repository's own instructions",
)

print("org-sync self-test: OK")
