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

sys.path.insert(0, os.path.join(HERE, "..", "zenodo"))
import zenodo  # noqa: E402

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
    check("differs" not in run("seeds", d)[1], f"every seed reads same right after init ({kind})")
    mk = read(os.path.join(d, "Makefile"))
    for t in org_sync.MAKE_TARGETS:
        assert f"\n{t}:" in mk, (kind, t)
    check(not re.search(r"@[A-Z_]+@", mk), f"no unrendered @PLACEHOLDER@ in the {kind} Makefile")

    lic = re.search(r"SPDX-License-Identifier: (.*)", mk).group(1)
    check(lic == "GPL-2.0-only", f"a partly dual repo's Makefile is GPL-2.0-only ({kind})")
    if kind == "protocol":
        for target in ("build", "test"):
            recipe = mk.split(f"\n{target}:", 1)[1].split("\n\n", 1)[0]
            check("if [ -d ns3 ]" in recipe, f"a protocol repo's {target} waits for ns3/")

# single dual-licensed files keep no trailing slash; directories get one
check(org_sync.dual_root("test/run.sh") == "test/run.sh", "a dual file root stays a file")
for root in ("./tools", ".github", ".github/", "tools"):
    check(org_sync.dual_root(root).endswith("/"), f"a dual directory root ends in / ({root})")
d = fresh()
run("init", d, "--kind", "container", "--dual", "tools/", "--dockerfile", "docker/Dockerfile")
check(
    "DOCKERFILE ?= docker/Dockerfile" in read(os.path.join(d, "Makefile")),
    "init --dockerfile reaches the seeded Makefile",
)

d = fresh()
run("init", d, "--kind", "python", "--dual", "")
check(
    "SPDX-License-Identifier: MIT OR GPL-2.0-only" in read(os.path.join(d, "Makefile")),
    "a fully dual repo's Makefile is dual",
)

# the site badge names the project's page; the image badge only where it builds
da = fresh()
run("init", da, "--kind", "protocol", "--title", "ARA", "--dual", "core/", "--arena-id", "ARA")
rd = read(os.path.join(da, "README.md"))
check(
    "https://swarm-routing.github.io/arena/ARA/" in rd,
    "a protocol repo's badge row links its page on the site",
)
dn = fresh()
run("init", dn, "--kind", "protocol", "--title", "demo", "--dual", "core/")
check(
    "arena/" not in read(os.path.join(dn, "README.md"))
    and 'arena_id = ""' in read(os.path.join(dn, ".github/org-sync.toml")),
    "a new repo without --arena-id gets no arena badge until the site lists it",
)
cfg = {"kind": "protocol", "title": "ARA"}
check(org_sync.arena_id(cfg) == "ARA", "an adopted repo without [docs] uses its title")
check(
    "packages/container/package/ns3-dev" in rd,
    "a protocol repo's badge row links the ns3-dev image",
)
# quality badges (SonarQube Cloud, Codecov, CodeRabbit) and their seeds
check(
    "project_badges/measure?project=swarm-routing_demo&metric=alert_status" in rd
    and "metric=sqale_rating" in rd
    and "coderabbit/prs/github/swarm-routing/demo" in rd
    and "utm_campaign=swarm-routing%2Fdemo" in rd,
    "a protocol repo gets the four SonarQube Cloud badges and CodeRabbit's",
)
check("codecov.io" not in rd, "no Codecov badge until a workflow uploads coverage")
check(
    "sonar.projectKey=swarm-routing_demo" in read(os.path.join(da, "sonar-project.properties"))
    and "target: 80%" in read(os.path.join(da, ".codecov.yml")),
    "a protocol repo is seeded with sonar-project.properties and .codecov.yml",
)
os.makedirs(os.path.join(da, ".github/workflows"), exist_ok=True)
with open(os.path.join(da, ".github/workflows/ci.yml"), "w") as f:
    f.write("    uses: swarm-routing/.github/.github/workflows/reusable-codecov.yml@main\n")
run("apply", da)
check(
    "codecov.io/gh/swarm-routing/demo/graph/badge.svg" in read(os.path.join(da, "README.md")),
    "the Codecov badge appears once a workflow uploads coverage",
)
dz = fresh()
run("init", dz, "--kind", "protocol", "--dual", "core/")
with open(os.path.join(dz, ".github/org-sync.toml"), "a") as f:
    f.write("\n[quality]\nsonar = false\n")
