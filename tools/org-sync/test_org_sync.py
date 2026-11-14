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
    "https://swarm-routing.github.io/projects/ARA/" in rd,
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
# the badges are a table, one row per group, a fixed order within a group (#415)
grouped = {k for _, kinds in org_sync.BADGE_GROUPS.values() for k in kinds}
every = set(org_sync.BASE_BADGES) | {k for ks in org_sync.KIND_BADGES.values() for k in ks}
check(
    every - {"sonar"} <= grouped and set(org_sync.SONAR_METRICS) <= grouped,
    "every badge kind belongs to a group",
)
block = re.search(r"<!-- org-sync:begin badges -->\n(.*?)<!-- org-sync:end badges -->", rd, re.S)
rows = block.group(1).splitlines()
check(
    rows[:2] == ["| Group | Badges |", "| --- | --- |"]
    and [r.split(" | ")[0] for r in rows[2:]]
    == ["| Build", "| Quality", "| Release", "| Trust", "| Stack", "| Community & docs"]
    and all(r.endswith(" |") and r.count(" | ") == 1 for r in rows[2:]),
    "a protocol repo's badges render as a two-column table, one row per group",
)
quality = next(r for r in rows if r.startswith("| Quality |"))
check(
    quality.index("alert_status") < quality.index("coderabbit")
    and "Build | [![Built on: ns3-dev]" in block.group(1)
    and "[![C++20]" in next(r for r in rows if r.startswith("| Stack |")),
    "each badge sits in its group: SonarQube before CodeRabbit in Quality, ns3-dev in Build, C++ in Stack",
)
db2 = fresh()
run("init", db2, "--kind", "protocol", "--dual", "core/")
edit(
    db2,
    ".github/org-sync.toml",
    'kind = "protocol"\n',
    'kind = "protocol"\nbadges = ["conventional", "licence", "codespaces"]\n',
)
os.makedirs(os.path.join(db2, ".devcontainer"))
with open(os.path.join(db2, ".github/org-sync.toml"), "a") as f:
    f.write(
        '\n[[extra_badges]]\ngroup = "quality"\nalt = "Core coverage"\n'
        'image = "https://img.shields.io/endpoint?url=x"\nlink = "https://example.org/ci"\n'
    )
run("apply", db2)
rows2 = read(os.path.join(db2, "README.md")).split("<!-- org-sync:begin badges -->\n")[1]
rows2 = rows2.split("<!-- org-sync:end badges -->")[0].splitlines()
check(
    rows2[2].startswith("| Quality | [![Core coverage](https://img.shields.io/endpoint?url=x)]")
    and rows2[3].startswith("| Release | [![Licence")
    and rows2[4].startswith("| Community & docs | [![Open in GitHub Codespaces]")
    and rows2[4].index("codespaces.new") < rows2[4].index("conventionalcommits")
    and len(rows2) == 5
    and run("check", db2)[0] == 0,
    "a repo's own badges list picks the badges, the groups order them; extra_badges join their"
    " group; codespaces with a .devcontainer; empty groups are left out",
)
edit(db2, ".github/org-sync.toml", 'group = "quality"', 'group = "misc"')
try:
    with contextlib.redirect_stderr(io.StringIO()):
        org_sync.load_config(db2)
    bad_extra = False
except SystemExit as e:
    bad_extra = "extra_badges" in str(e)
check(bad_extra, "an extra badge in an unknown group is a config error")
edit(db2, ".github/org-sync.toml", 'group = "misc"', 'group = "quality"')
edit(db2, ".github/org-sync.toml", "endpoint?url=x", "core coverage.svg")
try:
    with contextlib.redirect_stderr(io.StringIO()):
        org_sync.load_config(db2)
    bad_extra = False
except SystemExit as e:
    bad_extra = "extra_badges" in str(e)
check(bad_extra, "whitespace in an extra badge's image is a config error")
with open(os.path.join(da, ".github/workflows/ci.yml"), "w") as f:
    f.write(
        "      - uses: codecov/codecov-action@303a32d7a59b442fa8d48b6a1cc6825c09c847a5 # v7.1.1\n"
    )
