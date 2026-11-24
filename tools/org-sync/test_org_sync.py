#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Self-test for org_sync.py against throwaway fixture repos. Exits non-zero on
the first failure; no pytest dependency."""

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org_sync  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "zenodo"))
import zenodo  # noqa: E402

ORG = org_sync.ORG
# the template pin (#586): no lock unless a test names a commit, so the
# fixtures render the same on a feature branch, a dirty tree and CI
REAL_ORG_COMMIT = org_sync.org_commit
org_sync.org_commit = lambda: (None, "self-test")


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
# the class documentation (#883): the Doxyfile seed and the org's api-docs workflow
da_api = read(os.path.join(da, ".github/workflows/api-docs.yml"))
check(
    'PROJECT_NAME           = "ARA"' in read(os.path.join(da, "docs/api/Doxyfile"))
    and "reusable-doxygen.yml@" in da_api
    and 'doxyfile: "docs/api/Doxyfile"' in da_api
    and "@DOXYFILE@" not in da_api,
    "a protocol repo is seeded with docs/api/Doxyfile and gets api-docs.yml building it",
)
dx = fresh()
run("init", dx, "--kind", "protocol", "--dual", "core/")
# a top-level key: before the file's first table
write(
    os.path.join(dx, ".github/org-sync.toml"),
    '\ndoxyfile = "api/Doxyfile"\n' + read(os.path.join(dx, ".github/org-sync.toml")),
)
os.makedirs(os.path.join(dx, "api"), exist_ok=True)
write(os.path.join(dx, "api/Doxyfile"), 'PROJECT_NAME = "own"\n')
run("apply", dx)
check(
    read(os.path.join(dx, "api/Doxyfile")) == 'PROJECT_NAME = "own"\n'
    and 'doxyfile: "api/Doxyfile"' in read(os.path.join(dx, ".github/workflows/api-docs.yml")),
    "doxyfile names an own Doxyfile (AntHocNet's api/Doxyfile): kept, and the workflow builds it",
)
for bad in ('"../Doxyfile"', '"/etc/Doxyfile"', '"a b"', "3"):
    edit(dx, ".github/org-sync.toml", "\ndoxyfile = ", f"\ndoxyfile = {bad}\n# was ")
    try:
        refused = "doxyfile must be" in str(run("check", dx))
    except SystemExit as e:
        refused = "doxyfile must be" in str(e.code)
    check(refused, f"doxyfile = {bad} is refused")
    edit(dx, ".github/org-sync.toml", f"\ndoxyfile = {bad}\n# was ", "\ndoxyfile = ")
os.makedirs(os.path.join(da, ".github/workflows"), exist_ok=True)
with open(os.path.join(da, ".github/workflows/ci.yml"), "w") as f:
    f.write("    uses: swarm-routing/.github/.github/workflows/reusable-codecov.yml@main\n")
run("apply", da)
check(
    "codecov.io/gh/swarm-routing/demo/branch/main/graph/badge.svg"
    in read(os.path.join(da, "README.md")),
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
    and "[![C++23]" in next(r for r in rows if r.startswith("| Stack |")),
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
    and rows2[4].startswith("| Community & docs | [![Conventional Commits]")
    and "codespaces" not in "".join(rows2).lower()
    and len(rows2) == 5
    and run("check", db2)[0] == 0,
    "a repo's own badges list picks the badges, the groups order them; extra_badges join their"
    " group; no Codespaces badge even when listed and a .devcontainer exists; empty groups are left out",
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
    "codecov.io/gh/swarm-routing/demo/branch/main/graph/badge.svg"
    in read(os.path.join(da, "README.md")),
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
# RCAPA (ADR-0003): the flow and template seeded, the open-RCAPA badge, ns-3 bugs only with the register
dr2 = fresh()
run("init", dr2, "--kind", "protocol", "--dual", "core/")
rr = read(os.path.join(dr2, "README.md"))
idx = read(os.path.join(dr2, "docs/rcapa/README.md"))
check(
    idx.startswith("# RCAPA: regressions in a release of swarm-routing/demo\n")
    and "## Index" in idx
    and "```mermaid" in idx
    and os.path.exists(os.path.join(dr2, "docs/rcapa/_template.md"))
    and "[docs/rcapa/README.md](docs/rcapa/README.md)" in rr,
    "init seeds docs/rcapa/ (the flow with the repo's name, the template) and the Develop section links it",
)
check(
    "[![Open RCAPA](https://img.shields.io/github/issues/swarm-routing/demo/rcapa"
    "?label=open%20RCAPA&color=blue)](https://github.com/swarm-routing/demo/blob/main/docs/rcapa/README.md)"
    in rr
    and "ns-3 bugs" not in rr,
    "the open-RCAPA badge counts the repo's rcapa issues; no ns-3 bugs badge without docs/ns3-bugs.md",
)
write(os.path.join(dr2, "docs/rcapa/README.md"), "# RCAPA: our own flow\n")
write(os.path.join(dr2, "docs/ns3-bugs.md"), "# ns-3 bugs\n")
run("apply", dr2)
rr = read(os.path.join(dr2, "README.md"))
check(
    read(os.path.join(dr2, "docs/rcapa/README.md")) == "# RCAPA: our own flow\n"
    and "/ns3-upstream?label=ns-3%20bugs&color=blue)](docs/ns3-bugs.md)" in rr
    and rr.index("open%20RCAPA") < rr.index("ns-3%20bugs")
    and run("check", dr2)[0] == 0,
    "the rcapa seed stays the repo's own; docs/ns3-bugs.md adds the ns-3 bugs badge after it",
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

# vcpkg and pypi (#436): only when the config names the ports / the project
check(
    "vcpkg-registry" not in rq and "pypi" not in rq.lower(),
    "no vcpkg or PyPI badge without vcpkg_ports / pypi_project",
)
dv = fresh()
run("init", dv, "--kind", "protocol", "--dual", "core/")
edit(
    dv,
    ".github/org-sync.toml",
    'kind = "protocol"\n',
    'kind = "protocol"\nvcpkg_ports = ["swarm-core", "Not A Port", "trailing\\n"]\npypi_project = "ns3-tools"\n',
)
run("apply", dv)
rv = read(os.path.join(dv, "README.md"))
release_row = next(ln for ln in rv.splitlines() if ln.startswith("| Release |"))
check(
    "https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com"
    "%2Fswarm-routing%2Fvcpkg-registry%2Fmain%2Fports%2Fswarm-core%2Fvcpkg.json"
    "&query=%24%5B%22version-semver%22%5D&label=vcpkg%20swarm-core"
    in release_row
    and "(https://github.com/swarm-routing/vcpkg-registry/tree/main/ports/swarm-core)"
    in release_row
    and "Not A Port" not in rv
    and "trailing" not in rv
    and "[![PyPI](https://img.shields.io/pypi/v/ns3-tools?label=PyPI)](https://pypi.org/project/ns3-tools/)"
    in release_row
    and release_row.index("vcpkg") < release_row.index("PyPI") < release_row.index("Licence")
    and run("check", dv)[0] == 0,
    "vcpkg_ports and pypi_project render their badges in the Release row, before the licence; check is clean",
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
write(
    os.path.join(dr, ".github/workflows/release-sync.yml"),
    "# every release, sent by swarm-routing/.github's reusable-release.yml, reaches the site\n",
)
os.remove(os.path.join(dr, ".github/workflows/release.yml"))
run("apply", dr)
check(
    "github/v/release" not in read(os.path.join(dr, "README.md")),
    "a workflow that only names reusable-release.yml in a comment gives no release badge (the site's)",
)
write(os.path.join(dr, ".github/workflows/release.yml"), "on: workflow_dispatch\n")
run("apply", dr)
check(
    "github/v/release" in read(os.path.join(dr, "README.md")),
    "a release.yml of the repository's own gives the release badge (AntHocNet's)",
)
write(
    os.path.join(dr, ".github/workflows/release.yml"),
    "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main # the org's\n",
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
# `zenodo = false` (#811): releases, but no Zenodo archive, so no DOI anywhere
edit(dr, ".github/org-sync.toml", 'kind = "protocol"\n', 'kind = "protocol"\nzenodo = false\n')
run("apply", dr)
rc, out = run("reseed", "CITATION.cff", dr)
rr, cff = read(os.path.join(dr, "README.md")), read(os.path.join(dr, "CITATION.cff"))
check(
    rc == 0
    and "zenodo.org/badge" not in rr
    and "10.5281/zenodo" not in rr
    and "\ndoi:" not in cff
    and "identifiers:" not in cff
    and "It has no DOI yet" not in rr
    and "archived on [Zenodo]" not in rr
    and "Its releases are not archived on Zenodo, so it has no DOI" in rr
    and "built by the org's release workflow." in rr,
    "zenodo = false: no DOI badge, no doi line, no pending DOI, even with a zenodo_concept",
)
check(run("check", dr)[0] == 0, "check is clean with zenodo = false")
edit(dr, ".github/org-sync.toml", "zenodo = false\n", 'zenodo = "no"\n')
try:
    rc = run("plan", dr)[0]
except SystemExit as e:
    rc = e.code
check("zenodo must be true or false" in str(rc), "zenodo must be a bool")
edit(dr, ".github/org-sync.toml", 'zenodo = "no"\n', "")
run("apply", dr)
run("reseed", "CITATION.cff", dr)
check(
    'doi: "10.5281/zenodo.1234567"' in read(os.path.join(dr, "CITATION.cff")),
    "without the opt-out the concept DOI is back",
)
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

# the `adapter` role: a work built on this repository (swarm-core's ns-3 adapter).
# README lists it apart, never as work it builds on; CITATION.cff marks it, and
# its DOI is never taken for the repository's own
ad = fresh()
run("init", ad, "--kind", "protocol")
edit(ad, ".github/org-sync.toml", 'kind = "protocol"\n', 'kind = "protocol"\ncitation = true\n')
ADAPTER = r"""@software{SwarmCore,
  author    = {Joppi, Daniel Henrique},
  title     = {swarm-adapter-ns3},
  publisher = {Zenodo},
  year      = {2026},
  doi       = {10.5281/zenodo.24138628},
  note      = {Its ns-3 adapter.},
  keywords  = {adapter},
}
"""
write(os.path.join(ad, "docs/references.bib"), seed + ADAPTER)
run("apply", ad)
run("reseed", "CITATION.cff", ad)
rr = read(os.path.join(ad, "README.md"))
cff = read(os.path.join(ad, "CITATION.cff"))
check(
    "Please also cite" not in rr
    and "Works that build on it:\n\n- D. H. Joppi, *swarm-adapter-ns3*, 2026, "
    "[doi:10.5281/zenodo.24138628](https://doi.org/10.5281/zenodo.24138628). Its ns-3 adapter.\n"
    in rr,
    "adapter role: README lists it under its own heading, not as work it builds on",
)
check(
    '    notes: "Its ns-3 adapter."\n    keywords:\n      - "adapter"\n' in cff
    and zenodo.concept_from(cff) is None
    and run("check", ad)[0] == 0
    and fidelity.bib_check(ad)[0] == [],
    "adapter role: CITATION.cff marks it, it is not the repository's DOI, checks pass",
)
if yaml:
    check(
        yaml.safe_load(cff)["references"][0]["keywords"] == ["adapter"]
        and zenodo.cff_related(yaml.safe_load(cff))[0]["relation"] == "isRequiredBy",
        "adapter role: Zenodo gets isRequiredBy",
    )
write(
    os.path.join(ad, "docs/references.bib"),
    seed + ADAPTER.replace("keywords  = {adapter}", "keywords  = {tool, adapter}"),
)
run("apply", ad)
check(
    "Please also cite" not in read(os.path.join(ad, "README.md"))
    and "Works that build on it:" in read(os.path.join(ad, "README.md")),
    "adapter role: it wins after another role in keywords",
)

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
# Develop (#490): every README links docs/development.md through a managed section
rr = read(os.path.join(de, "README.md"))
check(
    "<!-- org-sync:begin develop -->\n## Develop\n" in rr
    and "](docs/development.md)" in rr
    and rr.index("org-sync:end develop") < rr.index("org-sync:begin citing") < rr.index("## Epics"),
    "init writes the Develop section; with citing on, Develop comes first, then citing",
)
dd = fresh()
run("init", dd, "--kind", "data")
rd = read(os.path.join(dd, "README.md"))
s0 = rd.index("<!-- org-sync:begin develop -->")
e0 = rd.index("<!-- org-sync:end develop -->\n\n") + len("<!-- org-sync:end develop -->\n\n")
write(os.path.join(dd, "README.md"), rd[:s0] + rd[e0:])
guide = read(os.path.join(dd, "docs/development.md")) or ""
check(
    guide.startswith("# Developer guide\n")
    and "## Troubleshooting\n" in guide
    and "{repo}" not in guide
    and re.search(r'^cd "\$\(basename [^/\s]+/[^/\s)]+\)"$', guide, re.M) is not None
    and "/rules/branches/main" in guide,
    "init seeds docs/development.md, the link's target, its placeholders filled",
)
check(run("check", dd)[0] == 1, "a README without the Develop section drifts")
run("apply", dd)
rd2 = read(os.path.join(dd, "README.md"))
check(
    rd2.index("org-sync:end develop -->\n\n## Contributing") > 0 and run("check", dd)[0] == 0,
    "apply inserts the Develop section into an existing README, before Contributing",
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
check(
    "own ns-3 CI (it does not call" in agents
    and "canary-dependencies" not in agents
    and "- **Working against an unreleased swarm-core**" in agents,
    "a lock, no reusable-ns3-ci.yml caller (AntHocNet): no canary bullet (#560)",
)
os.makedirs(os.path.join(d, ".github/workflows"), exist_ok=True)
write(
    os.path.join(d, ".github/workflows/ns3.yml"),
    "jobs:\n  ci:\n    uses: swarm-routing/.github/.github/workflows/reusable-ns3-ci.yml@main\n",
)
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#dependencies" in out, "a reusable-ns3-ci.yml caller added: drifts")
run("apply", d)
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "`canary-dependencies` names `@main`" in agents
    and "own ns-3 CI" not in agents
    and run("check", d)[0] == 0,
    "a lock and a reusable-ns3-ci.yml caller: the canary bullet",
)
write(os.path.join(d, "vcpkg.json"), '{"dependencies": ["swarm-core"]}\n')
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#dependencies" in out, "vcpkg.json added: the section drifts")
run("apply", d)
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "through vcpkg in manifest mode" in agents
    and "`FetchContent`" not in agents
    and run("check", d)[0] == 0,
    "vcpkg mode (#489): the vcpkg text replaces the lock text",
)
# vcpkg mode with the adapter's own lock beside swarm-core.lock (AntHocNet,
# swarm-routing/AntHocNet#1218): the ns-3 module comes from swarm-adapter-ns3.lock
d = fresh()
run("init", d, "--kind", "protocol")
write(os.path.join(d, "swarm-core.lock"), "SWARM_CORE_REPO=swarm-routing/swarm-core\n")
write(os.path.join(d, "vcpkg.json"), '{"dependencies": ["swarm-core"]}\n')
os.makedirs(os.path.join(d, "core"), exist_ok=True)
write(os.path.join(d, "core/CMakeLists.txt"), "find_package(swarm-core CONFIG REQUIRED)\n")
write(os.path.join(d, "swarm-adapter-ns3.lock"), "ADAPTER_REPO=swarm-routing/swarm-adapter-ns3\n")
run("apply", d)
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "through vcpkg in manifest mode" in agents
    and "`swarm-adapter-ns3.lock` (prefix `ADAPTER_`) names" in agents
    and "vcpkg has no ns-3 port, so the ns-3 build\n  keeps the release tag" not in agents
    and "own ns-3 CI (it does not call" in agents
    and run("check", d)[0] == 0,
    "vcpkg and the adapter's lock: the two-lock text, and check passes",
)
os.remove(os.path.join(d, "swarm-adapter-ns3.lock"))
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#dependencies" in out, "the adapter's lock removed: the vcpkg text")
# the ns-3 adapter (swarm-routing/swarm-adapter-ns3#258): a lock read by the root
# CMakeLists.txt, no core/: the adapter text, none of a protocol's pin places
d = fresh()
run("init", d, "--kind", "protocol")
write(os.path.join(d, "swarm-core.lock"), "SWARM_CORE_REPO=swarm-routing/swarm-core\n")
write(os.path.join(d, "CMakeLists.txt"), 'file(STRINGS "swarm-core.lock" lock)\n')
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#dependencies" in out, "an adapter lock: the section is planned")
run("apply", d)
agents = read(os.path.join(d, "AGENTS.md"))
check(
    "this is the ns-3 adapter of swarm-core's ports" in agents
    and "core/CMakeLists.txt" not in agents
    and "core-deps` (the licence" not in agents
    and "canary-dependencies" not in agents
    and run("check", d)[0] == 0,
    "the adapter layout: the adapter text, and check passes",
)
os.makedirs(os.path.join(d, "core"), exist_ok=True)
write(os.path.join(d, "core/CMakeLists.txt"), "file(STRINGS ../swarm-core.lock x)\n")
rc, out = run("check", d)
check(rc == 1 and "AGENTS.md#dependencies" in out, "a core/ added: the protocol's lock text")

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

# #586: the base is rendered with every file the render reads, not only the
# managed ones: a vcpkg-mode repository (swarm-core.lock + vcpkg.json) whose
# dependencies section a newer template changed, and a PR that touches no
# managed file, passes (the base's tree without vcpkg.json rendered no
# dependencies section, so the drift read as the PR's own)
dv2 = fresh()
write(os.path.join(dv2, "swarm-core.lock"), "SWARM_CORE_TAG=v1.0.0\n")
write(os.path.join(dv2, "vcpkg.json"), '{"dependencies": ["swarm-core"]}\n')
run("init", dv2, "--kind", "protocol")
check(
    "<!-- org-sync:begin dependencies -->" in read(os.path.join(dv2, "AGENTS.md")),
    "vcpkg mode renders the dependencies section",
)
text = read(os.path.join(dv2, "AGENTS.md"))
write(
    os.path.join(dv2, "AGENTS.md"),
    re.sub(r"(<!-- org-sync:begin dependencies -->\n)", r"\1- an older template line\n", text),
)
base = commit(dv2, "main, rendered from an older dependencies template")
os.makedirs(os.path.join(dv2, "src"))
write(os.path.join(dv2, "src/x.cc"), "int x;\n")
commit(dv2, "a PR that touches no managed file")
rc, out = run("check", "--changed-only", base, dv2)
check(
    rc == 0 and f"{WARN}AGENTS.md#dependencies: update" in out,
    "--changed-only: the base is rendered in its own swarm-core mode (vcpkg.json, the lock)",
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
edit(d5, "README.md", "\n## Licence", "\nA line of the repository's own.\n\n## Licence")
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

# #748: `backstop_tick = MINUTE` manages backstop-tick.yml with the hourly cron
# at that minute; without the key it is not managed, a bad minute is refused
tick = os.path.join(d6, ".github/workflows/backstop-tick.yml")
check(not os.path.exists(tick), "without backstop_tick no tick workflow")
edit(d6, ".github/org-sync.toml", "forms = true", "forms = true\nbackstop_tick = 33")
run("apply", d6)
body = read(tick) or ""
check(
    "- cron: '33 * * * *'" in body
    and "@MINUTE@" not in body
    and "-f event_type=backstop-tick" in body
    and run("check", d6)[0] == 0,
    "backstop_tick renders the tick at its minute and check is clean",
)
edit(d6, ".github/org-sync.toml", "backstop_tick = 33", "backstop_tick = 13")
rc, out = run("check", d6)
check(rc == 1 and ".github/workflows/backstop-tick.yml" in out, "a changed minute is drift")
for bad in ("0", "60", "true", '"13"'):
    edit(d6, ".github/org-sync.toml", "backstop_tick = 13", f"backstop_tick = {bad}")
    rc, _, _ = run_err("plan", d6)
    check("backstop_tick must be" in str(rc), f"backstop_tick = {bad} is refused")
    edit(d6, ".github/org-sync.toml", f"backstop_tick = {bad}", "backstop_tick = 13")
# the tick the template sends is the one backstop.yml listens for: a renamed
# event type on either side would leave the ticks unheard
listener = read(os.path.join(ORG, ".github/workflows/backstop.yml")) or ""
check(
    "  repository_dispatch:\n    types: [backstop-tick]\n" in listener
    and "repos/swarm-routing/.github/dispatches" in body,
    "backstop.yml runs on the repository_dispatch the tick sends",
)

# profile (#415): the org profile's badge table between its markers, the rest untouched
dp = tempfile.mkdtemp()
os.makedirs(os.path.join(dp, "profile"))
pf = os.path.join(dp, "profile/README.md")
write(
    pf, "# org\n\nIntro.\n\n<!-- org-sync:begin badges -->\n<!-- org-sync:end badges -->\n\nRest.\n"
)
rc, out = run("profile", dp, "--check")
check(rc == 1 and "drifted" in out, "profile --check: an empty badges section is drift")
rc, _ = run("profile", dp)
pr = read(pf)
titles = [
    "Main",
    "Platforms",
    "Containers",
    "Protocols",
    "Quality",
    "Trust",
    "Stack",
    "Open Tickets",
    "Community & docs",
]
rows = re.findall(r"^\| ([^|]+) \| ", pr, re.M)[2:]
check(
    rc == 0
    and pr.startswith("# org\n\nIntro.\n\n<!-- org-sync:begin badges -->\n| Group | Badges |\n")
    and pr.endswith("<!-- org-sync:end badges -->\n\nRest.\n")
    and rows == titles
    and "](#the-ai-first-engineering-model)" in pr
    and "[![Colony Arena](" in pr,
    "profile renders the grouped table between the markers, groups in order, the rest kept",
)
platforms = next(row for row in pr.splitlines() if row.startswith("| Platforms |"))
check(
    "[![ns-3](https://img.shields.io/badge/ns--3-Network_Simulator-1081c2)](https://www.nsnam.org/)"
    in platforms
    and "[![Browser: WebAssembly](https://img.shields.io/badge/Browser-WebAssembly-informational?logo=webassembly)]"
    "(https://swarm-routing.github.io/pipeline/)"
    in platforms,
    "profile retains the current platform badges and links",
)
tickets = next(row for row in pr.splitlines() if row.startswith("| Open Tickets |"))
ticket_badges = re.findall(r"\[!\[([^]]+)\]\(([^)]+)\)\]\(([^)]+)\)", tickets)
expected_tickets = [
    ("Open RCAPA", "rcapa", "rcapa", "darkred"),
    ("Open handoffs", "handoff", "handoffs", "green"),
    ("Open epics", "epic", "epics", "purple"),
    ("Open enhancements", "enhancement", "enhancements", "royalblue"),
    ("Open bugs", "bug", "bugs", "red"),
    ("Open chore", "chore", "chores", "yellow"),
    ("Open documentation", "documentation", "documentations", "green"),
    ("Open question", "question", "questions", "magenta"),
    ("Open verification", "verification", "verifications", "coral"),
    ("Open hold", "hold", "hold", "olive"),
]
check(len(ticket_badges) == len(expected_tickets), "profile renders all ticket badges")
for (alt, image, link), (name, label, badge_label, color) in zip(ticket_badges, expected_tickets):
    image_query = parse_qs(urlparse(image).query)
    link_query = parse_qs(urlparse(link).query)
    check(
        alt == name
        and set(image_query.get("query", [""])[0].split())
        == {"org:swarm-routing", f"label:{label}", "is:open", "is:issue"}
        and image_query.get("label") == [badge_label]
        and image_query.get("color") == [color]
        and set(link_query.get("q", [""])[0].split())
        == {"org:swarm-routing", f"label:{label}", "state:open", "is:issue"}
        and link_query.get("type") == ["issues"],
        f"profile {name} count and link select the same open issues",
    )
check(run("profile", dp, "--check")[0] == 0, "profile --check: today's render is current")
write(pf, "# org\n")
check(run("profile", dp)[0] == 1, "profile: no badges markers is an error")

# every template org-sync renders passes the private-library guard that each
# repository's references check applies to its text files (a template phrase
# such as "in the library's repository" turned every refresh PR red)
flagged = []
for root, _, files in os.walk(os.path.join(ORG, "templates")):
    for name in files:
        path = os.path.join(root, name)
        if fidelity.PRIVATE.search(read(path)):
            flagged.append(os.path.relpath(path, ORG))
check(not flagged, f"no template names the private paper library: {flagged}")

# 12. The template pin (#586): apply records the commit it rendered from in
# .github/org-sync.lock when it changes a file or the lock is missing, never
# otherwise, and never from a feature branch or a dirty tree.
SHA_A, SHA_B = "a" * 40, "b" * 40
# made-up commits: no history to read, so each is its own pin and no
# referenced workflow moved between them (section 12b tests both on real git)
REAL_CONTENT_PIN, REAL_REFS_MOVED = org_sync.content_pin, org_sync.refs_moved
org_sync.content_pin = lambda sha: sha
org_sync.refs_moved = lambda old, new: False
dk = fresh()
run("init", dk, "--kind", "data")
lock = os.path.join(dk, org_sync.LOCK)
check(not os.path.exists(lock), "no lock when the template commit cannot be named")
org_sync.org_commit = lambda: (SHA_A, "")
rc, out = run("apply", dk)
check(
    rc == 0 and f"create    {org_sync.LOCK}" in out and org_sync.read_lock(dk) == SHA_A,
    "a missing lock is written even when nothing else changed (the migration)",
)
# the workflow's own expression, read from it
wf = read(os.path.join(ORG, ".github", "workflows", "reusable-org-sync-check.yml"))
expr = re.search(r"sed -nE '([^']+)'", wf).group(1)
got = subprocess.run(["sed", "-nE", expr, lock], capture_output=True, text=True).stdout.strip()
check(
    got == SHA_A,
    "reusable-org-sync-check.yml reads the commit from the lock apply writes",
)
org_sync.org_commit = lambda: (SHA_B, "")
rc, out = run("apply", dk)
check(
    rc == 0 and "nothing to do" in out and org_sync.read_lock(dk) == SHA_A,
    "a newer commit that renders nothing new leaves the lock alone (no refresh PR)",
)
check(run("check", dk)[0] == 0, "the lock is not drift")
write(os.path.join(dk, ".github/workflows/dco.yml"), "hand edit\n")
err = io.StringIO()
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
    rc = org_sync.main(["check", dk])
check(
    rc == 1
    and f"this repository pins {SHA_A[:12]}" in err.getvalue()
    and f"ORG_REF={SHA_A}" in err.getvalue(),
    "check names the pin when the templates are another commit (no re-apply on unrelated PRs)",
)
run("apply", dk)  # back in sync (the lock moves to SHA_B with it)
write(lock, 'commit = "' + SHA_A + '"\n')
write(os.path.join(dk, ".github/workflows/dco.yml"), "hand edit\n")
rc, out = run("apply", dk)
check(
    rc == 0
    and "update    .github/workflows/dco.yml" in out
    and f"update    {org_sync.LOCK}" in out
    and org_sync.read_lock(dk) == SHA_B,
    "an apply that changes a file moves the lock with it",
)
org_sync.org_commit = lambda: (None, "the templates are on branch topic, not main")
write(lock, 'commit = "' + SHA_A + '"\n')
write(os.path.join(dk, ".github/workflows/dco.yml"), "hand edit\n")
rc, out = run("apply", dk)
check(
    org_sync.read_lock(dk) == SHA_A
    and "update    .github/workflows/dco.yml" in out
    and "kept      .github/org-sync.lock: the templates are on branch topic" in out,
    "a feature-branch or dirty checkout keeps the lock and says why",
)
# org_commit on a real git checkout: main and clean is a commit, a branch or a
# dirty template is not
with tempfile.TemporaryDirectory() as og:
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def og_git(*a):
        return subprocess.run(
            ["git", "-C", og, "-c", "user.name=t", "-c", "user.email=t@x", *a],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()

    og_git("init", "-q", "-b", "main")
    os.makedirs(os.path.join(og, "templates"))
    write(os.path.join(og, "templates", "t"), "x\n")
    og_git("add", "-A")
    og_git("commit", "-q", "-m", "t")
    head = og_git("rev-parse", "HEAD")
    saved = org_sync.ORG
    org_sync.ORG = og
    try:
        on_main = REAL_ORG_COMMIT()
        og_git("checkout", "-q", "--detach")
        detached = REAL_ORG_COMMIT()
        write(os.path.join(og, "templates", "t"), "y\n")
        dirty = REAL_ORG_COMMIT()
        og_git("checkout", "-q", "--", ".")
        og_git("checkout", "-q", "-b", "topic")
        branch = REAL_ORG_COMMIT()
    finally:
        org_sync.ORG = saved
    check(
        on_main == (head, "")
        and detached == (head, "")
        and dirty[0] is None
        and "uncommitted" in dirty[1]
        and branch[0] is None
        and "topic" in branch[1],
        "org_commit: main or detached and clean names HEAD; a dirty tree or a branch does not",
    )
org_sync.org_commit = lambda: (None, "self-test")

# 12b. The org's own references (#716): every `uses: swarm-routing/.github/...`
# line names the lock's commit, in the managed workflows and in the
# repository's own; check fails on any other ref, `@main` included, once a
# lock pins one; a comment after the commit is not compared; third-party and
# commented-out lines are never touched.
org_sync.org_commit = lambda: (SHA_A, "")
dr = fresh()
run("init", dr, "--kind", "data")
run("apply", dr)
check(
    f"reusable-dco.yml@{SHA_A} # main\n" in read(os.path.join(dr, ".github/workflows/dco.yml"))
    and "@main" not in read(os.path.join(dr, ".github/workflows/dco.yml")),
    "a managed workflow calls swarm-routing/.github at the lock's commit",
)
org_sync.org_commit = lambda: (SHA_B, "")
check(
    run("apply", dr)[1].strip() == "org-sync: nothing to do" and org_sync.read_lock(dr) == SHA_A,
    "a newer commit with no referenced workflow changed moves no reference",
)
org_sync.refs_moved = lambda old, new: True
rc, out = run("apply", dr)
check(
    org_sync.read_lock(dr) == SHA_B
    and f"reusable-dco.yml@{SHA_B} # main\n" in read(os.path.join(dr, ".github/workflows/dco.yml")),
    "a referenced workflow that changed moves the lock and the references, nothing else new",
)
org_sync.refs_moved = lambda old, new: False
org_sync.org_commit = lambda: (SHA_A, "")
write(os.path.join(dr, org_sync.LOCK), 'commit = "' + SHA_A + '"\n')
run("apply", dr)
own = os.path.join(dr, ".github/workflows/ci.yml")
CHECKOUT = "actions/checkout@" + "c" * 40 + " # v7.0.1"
OLD_PIN = "d" * 40
write(
    own,
    "jobs:\n"
    "  py:\n"
    "    uses: swarm-routing/.github/.github/workflows/reusable-python-ci.yml@main\n"
    "  tok:\n"
    "    steps:\n"
    f"      - uses: {CHECKOUT}\n"
    f"      - uses: swarm-routing/.github/.github/actions/bot-token@{OLD_PIN}  # main 2026-11-13\n"
    "#     uses: swarm-routing/.github/.github/workflows/reusable-dco.yml@main\n",
)
rc, out = run("check", dr)
check(
    rc == 1 and "drift     .github/workflows/ci.yml: update" in out,
    "check fails on the repository's own workflow calling swarm-routing/.github at @main or another commit",
)
rc, out = run("plan", dr)
check(
    "update    .github/workflows/ci.yml: references to swarm-routing/.github" in out
    and org_sync.read_lock(dr) == SHA_A,
    "plan names the own workflow's references",
)
run("apply", dr)
got = read(own)
check(
    f"reusable-python-ci.yml@{SHA_A} # main\n" in got
    and f"      - uses: swarm-routing/.github/.github/actions/bot-token@{SHA_A} # main\n" in got
    and f"      - uses: {CHECKOUT}\n" in got
    and "#     uses: swarm-routing/.github/.github/workflows/reusable-dco.yml@main\n" in got
    and run("check", dr)[0] == 0,
    "apply pins the own workflow's references; third-party and commented lines stay",
)
write(own, got.replace(f"{SHA_A} # main\n", f"{SHA_A} # main@2026-11-22\n"))
check(run("check", dr)[0] == 0, "a reference's comment is not compared")
write(own, got.replace("reusable-python-ci.yml@" + SHA_A, "reusable-python-ci.yml@main"))
edit(dr, org_sync.CONFIG, 'kind = "data"', 'kind = "data"\nskip = [".github/workflows/ci.yml"]')
check(run("check", dr)[0] == 0, "a skipped own workflow keeps its references")
edit(dr, org_sync.CONFIG, 'skip = [".github/workflows/ci.yml"]\n', "")
org_sync.org_commit = lambda: (None, "self-test")
dn = fresh()
run("init", dn, "--kind", "data")
write(os.path.join(dn, ".github/workflows/own.yml"), read(own))  # ci.yml would add a badge
check(
    not os.path.exists(os.path.join(dn, org_sync.LOCK))
    and "reusable-dco.yml@main\n" in read(os.path.join(dn, ".github/workflows/dco.yml"))
    and run("check", dn)[0] == 0,
    "without a lock no commit is named: the templates' @main, own references left as they are",
)
check(
    'dependency-name: "swarm-routing/.github*"' in org_sync.render_dependabot(dr),
    "the dependabot seed leaves the org's own references to org-bot",
)

# the pins on a real history: content_pin moves only on a commit that changes
# what renders or what a reference names; refs_moved only on a referenced
# workflow or action; self_pin (`refs`, this repository's own references)
# skips a commit that changed nothing but those references
org_sync.content_pin, org_sync.refs_moved = REAL_CONTENT_PIN, REAL_REFS_MOVED
with tempfile.TemporaryDirectory() as og:
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def og_git(*a):
        return subprocess.run(
            ["git", "-C", og, "-c", "user.name=t", "-c", "user.email=t@x", *a],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()

    def commit(path, text):
        os.makedirs(os.path.dirname(os.path.join(og, path)), exist_ok=True)
        write(os.path.join(og, path), text)
        og_git("add", "-A")
        og_git("commit", "-q", "-m", path)
        return og_git("rev-parse", "HEAD")

    og_git("init", "-q", "-b", "main")
    inner = "    uses: swarm-routing/.github/.github/actions/tok@main\n"
    reusable = "on:\n  workflow_call:\njobs:\n  x:\n" + inner
    c1 = commit(".github/workflows/reusable-x.yml", reusable)
    ca = commit(".github/actions/tok/action.yml", "runs: {using: composite, steps: []}\n")
    c2 = commit("templates/t", "x\n")
    c3 = commit("docs/notes.md", "docs\n")
    c4 = commit(".github/workflows/ci.yml", "on: push\n")  # not called by others
    c5 = commit(".github/workflows/reusable-x.yml", reusable.replace("@main", "@" + c2))
    c6 = commit(".github/workflows/reusable-x.yml", reusable.replace("x:\n", "y:\n"))
    c7 = commit(
        ".github/workflows/reusable-x.yml",
        reusable.replace("x:\n", "y:\n").replace("@main", "@" + c6),
    )
    c8 = commit("docs/notes.md", "more docs\n")
    saved = org_sync.ORG
    org_sync.ORG = og
    try:
        pins = [org_sync.content_pin(c) for c in (c3, c4, c5, c8)]
        moved = [org_sync.refs_moved(a, b) for a, b in ((c2, c4), (c1, c2), (c4, c5), (c7, c8))]
        selfs = [org_sync.self_pin(c) for c in (c5, c8)]
        date = og_git("show", "-s", "--format=%cs", c6)
        pinned = org_sync.pin_refs(inner, c6)
        sd = tempfile.mkdtemp()
        os.makedirs(os.path.join(sd, ".github", "workflows"))
        write(os.path.join(sd, ".github/workflows/reusable-x.yml"), reusable)
        rc_drift = run("refs", sd, "--rev", c8, "--check")[0]
        rc_write, out_write = run("refs", sd, "--rev", c8)
        rc_clean = run("refs", sd, "--rev", c8, "--check")[0]
    finally:
        org_sync.ORG = saved
    check(
        pins == [c2, c2, c5, c7],
        f"content_pin: the newest commit that renders or is referenced: {pins}",
    )
    check(
        moved == [False, True, True, False],
        f"refs_moved: only a referenced workflow or action: {moved}",
    )
    check(selfs == [ca, c6], f"self_pin skips a commit that only moved its own references: {selfs}")
    check(
        pinned == f"    uses: swarm-routing/.github/.github/actions/tok@{c6} # main@{date}\n",
        "a reference names the commit and its date",
    )
    check(
        rc_drift == 1
        and rc_write == 0
        and "update    .github/workflows/reusable-x.yml" in out_write
        and f"tok@{c6} # main@" in read(os.path.join(sd, ".github/workflows/reusable-x.yml"))
        and rc_clean == 0,
        "refs: this repository's own references, --check then written at self_pin",
    )

# 30. The shared parts of two seeds are managed sections (#615): the Makefile's
# org tooling (`org-tools`) and LICENSING.md's licence texts (`licence-texts`).
d = fresh()
run("init", d, "--kind", "python", "--title", "demo", "--dual", "tools/")
mk = read(os.path.join(d, "Makefile"))
body = read(os.path.join(ORG, "templates", "make", "org-tools.mk"))
check(
    mk.endswith(f"# org-sync:begin org-tools\n{body}# org-sync:end org-tools\n")
    and mk.count("org-sync-check:") == 1
    and mk.count("ORG_REF   ?=") == 1,
    "a seeded Makefile ends with the org-tools block, each org definition once",
)
lic = read(os.path.join(d, "LICENSING.md"))
check(
    "<!-- org-sync:begin licence-texts -->\nTexts: [`LICENSE`]" in lic and run("check", d)[0] == 0,
    "a seeded LICENSING.md has the licence-texts block, and check is clean",
)
# a template change to a shared target reaches the repository through apply (the
# refresh), and the repository's own recipes stay as they are
edit(d, "Makefile", "python3 -m pytest -q", "python3 -m unittest")
edit(d, "Makefile", '\tpython3 -I "$(ORG_DIR)/tools/org-sync/org_sync.py" check .', "\techo old")
rc, out = run("check", d)
check(rc == 1 and "Makefile#org-tools" in out, "an older org-tools block is drift")
run("apply", d)
mk = read(os.path.join(d, "Makefile"))
check(
    'org_sync.py" check .' in mk and "echo old" not in mk and "python3 -m unittest" in mk,
    "apply refreshes the org-tools block and keeps the repository's recipe",
)

# an old seed carries the org pieces unmarked: adopted when they are the org's text
OLD_VARS = org_sync.ADOPT_PIECES[("Makefile", "org-tools")]["old"][0]
ORG_TARGETS = (
    "org-tools:  # the same templates CI checks against: refreshed to ORG_REF every time\n"
    + "".join(ln + "\n" for ln in body.split("org-tools:  #", 1)[1].splitlines()[1:3])
)
SYNC_TARGET = (
    "org-sync-check: org-tools ## org-managed files match the org templates\n"
    '\tpython3 -I "$(ORG_DIR)/tools/org-sync/org_sync.py" check .\n'
)
OLD_MAKEFILE = (
    "# demo Makefile\n\nNS3_IMAGE ?= x\n"
    + OLD_VARS
    + "\n.DEFAULT_GOAL := help\n.PHONY: help org-sync-check org-tools\n\n"
    "help: ## list\n\t@echo help\n\n"
    + "".join(f"{t}: ## {t}\n\t@true\n" for t in ("build", "test", "lint", "format", "clean"))
    + "shell: ## shell\n\t@true\n\nci: check ## ci\n\n"
    + ORG_TARGETS
    + '\nheaders: org-tools ## licence headers\n\t"$(ORG_DIR)/tools/checks/check-headers.sh" .\n\n'
    + SYNC_TARGET
    + "\ncheck: headers org-sync-check ## all\n\nmine: ## a repo-only target\n\t@echo mine\n"
)
write(os.path.join(d, "Makefile"), OLD_MAKEFILE)
rc, out = run("plan", d)
check(
    "adopt     Makefile#org-tools: markers added; 3 org piece(s) replaced" in out,
    "plan adopts the old unmarked org pieces of a Makefile",
)
run("apply", d)
mk = read(os.path.join(d, "Makefile"))
check(
    "ORG_REF   ?= main" not in mk
    and mk.count("org-tools:") == 1
    and mk.count("org-sync-check:") == 1
    and mk.index("mine:") < mk.index("# org-sync:begin org-tools")
    and "\nci: check ## ci\n\nheaders:" in mk
    and "NS3_IMAGE ?= x\n\n.DEFAULT_GOAL" in mk
    and run("check", d)[0] == 0,
    "apply moves them into the block at the end, keeps the rest byte for byte, check is clean",
)
check(run("plan", d)[1].count("Makefile") == 0, "a second apply changes nothing")
# a piece the repository changed is never rewritten: a conflict, for a person
write(os.path.join(d, "Makefile"), OLD_MAKEFILE.replace("ORG_REF   ?= main", "ORG_REF   ?= v1"))
rc, out = run("apply", d)
check(
    rc == 1
    and "conflict  Makefile#org-tools" in out
    and "`ORG_REF   ?= v1`" in out
    and read(os.path.join(d, "Makefile"))
    == OLD_MAKEFILE.replace("ORG_REF   ?= main", "ORG_REF   ?= v1"),
    "an edited org piece is a conflict and the Makefile is left as it is",
)
write(
    os.path.join(d, "Makefile"),
    OLD_MAKEFILE.replace(SYNC_TARGET, "org-sync-check: ## mine\n\t@echo mine\n"),
)
rc, out = run("plan", d)
check(
    "conflict  Makefile#org-tools" in out and "`org-sync-check: ## mine`" in out,
    "a target of the repository's own under an org name is a conflict",
)
# a Makefile with none of the org pieces (AntHocNet's own) gets the block appended
write(os.path.join(d, "Makefile"), "# own\n\ncheck: ## all\n\t@true\n")
run("apply", d)
mk = read(os.path.join(d, "Makefile"))
check(
    mk.startswith("# own\n\ncheck: ## all\n\t@true\n\n# org-sync:begin org-tools\n"),
    "a Makefile with no org piece gets the block inserted at its end",
)

# LICENSING.md: the old seed's paragraph is the org's text, replaced in place
run("reseed", "Makefile", d)
lic = read(os.path.join(d, "LICENSING.md"))
s, e = org_sync.find_section(lic, "licence-texts", "LICENSING.md")
OLD_LIC = org_sync.ADOPT_PIECES[("LICENSING.md", "licence-texts")]["old"][0]
old_file = (
    lic[: s - len("<!-- org-sync:begin licence-texts -->\n")]
    + OLD_LIC
    + lic[e + len("<!-- org-sync:end licence-texts -->\n") :]
)
write(os.path.join(d, "LICENSING.md"), old_file)
run("apply", d)
check(
    read(os.path.join(d, "LICENSING.md")) == lic,
    "an old LICENSING.md paragraph is replaced by the block, in place",
)
own = "# Licensing\n\nOur own words. `tools/check.py` checks the headers.\n"
write(os.path.join(d, "LICENSING.md"), own)
rc, out = run("plan", d)
check(
    "LICENSING.md#licence-texts" not in out
    and run("apply", d)[0] == 0
    and read(os.path.join(d, "LICENSING.md")) == own
    and run("check", d)[0] == 0,
    "a LICENSING.md of the repository's own words is left unmanaged, not a conflict",
)
edited = old_file.replace("either licence", "either licence (ours)")
write(os.path.join(d, "LICENSING.md"), edited)
run("apply", d)
check(
    read(os.path.join(d, "LICENSING.md")) == edited,
    "an edited old paragraph is the repository's own: never rewritten",
)

# 31. Untouched seeds (#615): a seed still exactly as the pinned templates rendered
# it takes today's render with `apply --reseed-untouched`; an edited one never.
pin = tempfile.mkdtemp()
subprocess.run(["git", "init", "-q", pin], check=True)
for sub in ("templates", "tools/org-sync", "tools/fidelity"):
    shutil.copytree(
        os.path.join(ORG, sub), os.path.join(pin, sub), ignore=shutil.ignore_patterns("__pycache__")
    )
with open(os.path.join(pin, "templates", "SECURITY.md.in"), "a", encoding="utf-8") as f:
    f.write("\nAn older template's last line.\n")
git_env = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}
subprocess.run(["git", "-C", pin, "add", "-A"], check=True)
subprocess.run(["git", "-C", pin, "commit", "-qm", "pin"], check=True, env=git_env)
sha = subprocess.run(
    ["git", "-C", pin, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
).stdout.strip()
saved_pin = org_sync.PIN_ORG
org_sync.PIN_ORG = pin
try:
    d = fresh()
    run("init", d, "--kind", "data", "--title", "demo")
    today = read(os.path.join(d, "SECURITY.md"))
    write(os.path.join(d, ".github", "org-sync.lock"), f'commit = "{sha}"\n')
    old = org_sync.pinned_render(d, "swarm-routing/demo", sha, "SECURITY.md")
    check(
        old is not None and old.endswith("An older template's last line.\n") and old != today,
        "the pinned render comes from the pinned commit's own templates",
    )
    write(os.path.join(d, "SECURITY.md"), old)
    rc, out = run("apply", d)
    check(
        read(os.path.join(d, "SECURITY.md")) == old, "without --reseed-untouched no seed is written"
    )
    rc, out = run("apply", d, "--reseed-untouched")
    check(
        rc == 0
        and f"reseeded  SECURITY.md (untouched since the pinned templates {sha[:12]})" in out
        and read(os.path.join(d, "SECURITY.md")) == today,
        "an untouched seed takes today's render",
    )
    write(os.path.join(d, "SECURITY.md"), old.replace("## Verifying", "Our note.\n\n## Verifying"))
    rc, out = run("apply", d, "--reseed-untouched")
    check(
        "reseeded" not in out and "Our note." in read(os.path.join(d, "SECURITY.md")),
        "a seed the repository edited is never written",
    )
    write(os.path.join(d, "SECURITY.md"), old)
    write(os.path.join(d, ".github", "org-sync.lock"), f'commit = "{"f" * 40}"\n')
    rc, out = run("apply", d, "--reseed-untouched")
    check(
        "reseeded" not in out and read(os.path.join(d, "SECURITY.md")) == old,
        "a pin that cannot be rendered leaves the seed alone",
    )
    os.remove(os.path.join(d, ".github", "org-sync.lock"))
    rc, out = run("apply", d, "--reseed-untouched")
    check(
        "reseeded" not in out and read(os.path.join(d, "SECURITY.md")) == old,
        "without a lock no seed is written",
    )
finally:
    org_sync.PIN_ORG = saved_pin

# the dependabot seed (#716): github-actions always, plus each manifest's
# directory; fixtures and vendored trees are not watched; an existing file stays
d = fresh()
for path in (
    "go.mod",
    "docker/ci-tools/Dockerfile",
    "requirements/ruff.txt",
    "tools/requirements/ci.txt",
    "docs/requirements-docs.txt",
    "docs/notes.txt",
    "python/pyproject.toml",
    "web/package.json",
    "test/fixtures/x/package.json",
    "vendor/y/go.mod",
):
    os.makedirs(os.path.dirname(os.path.join(d, path)) or d, exist_ok=True)
    write(os.path.join(d, path), "")
subprocess.run(["git", "-C", d, "add", "-A"], check=True)
check(
    org_sync.dependabot_entries(d)
    == [
        ("github-actions", "/"),
        ("pip", "/docs"),
        ("pip", "/python"),
        ("pip", "/requirements"),
        ("pip", "/tools/requirements"),
        ("gomod", "/"),
        ("docker", "/docker/ci-tools"),
        ("npm", "/web"),
    ],
    "dependabot watches github-actions and each manifest's directory, no fixture or vendor",
)
run("init", d, "--kind", "python", "--dual", "")
dep = read(os.path.join(d, ".github", "dependabot.yml"))
check(
    dep.startswith("# Dependabot version updates")
    and "package-ecosystem: npm\n    directory: /web\n" in dep
    and '- "github/codeql-action*"' in dep,
    "init seeds .github/dependabot.yml",
)
write(os.path.join(d, ".github", "dependabot.yml"), "version: 2\nupdates: []\n")
run("apply", d)
check(
    read(os.path.join(d, ".github", "dependabot.yml")) == "version: 2\nupdates: []\n",
    "an existing dependabot.yml is the repository's own",
)
check(org_sync.dependabot_entries(fresh()) == [("github-actions", "/")], "an empty repo: actions")

print("org-sync self-test: OK")