os.remove(os.path.join(dz, "sonar-project.properties"))
run("apply", dz)
rz = read(os.path.join(dz, "README.md"))
check(
    "sonarcloud.io" not in rz
    and not os.path.exists(os.path.join(dz, "sonar-project.properties"))
    and os.path.exists(os.path.join(dz, ".codecov.yml")),
    "[quality] sonar = false: no SonarQube Cloud badges or properties seed, Codecov kept",
)
dq = fresh()
run("init", dq, "--kind", "container", "--dual", "")
rq = read(os.path.join(dq, "README.md"))
check(
    "hadolint" not in rq.lower() and not os.path.exists(os.path.join(dq, ".codecov.yml")),
    "a container repo gets no scanner badges before container-security.yml, and no C++ seeds",
)
os.makedirs(os.path.join(dq, ".github/workflows"), exist_ok=True)
with open(os.path.join(dq, ".github/workflows/container-security.yml"), "w") as f:
    f.write("name: Container Security\n")
run("apply", dq)
rq = read(os.path.join(dq, "README.md"))
check(
    "actions/workflows/container-security.yml/badge.svg" in rq
    and "check-runs/swarm-routing/demo/main?nameFilter=hadolint" in rq
    and "nameFilter=trivy-config" in rq
    and "metric=security_rating" in rq
    and "metric=bugs" not in rq,
    "a container repo's scanner badges are live: workflow, Hadolint and Trivy jobs, Sonar gate + security",
)
# OpenSSF Scorecard (#23): the caller workflow on every repo, its badge only with it
sc = os.path.join(dq, ".github/workflows/scorecard.yml")
check(
    "uses: swarm-routing/.github/.github/workflows/reusable-scorecard.yml@main" in read(sc)
    and "id-token: write" in read(sc)
    and "security-events: write" in read(sc),
    "init writes the Scorecard caller, granting what publish_results and SARIF need",
)
check(
    "api.securityscorecards.dev/projects/github.com/swarm-routing/demo/badge" in rq
    and "scorecard.dev/viewer/?uri=github.com/swarm-routing/demo" in rq,
    "the Scorecard badge links the repo's report on scorecard.dev",
)
dp = fresh()
run("init", dp, "--kind", "data", "--dual", "")
edit(
    dp, ".github/org-sync.toml", "\n[docs]", 'skip = [".github/workflows/scorecard.yml"]\n\n[docs]'
)
os.remove(os.path.join(dp, ".github/workflows/scorecard.yml"))
run("apply", dp)
check(
    not os.path.exists(os.path.join(dp, ".github/workflows/scorecard.yml"))
    and "securityscorecards" not in read(os.path.join(dp, "README.md"))
    and run("check", dp)[0] == 0,
    "a repo that skips the Scorecard workflow (a private one) gets no badge and stays clean",
)