run("apply", da)
check(
    "codecov.io/gh/swarm-routing/demo/graph/badge.svg" in read(os.path.join(da, "README.md")),
    "codecov-action called directly (AntHocNet's quality.yml) also turns on the Codecov badge",
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
# OpenSSF Best Practices (#23): the badge only with a bestpractices.dev project id
check(
    "bestpractices.dev" not in rq,
    "no Best Practices badge without bestpractices_project",
)
db = fresh()
run("init", db, "--kind", "protocol", "--dual", "core/")
edit(
    db,
    ".github/org-sync.toml",
    'kind = "protocol"\n',
    'kind = "protocol"\nbestpractices_project = "not-an-id"\n',
)
run("apply", db)
check(
    "bestpractices.dev" not in read(os.path.join(db, "README.md")),
    "a bestpractices_project that is not a project id renders no badge",
)
edit(db, ".github/org-sync.toml", '"not-an-id"', '"16656"')
run("apply", db)
rb = read(os.path.join(db, "README.md"))
check(
    "[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/16656/badge)]"
    "(https://www.bestpractices.dev/projects/16656)"
    in rb
    and rb.index("securityscorecards") < rb.index("bestpractices.dev")
    and run("check", db)[0] == 0,
    "bestpractices_project renders the Best Practices badge after Scorecard, and check is clean",
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
    and "<https://hdl.handle.net/1993/20935> (no DOI: a thesis in the university's repository). The primary source."
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

# docs/references.bib (#308): the seed, the bib's references, the bib over [[references]]
sys.path.insert(0, os.path.join(HERE, "..", "fidelity"))
import fidelity  # noqa: E402


def run_err(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = org_sync.main(list(argv))
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


head = read(os.path.join(ORG, "templates", "references-header.bib"))
seed = "% org-sync:begin bib-header\n" + head + "% org-sync:end bib-header\n"
check(
    read(os.path.join(dr, "docs/references.bib")) == seed
    and fidelity.bib.parse(seed) == []
    and not fidelity.PRIVATE.search(seed),
    "the references.bib seed: a header alone, no entries, no private-library phrase",
)
db = tempfile.mkdtemp()
os.makedirs(os.path.join(db, "docs"))
write(os.path.join(db, "docs/references.bib"), seed)
check(fidelity.bib_check(db) == ([], []), "fidelity.py bib check passes on the seed alone")
for kind in org_sync.KINDS:
    dk = fresh()
    run("init", dk, "--kind", kind)
    check(
        read(os.path.join(dk, "docs/references.bib")) == seed
        and fidelity.bib_check(dk) == ([], []),
        f"init --kind {kind} seeds docs/references.bib, and bib check passes on the fresh repo",
    )

# the bib header is a managed section (#343): a changed template is drift, the
# entries and the repository's own comment lines survive apply, and an old
# unmarked header (the seed before #343) is adopted and replaced
db = fresh()
run("init", db, "--kind", "protocol")
entry = "@misc{X1,\n  title    = {T},\n  url      = {https://example.org/x},\n  keywords = {background}\n}\n"
own = "%\n% This repository's own note, below the org header.\n"
write(os.path.join(db, "docs/references.bib"), seed + own + entry)
check(run("check", db)[0] == 0, "bib-header: a bib with entries and its own lines is clean")
edit(db, "docs/references.bib", "% Roles, in `keywords`", "% Roles (edited), in `keywords`")
rc, out = run("check", db)
check(rc == 1 and "bib-header" in out, "bib-header: a hand edit of the header is drift")
real = org_sync.template


def changed_template(name):
    t = real(name)
    return t + "% a new org line\n" if name == "references-header.bib" else t


org_sync.template = changed_template
try:
    write(os.path.join(db, "docs/references.bib"), seed + own + entry)
    rc, out = run("check", db)
    check(rc == 1 and "bib-header" in out, "bib-header: a changed header template is drift")
    run("apply", db)
    got = read(os.path.join(db, "docs/references.bib"))
    check(
        got == seed.replace("% org-sync:end", "% a new org line\n% org-sync:end") + own + entry,
        "bib-header: apply takes the new header; the entries and own lines are unchanged",
    )
finally:
    org_sync.template = real
for text, what in (
    ("% Repository-specific citation instructions\n" + entry, "a comment of the repository's own"),
    (head.replace("% this header alone.\n", "") + entry, "a header without the seed's last line"),
    (entry, "no header at all"),
):
    write(os.path.join(db, "docs/references.bib"), text)
    rc, out = run("check", db)
    run("apply", db)
    check(
        rc == 1 and "bib-header" in out and read(os.path.join(db, "docs/references.bib")) == text,
        f"bib-header: {what} is not an old org header: a conflict, the file left as it is",
    )
old_head = head.replace("Roles, in", "Roles (an older wording), in")
for tail, what in ((entry, "entries"), (own + entry, "own lines and entries"), ("", "empty rest")):
    write(os.path.join(db, "docs/references.bib"), old_head + tail)
    rc, out = run("check", db)
    check(rc == 1 and "bib-header" in out, f"bib-header: an unmarked old header is drift ({what})")
    run("apply", db)
    check(
        read(os.path.join(db, "docs/references.bib")) == seed + tail and run("check", db)[0] == 0,
        f"bib-header: apply adopts an old header and replaces it, keeping the {what}",
    )

BIB = r"""% the header
@inproceedings{G02,
  author    = {Güneş, Mesut and Sorges, Udo and Bouazizi, Imed},
  title     = {{ARA} -- The Ant-Colony Based Routing Algorithm for {MANETs}},
  booktitle = {Proceedings. International Conference on Parallel Processing Workshop},
  pages     = {79--85},
  publisher = {IEEE},
  year      = {2002},
  doi       = {10.1109/ICPPW.2002.1039715},
  keywords  = {implemented},
}
@mastersthesis{W07,
  author   = {Jianping Wang},
  title    = {A thesis},
  school   = {University of Manitoba},
  year     = {2007},
  url      = {https://hdl.handle.net/1993/20935},
  note     = {The primary source.},
  keywords = {implemented, compared},
}
@software{ns3tools,
  author    = {Joppi, Daniel},
  title     = {ns3-tools},
  publisher = {Zenodo},
  year      = {2026},
  version   = {v0.1.0},
  doi       = {10.5281/zenodo.24136068},
  url       = {https://doi.org/10.5281/zenodo.24136068},
  keywords  = {tool},
}
@misc{runs,
  author   = {{swarm-routing}},
  title    = {Benchmark runs},
  year     = {2026},
  doi      = {10.5281/zenodo.1},
  keywords = {dataset},
}
@article{D05,
  author   = {Di Caro, Gianni},
  title    = {Background only},
  journal  = {J},
  year     = {2005},
  doi      = {10.1000/bg},
  keywords = {background},
}
"""
BIB = seed + BIB.removeprefix("% the header\n")  # a bib as org-sync seeds it (#343)
# toml-only: the render above is today's; the bib-only repo below gets the same shape
bo = fresh()
run("init", bo, "--kind", "protocol")
edit(bo, ".github/org-sync.toml", 'kind = "protocol"\n', 'kind = "protocol"\ncitation = true\n')
write(os.path.join(bo, "docs/references.bib"), BIB)
rc, out, err = run_err("apply", bo)
run("reseed", "CITATION.cff", bo)
rr = read(os.path.join(bo, "README.md"))
cff = read(os.path.join(bo, "CITATION.cff"))
check(rc == 0 and "redundant" not in err, "bib only: apply succeeds, no warning")
check(
    "- M. Güneş, U. Sorges, I. Bouazizi, *ARA -- The Ant-Colony Based Routing Algorithm "
    "for MANETs*, Proceedings. International Conference on Parallel Processing Workshop, "
    "pp. 79–85, 2002, [doi:10.1109/ICPPW.2002.1039715](https://doi.org/10.1109/ICPPW.2002.1039715). "
    "The work this repository implements.\n"
    in rr
    and "- J. Wang, *A thesis*, University of Manitoba, 2007, <https://hdl.handle.net/1993/20935> "
    "(no DOI: none registered). The primary source.\n"
    in rr
    and "- D. Joppi, *ns3-tools*, 2026, [doi:10.5281/zenodo.24136068]"
    "(https://doi.org/10.5281/zenodo.24136068). A tool this repository uses.\n"
    in rr
    and "- swarm-routing, *Benchmark runs*, 2026, [doi:10.5281/zenodo.1]" in rr
    and "Background only" not in rr
    and rr.index("*ARA") < rr.index("*A thesis*") < rr.index("*ns3-tools*"),
    "bib only: README cites the implemented, tool and dataset entries in file order, doi.org links",
)
check(
    '  - type: conference-paper\n    title: "ARA -- The Ant-Colony Based Routing Algorithm for MANETs"\n'
    in cff
    and '      - family-names: "Güneş"\n        given-names: "Mesut"\n' in cff
    and '    start: "79"\n    end: "85"\n    year: 2002\n    publisher:\n      name: "IEEE"\n'
    '    doi: "10.1109/ICPPW.2002.1039715"\n'
    in cff
    and "  - type: thesis\n" in cff
    and '    thesis-type: "Master\'s thesis"\n' in cff
    and '    url: "https://hdl.handle.net/1993/20935"\n    notes: "The primary source. No DOI: none registered."\n'
    in cff
    and "  - type: software\n" in cff
    and 'zenodo.24136068"\n    notes' in cff
    and "  - type: data\n" in cff
    and '  - type: data\n    title: "Benchmark runs"\n    authors:\n      - name: "swarm-routing"\n'
    in cff
    and "10.1000/bg" not in cff,
    "bib only: CITATION.cff references: CFF types, authors, DOI (url only without one), role as notes",
)
if yaml:
    check(len(yaml.safe_load(cff)["references"]) == 4, "bib only: CITATION.cff parses as YAML")
check(run("check", bo)[0] == 0, "bib only: check is clean")
check(fidelity.bib_check(bo)[0] == [], "bib only: fidelity.py bib check agrees with the render")

# citation-refs (#307): only CITATION.cff's references: block, from the bib
rc, out = run("citation-refs", bo, "--check")
check(rc == 0 and "up to date" in out, "citation-refs --check: a reseeded CITATION.cff is current")
LNCS = r"""@incollection{DD04,
  author    = {Di Caro, Gianni and Ducatelle, Frederick},
  title     = {AntHocNet},
  booktitle = {Parallel Problem Solving from Nature - PPSN VIII},
  series    = {Lecture Notes in Computer Science},
  pages     = {461--470},
  year      = {2004},
  doi       = {10.1007/978-3-540-30217-9_47},
  keywords  = {implemented},
}
@incollection{RH10,
  author    = {Riley, George F. and Henderson, Thomas R.},
  title     = {The ns-3 Network Simulator},
  booktitle = {Modeling and Tools for Network Simulation},
  year      = {2010},
  doi       = {10.1007/978-3-642-12331-3_2},
  keywords  = {tool},
}
@incollection{W09,
  author    = {Wang, J.},
  title     = {HOPNET},
  booktitle = {Proceedings of the 2009 Workshop on Ants},
  year      = {2009},
  doi       = {10.1000/w09},
  keywords  = {compared, implemented},
}
"""
cr = tempfile.mkdtemp()  # no .github/org-sync.toml: citation-refs reads none
os.makedirs(os.path.join(cr, "docs"))
write(os.path.join(cr, "docs/references.bib"), LNCS)
rc, out = run("citation-refs", cr)
check(rc == 0 and "no CITATION.cff" in out, "citation-refs: without CITATION.cff, nothing to do")
HEAD = '# a hand-written file\ncff-version: 1.2.0\ntitle: "X"\nauthors:\n  - name: "Y"\n'
TAIL = "# a trailing comment\nkeywords:\n  - ants\n"
old_refs = 'references:\n  - type: book\n    title: "stale"\n\n'
write(os.path.join(cr, "CITATION.cff"), HEAD + old_refs + TAIL)
rc, out = run("citation-refs", cr, "--check")
check(
    rc == 1
    and "drifted" in out
    and '-    title: "stale"' in out
    and read(os.path.join(cr, "CITATION.cff")) == HEAD + old_refs + TAIL,
    "citation-refs --check: stale references are drift, exit 1, nothing written",
)
rc, out = run("citation-refs", cr)
cff2 = read(os.path.join(cr, "CITATION.cff"))
block = org_sync.cff_references(org_sync.bib_references(cr))
check(
    rc == 0 and "rewritten" in out and cff2 == HEAD + block + "\n" + TAIL,
    "citation-refs: only the references: block changes, every other byte as it was",
)
check(run("citation-refs", cr, "--check")[0] == 0, "citation-refs: idempotent")
check(
    '  - type: conference-paper\n    title: "AntHocNet"\n' in cff2
    and '    collection-title: "Parallel Problem Solving from Nature - PPSN VIII"\n'
    "    collection-type: proceedings\n"
    in cff2
    and '  - type: book\n    title: "The ns-3 Network Simulator"\n' in cff2
    and '  - type: conference-paper\n    title: "HOPNET"\n' in cff2,
    "#331: an LNCS or proceedings @incollection is a conference-paper; a book chapter stays book",
)
if yaml:
    check(
        [r["type"] for r in yaml.safe_load(cff2)["references"]]
        == ["conference-paper", "book", "conference-paper"]
        and yaml.safe_load(cff2)["keywords"] == ["ants"],
        "citation-refs: the result parses as YAML, the keys after it intact",
    )
inner = 'references:\n  - type: book\n    title: "Old A"\n# between items\n  - type: book\n    title: "Old B"\n\n'
write(os.path.join(cr, "CITATION.cff"), HEAD + inner + TAIL)
run("citation-refs", cr)
check(
    read(os.path.join(cr, "CITATION.cff")) == HEAD + block + "\n" + TAIL,
    "citation-refs: a comment between items is inside the block, the one before a key outside",
)
for flow in ("references: []\n", 'references: [{type: book, title: "x"}]\n'):
    write(os.path.join(cr, "CITATION.cff"), HEAD + flow + TAIL)
    run("citation-refs", cr)
    check(
        read(os.path.join(cr, "CITATION.cff")) == HEAD + block + TAIL,
        f"citation-refs: a one-line flow value is replaced, not duplicated ({flow.strip()})",
    )
write(os.path.join(cr, "CITATION.cff"), HEAD)
run("citation-refs", cr)
check(
    read(os.path.join(cr, "CITATION.cff")) == HEAD + block,
    "citation-refs: a CITATION.cff without references: gets the block at its end",
)
write(
    os.path.join(cr, "docs/references.bib"),
    "@misc{B1, title = {t}, url = {https://e.org}, keywords = {background}}\n",
)
write(os.path.join(cr, "CITATION.cff"), HEAD + old_refs + TAIL)
run("citation-refs", cr)
check(
    read(os.path.join(cr, "CITATION.cff")) == HEAD + "\n" + TAIL,
    "citation-refs: no implemented, tool or dataset entry removes the block",
)
write(os.path.join(cr, "docs/references.bib"), seed)
write(os.path.join(cr, "CITATION.cff"), HEAD + old_refs + TAIL)
rc, out = run("citation-refs", cr, "--check")
check(
    rc == 0
    and "no entry" in out
    and read(os.path.join(cr, "CITATION.cff")) == HEAD + old_refs + TAIL,
    "citation-refs: with the seed bib (no entry) it leaves CITATION.cff alone",
)
# both: the bib wins, [[references]] is reported as redundant (and left in place)
toml_before = read(os.path.join(dr, ".github/org-sync.toml"))
readme_before = read(os.path.join(dr, "README.md"))
write(os.path.join(dr, "docs/references.bib"), BIB)
rc, out, err = run_err("check", dr)
check(
    rc == 1 and "README.md#citing" in out and "[[references]]" in err and "redundant" in err,
    "both: the bib wins (the citing section drifts) and [[references]] is reported redundant",
)
run_err("apply", dr)
rr = read(os.path.join(dr, "README.md"))
check(
    "*ns3-tools*" in rr
    and "a thesis in the university's repository" not in rr
    and read(os.path.join(dr, ".github/org-sync.toml")) == toml_before,
    "both: the README cites the bib's entries; [[references]] is not deleted",
)
write(os.path.join(dr, "docs/references.bib"), seed)
run_err("apply", dr)
check(
    read(os.path.join(dr, "README.md")) == readme_before,
    "toml only: with the seed (no entry), [[references]] renders byte-identically to before",
)
os.remove(os.path.join(dr, "docs/references.bib"))
rc, out, err = run_err("plan", dr)
check(
    rc == 0 and "docs/references.bib" in out and "redundant" not in err,
    "toml only: without the bib, plan proposes the seed and gives no warning",
)
write(os.path.join(dr, "docs/references.bib"), seed)
# malformed: a clear error naming the file and the line
for bad, why in (
    ("@article{X,\n  title = {unclosed,\n", "unbalanced braces"),
    ("@article{X,\n  title = bare,\n}\n", "macro"),
    (
        "@article{X,\n  author = {A, B}, title = {T}, year = {2000}, doi = {not-a-doi},\n"
        "  keywords = {implemented},\n}\n",
        "not a DOI",
    ),
    (
        "@article{X,\n  title = {T}, year = {2000}, doi = {10.1/x}, keywords = {implemented},\n}\n",
        "author",
    ),
):
    write(os.path.join(bo, "docs/references.bib"), bad)
    rc, out, err = run_err("plan", bo)
    check(
        rc not in (0, None) and "docs/references.bib" in str(rc) + err and why in str(rc) + err,
        f"malformed bib refused: {why}",
    )
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
    '[[references]]\ntype = "article"\ntitle = "t"\nauthors = ["A, B"]\nyear = 2000\nrole = "r"\n'
    'doi = "https://doi.org/10.1/x"\n',
    '[[references]]\ntype = "article"\ntitle = "t"\nauthors = ["A, B"]\nyear = 2000.5\nrole = "r"\n'
    'doi = "10.1/x"\n',
    '[[references]]\ntype = "article"\ntitle = "t"\nauthors = ["A, B"]\nyear = 2000\nrole = 7\n'
    'doi = "10.1/x"\n',
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
    "adopt     AGENTS.md#org-rules" in out and "adopt     AGENTS.md#agent-defaults" in out,
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
gw_end = "<!-- org-sync:end git-workflow -->\n"
edit(
    d,
    "AGENTS.md",
    gw_end + agents[agents.index(gw_end) + len(gw_end) :].split("## Where to look")[0],
    gw_end + "\n",
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
    "## Agent skills" in read(os.path.join(d, "AGENTS.md"))
    and "<!-- org-sync:begin agent-defaults -->" in read(os.path.join(d, "AGENTS.md"))
    and run("check", d)[0] == 0,
    "the skills section is inserted when the heading has no blank line before it",
)

# 5b. The swarm-core dependencies section renders only where it is true
#     (swarm-routing/ns3-swarm-core#134): none without a pin, the commit-pin text
#     with SWARM_CORE_REF, the lock text with swarm-core.lock.
d = fresh()
run("init", d, "--kind", "protocol")
check(
    "org-sync:begin dependencies" not in read(os.path.join(d, "AGENTS.md")),
    "no swarm-core pin: no dependencies section",
)
os.makedirs(os.path.join(d, "core"), exist_ok=True)
write(
    os.path.join(d, "core/CMakeLists.txt"),
    'set(SWARM_CORE_REF "' + "a" * 40 + '" CACHE STRING "x")\n',
)
rc, out = run("plan", d)
check("adopt     AGENTS.md#dependencies" in out, "a commit pin: the section is planned")
run("apply", d)
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "<!-- org-sync:begin dependencies -->\n## How this repository gets swarm-core" in agents
    and "fetches it with CMake\n  `FetchContent` at one commit" in agents
    and agents.index("## How this repository gets") < agents.index("## Golden rules")
    and run("check", d)[0] == 0,
    "a commit pin: the pin text, before the golden rules, and check passes",
)
write(os.path.join(d, "swarm-core.lock"), "SWARM_CORE_REPO=swarm-routing/ns3-swarm-core\n")
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#dependencies" in out, "a lock added: the section drifts")
run("apply", d)
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "`swarm-core.lock` names one swarm-core release" in agents
    and "at one commit" not in agents
    and run("check", d)[0] == 0,
    "a lock: the lock text replaces the pin text",
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

# A repository's own path_filters (swarm-routing/AntHocNet#838: generated data) are rendered
# into the head after the org's, as list entries, not hand edits.
toml = os.path.join(d, ".github/org-sync.toml")
write(toml, 'coderabbit_path_filters = ["!results/**", "!docs/*.png"]\n' + read(toml))
rc, out = run("check", d)
check(rc == 1 and ".coderabbit.yaml#coderabbit-head" in out, "a new path filter is drift")
run("apply", d)
text = read(cr)
check(
    run("check", d)[0] == 0
    and '    - "!**/*.pdf"\n    - "!results/**"\n    - "!docs/*.png"\n  path_instructions:' in text
    and "LOCAL RULE" in text,
    "apply renders the repository's path filters after the org's, in order",
)
for bad in ('coderabbit_path_filters = "!results/**"\n', 'coderabbit_path_filters = ["a\\"b"]\n'):
    db = fresh()
    os.makedirs(os.path.join(db, ".github"))
    write(os.path.join(db, ".github/org-sync.toml"), bad + 'kind = "data"\n')
    try:
        rc = run("plan", db)[0]
    except SystemExit as e:
        rc = e.code
    check(rc not in (0, None), "refused: " + bad.strip())

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
text = read(os.path.join(d2, "AGENTS.md"))
write(
    os.path.join(d2, "AGENTS.md"),
    re.sub(r"(<!-- org-sync:begin agent-defaults -->\n)(.*\n)", r"\1", text),
)
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


# Orphan blocks (#235): a block in a managed file whose section is skipped or not
# enabled (benchmarks#46/#47: a refresh rendered `citing` from a config the skip
# had already replaced) is drift; apply removes it only with --prune-orphans.
d8 = fresh()
run("init", d8, "--kind", "data")
cfgp = os.path.join(d8, ".github/org-sync.toml")
write(cfgp, "citation = true\n" + read(cfgp))
run("apply", d8)
check(
    "<!-- org-sync:begin citing -->" in read(os.path.join(d8, "README.md"))
    and run("check", d8)[0] == 0,
    "citation = true renders the citing section, in sync",
)
base = commit(d8, "main with the citing section")
write(cfgp, 'skip = ["README.md#citing"]\n' + read(cfgp))
commit(d8, "the PR skips the section and leaves its block")
rc, out = run("check", d8)
check(
    rc == 1
    and "drift     README.md#citing: orphan (orphan block citing in README.md" in out
    and "drop the skip" in out,
    "check reports a skipped section's block as an orphan, naming it and its file",
)
rc, out = run("plan", d8)
check("orphan    README.md#citing" in out, "plan lists the orphan")
check(
    '"item":"README.md#citing","status":"orphan","lines":' in run("plan", "--json", d8)[1],
    "plan --json lists the orphan with its line count",
)
rc, out = run("check", "--changed-only", base, d8)
check(
    rc == 1 and "drift     README.md#citing: orphan" in out,
    "--changed-only: an orphan the PR brings in (a new skip) is red, though the block was "
    "managed at the base",
)
orphaned = commit(d8, "main with the orphan (benchmarks after #46 and #47)")
edit(d8, "README.md", "\n## Contributing", "\nA line of the repository's own.\n\n## Contributing")
commit(d8, "a later PR that does not touch the block")
rc, out = run("check", "--changed-only", orphaned, d8)
check(
    rc == 0 and f"{WARN}README.md#citing: orphan" in out,
    "--changed-only: an orphan already at the base is a warning",
)
edit(d8, "README.md", "## Releases & citing", "## Releases and citing")
commit(d8, "a PR that edits the orphan block by hand")
check(
    run("check", "--changed-only", orphaned, d8)[0] == 1,
    "--changed-only: a PR that edits an orphan block is red",
)
before = read(os.path.join(d8, "README.md"))
rc, out = run("apply", d8)
check(
    rc == 1
    and "orphan    README.md#citing:" in out
    and read(os.path.join(d8, "README.md")) == before,
    "apply without --prune-orphans leaves the orphan and reports it (exit 1)",
)
rc, out = run("apply", d8, "--prune-orphans")
rr = read(os.path.join(d8, "README.md"))
check(
    rc == 0
    and "removed   README.md#citing (orphan)" in out
    and "org-sync:begin citing" not in rr
    and "Releases and citing" not in rr
    and "\n\n\n" not in rr
    and "A line of the repository's own." in rr
    and run("check", d8)[0] == 0,
    "apply --prune-orphans removes the block, its markers and one blank line; check is clean",
)
# a block of a section that is not enabled (citation off), in YAML too; the
# repository's own text around it and other files' blocks are left alone
d9 = fresh()
run("init", d9, "--kind", "python")
edit(
    d9,
    "AGENTS.md",
    "## Where to look",
    "<!-- org-sync:begin stale -->\nold\n<!-- org-sync:end stale -->\n\n## Where to look",
)
with open(os.path.join(d9, ".coderabbit.yaml"), "a", encoding="utf-8") as f:
    f.write("# org-sync:begin old\nold: 1\n# org-sync:end old\n")
write(os.path.join(d9, "notes.md"), "<!-- org-sync:begin x -->\nx\n<!-- org-sync:end x -->\n")
rc, out = run("check", d9)
check(
    rc == 1
    and "drift     AGENTS.md#stale: orphan" in out
    and "drift     .coderabbit.yaml#old: orphan" in out
    and "enable its item" in out
    and "notes.md" not in out
    and out.count("drift     ") == 2,
    "a block of a section that is not enabled is an orphan (Markdown and YAML markers); "
    "a file org-sync does not manage is not scanned",
)
run("apply", d9, "--prune-orphans")
check(
    run("check", d9)[0] == 0
    and "## Where to look" in read(os.path.join(d9, "AGENTS.md"))
    and "x\n" in read(os.path.join(d9, "notes.md")),
    "--prune-orphans clears both; the repository's own text stays",
)

# citation_message (#235): the repository's own CITATION.cff message, kept on reseed
dm = fresh()
run("init", dm, "--kind", "data")
msg = (
    "If you use these data, please cite the dataset version (its DOI) and the run directory, "
    "using the metadata below."
)
cfgp = os.path.join(dm, ".github/org-sync.toml")
write(
    cfgp, f'citation = true\ncitation_type = "dataset"\ncitation_message = "{msg}"\n' + read(cfgp)
)
run("apply", dm)
cff = os.path.join(dm, "CITATION.cff")
check(f'message: "{msg}"\n' in read(cff), "citation_message sets CITATION.cff's message")
edit(dm, "CITATION.cff", msg, "something else")
run("reseed", "CITATION.cff", dm)
check(
    f'message: "{msg}"\n' in read(cff) and "\ntype: dataset\n" in read(cff),
    "reseed CITATION.cff keeps citation_message",
)
for bad in (
    'citation_message = "a \\"quoted\\" word"\n',
    'citation_message = ""\n',
    "citation_message = 3\n",
    'citation_message = "a\\nb"\n',
):
    db = fresh()
    os.makedirs(os.path.join(db, ".github"))
    write(os.path.join(db, ".github/org-sync.toml"), 'kind = "data"\ncitation = true\n' + bad)
    try:
        rc = run("plan", db)[0]
    except SystemExit as e:
        rc = e.code
    check(rc not in (0, None), f"an invalid citation_message is refused: {bad.strip()}")

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

# #277: CLAUDE.md is the org's whole file; an old CLAUDE.md with its own text and
# an `org` block is replaced by `@AGENTS.md`, not reported or pruned as an orphan
d5 = fresh()
run("init", d5, "--kind", "python")
write(
    os.path.join(d5, "CLAUDE.md"),
    "# CLAUDE.md\n\n@AGENTS.md\n\nRepo text.\n\n<!-- org-sync:begin org -->\nold\n"
    "<!-- org-sync:end org -->\n",
)
rc, out = run("plan", d5)
check(
    "update    CLAUDE.md" in out and "orphan" not in out, "an old CLAUDE.md is an update, no orphan"
)
run("apply", d5, "--prune-orphans")
check(
    read(os.path.join(d5, "CLAUDE.md")) == "@AGENTS.md\n" and run("check", d5)[0] == 0,
    "apply leaves CLAUDE.md as the single import line",
)

# #318: `forms = true` manages each org form as a whole file; config.yml and a
# repository-only form stay the repository's
d6 = fresh()
run("init", d6, "--kind", "python")
forms = os.path.join(d6, ".github/ISSUE_TEMPLATE")
check(not os.path.exists(os.path.join(forms, "chore.yml")), "without the opt-in no form is managed")
edit(d6, ".github/org-sync.toml", 'kind = "python"', 'kind = "python"\nforms = true')
os.makedirs(forms, exist_ok=True)
write(os.path.join(forms, "config.yml"), "blank_issues_enabled: true\n")
write(os.path.join(forms, "image-request.yml"), "name: Image request\n")
run("apply", d6)
check(
    read(os.path.join(forms, "chore.yml")) == read(os.path.join(ORG, "ISSUE_TEMPLATE/chore.yml"))
    and run("check", d6)[0] == 0,
    "apply copies every org form and check is clean",
)
edit(d6, ".github/ISSUE_TEMPLATE/literature.yml", "name:", "name: old")
rc, out = run("check", d6)
check(rc == 1 and ".github/ISSUE_TEMPLATE/literature.yml" in out, "a changed org form is drift")
run("apply", d6)
check(
    read(os.path.join(forms, "config.yml")) == "blank_issues_enabled: true\n"
    and read(os.path.join(forms, "image-request.yml")) == "name: Image request\n"
    and run("check", d6)[0] == 0,
    "config.yml and a repository-only form are left alone",
)

print("org-sync self-test: OK")