# release, doi and cite: each only when its target exists
GH_DESC = (
    "The GitHub description: ant-colony routing over routing zones, a simulator-agnostic"
    " C++ core, little-endian wire helpers and an ns-3 contrib module on swarm-core."
)
dr = fresh()
run("init", dr, "--kind", "protocol", "--dual", "core/")
rr = read(os.path.join(dr, "README.md"))
check(
    "github/v/release" not in rr
    and "zenodo.org" not in rr
    and "CITATION.cff" not in rr
    and not os.path.exists(os.path.join(dr, "CITATION.cff")),
    "no release, DOI or cite badge and no CITATION.cff by default",
)
os.makedirs(os.path.join(dr, ".github/workflows"), exist_ok=True)
write(
    os.path.join(dr, ".github/workflows/release.yml"),
    "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main\n",
)
write(
    os.path.join(dr, ".cz.toml"),
    '[tool.commitizen]\nversion = "0.1.0"\nversion_files = ["CITATION.cff:^version:"]\n',
)
# top-level keys, so before the [docs] table init wrote
edit(
    dr,
    ".github/org-sync.toml",
    'kind = "protocol"\n',
    'kind = "protocol"\ncitation = true\nzenodo_concept = "not-read-from-zenodo"\n',
)
run("apply", dr)
rr = read(os.path.join(dr, "README.md"))
cff = read(os.path.join(dr, "CITATION.cff"))
check(
    "[![Release](https://img.shields.io/github/v/release/swarm-routing/demo?sort=semver&cacheSeconds=1800)]"
    "(https://github.com/swarm-routing/demo/releases)" in rr,
    "the release badge appears once a workflow calls reusable-release.yml (AntHocNet's form)",
)
check(
    "[![Cite](https://img.shields.io/badge/cite-CITATION.cff-blue)](CITATION.cff)" in rr,
    "citation = true seeds CITATION.cff, and the cite badge follows it",
)
check(
    "zenodo.org/badge" not in rr and "\ndoi:" not in cff,
    "a zenodo_concept that is not a record id renders no DOI",
)
check(
    'version: "0.1.0"\n' in cff
    and 'repository-code: "https://github.com/swarm-routing/demo"' in cff
    and 'orcid: "https://orcid.org/0009-0009-6436-8174"' in cff
    and "\nlicense: GPL-2.0-only\n" in cff
    and "  - MIT" not in cff
    and "abstract: >-\n  **Status: empty.**" in cff,
    "CITATION.cff: Commitizen's version, the repo URL, AntHocNet's author entry, GPL-2.0-only for a partly dual work",
)
try:
    import yaml  # optional: the CFF parses as YAML when PyYAML is there
except ImportError:
    yaml = None
if yaml:
    doc = yaml.safe_load(cff)
    check(doc["cff-version"] == "1.2.0" and doc["title"] == "demo", "CITATION.cff is valid YAML")
edit(dr, ".github/org-sync.toml", '"not-read-from-zenodo"', '"1234567"')
run("apply", dr)
rr = read(os.path.join(dr, "README.md"))
check(
    "[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.1234567.svg)]"
    "(https://doi.org/10.5281/zenodo.1234567)" in rr,
    "zenodo_concept renders the DOI badge",
)
check(
    "\ndoi:" not in read(os.path.join(dr, "CITATION.cff")),
    "a written CITATION.cff is the repo's own",
)
rc, out = run("reseed", "CITATION.cff", dr)
cff = read(os.path.join(dr, "CITATION.cff"))
check(
    rc == 0 and 'doi: "10.5281/zenodo.1234567"' in cff and zenodo.concept_from(cff) == "1234567",
    "reseed CITATION.cff writes the concept DOI once zenodo_concept is set, as zenodo.py reads it",
)
check(run("check", dr)[0] == 0, "check is clean with release, doi and cite")
with open(os.path.join(dr, ".github/org-sync.toml"), "a") as f:
    f.write(f'\n[settings]\ndescription = "{GH_DESC}"\n')
run("reseed", "CITATION.cff", dr)
cff = read(os.path.join(dr, "CITATION.cff"))
check(
    "abstract: >-\n  The GitHub description:" in cff
    and (not yaml or yaml.safe_load(cff)["abstract"] == GH_DESC),
    "the abstract is [settings] description, every hyphenated word whole",
)
write(os.path.join(dr, ".cz.toml"), '[tool.commitizen]\nversion = "1.20"\n')
edit(
    dr, ".github/org-sync.toml", 'kind = "protocol"\n', 'kind = "protocol"\ntitle = "Test @REPO@"\n'
)
run("reseed", "CITATION.cff", dr)
cff = read(os.path.join(dr, "CITATION.cff"))
check(
    'title: "Test @REPO@"\n' in cff
    and 'version: "1.20"\n' in cff
    and (not yaml or yaml.safe_load(cff)["version"] == "1.20"),
    "CITATION.cff: placeholders filled in one pass, the version quoted (1.20 stays a string)",
)
# Releases & citing (README section) and CITATION.cff references, from [[references]]
rr = read(os.path.join(dr, "README.md"))
check(
    "<!-- org-sync:begin citing -->\n## Releases & citing\n" in rr
    and rr.index("org-sync:end citing") < rr.index("## Contributing")
    and "| [`10.5281/zenodo.1234567`](https://doi.org/10.5281/zenodo.1234567) | **concept DOI**"
    in rr
    and "own **version DOI**" in rr
    and "citing the DOI helps just as much" in rr
    and "Please also cite" not in rr,
    "citation = true renders Releases & citing before Contributing: the concept DOI, no version rows",
)
REFS = """
[[references]]
type = "conference-paper"
title = "ARA-the ant-colony based routing algorithm for MANETs"
authors = ["G\u00fcne\u015f, Mesut", "Sorges, Udo", "Bouazizi, Imed"]
year = 2002
venue = "Proceedings. International Conference on Parallel Processing Workshop"
pages = "79-85"
publisher = "IEEE"
doi = "10.1109/ICPPW.2002.1039715"
role = "The algorithm this repository implements."

[[references]]
type = "thesis"
title = "A \\"quoted\\" thesis"
authors = ["Wang, Jianping"]
year = 2007
venue = "University of Manitoba"
thesis_type = "MSc thesis"
url = "https://hdl.handle.net/1993/20935"
no_doi = "a thesis in the university's repository."
role = "The primary source."
"""
with open(os.path.join(dr, ".github/org-sync.toml"), "a") as f:
    f.write(REFS)
write(os.path.join(dr, "docs/fidelity.md"), "# Fidelity\n")
rc, out = run("check", dr)
check(rc == 1 and "README.md#citing" in out, "a new reference is drift in the managed section")
run("apply", dr)
run("reseed", "CITATION.cff", dr)
rr = read(os.path.join(dr, "README.md"))
cff = read(os.path.join(dr, "CITATION.cff"))
check(
    "- M. G\u00fcne\u015f, U. Sorges, I. Bouazizi, *ARA-the ant-colony based routing algorithm for MANETs*, "
    "Proceedings. International Conference on Parallel Processing Workshop, pp. 79\u201385, 2002, "
    "[doi:10.1109/ICPPW.2002.1039715](https://doi.org/10.1109/ICPPW.2002.1039715). "
    "The algorithm this repository implements.\n"
    in rr
    and "<https://hdl.handle.net/1993/20935> (no DOI: a thesis in the university's repository.)"
    in rr
    and "[docs/fidelity.md](docs/fidelity.md)" in rr,
    "README cites each reference with its doi.org link, or its page and why it has no DOI",
)
check(
    cff.rstrip().endswith(
        'notes: "The primary source. No DOI: a thesis in the university\'s repository."'
    )
    and '    doi: "10.1109/ICPPW.2002.1039715"\n' in cff
    and '    collection-title: "Proceedings. International Conference on Parallel Processing Workshop"\n'
    "    collection-type: proceedings\n"
    in cff
    and '    start: "79"\n    end: "85"\n    year: 2002\n' in cff
    and '    institution:\n      name: "University of Manitoba"\n' in cff
    and '      - family-names: "G\u00fcne\u015f"\n        given-names: "Mesut"\n' in cff
    and 'title: "A \\"quoted\\" thesis"' in cff,
    "CITATION.cff references: CFF keys per type, a DOI or a URL with the reason",
)
if yaml:
    refs = yaml.safe_load(cff)["references"]
    check(
        len(refs) == 2 and refs[1]["title"] == 'A "quoted" thesis' and refs[0]["year"] == 2002,
        "CITATION.cff references parse as YAML",
    )
check(run("check", dr)[0] == 0, "check is clean with references")
dd = fresh()
run("init", dd, "--kind", "data", "--dual", "tools/")
edit(
    dd,
    ".github/org-sync.toml",
    'kind = "data"\n',
    'kind = "data"\ncitation = true\ncitation_type = "dataset"\n',
)
run("apply", dd)
cff = read(os.path.join(dd, "CITATION.cff"))
rr = read(os.path.join(dd, "README.md"))
check(
    "\ntype: dataset\n" in cff
    and 'message: "If you use these data, please cite them using the metadata below."' in cff
    and "references:" not in cff
    and "To cite these data" in rr
    and "It has no DOI yet" in rr
    and "citing it helps just as much" in rr
    and "Releases](" not in rr,
    "citation_type = dataset: type and message; no concept yet: the citing section says so",
)
check(
    "\ntype: software\n" in read(os.path.join(dr, "CITATION.cff")),
    "the default citation_type is software",
)
for bad in (
    'citation_type = "paper"\n',
    '[[references]]\ntype = "article"\ntitle = "t"\nauthors = ["A, B"]\nyear = 2000\nrole = "r"\n',
):
    db = fresh()
    os.makedirs(os.path.join(db, ".github"))
    write(os.path.join(db, ".github/org-sync.toml"), 'kind = "data"\ncitation = true\n' + bad)
    try:
        rc = run("plan", db)[0]
    except SystemExit as e:
        rc = e.code
    check(rc not in (0, None), "refused: " + bad.splitlines()[0])
# an existing README without Contributing: the section goes before Epics
de = fresh()
run("init", de, "--kind", "protocol")
edit(de, "README.md", "## Contributing", "## Epics\n\nx\n\n## Contributing")
edit(de, ".github/org-sync.toml", 'kind = "protocol"\n', 'kind = "protocol"\ncitation = true\n')
run("apply", de)
rr = read(os.path.join(de, "README.md"))
check(
    rr.index("org-sync:end citing -->\n\n## Epics") > 0 and run("check", de)[0] == 0,
    "the citing section is inserted before the first of Contributing, Epics, Licence",
)

dl = fresh()
run("init", dl, "--kind", "python", "--dual", "")
edit(dl, ".github/org-sync.toml", 'kind = "python"\n', 'kind = "python"\ncitation = true\n')
run("apply", dl)
cff = read(os.path.join(dl, "CITATION.cff"))
check(
    "license:\n  - MIT\n  - GPL-2.0-only\n" in cff and 'version: "0.0.0"\n' in cff,
    "a fully dual repo's CITATION.cff lists both licences; no .cz.toml reads 0.0.0",
)
da = fresh()
run("init", da, "--kind", "skills", "--dual", "")
rd = read(os.path.join(da, "README.md"))
check(
    "arena/" not in rd and "ns3-dev" not in rd, "the skills repo gets neither (no page, no image)"
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

# 11. Seeds: `seeds` reports each against today's render (information, exit 0);
# `reseed` takes today's render for one seed and refuses anything else (#91).
d = fresh()
run("init", d, "--kind", "protocol", "--title", "demo", "--dual", "core/")
rc, out = run("seeds", d)
check(
    rc == 0 and "same      SECURITY.md" in out and "differs" not in out and "missing" not in out,
    "right after init every seed reads same",
)
edit(
    d,
    ".github/org-sync.toml",
    'kind = "protocol"\n',
    'kind = "protocol"\ntrust_boundary = "The wire decoder is the only parser."\n',
)
rc, out = run("seeds", d)
check(
    rc == 0 and "differs   SECURITY.md (2 lines)" in out and "same      Makefile" in out,
    "a config change shows the seed it reaches as differs, with its line count",
)
check(run("check", d)[0] == 0, "a differing seed is not drift: check stays clean")
edit(
    d,
    "Makefile",
    "SPDX-License-Identifier: GPL-2.0-only",
    "SPDX-License-Identifier: MIT OR GPL-2.0-only",
)
rc, out = run("seeds", d)
check("differs   Makefile (2 lines)" in out, "an old Makefile header (#86) shows as differs")
edit(d, "SECURITY.md", "## Verifying what it ships", "LOCAL NOTE\n\n## Verifying what it ships")
rc, out = run("reseed", "SECURITY.md", d)
sec = read(os.path.join(d, "SECURITY.md"))
check(
    rc == 0
    and "+The wire decoder is the only parser." in out
    and "-LOCAL NOTE" in out
    and "reseeded  SECURITY.md" in out,
    "reseed prints the diff it writes",
)
check(
    "The wire decoder is the only parser." in sec
    and "LOCAL NOTE" not in sec
    and "<!-- org-sync:begin reporting -->\n## Reporting" in sec,
    "reseed writes today's render, its managed section filled in",
)
run("reseed", "Makefile", d)
rc, out = run("seeds", d)
check("differs" not in out and run("check", d)[0] == 0, "after reseed the seeds read same again")
for f in ("LICENSE", ".github/workflows/org-sync.yml", "core/x.h"):
    before = read(os.path.join(d, f)) if os.path.exists(os.path.join(d, f)) else None
    rc, out = run("reseed", f, d)
    after = read(os.path.join(d, f)) if os.path.exists(os.path.join(d, f)) else None
    check(rc == 2 and "is not a seed" in out and before == after, f"reseed refuses {f}")
outside = os.path.join(tempfile.mkdtemp(), "elsewhere.md")
write(outside, "NOT THE REPO'S\n")
os.remove(os.path.join(d, "SECURITY.md"))
os.symlink(outside, os.path.join(d, "SECURITY.md"))
rc, out = run("reseed", "SECURITY.md", d)
check(
    rc == 2 and "resolves outside the repository" in out and read(outside) == "NOT THE REPO'S\n",
    "reseed refuses a seed symlinked outside the repository, leaving the target unchanged",
)
os.remove(os.path.join(d, "SECURITY.md"))
run("reseed", "SECURITY.md", d)
os.remove(os.path.join(d, "CONTEXT.md"))
adr = "docs/adr/0001-record-architecture-decisions.md"
edit(d, adr, "- **Date:** " + org_sync.datetime.date.today().isoformat(), "- **Date:** 2020-01-02")
rc, out = run("seeds", d)
check("missing   CONTEXT.md" in out, "a deleted seed reads missing")
check(f"same      {adr}" in out, "a dated seed keeps its own date: same")
rc, out = run("seeds", "--json", d)
check(
    '{"file":"CONTEXT.md","status":"missing","lines":0}' in out,
    "seeds --json gives file, status and lines",
)
run("reseed", "CONTEXT.md", d)
check(os.path.exists(os.path.join(d, "CONTEXT.md")), "reseed creates a missing seed")


# check --changed-only BASE (#159): on a PR or a merge group, only the drift the
# change brought in is red; drift a newer template left on the base is a warning.
def commit(d, msg):
    git = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", msg], check=True)
    return subprocess.run(
        ["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


d = fresh()
run("init", d, "--kind", "python")
commit(d, "init")
# the templates moved on after the PR branched: main's managed text is now stale
edit(d, "AGENTS.md", "1. **Licensing per directory", "1. **Licensing (an older template)")
edit(d, "LICENSE", "GNU GENERAL PUBLIC LICENSE", "GNU GENERAL PUBLIC LICENCE (older)")
base = commit(d, "main before the template change")
check(run("check", d)[0] == 1, "plain check is red on a template change (push to main)")
os.makedirs(os.path.join(d, "src"))
write(os.path.join(d, "src/x.py"), "print(1)\n")
commit(d, "a PR that touches no managed file")
rc, out = run("check", "--changed-only", base, d)
WARN = "::warning title=org-sync::"
check(
    rc == 0
    and f"{WARN}AGENTS.md#org-rules: update" in out
    and f"{WARN}LICENSE: update" in out
    and "drift     " not in out,
    "--changed-only: a PR that touches no managed file passes, the base's drift a warning",
)
edit(d, "AGENTS.md", "## Where to look", "## Where to look (the repo's own heading)")
commit(d, "the PR edits AGENTS.md outside every managed section")
rc, out = run("check", "--changed-only", base, d)
check(rc == 0, "--changed-only: an edit in a managed file but outside its sections passes")
edit(d, "AGENTS.md", "CI hygiene.", "CI hygiene, edited by hand.")
commit(d, "the PR edits a managed section by hand")
rc, out = run("check", "--changed-only", base, d)
check(
    rc == 1 and "drift     AGENTS.md#org-rules" in out and f"{WARN}LICENSE" in out,
    "--changed-only: a PR that edits a managed section by hand is red (that section only)",
)
d2 = fresh()
run("init", d2, "--kind", "python")
base = commit(d2, "init")
text = read(os.path.join(d2, "CLAUDE.md"))
write(os.path.join(d2, "CLAUDE.md"), re.sub(r"(<!-- org-sync:begin org -->\n)(.*\n)", r"\1", text))
commit(d2, "the PR deletes a line inside a managed section")
check(
    run("check", "--changed-only", base, d2)[0] == 1,
    "--changed-only: a deletion inside a section is red",
)
d3 = fresh()
run("init", d3, "--kind", "python")
base = commit(d3, "init")
edit(d3, "LICENSE", "GNU GENERAL PUBLIC LICENSE", "GNU GENERAL PUBLIC LICENCE")
os.remove(os.path.join(d3, "SECURITY.md"))
commit(d3, "the PR edits a managed file and deletes a seed")
rc, out = run("check", "--changed-only", base, d3)
check(
    rc == 1 and "drift     LICENSE" in out and "drift     SECURITY.md" in out,
    "--changed-only: a PR that edits a managed file or deletes a seed is red",
)

# hunk text that looks like a file header (`-- `/`++ ` lines) is content, not a path
d4 = fresh()
run("init", d4, "--kind", "python")
base = commit(d4, "init")
agents = read(os.path.join(d4, "AGENTS.md"))
head, rest = agents.split("\n", 1)
write(os.path.join(d4, "AGENTS.md"), head + "\n++ b/elsewhere.md\n" + rest)
edit(d4, "AGENTS.md", "CI hygiene.", "CI hygiene, edited by hand.")
commit(d4, "the PR adds a `++ ` line above a managed section and edits the section")
rc, out = run("check", "--changed-only", base, d4)
check(
    rc == 1 and "drift     AGENTS.md#org-rules" in out,
    "--changed-only: a `+++ ` line inside a hunk is not taken for a file header",
)
# HOPNET#32: a PR that only edits .github/org-sync.toml (a [settings] key) on a
# base that already drifts gets warnings, not a red check
d5 = fresh()
run("init", d5, "--kind", "python")
edit(d5, "LICENSE", "GNU GENERAL PUBLIC LICENSE", "GNU GENERAL PUBLIC LICENCE")
edit(d5, "AGENTS.md", "1. **Licensing per directory", "1. **Licensing (an older template)")
os.remove(os.path.join(d5, ".github/CODEOWNERS"))
base = commit(d5, "init, with drift on main")
with open(os.path.join(d5, ".github/org-sync.toml"), "a", encoding="utf-8") as f:
    f.write('\n[settings]\nrequired_checks = ["core-test"]\n')
commit(d5, "the PR edits .github/org-sync.toml only")
rc, out = run("check", "--changed-only", base, d5)
check(
    rc == 0
    and all(
        f"{WARN}{x}" in out
        for x in ("LICENSE: update", "AGENTS.md#org-rules: update", ".github/CODEOWNERS: create")
    )
    and "drift     " not in out,
    "--changed-only: a config-only PR on a drifting base passes with a warning per item",
)
check(run("check", d5)[0] == 1, "plain check on the same tree is still red (push to main)")
# the base's drift is judged on the merge base: a merge group's base_sha is the same call
edit(d5, "README.md", "\n## ", "\nA line of the repository's own.\n\n## ")
commit(d5, "a second queued PR in the merge group, touching no managed section")
rc, out = run("check", "--changed-only", base, d5)
check(
    rc == 0 and f"{WARN}LICENSE: update" in out and "drift     " not in out,
    "--changed-only on a merge group (several commits past its base) warns the same way",
)
# a config change whose render the PR did not apply is the PR's own drift
d6 = fresh()
run("init", d6, "--kind", "python")
base = commit(d6, "init, in sync")
cfgp = os.path.join(d6, ".github/org-sync.toml")
write(cfgp, 'badges = ["licence"]\n' + read(cfgp))
commit(d6, "the PR changes the badge list without running apply")
rc, out = run("check", "--changed-only", base, d6)
check(
    rc == 1 and "drift     README.md#badges" in out,
    "--changed-only: a config change whose render the PR did not apply is red",
)
# ... and stays red when other items already drift at the base
subprocess.run(["git", "-C", d6, "checkout", "-q", base], check=True)
edit(d6, "LICENSE", "GNU GENERAL PUBLIC LICENSE", "GNU GENERAL PUBLIC LICENCE")
base2 = commit(d6, "main with template drift")
write(cfgp, 'badges = ["licence"]\n' + read(cfgp))
commit(d6, "the PR changes the badge list without running apply")
rc, out = run("check", "--changed-only", base2, d6)
check(
    rc == 1 and "drift     README.md#badges" in out and f"{WARN}LICENSE: update" in out,
    "--changed-only: the PR's own drift is red, the base's beside it a warning",
)
# a PR that adds the config: nothing to compare against, every drift is its own
d7 = fresh()
write(os.path.join(d7, "x.txt"), "x\n")
base = commit(d7, "before org-sync")
run("init", d7, "--kind", "python")
edit(d7, "LICENSE", "GNU GENERAL PUBLIC LICENSE", "GNU GENERAL PUBLIC LICENCE")
commit(d7, "the PR adopts org-sync, with a hand edit")
rc, out = run("check", "--changed-only", base, d7)
check(
    rc == 1 and "drift     LICENSE" in out, "--changed-only: a base without a config warns nothing"
)

# CODEOWNERS (#31): a per-kind org section with `#` markers, last in the file,
# under the repository's own rules, which survive apply.
for kind, owned, unowned in (
    ("protocol", ("/core/", "*-header.*", "wire-format.md"), ("/runs/", "/skills/")),
    ("data", ("/runs/",), ("/core/", "*-header.*")),
    ("skills", ("/.claude-plugin/", "/skills/"), ("/core/",)),
):
    d = fresh()
    run("init", d, "--kind", kind, "--dual", "tools/")
    co = read(os.path.join(d, ".github/CODEOWNERS"))
    lines = [ln.split()[0] for ln in co.splitlines() if ln and not ln.startswith("#")]
    check(
        all(p in lines for p in owned + ("/LICENSING.md", "/.github/workflows/"))
        and not any(p in lines for p in unowned),
        f"CODEOWNERS covers the {kind} kind's invariant paths, and only its own",
    )
    check(
        co.rstrip("\n").endswith("# org-sync:end codeowners"),
        f"the org section ends the {kind} CODEOWNERS (the last match wins)",
    )
edit(
    d,
    ".github/CODEOWNERS",
    "# org-sync:begin codeowners\n",
    "/docs/ @someone\n# org-sync:begin codeowners\n",
)
edit(d, ".github/CODEOWNERS", "/skills/ ", "/skillz/ ")
rc, out = run("check", d)
check(
    rc == 1 and ".github/CODEOWNERS#codeowners" in out,
    "an edit in the CODEOWNERS org section is drift",
)
run("apply", d)
co = read(os.path.join(d, ".github/CODEOWNERS"))
check(
    run("check", d)[0] == 0 and "/docs/ @someone" in co and "/skills/ " in co,
    "apply restores the CODEOWNERS org section and keeps the repository's own rule",
)

with open(os.path.join(d, ".github/CODEOWNERS"), "a", encoding="utf-8") as f:
    f.write("/LICENSE @someone\n")
rc, out = run("check", d)
check(rc == 1 and "override it" in out, "a rule after the CODEOWNERS org section is drift")
d = fresh()
os.makedirs(os.path.join(d, ".github"))
write(os.path.join(d, ".github/CODEOWNERS"), "* @someone\n")
run("init", d, "--kind", "container")
co = read(os.path.join(d, ".github/CODEOWNERS"))
check(
    co.startswith("* @someone\n")
    and co.rstrip("\n").endswith("# org-sync:end codeowners")
    and run("check", d)[0] == 0,
    "an existing CODEOWNERS keeps its rules and gets the org section appended",
)

# a settings-only org-sync.toml (no kind, tools/repo-settings) manages nothing and is not an error
d = fresh()
os.makedirs(os.path.join(d, ".github"))
write(os.path.join(d, ".github/org-sync.toml"), '[settings]\ndescription = "x"\n')
for cmd in ("plan", "apply", "check", "conflicts", "seeds"):
    rc, out = run(cmd, d)
    check(rc == 0 and "settings only" in out, f"{cmd} on a settings-only config exits 0")
check(sorted(os.listdir(d)) == [".git", ".github"], "a settings-only config writes nothing")
check(
    run("plan", "--json", d)[1].strip() == '{"unchanged":0,"changes":[]}', "plan --json stays JSON"
)
check(run("seeds", "--json", d)[1].strip() == "[]", "seeds --json stays JSON")
# no kind and no [settings] is still an error (a typo must not pass as settings only)
write(os.path.join(d, ".github/org-sync.toml"), 'title = "x"\n')
try:
    rc = run("check", d)[0]
except SystemExit as e:
    rc = e.code
check(rc not in (0, None), "a config with neither kind nor [settings] is an error")

print("org-sync self-test: OK")
