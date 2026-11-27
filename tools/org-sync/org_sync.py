#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Apply the swarm-routing org templates to a repository, and check for drift.

Usage: org_sync.py {init,plan,apply,conflicts,check,seeds,settings,refs} [REPO_DIR] [options]
       org_sync.py reseed FILE [REPO_DIR]
       org_sync.py citation-refs [REPO_DIR] [--check]
       org_sync.py profile [REPO_DIR] [--check]

`profile` (swarm-routing/.github only) renders the org's badge table into
profile/README.md, between `<!-- org-sync:begin badges -->` and its end
marker: the profile's groups and badges from PROFILE_BADGES, each
badge live or a fixed fact, never a typed number; `--check` exits 1 when the
section is not today's render.

The repository describes itself in `.github/org-sync.toml` (`init` writes it).
Each managed item is one of:

  section  the text between `<!-- org-sync:begin NAME -->` and
           `<!-- org-sync:end NAME -->` in a Markdown file (`# org-sync:begin
           NAME` / `# org-sync:end NAME` in a YAML file); the rest of the file
           is the repository's own
  file     the whole file is the org's
  seed     created once from a template, then the repository's own: `check`
           never compares it again. `seeds` reports, for information (exit
           0), whether each reads `same` as today's render, `differs (N
           lines)` or is `missing` (managed sections inside it are left to
           `check`); `reseed FILE` prints the diff and writes today's render
           over that one seed, and refuses any file that is not a seed.
           `apply --reseed-untouched` (org-bot) writes today's render over
           each seed whose own text is still what the templates the lock pins
           rendered; a seed the repository edited is never written (#615)
  json     only the named keys of a JSON file are the org's
  targets  a Makefile that is the repository's own, checked only for the
           org's standard target names (swarm-routing/.github#11)

Two seeds carry the org's shared text as sections (#615): the Makefile's
`org-tools` block at its end (`# org-sync:begin org-tools`: the ORG_DIR,
ORG_REF and TITLE variables, `org-tools`, `org-sync-check`, `pre-push`,
`doctor`) and
LICENSING.md's `licence-texts`. A seed from before carries that text
unmarked, in pieces (ADOPT_PIECES): each is adopted only when it is the
template's text, or an older render's, byte for byte; an edited piece, or a
definition of the repository's own under an org name, is a conflict. A
LICENSING.md with none of the org's text keeps its own, unmanaged.

An orphan is an `org-sync:begin NAME` / `org-sync:end NAME` block left in a
managed file whose section is not one of the repository's items (skipped, or
not enabled), e.g. rendered by a refresh that branched before the skip landed
(swarm-routing/.github#235). `plan` and `check` report it as drift, status
`orphan`; `apply` removes it only with `--prune-orphans` (org-bot passes it,
so the removal is proposed in a reviewed PR), otherwise leaves it, reports it
and exits 1, like a conflict.

Citations (`citation = true`): CITATION.cff's `references:` and the README's
Releases & citing list come from `docs/references.bib` once it has an entry
(its `implemented`, `tool` and `dataset` entries, read with
tools/fidelity/bib.py), else from `[[references]]`; with both, the bib wins
and a warning names `[[references]]` as redundant. Every repository gets the
bib as a seed: a commented header, no entry (#308). The header is the org's
rules, so it is a managed section, `bib-header` between `% org-sync:begin`
and `% org-sync:end` lines: a template change reaches every repository
through the refresh, and an edit there is drift; a bib seeded before that is
adopted, its old header replaced; the entries, and any comment lines after
the end marker, stay the repository's (#343). An @incollection whose
booktitle names proceedings, a conference, workshop or symposium, or whose
series is a proceedings series (Lecture Notes in Computer Science), is a CFF
`conference-paper` (#331).

`citation-refs [REPO] [--check]` rewrites only CITATION.cff's `references:`
block from docs/references.bib, every other byte of the file as it was, for
any repository with both files, `citation = true` or not (CITATION.cff is a
seed, so a bib change never reaches it otherwise); `--check` changes nothing
and exits 1 on drift. Without CITATION.cff, or with a bib that has no entry,
it does nothing (exit 0). It reads no `.github/org-sync.toml`.

Issue forms (`forms = true`): a repository with its own
`.github/ISSUE_TEMPLATE/` loses the org's default forms, so it keeps a copy.
With the opt-in each org form (every `ISSUE_TEMPLATE/*.yml` here but
`config.yml`) is a whole file there; `config.yml` and the repository's own
forms stay its own, and a changed org form is drift (#318).

The class documentation (#881, #883): every C++ kind gets a Doxyfile seed at
`doxyfile` (default `docs/api/Doxyfile`; AntHocNet's is `api/Doxyfile`) and
the org's `.github/workflows/api-docs.yml`, which builds it with
reusable-doxygen.yml on every PR.

The backstop tick (`backstop_tick = MINUTE`, an integer 1-59): a few active
repositories carry `.github/workflows/backstop-tick.yml`, an hourly cron at
that minute that sends repository_dispatch `backstop-tick` to
swarm-routing/.github, whose backstop.yml then dispatches what is overdue
(#748). Each repository takes its own minute, away from the ones
swarm-routing/.github's own workflows use, so one dropped schedule leaves the
others. Without the key the file is not managed.

A `[settings]` table holds the repository's GitHub settings (description,
homepage, topics, ruleset profile, required checks, and overrides of the
profile's features, security features and release environment), which
`tools/repo-settings/repo_settings.py` applies; org-sync ignores it. A file
with `[settings]` and no `kind` is settings only: every command here says so
and exits 0, so org-bot finds nothing to propose there.

`check --changed-only BASE` fails only on the drift the change since BASE
brought in (a PR's or a merge group's own, swarm-routing/.github#159): an
item fails when it drifts at HEAD and either did not drift at BASE (the same
templates rendered against BASE's tree, e.g. a config change whose render the
PR did not apply) or the change edited it by hand (a changed line between a
section's markers, any change to another item's file; editing only
.github/org-sync.toml is not a hand edit). Every other drifting item, drift a
newer template left on BASE, is a `::warning::` line and exit 0, so a template
merge in swarm-routing/.github does not block every PR until the org-bot
refresh lands; plain `check` (pushes to main) still fails on it.

The template pin (#586): `apply` records in `.github/org-sync.lock` the
swarm-routing/.github commit it rendered from (`commit = "<40 hex>"`), and
reusable-org-sync-check.yml checks the repository against the templates and
tools at that commit, so a template merge here never turns another
repository's check red: only org-bot's refresh PR, which moves the pin and
the rendered text together, brings the new templates in (the swarm-core.lock
model). `apply` writes the lock only when it changed a file or the lock is
missing (the first refresh after #586 writes it everywhere), so a commit here
that renders nothing new opens no PR. It records the commit only from a clean
checkout (`templates/`, `tools/org-sync/`, `tools/fidelity/` unchanged) on
`main` or a detached HEAD (CI); from a feature branch or a dirty tree it
leaves the lock as it is and says so. The lock is separate from
`.github/org-sync.toml`: that file is the repository's own configuration (and
a push changing it re-applies the repository's settings), the lock is
machine-written state, never edited by hand.

The org's own references (#716, ADR-0004): every `uses:
swarm-routing/.github/<path>@<ref>` line of a repository's workflows and
composite actions names the lock's commit, `@<sha> # main@<date>`: the
managed workflows are rendered so, and each of the repository's own workflow
or action files that calls this repository is a `refs` item (only that
reference is the org's); `check` fails on any other ref, `@main` included;
the comment after the commit is not compared. `apply` pins the lock and the
references to `content_pin`: the newest first-parent commit that changed
what renders or a workflow or action the references name, and keeps the
lock's commit when that renders nothing new and no referenced workflow
changed (`target_pin`). `refs [REPO] [--check] [--rev REV]` is the same for
swarm-routing/.github's own reusable workflows (org-bot runs it there): their
calls to its own actions and workflows at `self_pin`, the newest commit that
changed those by more than these references.

Output is a summary, never file contents, so an agent reads a few lines per
run (AntHocNet ADR-0014). Only `conflicts` and `reseed` print text: the hunks
that need a person's judgement, and the change a reseed makes. Stdlib only; Python 3.11+ (tomllib).
"""

import argparse
import datetime
import difflib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
from urllib.parse import quote

ORG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = os.path.join(ORG, "templates")
sys.path.insert(0, os.path.join(ORG, "tools", "fidelity"))
import bib  # noqa: E402  (tools/fidelity/bib.py: the docs/references.bib reader, #308)

CONFIG = ".github/org-sync.toml"
LOCK = ".github/org-sync.lock"  # the swarm-routing/.github commit last rendered from (#586)
LOCK_LINE = re.compile(r'^commit = "([0-9a-f]{40})"[ \t]*$', re.M)
KINDS = ("protocol", "c-cpp", "python", "container", "data", "site", "skills")
CXX_KINDS = ("protocol", "c-cpp")
MAKE_TARGETS = ("help", "build", "test", "lint", "format", "check", "clean", "shell", "ci")
BEGIN = "<!-- org-sync:begin {} -->"
END = "<!-- org-sync:end {} -->"
YAML_BEGIN = "# org-sync:begin {}"
YAML_END = "# org-sync:end {}"
BIB_BEGIN = "% org-sync:begin {}"  # docs/references.bib's org header (#343)
BIB_END = "% org-sync:end {}"


def markers(path):
    """The (begin, end) marker formats for a managed section in this file."""
    if path.endswith((".yaml", ".yml")) or os.path.basename(path) in ("CODEOWNERS", "Makefile"):
        return YAML_BEGIN, YAML_END
    if path.endswith(".bib"):
        return BIB_BEGIN, BIB_END
    return BEGIN, END


# Badges per kind (swarm-routing/.github#8). Each appears only when its target
# exists (see badge_lines): `release` when a workflow calls reusable-release.yml,
# `doi` when the config names its `zenodo_concept` (read from Zenodo, never
# typed: the concept exists only after the first release is archived; never
# with `zenodo = false`, a repository Zenodo does not archive, #811), `cite`
# when the repository has a CITATION.cff (`citation = true` seeds one);
# `scorecard` (OpenSSF Scorecard, #23) only where
# .github/workflows/scorecard.yml runs it, so a private repository, which skips
# that workflow (`skip = [".github/workflows/scorecard.yml"]`), never gets one;
# `bestpractices` (OpenSSF Best Practices, #23) only when the config names the
# repository's bestpractices.dev project as `bestpractices_project = "<id>"`.
# `vcpkg` (swarm-routing/.github#436) only when the config names the
# repository's ports in swarm-routing/vcpkg-registry, `vcpkg_ports = ["<port>"]`:
# one badge per port, its version read live from the port's vcpkg.json on the
# registry's main (shields' /vcpkg/ badge reads only microsoft/vcpkg). `pypi`
# only when the config names a PyPI project, `pypi_project = "<name>"`: set it
# after the project's first publish (before it, shields shows "package not
# found").
# `indexes` (swarm-routing/.github#963, #966): one badge per external index that
# lists the repository, only for the indexes the config names, each with the
# id the index issued its listing (never derived from owner/name):
# `indexes = { m8ven-mcp = "<id>" }`, or `{ id = "<id>", variant = "verified" }`
# per entry, or `{ id = "<id>", verify_id = "<verify id>" }` for the verified
# publisher's badge in place of the score badge (#968; INDEXES; an unknown
# index, id, variant or verify id, or a variant with a verify id, is a config
# error). `glama = "<namespace>/<slug>"`: Glama's score badge for the listing
# (#990), its id the listing's path, written out even where it is owner/name.
# `sonar` is the four SonarQube Cloud badges (quality gate, bugs, security,
# maintainability); `sonar-gate`, `sonar-bugs`,
# `sonar-security` and `sonar-maintainability` pick one.
SONAR_METRICS = {
    "sonar-gate": ("Quality Gate Status", "alert_status"),
    "sonar-bugs": ("Bugs", "bugs"),
    "sonar-security": ("Security Rating", "security_rating"),
    "sonar-maintainability": ("Maintainability Rating", "sqale_rating"),
}
BASE_BADGES = [
    "ci",
    "release",
    "doi",
    "cite",
    "vcpkg",
    "pypi",
    "licence",
    "conventional",
    "arena",
    "scorecard",
    "bestpractices",
    "indexes",
    "rcapa",
    "ns3-bugs",
]
# The external indexes a repository may opt into (`indexes`): name -> (alt,
# image, link, variants, verify, id), image and link formats of the listing's
# `{id}` (the alt may name `{name}`, the id's last segment), each accepted
# `variant` -> the image's query, `verify`, None or (alt, image, link, pattern)
# of the badge the index issues a verified publisher by a separate `verify_id`
# (#968), and the pattern of the index's listing ids. A row renders the
# indexes in this order, whatever the config's order. The Indexes group is for
# directories that list or score a repository from outside; OpenSSF Best
# Practices stays in Trust (a certification the project answers, #23).
INDEXES = {
    # the M8ven Trust Index of public MCP servers: the id M8ven issued once the
    # publisher claimed the listing; `verified` once the publisher is verified
    # (the score badge's verified look, kept for #963's configs); `verify_id`
    # the id of the "M8ven Verified" badge M8ven issues a verified publisher,
    # its URLs exactly as M8ven gives them (#968)
    "m8ven-mcp": (
        "M8ven Score",
        "https://m8ven.ai/badge/mcp/{id}",
        "https://m8ven.ai/mcp/{id}?s=readme",
        {"verified": "?variant=verified"},
        (
            "M8ven Verified",
            "https://m8ven.ai/api/agent-verify/badge?id={id}",
            "https://m8ven.ai/verified/verify?id={id}",
            re.compile(r"[0-9a-f]{16}"),
        ),
        re.compile(r"[a-z0-9][a-z0-9-]*"),
    ),
    # Glama's MCP server directory: the listing's `<namespace>/<slug>` (the
    # GitHub owner/name it lists), its score badge, link and alt text exactly
    # as the listing's "GitHub badge" page gives them, the slug as the display
    # name (#990)
    "glama": (
        "{name} MCP server – quality and maintenance score on Glama",
        "https://glama.ai/mcp/servers/{id}/badges/score.svg",
        "https://glama.ai/mcp/servers/{id}",
        {},
        None,
        re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._][A-Za-z0-9._-]*"),
    ),
}
KIND_BADGES = {
    "protocol": ["cxx", "ns3", "ns3dev", "sonar", "codecov", "coderabbit"],
    "c-cpp": ["cxx", "ns3dev", "sonar", "codecov", "coderabbit"],
    "python": ["python"],
    "container": [
        "ghcr",
        "cosign",
        "container-security",
        "sonar-gate",
        "sonar-security",
        "hadolint",
        "trivy",
        "coderabbit",
    ],
    "data": [],
    "site": ["docs"],
    "skills": ["claude-plugin"],
}
# The README badges are a table, one row per group (swarm-routing/.github#415):
# every kind belongs to one group, a group's badges keep this order whatever the
# order of a repository's `badges` list, and a group with no badge is left out.
# `[[extra_badges]]` adds a repository's own badge to a group (after its kinds):
#
#   [[extra_badges]]
#   group = "quality"    # build, quality, release, trust, indexes, stack or community
#   alt = "Core coverage"
#   image = "https://img.shields.io/endpoint?url=..."
#   link = "https://github.com/..."
BADGE_GROUPS = {
    "build": ("Build", ["ci", "container-security", "hadolint", "trivy", "ghcr", "ns3dev"]),
    "quality": ("Quality", [*SONAR_METRICS, "codecov", "coderabbit"]),
    "release": ("Release", ["release", "doi", "cite", "vcpkg", "pypi", "licence"]),
    "trust": ("Trust", ["scorecard", "bestpractices", "cosign"]),
    "indexes": ("Indexes", ["indexes"]),
    "stack": ("Stack", ["cxx", "ns3", "python"]),
    "community": (
        "Community & docs",
        ["docs", "arena", "rcapa", "ns3-bugs", "claude-plugin", "conventional"],
    ),
}
BADGE_TABLE_HEAD = "| Group | Badges |\n| --- | --- |\n"

# Where an existing, unmarked section starts and stops, so `apply` can adopt
# text that predates the markers: (file, section) -> (start regex, stop regex).
ADOPT = {
    ("AGENTS.md", "org-rules"): (r"^1\. \*\*Licensing per directory", r"^(10\. |## )"),
    ("AGENTS.md", "conventions"): (r"^- Issues follow the org taxonomy", r"^## "),
    ("AGENTS.md", "git-workflow"): (r"^- Branch from `main`", r"^## "),
    ("AGENTS.md", "agent-defaults"): (
        r"^## Working defaults\n",
        r"^(<!-- org-sync:begin |## Where to look\n)",
    ),
    ("SECURITY.md", "reporting"): (r"^## Reporting a vulnerability\n", r"^## "),
    # the header every bib was seeded with before it was managed (#343), and only
    # that: from its first line ("% docs/references.bib: ...") at the top of the
    # file to the seed's last line ("% this header alone."); a file without both
    # is a conflict, never rewritten. A repository's own comment lines after it
    # stay its own, below the end marker
    ("docs/references.bib", "bib-header"): (
        r"\A% docs/references\.bib: ",
        r"(?<=^% this header alone\.\n)",
    ),
}
# Adopted sections whose old text is the org's, not the repository's: a
# difference from the template is replaced, not a conflict (#343)
ADOPT_REPLACE = {("docs/references.bib", "bib-header")}
# The shared parts of two seeds (#615): a seed written before its section was
# managed carries the org's text unmarked, in pieces. `apply` adopts a piece only
# when it is, byte for byte, the template's text or one it rendered before
# (`old`), so a piece the repository changed is never rewritten. `own`: a line
# that, left outside the markers after adoption, would define what the section
# defines (a conflict, for a person). `at`: "end" appends the block at the end
# of the file; "first" puts it where the first adopted piece was. `optional`: a
# file with no piece and no markers keeps its own text, unmanaged (it is listed
# by `seeds`), instead of a conflict.
ADOPT_PIECES = {
    ("Makefile", "org-tools"): {
        "old": (
            # Makefile.in from #13 to #586: the org tooling's variables
            "# The org tooling (check-headers, org-sync): a shallow clone, refreshed to ORG_REF.\n"
            "ORG_DIR   ?= $(HOME)/.cache/swarm-routing/dotgithub\n"
            "ORG_REF   ?= main\n",
        ),
        "own": r"^(?:(?:ORG_DIR|ORG_REF|TITLE_RE)\s*[:?+!]?=|export TITLE\b|"
        r"(?:org-tools|org-sync-check|pre-push|doctor)\s*:(?!=))",
        "at": "end",
        "optional": False,
    },
    ("LICENSING.md", "licence-texts"): {
        "old": (
            # LICENSING.md.in before #615
            "`MIT OR GPL-2.0-only` means you may use that code under either licence, at\n"
            "your option ([LICENSE-MIT](LICENSE-MIT) or [LICENSE](LICENSE)). Every source\n"
            "file carries its SPDX identifier; CI checks it (`reusable-licence-check.yml`).\n",
        ),
        "own": None,
        "at": "first",
        "optional": True,
    },
}
# Sections with nothing to adopt: inserted after the first match of the regex.
INSERT_AFTER = {
    ("README.md", "badges"): r"^# .*\n",
    # Develop (#490): before the first of Contributing, Epics or Licence, so
    # ahead of Releases & citing when both are new
    ("README.md", "develop"): r"\n(?=\n?## (?:Contributing|Epics|Licen[cs]e)\b)",
    # Releases & citing: before the first of Contributing, Epics or Licence
    ("README.md", "citing"): r"\n(?=\n?## (?:Contributing|Epics|Licen[cs]e)\b)",
    # new in every AGENTS.md: placed before the repository's own table
    # (with or without a blank line before the heading)
    ("AGENTS.md", "skills"): r"\n(?=\n?## Where to look\n)",
    # after the skills block, before the repository's own table (#277: what
    # CLAUDE.md held, so CLAUDE.md is only `@AGENTS.md`)
    ("AGENTS.md", "agent-defaults"): r"\n(?=\n?## Where to look\n)",
    # how a protocol gets swarm-core (swarm-routing/swarm-adapter-ns3#134): after
    # Build & verify, before the golden rules
    ("AGENTS.md", "dependencies"): r"\n(?=\n?## Golden rules)",
    # an existing CODEOWNERS keeps its rules; the org's go last (the last match wins)
    (".github/CODEOWNERS", "codeowners"): r"\Z",
}


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


# the ns-3 bullet of a `dependencies` section, up to the next bullet
NS3_BULLET = re.compile(r"^- \*\*The ns-3 (?:build|canary)\*\*:.*?(?=^- \*\*)", re.M | re.S)


def template(name):
    return read(os.path.join(TEMPLATES, name))


def shield(label, message, color):
    def esc(s):
        return quote(s.replace("-", "--").replace("_", "__"), safe="")

    return f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{color}"


PROFILE = "profile/README.md"
PROFILE_BADGES = {
    "Main": [
        (
            "Website",
            "https://img.shields.io/badge/Website-swarm--routing.github.io-blue",
            "https://swarm-routing.github.io",
        ),
        (
            "AI First",
            "https://img.shields.io/badge/Maintained_with-AI_Agents-8A2BE2",
            "#the-ai-first-engineering-model",
        ),
    ],
    "Platforms": [
        (
            "ns-3",
            "https://img.shields.io/badge/ns--3-Network_Simulator-1081c2",
            "https://www.nsnam.org/",
        ),
        (
            "Browser: WebAssembly",
            "https://img.shields.io/badge/Browser-WebAssembly-informational?logo=webassembly",
            "https://swarm-routing.github.io/pipeline/",
        ),
    ],
    "Containers": [
        (
            "GHCR: ns3-dev",
            "https://img.shields.io/badge/ghcr.io-swarm--routing%2Fns3--dev-blue?logo=docker",
            "https://github.com/orgs/swarm-routing/packages/container/package/ns3-dev",
        )
    ],
    "Protocols": [
        (
            "Protocol: AntHocNet",
            "https://img.shields.io/badge/Protocol-AntHocNet-green",
            "https://github.com/swarm-routing/AntHocNet",
        ),
        (
            "Protocol: ARA",
            "https://img.shields.io/badge/Protocol-ARA-orange",
            "https://github.com/swarm-routing/ARA",
        ),
        (
            "Protocol: BeeAdHoc",
            "https://img.shields.io/badge/Protocol-BeeAdHoc-orange",
            "https://github.com/swarm-routing/BeeAdHoc",
        ),
        (
            "Protocol: HOPNET",
            "https://img.shields.io/badge/Protocol-HOPNET-orange",
            "https://github.com/swarm-routing/HOPNET",
        ),
        (
            "Protocol: Termite",
            "https://img.shields.io/badge/Protocol-Termite-orange",
            "https://github.com/swarm-routing/Termite",
        ),
    ],
    "Quality": [
        (
            "SonarQube Cloud",
            "https://img.shields.io/badge/SonarQube-Cloud-F3A000?logo=sonarqube",
            "https://sonarcloud.io/",
        ),
        (
            "Codecov",
            "https://img.shields.io/badge/Codecov-Enabled-F01F7A?logo=codecov",
            "https://codecov.io/",
        ),
        (
            "OpenSSF Scorecard",
            "https://img.shields.io/badge/OpenSSF-Scorecard-a00000?logo=linuxfoundation",
            "https://securityscorecards.dev/",
        ),
    ],
    "Trust": [
        (
            "OpenSSF Scorecard: AntHocNet",
            "https://api.securityscorecards.dev/projects/github.com/swarm-routing/AntHocNet/badge",
            "https://scorecard.dev/viewer/?uri=github.com/swarm-routing/AntHocNet",
        ),
        (
            "OpenSSF Best Practices: AntHocNet",
            "https://www.bestpractices.dev/projects/16656/badge",
            "https://www.bestpractices.dev/projects/16656",
        ),
        (
            "Images signed: cosign",
            shield("images signed", "cosign", "success"),
            "https://github.com/swarm-routing/sim-containers/blob/main/SECURITY.md",
        ),
    ],
    "Stack": [
        (
            "Runs on ns-3",
            shield("runs on", "ns-3", "informational"),
            "https://www.nsnam.org",
        ),
        (
            "C++23",
            shield("C++", "23", "blue") + "?logo=cplusplus",
            "https://github.com/swarm-routing/swarm-adapter-ns3",
        ),
        (
            "Python 3.10+",
            "https://img.shields.io/badge/python-3.10%2B-blue?logo=python",
            "https://github.com/swarm-routing/swarm-adapter-ns3",
        ),
        (
            "Go 1.27",
            "https://img.shields.io/badge/go-1.27-blue?logo=go",
            "https://github.com/swarm-routing/swarm-adapter-ns3",
        ),
    ],
    "Open Tickets": [
        (
            "Open RCAPA",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Arcapa"
            "%20is%3Aopen%20is%3Aissue&label=rcapa&color=darkred",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Arcapa+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open handoffs",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Ahandoff"
            "%20is%3Aopen%20is%3Aissue&label=handoffs&color=green",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Ahandoff+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open epics",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Aepic"
            "%20is%3Aopen%20is%3Aissue&label=epics&color=purple",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Aepic+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open enhancements",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Aenhancement"
            "%20is%3Aopen%20is%3Aissue&label=enhancements&color=royalblue",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Aenhancement+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open bugs",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Abug"
            "%20is%3Aopen%20is%3Aissue&label=bugs&color=red",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Abug+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open chore",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Achore"
            "%20is%3Aopen%20is%3Aissue&label=chores&color=yellow",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Achore+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open documentation",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Adocumentation"
            "%20is%3Aopen%20is%3Aissue&label=documentations&color=green",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Adocumentation+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open question",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Aquestion"
            "%20is%3Aopen%20is%3Aissue&label=questions&color=magenta",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Aquestion+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open verification",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Averification"
            "%20is%3Aopen%20is%3Aissue&label=verifications&color=coral",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Averification+state%3Aopen+is%3Aissue&type=issues",
        ),
        (
            "Open hold",
            "https://img.shields.io/github/issues-search?query=org%3Aswarm-routing%20label%3Ahold"
            "%20is%3Aopen%20is%3Aissue&label=hold&color=olive",
            "https://github.com/search?q=org%3Aswarm-routing+label%3Ahold+state%3Aopen+is%3Aissue&type=issues",
        ),
    ],
    "Community & docs": [
        (
            "Colony Arena",
            "https://img.shields.io/website?url=https%3A%2F%2Fswarm-routing.github.io&label=Colony%20Arena",
            "https://swarm-routing.github.io",
        ),
        (
            "Claude Code plugin",
            "https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com"
            "%2Fswarm-routing%2Fskills%2Fmain%2F.claude-plugin%2Fplugin.json&query=%24.version"
            "&label=Claude%20Code%20plugin&color=blueviolet",
            "https://github.com/swarm-routing/skills",
        ),
        (
            "Conventional Commits",
            shield("Conventional Commits", "1.0.0", "yellow"),
            "https://www.conventionalcommits.org",
        ),
        (
            "Sponsor",
            "https://img.shields.io/github/sponsors/danieljoppi?label=sponsor&logo=githubsponsors&color=ea4aaa",
            "https://github.com/sponsors/danieljoppi",
        ),
    ],
}


# --- configuration -----------------------------------------------------------


def git_slug(repo_dir):
    try:
        url = subprocess.run(
            ["git", "-C", repo_dir, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def swarm_core_mode(repo_dir):
    """How the repository gets swarm-core's core/: "vcpkg-adapter-lock" (vcpkg mode
    with the adapter's own swarm-adapter-ns3.lock beside swarm-core.lock, the
    ns-3 module's release: AntHocNet, swarm-routing/AntHocNet#1218), "vcpkg"
    (swarm-core.lock and a vcpkg.json that depends on swarm-core, #489), "adapter" (swarm-core.lock read by
    the root CMakeLists.txt, no core/: the ns-3 adapter, swarm-routing/swarm-adapter-ns3#258),
    "lock" (swarm-core.lock), "pin"
    (a commit SWARM_CORE_REF in core/CMakeLists.txt) or None. The `dependencies`
    section of AGENTS.md renders only where one holds, in the matching text, so
    it never says what the repository cannot back (swarm-routing/swarm-adapter-ns3#134)."""
    if os.path.exists(os.path.join(repo_dir, "swarm-core.lock")):
        try:
            deps = json.loads(read(os.path.join(repo_dir, "vcpkg.json")) or "{}")
            deps = deps.get("dependencies") or []
        except (ValueError, AttributeError):
            deps = []
        names = [d.get("name") if isinstance(d, dict) else d for d in deps]
        if "swarm-core" in names:
            adapter_lock = os.path.join(repo_dir, "swarm-adapter-ns3.lock")
            return "vcpkg-adapter-lock" if os.path.exists(adapter_lock) else "vcpkg"
        root = read(os.path.join(repo_dir, "CMakeLists.txt")) or ""
        if not os.path.exists(os.path.join(repo_dir, "core", "CMakeLists.txt")) and re.search(
            r"^[^#\n]*file\(\s*(?:STRINGS|READ)\b[^#\n]*swarm-core\.lock", root, re.M
        ):
            return "adapter"  # the ns-3 adapter: no core/, the root CMakeLists.txt reads the lock
        return "lock"
    cmake = read(os.path.join(repo_dir, "core", "CMakeLists.txt")) or ""
    return "pin" if re.search(r"^\s*set\(\s*SWARM_CORE_REF\b", cmake, re.M) else None


class SettingsOnly(Exception):
    """The config has `[settings]` and no `kind`: no templates are managed."""


# what each --json command prints for a settings-only config
SETTINGS_ONLY_JSON = {"plan": '{"unchanged":0,"changes":[]}', "seeds": "[]", "settings": "{}"}


# --- the org's own workflow references (#716) ----------------------------------
# Every `uses: swarm-routing/.github/<path>@<ref>` line in a repository's
# workflows and composite actions names the commit .github/org-sync.lock pins,
# `@<sha> # main@<its date>`, so OpenSSF Scorecard's Pinned-Dependencies sees a
# commit, and org-bot's refresh PR moves the pin and every reference together.
# The org-managed workflows are rendered so; the repository's own workflow
# files are the `refs` items: only that reference is the org's, the rest of the
# file stays the repository's. A comment after the commit is not compared.
REF_LINE = re.compile(
    r"^([ \t]*(?:-[ \t]+)?uses:[ \t]*swarm-routing/\.github/[^@\s#\"']+)@([^\s#\"']+)"
    r"(?:[ \t]*#[^\n]*)?[ \t]*$",
    re.M,
)
# what decides a render: the files of this repository org-sync reads (the lock
# moves to the newest commit that changed one of them, or a workflow a
# reference names), so a commit that touches none of them moves no pin
RENDER_PATHS = ("templates", "tools/org-sync", "tools/fidelity", "ISSUE_TEMPLATE", "LICENSE")
_dates = {}


def ref_files(repo_dir):
    """The workflow and composite-action files of `repo_dir` that call this repository."""
    out = []
    wf = os.path.join(repo_dir, ".github", "workflows")
    for name in sorted(os.listdir(wf)) if os.path.isdir(wf) else ():
        if name.endswith((".yml", ".yaml")):
            out.append(f".github/workflows/{name}")
    acts = os.path.join(repo_dir, ".github", "actions")
    for root, dirs, files in os.walk(acts):
        dirs.sort()
        for name in sorted(files):
            if name in ("action.yml", "action.yaml"):
                out.append(os.path.relpath(os.path.join(root, name), repo_dir).replace(os.sep, "/"))
    return [
        p
        for p in out
        if not os.path.islink(os.path.join(repo_dir, p))
        and REF_LINE.search(read(os.path.join(repo_dir, p)) or "")
    ]


def org_git(*args):
    return subprocess.run(["git", "-C", ORG, *args], capture_output=True, text=True)


def pin_refs(text, pin):
    """`text` with every reference to this repository at commit `pin` (None: as it is)."""
    if not pin:
        return text
    if pin not in _dates:
        r = org_git("show", "-s", "--format=%cs", pin)
        _dates[pin] = r.stdout.strip() if r.returncode == 0 else ""
    note = f"# main@{_dates[pin]}" if _dates[pin] else "# main"
    return REF_LINE.sub(lambda m: f"{m.group(1)}@{pin} {note}", text)


def ref_key(text):
    """`text` as references are compared: the commit kept, its comment dropped."""
    return REF_LINE.sub(lambda m: f"{m.group(1)}@{m.group(2)}", text)


def history():
    """Make this checkout's history complete enough to read (org-bot's is shallow)."""
    if org_git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        org_git("fetch", "-q", "--unshallow", "origin")


def reusable_paths(rev):
    """The workflows of this repository at `rev` that others call, and its actions."""
    names = org_git("ls-tree", "--name-only", f"{rev}:.github/workflows").stdout.split()
    out = [".github/actions"]
    for name in names:
        r = org_git("show", f"{rev}:.github/workflows/{name}")
        if r.returncode == 0 and re.search(r"^[ \t]*workflow_call:", r.stdout, re.M):
            out.append(f".github/workflows/{name}")
    return out


def content_pin(sha):
    """The newest first-parent commit up to `sha` that changed what a render reads
    or what a reference names: every later commit renders the same text, so the
    pin (and every reference) stays where it was. `sha` itself when unreadable."""
    history()
    r = org_git(
        "log", "-1", "--first-parent", "--format=%H", sha, "--", *RENDER_PATHS, *reusable_paths(sha)
    )
    got = r.stdout.strip()
    return got if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", got) else sha


def refs_moved(old, new):
    """Did a workflow or an action others call change between `old` and `new`?"""
    if old == new:
        return False
    history()
    r = org_git("diff", "--quiet", old, new, "--", *reusable_paths(new))
    return r.returncode != 0


def ref_only(commit, paths):
    """Did `commit` change nothing in `paths` but references to this repository?"""
    r = org_git("diff", "-U0", "--no-color", "--no-ext-diff", f"{commit}^", commit, "--", *paths)
    if r.returncode:
        return False  # the root commit, or history this checkout lacks
    minus, plus = [], []
    for ln in r.stdout.splitlines():
        if ln.startswith(("---", "+++")):
            continue
        if ln[:1] in "-+":
            (minus if ln[0] == "-" else plus).append(REF_LINE.sub(r"\1@REF", ln[1:]))
    return sorted(minus) == sorted(plus)


def self_pin(sha):
    """For this repository's own workflows (`refs`): the newest first-parent commit
    up to `sha` that changed a workflow others call, or an action, by more than
    the references to itself. Pinning a reference rewrites only those lines, so
    the pin never chases its own refresh."""
    history()
    paths = reusable_paths(sha)
    r = org_git("log", "--first-parent", "--format=%H", sha, "--", *paths)
    for commit in r.stdout.split():
        if not ref_only(commit, paths):
            return commit
    return sha


def load_config(repo_dir, slug=None):
    text = read(os.path.join(repo_dir, CONFIG))
    if text is None:
        sys.exit(f"org-sync: no {CONFIG} in {repo_dir}; run `org_sync.py init --kind KIND`")
    cfg = tomllib.loads(text)
    if "kind" not in cfg and isinstance(cfg.get("settings"), dict):
        # a settings-only file: tools/repo-settings reads its [settings], org-sync manages nothing
        raise SettingsOnly()
    if cfg.get("kind") not in KINDS:
        sys.exit(f"org-sync: {CONFIG}: kind must be one of {', '.join(KINDS)}")
    cfg.setdefault(
        "repo",
        slug
        or git_slug(repo_dir)
        or "swarm-routing/" + os.path.basename(os.path.abspath(repo_dir)),
    )
    cfg.setdefault("title", cfg["repo"].split("/")[1])
    cfg.setdefault("description", "**Status: empty.** Describe the repository here.")
    cfg.setdefault("ci_workflow", "ci.yml")
    cfg.setdefault("dual", [])
    cfg.setdefault("badges", BASE_BADGES + KIND_BADGES[cfg["kind"]])
    cfg.setdefault("manage", [])
    if cfg.setdefault("citation_type", "software") not in CITATION_TYPES:
        sys.exit(f"org-sync: {CONFIG}: citation_type must be one of {', '.join(CITATION_TYPES)}")
    msg = cfg.get("citation_message")
    if msg is not None and (
        not isinstance(msg, str) or not msg.strip() or re.search(r'["\\\x00-\x1f]', msg)
    ):
        sys.exit(
            f"org-sync: {CONFIG}: citation_message must be one line of text, "
            "without double quotes or backslashes"
        )
    filters = cfg.setdefault("coderabbit_path_filters", [])
    if not isinstance(filters, list) or not all(
        isinstance(f, str) and f.strip() and not re.search(r'["\\\x00-\x1f]', f) for f in filters
    ):
        sys.exit(
            f"org-sync: {CONFIG}: coderabbit_path_filters must be a list of glob strings, "
            "without double quotes or backslashes"
        )
    if not isinstance(cfg.get("zenodo", True), bool):
        sys.exit(f"org-sync: {CONFIG}: zenodo must be true or false (false: no Zenodo archive)")
    tick = cfg.get("backstop_tick")
    if tick is not None and (type(tick) is not int or not 1 <= tick <= 59):
        sys.exit(
            f"org-sync: {CONFIG}: backstop_tick must be the minute of the hourly tick, 1 to 59"
        )
    doxyfile = cfg.setdefault("doxyfile", "docs/api/Doxyfile")
    if (
        not isinstance(doxyfile, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", doxyfile)
        or ".." in doxyfile.split("/")
    ):
        sys.exit(
            f"org-sync: {CONFIG}: doxyfile must be a relative path in the repository "
            "(default docs/api/Doxyfile)"
        )
    cfg["extra_badges"] = check_extra_badges(cfg.get("extra_badges", []))
    cfg["indexes"] = check_indexes(cfg.get("indexes", {}))
    # whether the repository builds on ns-3 (#961): every protocol does; a
    # C++ library, adapter or daemon only when it says so (`ns3 = true`)
    if not isinstance(cfg.setdefault("ns3", cfg["kind"] == "protocol"), bool):
        sys.exit(f"org-sync: {CONFIG}: ns3 must be true or false (does it build on ns-3?)")
    cfg["swarm_core_mode"] = swarm_core_mode(repo_dir)
    # the commit every reference to this repository names: the lock's (apply may move it)
    cfg["pin"] = read_lock(repo_dir)
    cfg["ref_files"] = ref_files(repo_dir)
    cfg["references"] = check_references(cfg.get("references", []))
    if cfg["references"] and bib_references(repo_dir) is not None:
        print(
            f"org-sync: warning: {BIB} gives the references (its implemented, tool and dataset "
            f"entries); [[references]] in {CONFIG} is now redundant: remove it",
            file=sys.stderr,
        )
    return cfg


def check_indexes(indexes):
    """`indexes`: a table keyed by a known index (INDEXES), each the listing id the
    index issued, or `{ id = "<id>", variant = "<variant>" }`, or
    `{ id = "<id>", verify_id = "<verify id>" }`; returns name -> (id, variant or
    None, verify id or None)."""
    usage = (
        f"org-sync: {CONFIG}: indexes must be a table keyed by a known index "
        f"({', '.join(INDEXES)}), each the listing id the index issued "
        '(e.g. indexes = { m8ven-mcp = "<id>" }) or { id = "<id>", variant = "<variant>" }; '
        "an id matches " + ", ".join(f"{n}: {e[5].pattern}" for n, e in INDEXES.items())
    )
    if not isinstance(indexes, dict):
        sys.exit(f"{usage}; got {indexes!r}")
    out = {}
    for name, entry in indexes.items():
        if name not in INDEXES:
            sys.exit(f"{usage}; unknown index {name!r}")
        if isinstance(entry, str):
            entry = {"id": entry}
        variants = INDEXES[name][3]
        if (
            not isinstance(entry, dict)
            or set(entry) - {"id", "variant", "verify_id"}
            or not isinstance(entry.get("id"), str)
            or not INDEXES[name][5].fullmatch(entry["id"])
        ):
            sys.exit(f"{usage}; got {name} = {entry!r}")
        variant = entry.get("variant")
        if variant is not None and variant not in variants:
            sys.exit(
                f"org-sync: {CONFIG}: indexes.{name}: variant must be one of "
                f"{', '.join(variants) or '(none)'}; got {variant!r}"
            )
        verify_id = entry.get("verify_id")
        verify = INDEXES[name][4]
        if verify_id is not None and (
            verify is None
            or not isinstance(verify_id, str)
            or not verify[3].fullmatch(verify_id)
            or variant is not None
        ):
            sys.exit(
                f"org-sync: {CONFIG}: indexes.{name}: verify_id must match "
                f"{verify[3].pattern if verify else '(none: the index issues no verify badge)'}"
                f" and replaces variant (the verified badge is a different badge); "
                f"got {entry!r}"
            )
        out[name] = (entry["id"], variant, verify_id)
    return out


def check_extra_badges(extras):
    """`[[extra_badges]]`: each a known group, an alt text, an https image and a
    link, none holding a character that would break the table or the link
    (whitespace, too, in the image and the link)."""
    bad = re.compile(r"[|\[\]()\x00-\x1f]")
    if not isinstance(extras, list):
        sys.exit(f"org-sync: {CONFIG}: extra_badges must be a list of tables")
    for e in extras:
        if (
            not isinstance(e, dict)
            or e.get("group") not in BADGE_GROUPS
            or not all(isinstance(e.get(k), str) and e[k].strip() for k in ("alt", "image", "link"))
            or not e["image"].startswith("https://")
            or any(bad.search(e[k]) for k in ("alt", "image", "link"))
            or any(re.search(r"\s", e[k]) for k in ("image", "link"))
        ):
            sys.exit(
                f"org-sync: {CONFIG}: each [[extra_badges]] needs group (one of "
                f"{', '.join(BADGE_GROUPS)}), alt, an https image and a link, "
                "without | [ ] ( ) or control characters, and no whitespace in image or link"
            )
    return extras


# --- citation ------------------------------------------------------------------
# `citation_type` (#218) sets CITATION.cff's `type:` and message; `citation_message`
# (#235), one line, replaces that message with the repository's own (CITATION.cff
# is a seed: it reaches the file on init and on `reseed CITATION.cff`). `[[references]]`
# lists the work a repository implements or builds on, once, for both the README's
# "Releases & citing" section and CITATION.cff's `references:` (as AntHocNet's):
#
#   [[references]]
#   type = "conference-paper"    # article, conference-paper, book, thesis, report, software
#   title = "..."                # as Crossref has it (lit_search.py confirm DOI)
#   authors = ["Family, Given"]  # in order
#   year = 2002
#   venue = "..."                # journal, proceedings or book; the institution of a thesis or report
#   pages = "79-85"              # optional, as are volume, issue, publisher, thesis_type
#   doi = "10.1109/..."          # or, for a work with none: url and no_doi (the reason)
#   role = "The algorithm this repository implements."
CITATION_TYPES = {
    "software": "If you use this software, please cite it using the metadata below.",
    "dataset": "If you use these data, please cite them using the metadata below.",
}
REF_VENUE = {
    "article": "journal",
    "conference-paper": "collection-title",
    "book": "collection-title",
    "thesis": "institution",
    "report": "institution",
    "software": None,
}


# `docs/references.bib` (#308), the repository's one bibliography, wins over
# `[[references]]` once it has an entry (the seed, a header alone, leaves
# `[[references]]` in charge until the repository fills it): its entries whose `keywords` hold `implemented`,
# `tool` or `dataset` become the same reference tables, in file order, so both
# render through cff_references() and reference_line(). An entry's `note` is its
# role line; without one, the role's line below. A url-only entry is rendered
# with "no DOI: none registered" (`fidelity.py bib check --online` asks Crossref).
BIB = "docs/references.bib"
BIB_ROLES = {
    "implemented": "The work this repository implements.",
    "tool": "A tool this repository uses.",
    "dataset": "Data this repository uses.",
    # the reverse relation: a work built on this repository (swarm-core's ns-3
    # adapter). README lists it apart, never under "Please also cite"; CITATION.cff
    # carries it with `keywords: ["adapter"]`, which zenodo.py makes `isRequiredBy`
    "adapter": "A work that builds on this repository.",
}
BIB_TYPES = {
    "article": ("article", "journal"),
    "inproceedings": ("conference-paper", "booktitle"),
    "incollection": ("book", "booktitle"),
    "book": ("book", None),
    "phdthesis": ("thesis", "school"),
    "mastersthesis": ("thesis", "school"),
    "techreport": ("report", "institution"),
    "software": ("software", None),
    "misc": ("generic", None),
}
# an @incollection that is a conference paper (Crossref types every LNCS paper as a
# `book-chapter`, so `fidelity.py bib entry` writes @incollection): its booktitle names
# proceedings, a conference, workshop or symposium, or its series is a proceedings
# series; it renders as a conference-paper in proceedings (#331), any other stays a book
PROCEEDINGS_BOOK = re.compile(r"proceedings|conference|workshop|symposium", re.I)
PROCEEDINGS_SERIES = re.compile(
    r"lecture\s+notes|\bLNCS\b|\bLNICST\b|communications\s+in\s+computer", re.I
)


def bib_kind(entry):
    """The CFF type and venue field of a bib entry."""
    kind, venue = BIB_TYPES[entry["type"]]
    f = entry["fields"]
    if entry["type"] == "incollection" and (
        PROCEEDINGS_BOOK.search(bib.plain(f.get("booktitle", "")))
        or PROCEEDINGS_SERIES.search(bib.plain(f.get("series", "")))
    ):
        kind = "conference-paper"
    return kind, venue


def bib_references(repo_dir):
    """The reference tables from docs/references.bib; None without the file or
    without an entry (the seed). A malformed file exits with the line."""
    path = os.path.join(repo_dir, BIB)
    if not os.path.exists(path):
        return None
    try:
        entries = bib.load(path)
    except bib.BibError as e:
        sys.exit(f"org-sync: {BIB}: {e} (`fidelity.py bib check` lists every rule)")
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"org-sync: {BIB}: cannot read it: {e}")
    if not entries:
        return None
    refs = []
    for e in entries:
        roles = bib.roles(e)
        # `adapter` wins in any keyword order: a work built on this repository is
        # never also work it builds on
        role = "adapter" if "adapter" in roles else next((r for r in roles if r in BIB_ROLES), None)
        if role is None:
            continue
        f, where = e["fields"], f"org-sync: {BIB}: line {e['line']}: {e['key']}"
        for key in ("title", "author", "year"):
            if not bib.plain(f.get(key, "")):
                sys.exit(f"{where}: needs {key} to be cited (role {role})")
        year = bib.plain(f["year"])
        if not year.isdigit():
            sys.exit(f"{where}: year is a number")
        kind, venue = bib_kind(e)
        if kind == "generic" and role == "dataset":
            kind = "data"
        r = {
            "type": kind,
            "title": bib.plain(f["title"]),
            # an organization ({braced} whole name) is CFF's `name`, a person family/given
            "authors": [
                {"name": fam} if org else fam + (f", {giv}" if giv else "")
                for (fam, giv), org in zip(
                    bib.split_authors(f["author"]), bib.corporate(f["author"])
                )
            ],
            "year": int(year),
            "role": bib.plain(f.get("note", "")) or BIB_ROLES[role],
        }
        if role == "adapter":
            r["adapter"] = True
        if venue and bib.plain(f.get(venue, "")):
            r["venue"] = bib.plain(f[venue])
        if e["type"] in ("phdthesis", "mastersthesis"):
            r["thesis_type"] = "PhD thesis" if e["type"] == "phdthesis" else "Master's thesis"
        for src, dst in (("volume", "volume"), ("number", "issue"), ("publisher", "publisher")):
            if bib.plain(f.get(src, "")):
                r[dst] = bib.plain(f[src])
        if bib.plain(f.get("pages", "")):
            r["pages"] = re.sub(r"-+", "-", bib.plain(f["pages"]))
        doi = bib.norm_doi(f.get("doi"))
        if doi and not re.match(r"^10\.\d{4,9}/\S+$", doi):
            sys.exit(f"{where}: doi {doi} is not a DOI (10.NNNN/...)")
        if doi:
            r["doi"] = doi
        elif f.get("url"):
            r["url"], r["no_doi"] = f["url"], "none registered"
        else:
            sys.exit(f"{where}: needs a doi, or a url")
        refs.append(r)
    return refs


def references(cfg, repo_dir):
    """What the citing section and CITATION.cff cite: the bib's, else `[[references]]`."""
    refs = bib_references(repo_dir)
    return cfg["references"] if refs is None else refs


def check_references(refs):
    """`[[references]]` entries, checked: each has a type, a title, authors, a
    year and a role, and a DOI or else a URL and the reason it has no DOI."""
    if not isinstance(refs, list):
        sys.exit(f"org-sync: {CONFIG}: references must be an array of tables ([[references]])")
    for i, r in enumerate(refs, 1):
        where = f"org-sync: {CONFIG}: references #{i}"
        if not isinstance(r, dict):
            sys.exit(f"{where}: not a table")
        if r.get("type") not in REF_VENUE:
            sys.exit(f"{where}: type must be one of {', '.join(REF_VENUE)}")
        for key in ("title", "authors", "year", "role"):
            if not r.get(key):
                sys.exit(f"{where}: needs {key}")
        if not isinstance(r["authors"], list) or not all(
            isinstance(a, str) and a.strip() for a in r["authors"]
        ):
            sys.exit(f'{where}: authors is a list of "Family, Given" strings')
        if not isinstance(r["year"], int) or isinstance(r["year"], bool):
            sys.exit(f"{where}: year is an integer")
        for key in ("title", "role", "venue", "doi", "url", "no_doi", "publisher", "thesis_type"):
            if key in r and not isinstance(r[key], str):
                sys.exit(f"{where}: {key} is a string")
        if not r.get("doi") and not (r.get("url") and r.get("no_doi")):
            sys.exit(f"{where}: needs a doi, or a url and no_doi (why it has none)")
        if r.get("doi") and not re.match(r"^10\.\d{4,9}/\S+$", r["doi"]):
            sys.exit(f"{where}: doi is the identifier (10.NNNN/...), not a resolver URL")
        if "adapter" in r and not isinstance(r["adapter"], bool):
            sys.exit(f"{where}: adapter is true or false (a work built on this repository)")
    return refs


def yq(s):
    """A double-quoted YAML scalar."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def split_author(a):
    family, _, given = a.partition(",")
    return family.strip(), given.strip()


def short_authors(authors):
    """`G. Di Caro, F. Ducatelle, L. M. Gambardella`; more than four: the first, et al."""

    def one(a):
        if isinstance(a, dict):  # an organization (docs/references.bib only)
            return a["name"]
        family, given = split_author(a)
        initials = " ".join(p[0] + "." for p in re.split(r"[\s.]+", given) if p)
        return f"{initials} {family}".strip()

    names = [one(a) for a in authors]
    return names[0] + " et al." if len(names) > 4 else ", ".join(names)


def cff_references(refs):
    """The `references:` block of CITATION.cff, '' without references."""
    if not refs:
        return ""
    out = ["references:"]
    for r in refs:
        out.append(f"  - type: {r['type']}")
        out.append(f"    title: {yq(r['title'])}")
        out.append("    authors:")
        for a in r["authors"]:
            if isinstance(a, dict):  # an organization (docs/references.bib only)
                out.append(f"      - name: {yq(a['name'])}")
                continue
            family, given = split_author(a)
            out.append(f"      - family-names: {yq(family)}")
            if given:
                out.append(f"        given-names: {yq(given)}")
        venue = REF_VENUE.get(r["type"])
        if r.get("venue") and venue == "institution":
            out.append(f"    institution:\n      name: {yq(r['venue'])}")
        elif r.get("venue") and venue:
            out.append(f"    {venue}: {yq(r['venue'])}")
            if venue == "collection-title" and r["type"] == "conference-paper":
                out.append("    collection-type: proceedings")
        if r.get("thesis_type"):
            out.append(f"    thesis-type: {yq(r['thesis_type'])}")
        for key in ("volume", "issue"):
            if r.get(key):
                out.append(f"    {key}: {yq(r[key])}")
        if r.get("pages"):
            start, _, end = str(r["pages"]).replace("\u2013", "-").partition("-")
            out.append(f"    start: {yq(start.strip())}")
            if end:
                out.append(f"    end: {yq(end.strip())}")
        out.append(f"    year: {int(r['year'])}")
        if r.get("publisher"):
            out.append(f"    publisher:\n      name: {yq(r['publisher'])}")
        if r.get("doi"):
            out.append(f"    doi: {yq(r['doi'])}")
        if r.get("url"):
            out.append(f"    url: {yq(r['url'])}")
        notes = r["role"].strip() + (f" No DOI: {no_doi(r)}." if r.get("no_doi") else "")
        out.append(f"    notes: {yq(notes)}")
        if r.get("adapter"):
            out.append('    keywords:\n      - "adapter"')
    return "\n".join(out) + "\n"


def no_doi(r):
    """Why a reference has no DOI, without a closing full stop."""
    return r["no_doi"].strip().rstrip(".")


def reference_line(r):
    """One README bullet, as AntHocNet's: authors, *title*, venue, pages, year, link: role."""
    parts = [short_authors(r["authors"]), f"*{r['title']}*"]
    if r.get("venue"):
        venue, issue = r["venue"], f"({r['issue']})" if r.get("issue") else ""
        if r.get("volume"):
            # a journal's 7(4); a proceedings' or a book's ", vol. 5"
            venue += f" {r['volume']}{issue}" if r["type"] == "article" else f", vol. {r['volume']}"
        parts.append(venue)
    if r.get("pages"):
        parts.append("pp. " + str(r["pages"]).replace("-", "\u2013"))
    parts.append(str(r["year"]))
    if r.get("doi"):
        parts.append(f"[doi:{r['doi']}](https://doi.org/{r['doi']})")
    else:
        parts.append(f"<{r['url']}> (no DOI: {no_doi(r)})")
    return f"- {', '.join(parts)}. {r['role'].strip()}"


def citing_section(cfg, repo_dir):
    """README "Releases & citing", as AntHocNet's: how releases ship, the
    concept DOI (each version DOI is on its Zenodo record, never typed here),
    the work it builds on, the fidelity sheet. Rendered for `citation = true`;
    one line per paragraph."""
    repo, concept = cfg["repo"], zenodo_concept(cfg)
    out = ["## Releases & citing", ""]
    changelog = os.path.exists(os.path.join(repo_dir, "CHANGELOG.md"))
    if calls_workflow(repo_dir, "reusable-release.yml"):
        out += [
            "Versions follow [SemVer](https://semver.org)"
            + (" ([CHANGELOG.md](CHANGELOG.md))" if changelog else "")
            + f". Each release is listed under [Releases](https://github.com/{repo}/releases),"
            " built by the org's release workflow"
            + (
                " and archived on [Zenodo](https://zenodo.org) with its own DOI."
                if zenodo_archived(cfg)
                else "."
            ),
            "",
        ]
    what = "these data" if cfg["citation_type"] == "dataset" else "this repository"
    cite = f"To cite {what}, use the \u201cCite this repository\u201d button (from [CITATION.cff](CITATION.cff))"
    if concept:
        doi = f"10.5281/zenodo.{concept}"
        out += [
            cite + ":",
            "",
            "| DOI | resolves to |",
            "|---|---|",
            f"| [`{doi}`](https://doi.org/{doi}) | **concept DOI**: always the latest release. "
            "This is the badge above, and the right citation when you mean this project. |",
            "",
            "Each release also has its own **version DOI**, listed on"
            f" [its Zenodo record](https://doi.org/{doi}): cite that one when you reproduce a"
            " number measured at that release.",
        ]
    elif not zenodo_archived(cfg):
        out += [
            cite + ". Its releases are not archived on Zenodo, so it has no DOI: name the"
            " release you used by its tag.",
        ]
    else:
        out += [
            cite + ". It has no DOI yet: the concept DOI appears here and in the badge above"
            " once Zenodo archives its first release.",
        ]
    refs = references(cfg, repo_dir)
    cited = [r for r in refs if not r.get("adapter")]
    if cited:
        out += ["", "Please also cite the work it builds on:", ""]
        out += [reference_line(r) for r in cited]
    adapters = [r for r in refs if r.get("adapter")]
    if adapters:
        out += ["", "Works that build on it:", ""]
        out += [reference_line(r) for r in adapters]
    if os.path.exists(os.path.join(repo_dir, "docs/fidelity.md")):
        out += [
            "",
            "What this implementation reproduces from its sources, and every deliberate"
            " deviation, is in [docs/fidelity.md](docs/fidelity.md).",
        ]
    out += [
        "",
        "Using it in your work? Contributions are welcome, and citing "
        + ("the DOI" if concept else "it")
        + " helps just as much.",
    ]
    return "\n".join(out) + "\n"


def licence_text(cfg):
    if cfg.get("licence_badge"):
        return cfg["licence_badge"]
    if cfg["dual"] == [""]:
        return "MIT OR GPL-2.0-only"
    if cfg["dual"]:
        return "GPL-2.0-only, " + " ".join(cfg["dual"]) + " MIT OR GPL-2.0-only"
    return "GPL-2.0-only"


def arena_id(cfg):
    """The project's id on the site; none for the site itself and the skills repo,
    which have no project page, unless `[docs] arena_id` says otherwise."""
    docs = cfg.get("docs", {})
    if "arena_id" in docs:
        return docs["arena_id"]
    return "" if cfg["kind"] in ("site", "skills") else cfg["title"]


def sonar_key(cfg):
    """The SonarQube Cloud project key: `[quality] sonar_key`, else
    `<owner>_<repo>` as SonarQube Cloud names an imported GitHub repository."""
    return cfg.get("quality", {}).get("sonar_key") or cfg["repo"].replace("/", "_")


def calls_workflow(repo_dir, reusable):
    """True when a workflow of the repository calls this reusable workflow (or
    action): a YAML comment naming it does not count (the site's release-sync.yml
    describes reusable-release.yml, and the site has no release, so its badge read
    "no releases found")."""
    wfdir = os.path.join(repo_dir, ".github/workflows")
    try:
        names = sorted(os.listdir(wfdir))
    except OSError:
        return False
    return any(
        reusable in line.split("#", 1)[0]
        for n in names
        for line in (read(os.path.join(wfdir, n)) or "").splitlines()
    )


def uploads_coverage(cfg, repo_dir):
    """True when a workflow of the repository sends coverage to Codecov (the
    reusable-codecov.yml job, or codecov-action itself as AntHocNet's quality.yml),
    so the badge never reads `unknown`."""
    return calls_workflow(repo_dir, "reusable-codecov.yml") or calls_workflow(
        repo_dir, "codecov/codecov-action@"
    )


def zenodo_archived(cfg):
    """False when the config opts out of Zenodo (`zenodo = false`, #811): the
    repository's releases stay GitHub releases, with no archive and no DOI."""
    return cfg.get("zenodo", True) is not False


def zenodo_concept(cfg):
    """The Zenodo concept record id from `zenodo_concept`, digits only, else ''
    (always '' with `zenodo = false`: no DOI badge, no `doi:` line)."""
    c = str(cfg.get("zenodo_concept", "")).strip()
    return c if c.isdigit() and zenodo_archived(cfg) else ""


VCPKG_REGISTRY = "swarm-routing/vcpkg-registry"
PORT_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def vcpkg_ports(cfg):
    """The repository's ports in swarm-routing/vcpkg-registry (`vcpkg_ports`), valid names only."""
    ports = cfg.get("vcpkg_ports", [])
    return (
        [p for p in ports if isinstance(p, str) and PORT_NAME.fullmatch(p)]
        if isinstance(ports, list)
        else []
    )


def vcpkg_badge(port):
    """A port's version on the registry's main, as a shields dynamic JSON badge."""
    raw = f"https://raw.githubusercontent.com/{VCPKG_REGISTRY}/main/ports/{port}/vcpkg.json"
    q = quote('$["version-semver"]', safe="")
    url = f"https://img.shields.io/badge/dynamic/json?url={quote(raw, safe='')}&query={q}&label={quote('vcpkg ' + port)}"
    return f"[![vcpkg: {port}]({url})](https://github.com/{VCPKG_REGISTRY}/tree/main/ports/{port})"


def pypi_project(cfg):
    """The PyPI project name from `pypi_project` (PEP 508 name characters), else ''."""
    name = cfg.get("pypi_project", "")
    return (
        name if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) else ""
    )


def bestpractices_project(cfg):
    """The bestpractices.dev project id from `bestpractices_project`, digits only, else ''."""
    p = str(cfg.get("bestpractices_project", "")).strip()
    return p if p.isdigit() else ""


def check_runs_badge(repo, label, job, logo):
    """A live badge for one job's check run on main (shields.io check-runs)."""
    q = f"nameFilter={quote(job)}&label={quote(label)}&logo={logo}"
    return f"https://img.shields.io/github/check-runs/{repo}/main?{q}"


def badge_lines(cfg, repo_dir):
    """The README badges: a table, one row per group that has one (BADGE_GROUPS)."""
    rendered = badges_by_kind(cfg, repo_dir)
    rows = []
    for group, (title, kinds) in BADGE_GROUPS.items():
        cells = [rendered[k] for k in kinds if k in rendered]
        cells += [
            f"[![{e['alt']}]({e['image']})]({e['link']})"
            for e in cfg.get("extra_badges", [])
            if e["group"] == group
        ]
        if cells:
            rows.append(f"| {title} | {' '.join(cells)} |\n")
    return BADGE_TABLE_HEAD + "".join(rows) if rows else ""


def profile_badge_lines():
    """The org profile's badge table, in PROFILE_BADGES order."""
    rows = [
        f"| {title} | {' '.join(f'[![{a}]({i})]({u})' for a, i, u in badges)} |\n"
        for title, badges in PROFILE_BADGES.items()
        if badges
    ]
    return BADGE_TABLE_HEAD + "".join(rows)


def badges_by_kind(cfg, repo_dir):
    """Each badge of the repository's `badges` list whose target exists, by kind."""
    repo, out = cfg["repo"], {}
    names = []
    sonar = cfg.get("quality", {}).get("sonar", True)
    for b in cfg["badges"]:
        if b == "sonar":
            # `[quality] sonar = false`: no SonarQube Cloud project (yet), so
            # no "project not found" badges; a single sonar-* name still renders
            names += list(SONAR_METRICS) if sonar else []
        else:
            names.append(b)
    for b in names:
        if b == "ci":
            wf = cfg["ci_workflow"]
            if os.path.exists(os.path.join(repo_dir, ".github/workflows", wf)):
                url = f"https://github.com/{repo}/actions/workflows/{wf}"
                out[b] = f"[![CI]({url}/badge.svg)]({url})"
        elif b == "release" and (
            # the org's reusable release, or a release.yml of the repository's own
            # (AntHocNet's, which names reusable-release.yml only in a comment)
            calls_workflow(repo_dir, "reusable-release.yml")
            or os.path.exists(os.path.join(repo_dir, ".github/workflows/release.yml"))
        ):
            out[b] = (
                f"[![Release](https://img.shields.io/github/v/release/{repo}?sort=semver&cacheSeconds=1800)]"
                f"(https://github.com/{repo}/releases)"
            )
        elif b == "doi" and zenodo_concept(cfg):
            doi = f"10.5281/zenodo.{zenodo_concept(cfg)}"
            out[b] = f"[![DOI](https://zenodo.org/badge/DOI/{doi}.svg)](https://doi.org/{doi})"
        elif b == "cite" and os.path.exists(os.path.join(repo_dir, "CITATION.cff")):
            out[b] = "[![Cite](https://img.shields.io/badge/cite-CITATION.cff-blue)](CITATION.cff)"
        elif b == "vcpkg" and vcpkg_ports(cfg):
            out[b] = " ".join(vcpkg_badge(port) for port in vcpkg_ports(cfg))
        elif b == "pypi" and pypi_project(cfg):
            name = pypi_project(cfg)
            out[b] = (
                f"[![PyPI](https://img.shields.io/pypi/v/{name}?label=PyPI)]"
                f"(https://pypi.org/project/{name}/)"
            )
        elif b == "licence":
            out[b] = (
                f"[![Licence: {licence_text(cfg)}]({shield('licence', licence_text(cfg), 'blue')})](LICENSING.md)"
            )
        elif b == "conventional":
            out[b] = (
                f"[![Conventional Commits]({shield('Conventional Commits', '1.0.0', 'yellow')})]"
                "(https://www.conventionalcommits.org)"
            )
        elif b == "cxx":
            # default: the C++ standard of the ns-3 release the org supports
            # (CONTRIBUTING invariant 7); a repo still behind it sets `cxx`
            cxx = cfg.get("cxx", "23")
            out[b] = f"[![C++{cxx}]({shield('C++', str(cxx), 'blue')}?logo=cplusplus)](AGENTS.md)"
        elif b == "ns3":
            out[b] = (
                f"[![Runs on ns-3]({shield('runs on', 'ns-3', 'informational')})](https://www.nsnam.org)"
            )
        elif b == "python":
            py = cfg.get("python", "3.10")
            out[b] = (
                f"[![Python {py}+]({shield('python', py + '+', 'blue')}?logo=python)](AGENTS.md)"
            )
        elif b == "ghcr" and cfg.get("image"):
            owner, name = repo.split("/")[0], cfg["image"]
            out[b] = (
                f"[![GHCR: {name}]({shield('ghcr.io', f'{owner}/{name}', 'blue')}?logo=docker)]"
                f"(https://github.com/orgs/{owner}/packages/container/package/{name})"
            )
        elif b == "cosign" and os.path.exists(os.path.join(repo_dir, "SECURITY.md")):
            out[b] = (
                f"[![Images signed: cosign]({shield('images signed', 'cosign', 'success')})]"
                "(SECURITY.md#verifying-what-it-ships)"
            )
        elif b == "docs" and cfg.get("docs_url"):
            out[b] = f"[![Docs]({shield('docs', 'site', 'blue')})]({cfg['docs_url']})"
        elif b == "arena" and arena_id(cfg):
            # the project's page on the org site (Colony Arena), as in site/hub/projects.json;
            # at /projects/<id>/ since swarm-routing/swarm-routing.github.io#102 (was /arena/<id>/)
            url = f"https://swarm-routing.github.io/projects/{arena_id(cfg)}/"
            out[b] = (
                f"[![Colony Arena: {arena_id(cfg)}]({shield('Colony Arena', 'project page', 'orange')})]({url})"
            )
        elif b == "ns3dev":
            out[b] = (
                f"[![Built on: ns3-dev]({shield('built on', 'ns3-dev image', 'blue')}?logo=docker)]"
                "(https://github.com/orgs/swarm-routing/packages/container/package/ns3-dev)"
            )
        elif b in SONAR_METRICS:
            alt, metric = SONAR_METRICS[b]
            key = sonar_key(cfg)
            out[b] = (
                f"[![{alt}](https://sonarcloud.io/api/project_badges/measure?project={key}&metric={metric})]"
                f"(https://sonarcloud.io/summary/new_code?id={key})"
            )
        elif b == "codecov" and uploads_coverage(cfg, repo_dir):
            # main named: Codecov's own default branch can be stale (AntHocNet's
            # still read `master`, so the branchless badge said "unknown")
            out[b] = (
                f"[![codecov](https://codecov.io/gh/{repo}/branch/main/graph/badge.svg)]"
                f"(https://codecov.io/gh/{repo}/tree/main)"
            )
        elif b == "coderabbit":
            camp = quote(repo, safe="")
            out[b] = (
                f"[![CodeRabbit Pull Request Reviews](https://img.shields.io/coderabbit/prs/github/{repo}"
                f"?utm_source=oss&utm_medium=github&utm_campaign={camp}&labelColor=171717&color=FF570A"
                "&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit+Reviews)](https://coderabbit.ai)"
            )
        elif b == "container-security" and os.path.exists(
            os.path.join(repo_dir, ".github/workflows/container-security.yml")
        ):
            url = f"https://github.com/{repo}/actions/workflows/container-security.yml"
            out[b] = f"[![Container Security (Hadolint & Trivy)]({url}/badge.svg)]({url})"
        elif b in ("hadolint", "trivy") and os.path.exists(
            os.path.join(repo_dir, ".github/workflows/container-security.yml")
        ):
            # live: the job's last check run on main, never a fixed "passing"
            if b == "hadolint":
                img = check_runs_badge(repo, "Hadolint", "hadolint", "docker")
                link = f"https://github.com/{repo}/actions/workflows/container-security.yml"
            else:
                img = check_runs_badge(repo, "Trivy", "trivy-config", "aquasecurity")
                link = f"https://github.com/{repo}/security/code-scanning"
            out[b] = f"[![{b.capitalize()}]({img})]({link})"
        elif b == "scorecard" and os.path.exists(
            os.path.join(repo_dir, ".github/workflows/scorecard.yml")
        ):
            # the score the workflow publishes to the public OpenSSF API
            out[b] = (
                f"[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/{repo}/badge)]"
                f"(https://scorecard.dev/viewer/?uri=github.com/{repo})"
            )
        elif b == "bestpractices" and bestpractices_project(cfg):
            # the project's level on bestpractices.dev (in progress, passing, ...)
            url = f"https://www.bestpractices.dev/projects/{bestpractices_project(cfg)}"
            out[b] = f"[![OpenSSF Best Practices]({url}/badge)]({url})"
        elif b == "indexes" and cfg["indexes"]:
            # the external indexes the repository opted into, in INDEXES order,
            # each by the listing id the index issued
            cells = []
            for name, (alt, image, link, variants, verify, _) in INDEXES.items():
                if name in cfg["indexes"]:
                    lid, variant, verify_id = cfg["indexes"][name]
                    if verify_id:
                        # the verified publisher's badge, in place of the score (#968)
                        valt, vimg, vlink, _ = verify
                        img, url = vimg.format(id=verify_id), vlink.format(id=verify_id)
                        cells.append(f"[![{valt}]({img})]({url})")
                        continue
                    img = image.format(id=lid) + (variants[variant] if variant else "")
                    alt = alt.format(name=lid.rsplit("/", 1)[-1])
                    cells.append(f"[![{alt}]({img})]({link.format(id=lid)})")
            out[b] = " ".join(cells)
        elif b == "rcapa" and "docs/rcapa/README.md" not in cfg.get("skip", []):
            # open RCAPA tickets (label `rcapa`), linking the project's flow (ADR-0003);
            # an absolute link, so the badge holds before the docs/rcapa/ seed lands
            out[b] = (
                f"[![Open RCAPA](https://img.shields.io/github/issues/{repo}/rcapa"
                "?label=open%20RCAPA&color=blue)]"
                f"(https://github.com/{repo}/blob/main/docs/rcapa/README.md)"
            )
        elif b == "ns3-bugs" and os.path.exists(os.path.join(repo_dir, "docs/ns3-bugs.md")):
            # the upstream ns-3 bug register (sim-tools): open tickets labelled `ns3-upstream`
            out[b] = (
                f"[![ns-3 bugs](https://img.shields.io/github/issues/{repo}/ns3-upstream"
                "?label=ns-3%20bugs&color=blue)](docs/ns3-bugs.md)"
            )
        elif b == "claude-plugin":
            out[b] = (
                f"[![Claude Code plugins]({shield('Claude Code', 'plugin marketplace', 'blueviolet')})]"
                "(https://docs.claude.com/en/docs/claude-code/plugin-marketplaces)"
            )
    return out


def licensing_rows(cfg):
    rows = []
    for d in cfg["dual"]:
        rows.append(f"| `{d or '*'}` | `MIT OR GPL-2.0-only` |")
    if cfg["dual"] != [""]:
        rows.append("| everything else (ns-3 modules, docs, data) | `GPL-2.0-only` |")
    return "\n".join(rows)


def render_makefile(cfg):
    """Makefile.in with this kind's commands (templates/make/kinds.toml)."""
    with open(os.path.join(TEMPLATES, "make/kinds.toml"), "rb") as f:
        kind = tomllib.load(f)[cfg["kind"]]
    text = template("make/Makefile.in")
    for key in ("build", "test", "lint", "format", "clean"):
        cmd = cfg.get("make", {}).get(key, kind.get(key))
        lines = (
            cmd.strip().splitlines()
            if cmd
            else [f'@echo "make {key}: nothing to do in this repo (kind {cfg["kind"]})"']
        )
        recipe = "\n".join(f"\t{line.strip()}" for line in lines)
        text = text.replace(f"@{key.upper()}@", recipe)
    module = cfg.get("module", cfg["title"].lower())
    # the template is the org's tooling (dual); the Makefile it seeds belongs to
    # the repo, dual only when the whole repo is
    if cfg["dual"] != [""]:
        text = text.replace(
            "SPDX-License-Identifier: MIT OR GPL-2.0-only",
            "SPDX-License-Identifier: GPL-2.0-only",
            1,
        )
    return (
        text.replace("@TITLE@", cfg["title"])
        .replace("@MODULE@", module)
        .replace("@DOCKERFILE@", cfg.get("dockerfile", "Dockerfile"))
        .replace("@HEADER_ARGS@", header_args(cfg))
        .replace("@SHELL_IMAGE@", kind.get("shell_image", "$(NS3_IMAGE)"))
    )


# Dependabot ecosystems by manifest file name (#716); a directory under one of
# DEPENDABOT_SKIP (fixtures, vendored or built trees) is never watched.
DEPENDABOT_MANIFESTS = {
    "pip": ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"),
    "gomod": ("go.mod",),
    "docker": ("Dockerfile",),
    "npm": ("package.json",),
}
DEPENDABOT_SKIP = {
    ".git",
    "node_modules",
    "build",
    "dist",
    "vendor",
    "third_party",
    "third-party",
    "testdata",
    "fixtures",
    ".venv",
    "venv",
}


def repo_files(repo_dir):
    """The repository's tracked files (git ls-files), else every file on disk."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout.decode()
        files = [f for f in out.split("\0") if f]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for root, dirs, names in os.walk(repo_dir):
        dirs[:] = [x for x in dirs if x != ".git"]
        found += [os.path.relpath(os.path.join(root, n), repo_dir) for n in names]
    return found


def dependabot_entries(repo_dir):
    """(ecosystem, directory) pairs Dependabot should watch, sorted."""
    out = {("github-actions", "/")}
    for path in repo_files(repo_dir):
        parts = path.replace(os.sep, "/").split("/")
        if any(p in DEPENDABOT_SKIP for p in parts[:-1]):
            continue
        name = parts[-1]
        for eco, manifests in DEPENDABOT_MANIFESTS.items():
            # requirements-dev.txt, any .txt lock in a requirements/ directory
            # (AntHocNet's, tools/requirements/), Dockerfile.ns3, ci.Dockerfile count too
            pip_lock = re.fullmatch(r"requirements[\w.-]*\.txt", name) or (
                len(parts) > 1 and parts[-2] == "requirements" and name.endswith(".txt")
            )
            extra = (eco == "pip" and pip_lock) or (
                eco == "docker" and re.fullmatch(r"Dockerfile\.[\w.-]+|[\w.-]+\.Dockerfile", name)
            )
            if name in manifests or extra:
                out.add((eco, "/" + "/".join(parts[:-1])))
    order = ["github-actions", *DEPENDABOT_MANIFESTS]
    return sorted(out, key=lambda e: (order.index(e[0]), e[1]))


def render_dependabot(repo_dir):
    """dependabot.yml.in plus one monthly entry per (ecosystem, directory)."""
    text = template("dependabot/dependabot.yml.in")
    for eco, directory in dependabot_entries(repo_dir):
        text += (
            f"  - package-ecosystem: {eco}\n"
            f"    directory: {directory}\n"
            "    schedule:\n"
            "      interval: monthly\n"
            "    commit-message:\n"
            '      prefix: "chore(deps)"\n'
        )
        if eco == "github-actions":
            text += (
                "    groups:\n"
                "      codeql-action:\n"
                "        patterns:\n"
                '          - "github/codeql-action*"\n'
                "    ignore:\n"
                '      - dependency-name: "swarm-routing/.github*"\n'
            )
    return text


def render_citation(cfg, repo_dir):
    """CITATION.cff.in for this repository: the abstract from the GitHub
    description (`[settings] description`, else the README's `description`),
    the whole work's licence (a CFF list means a choice, so a partly dual repo
    is GPL-2.0-only and LICENSING.md keeps the per-directory MIT),
    the version Commitizen holds, the concept DOI only when `zenodo_concept`,
    `citation_type`'s type and message (or `citation_message`), and `[[references]]`."""
    settings = cfg.get("settings") if isinstance(cfg.get("settings"), dict) else {}
    abstract = re.sub(r"\s+", " ", settings.get("description") or cfg["description"]).strip()
    cz = read(os.path.join(repo_dir, ".cz.toml"))
    try:
        version = tomllib.loads(cz)["tool"]["commitizen"]["version"] if cz else "0.0.0"
    except (tomllib.TOMLDecodeError, KeyError, TypeError):
        version = "0.0.0"
    if cfg["dual"] == [""]:
        # a list in CFF is a choice: the whole work is MIT OR GPL-2.0-only
        lic = "license:\n  - MIT\n  - GPL-2.0-only\n"
    elif cfg["dual"]:
        # a list would offer MIT for the whole work; only the dual roots are
        roots = " ".join(dual_root(d) for d in cfg["dual"])
        lic = (
            f"# The work as a whole; {roots} also MIT OR GPL-2.0-only (LICENSING.md).\n"
            "license: GPL-2.0-only\n"
        )
    else:
        lic = "license: GPL-2.0-only\n"
    doi = ""
    if zenodo_concept(cfg):
        d = f"10.5281/zenodo.{zenodo_concept(cfg)}"
        doi = (
            f'doi: "{d}"\nidentifiers:\n  - type: doi\n    value: "{d}"\n'
            '    description: "Concept DOI: always resolves to the latest released version."\n'
        )
    abstract = textwrap.fill(
        abstract,
        78,
        initial_indent="  ",
        subsequent_indent="  ",
        # a folded scalar joins lines with a space: never split a word
        break_on_hyphens=False,
        break_long_words=False,
    )
    fields = {
        "TITLE": cfg["title"].replace('"', "'"),
        "ABSTRACT": abstract,
        "VERSION": version.replace('"', ""),
        "LICENSE": lic,
        "REPO": cfg["repo"],
        "TYPE": cfg["citation_type"],
        "MESSAGE": cfg.get("citation_message") or CITATION_TYPES[cfg["citation_type"]],
    }
    # one pass over the template, so a value that contains @NAME@ stays as
    # written; @DOI@ fills its whole line, or drops it
    refs = cff_references(references(cfg, repo_dir))
    whole = {"@DOI@\n": doi, "@REFERENCES@\n": refs}
    return re.sub(
        r"@DOI@\n|@REFERENCES@\n|@([A-Z]+)@",
        lambda m: whole[m.group(0)] if m.group(1) is None else fields.get(m.group(1), m.group(0)),
        template("CITATION.cff.in"),
    )


def header_args(cfg):
    """check-headers flags from the repo's dual roots (the same list
    LICENSING.md is rendered from); a dual `core/` also gets the include check."""
    roots = [dual_root(d) for d in cfg["dual"]]
    args = [f"--dual {d}" if d else "--dual ''" for d in roots]
    if "" in roots or "core/" in roots:
        args.append("--core core/")
    return " ".join(args)


def dual_root(d):
    """A Git-relative directory prefix, as check-headers compares it:
    `./tools`, `tools` and `tools/` all become `tools/`; '' stays the whole repo."""
    d = d.strip().replace("\\", "/")
    while d.startswith("./"):
        d = d[2:]
    # a trailing slash, or no extension in the last part (a leading dot is not
    # one: `.github` is a directory), marks a directory
    is_dir = d.endswith("/") or "." not in d.rstrip("/").rsplit("/", 1)[-1].lstrip(".")
    d = d.strip("/")
    if not d:
        return ""
    # a single dual-licensed file (`test/run.sh`) stays a file path: a trailing
    # slash would make check-headers' prefix test never match it
    return f"{d}/" if is_dir else d


def values(cfg):
    v = SafeDict(cfg)
    v.update(
        repo=cfg["repo"],
        title=cfg["title"],
        description=cfg["description"].strip(),
        licensing_rows=licensing_rows(cfg),
        dual_rows="\n".join(f"    {d or 'everything':14}" for d in cfg["dual"]).rstrip(),
        date=datetime.date.today().isoformat(),
        module=cfg.get("module", cfg["title"].lower()),
        sonar_key=sonar_key(cfg),
        trust_boundary=cfg.get(
            "trust_boundary", "Nothing in this repository parses untrusted input yet."
        ).strip(),
        limitations=cfg.get("limitations", "None recorded yet.").strip(),
        posture=cfg.get("posture", "research code for network simulation").strip(),
        verifying=cfg.get(
            "verifying", "Nothing is released yet, so there is nothing to verify."
        ).strip(),
    )
    return v


# --- managed items -----------------------------------------------------------


def items(cfg):
    """(kind, path, source, extra) for every item this repository manages."""
    out = [
        ("seed", "README.md", "README.md.in", None),
        ("section", "README.md", None, "badges"),
        # "Develop": where a newcomer starts, docs/development.md (#490)
        ("section", "README.md", "readme-develop.md", "develop"),
        # the developer guide the Develop section links (#490): a seed, the repository's own once written
        ("seed", "docs/development.md", "development.md", None),
        ("seed", "AGENTS.md", "agents/AGENTS.md.in", None),
        ("section", "AGENTS.md", "agents/org-rules.md", "org-rules"),
        ("section", "AGENTS.md", "agents/conventions.md", "conventions"),
        ("section", "AGENTS.md", "agents/git-workflow.md", "git-workflow"),
        ("section", "AGENTS.md", "agents/skills.md", "skills"),
        ("section", "AGENTS.md", "agents/agent-defaults.md", "agent-defaults"),
        # CLAUDE.md is the org's whole file: one import, so every agent rule
        # lives once, in AGENTS.md (#277)
        ("file", "CLAUDE.md", "claude/CLAUDE.md", None),
        ("seed", "CONTEXT.md", "CONTEXT.md.in", None),
        ("seed", "SECURITY.md", "SECURITY.md.in", None),
        ("section", "SECURITY.md", "security-reporting.md", "reporting"),
        ("file", "LICENSE", "../LICENSE", None),
        ("seed", "LICENSING.md", "LICENSING.md.in", None),
        # the licence texts and the header check: the org's, refreshed (#615)
        ("section", "LICENSING.md", "licensing-texts.md", "licence-texts"),
        ("file", "docs/adr/0000-template.md", "adr/0000-template.md", None),
        ("seed", "docs/adr/README.md", "adr/README.md", None),
        (
            "seed",
            "docs/adr/0001-record-architecture-decisions.md",
            "adr/0001-record-architecture-decisions.md",
            None,
        ),
        ("seed", "Makefile", "make/Makefile.in", None),
        # the org tooling's variables and targets (org-tools, org-sync-check,
        # pre-push): the org's, refreshed; the recipes stay the repository's (#615)
        ("section", "Makefile", "make/org-tools.mk", "org-tools"),
        ("targets", "Makefile", None, "targets"),
        ("file", ".github/workflows/org-sync.yml", "workflows/org-sync.yml", None),
        ("file", ".github/workflows/dco.yml", "workflows/dco.yml", None),
        ("file", ".github/workflows/review-gate.yml", "workflows/review-gate.yml", None),
        ("file", ".github/workflows/scorecard.yml", "workflows/scorecard.yml", None),
        # a push that changes the Best Practices evidence asks org-bot to
        # regenerate .bestpractices.json (#531)
        (
            "file",
            ".github/workflows/bestpractices-evidence.yml",
            "workflows/bestpractices-evidence.yml",
            None,
        ),
        # a push that changes [settings] asks repo-settings to apply it (#569)
        ("file", ".github/workflows/settings-apply.yml", "workflows/settings-apply.yml", None),
        # an issue change that can move an epic list asks epics-refresh to run (#572)
        ("file", ".github/workflows/epics-changed.yml", "workflows/epics-changed.yml", None),
        # every open security alert starts an automated fix; the maintainer keeps
        # dismissals and secret rotation (#629)
        ("file", ".github/workflows/security-autofix.yml", "workflows/security-autofix.yml", None),
        # version updates for every ecosystem the repository has (OpenSSF
        # Scorecard Dependency-Update-Tool, #716): a seed, the repository's own
        ("seed", ".github/dependabot.yml", "dependabot/dependabot.yml.in", None),
        ("json", ".claude/settings.json", "claude-settings.json", None),
        ("seed", ".coderabbit.yaml", "coderabbit/coderabbit.yaml.in", None),
        ("section", ".coderabbit.yaml", "coderabbit/head.yaml", "coderabbit-head"),
        ("section", ".coderabbit.yaml", "coderabbit/tail.yaml", "coderabbit-tail"),
        # The invariant paths' owner (#31), per kind; the org section is last,
        # so it wins over the repository's own lines above it.
        ("seed", ".github/CODEOWNERS", "codeowners/CODEOWNERS.in", None),
        ("section", ".github/CODEOWNERS", f"codeowners/{cfg['kind']}", "codeowners"),
        # the repository's one bibliography (#308): a commented header, no entries
        ("seed", BIB, "references.bib.in", None),
        # its header is the org's rules, managed so a change reaches every repository (#343)
        ("section", BIB, "references-header.bib", "bib-header"),
        # the project's RCAPA flow and index, and the document template (ADR-0003)
        ("seed", "docs/rcapa/README.md", "rcapa/README.md", None),
        ("seed", "docs/rcapa/_template.md", "rcapa/_template.md", None),
    ]
    if cfg["dual"]:
        out.insert(12, ("seed", "LICENSE-MIT", "LICENSE-MIT.in", None))
    if cfg.get("swarm_core_mode"):
        # only where the repository builds on swarm-core, in the text that is true for it
        mode = cfg["swarm_core_mode"]
        out.append(("section", "AGENTS.md", f"agents/dependencies-{mode}.md", "dependencies"))
    if cfg["kind"] in CXX_KINDS:
        # Codecov and SonarQube Cloud settings for reusable-codecov.yml and the
        # reusable ns-3 CI's `sonar` input; the repository's own once written.
        # `[quality] sonar = false`: the repo has no SonarQube Cloud project.
        out.append(("seed", ".codecov.yml", "quality/codecov.yml", None))
        # the install guide (#881, #884): a seed the repository fills in; its
        # known-bugs table is generated from sim-tools' ns-3 bug register by
        # cmd/ns3-bugs, so it is the org's, refreshed
        out.append(("seed", "docs/install.md", "install/install.md.in", None))
        # only where the repository builds on ns-3; elsewhere a line saying the
        # register does not apply (the OMNeT++ adapter, the daemon, #961)
        kb = "known-bugs.md" if cfg["ns3"] else "known-bugs-none.md"
        out.append(("section", "docs/install.md", f"install/{kb}", "known-bugs"))
        if cfg.get("quality", {}).get("sonar", True):
            out.append(
                ("seed", "sonar-project.properties", "quality/sonar-project.properties.in", None)
            )
    if cfg.get("citation"):
        # opt-in: citation metadata for a repository that releases (Zenodo, cite badge)
        out.append(("seed", "CITATION.cff", "CITATION.cff.in", None))
        out.append(("section", "README.md", None, "citing"))
    if cfg["kind"] in CXX_KINDS:
        # the class documentation (#881, #883): the Doxyfile a seed (at
        # `doxyfile`, default docs/api/Doxyfile), the workflow that builds it the org's
        out.append(("seed", cfg["doxyfile"], "api/Doxyfile.in", None))
        out.append(("file", ".github/workflows/api-docs.yml", "workflows/api-docs.yml", None))
    if cfg.get("backstop_tick"):
        # opt-in: an hourly tick of swarm-routing/.github's backstop, at the
        # repository's own minute (#748)
        out.append(
            ("file", ".github/workflows/backstop-tick.yml", "workflows/backstop-tick.yml", None)
        )
    if cfg.get("forms"):
        # opt-in for a repository with its own .github/ISSUE_TEMPLATE/, which
        # hides the org's default forms: each org form is a whole file there;
        # config.yml and the repository's own forms stay its own (#318)
        for name in sorted(os.listdir(os.path.join(ORG, "ISSUE_TEMPLATE"))):
            if name.endswith(".yml") and name != "config.yml":
                out.append(
                    ("file", f".github/ISSUE_TEMPLATE/{name}", f"../ISSUE_TEMPLATE/{name}", None)
                )
    # the repository's own workflows and actions: only their references to
    # swarm-routing/.github are the org's, pinned to the lock's commit (#716)
    managed = {i[1] for i in out if i[0] == "file"}
    out += [("refs", p, None, None) for p in cfg.get("ref_files", []) if p not in managed]
    skip = set(cfg.get("skip", []))
    return [i for i in out if i[1] not in skip and f"{i[1]}#{i[3]}" not in skip]


def find_section(text, name, path=""):
    begin, end = markers(path)
    b, e = begin.format(name), end.format(name)
    i = text.find(b)
    if i < 0:
        return None
    j = text.find(e, i)
    if j < 0:
        return None
    start = i + len(b) + 1  # after the begin line's newline
    return start, j


def block_names(text, path):
    """The names of the complete org-sync blocks in `text`, in order."""
    pre, post = markers(path)[0].split("{}")
    pat = re.compile("^" + re.escape(pre) + r"(\S+)" + re.escape(post) + "$", re.M)
    out = []
    for m in pat.finditer(text):
        if m.group(1) not in out and find_section(text, m.group(1), path):
            out.append(m.group(1))
    return out


def remove_block(text, name, path):
    """`text` without the block `name`, markers included, and without the blank
    line that separated it from what follows when one also precedes it."""
    begin, end = (m.format(name) for m in markers(path))
    s = text.find(begin)
    e = text.find(end, s) + len(end)
    if text[e : e + 1] == "\n":
        e += 1
    if (s == 0 or text[:s].endswith("\n\n")) and text[e : e + 1] == "\n":
        e += 1
    return text[:s] + text[e:]


def orphans(cfg, repo_dir):
    """(item, new_text, detail) for each org-sync block in a managed file whose
    section is not one of this repository's items: skipped, or not enabled
    (#235). The item is ("orphan", path, None, name); new_text drops the block."""
    its = items(cfg)
    known = {(i[1], i[3]) for i in its if i[0] == "section"}
    skip = set(cfg.get("skip", []))
    out = []
    whole = {i[1] for i in its if i[0] == "file"}
    # a whole-file item replaces its blocks with the file (CLAUDE.md's old
    # `org` block, #277): not an orphan to remove on top of that update
    for path in dict.fromkeys(i[1] for i in its if i[1] not in whole):
        text = read(os.path.join(repo_dir, path))
        if text is None:
            continue
        for name in block_names(text, path):
            if (path, name) in known:
                continue
            fix = "drop the skip" if f"{path}#{name}" in skip else "enable its item"
            out.append(
                (
                    ("orphan", path, None, name),
                    remove_block(text, name, path),
                    f"orphan block {name} in {path}: not one of this repository's items "
                    f"(skipped, or not enabled); remove it (`apply --prune-orphans`), or {fix}",
                )
            )
    return out


def insert_seed_block(cfg, cur, path, name, want):
    """The text with a block a Markdown seed gained after the repository was
    seeded (#961): under the seed's heading for it, after that heading when the
    repository has it, else heading and block before the seed's next heading
    (at the end when the repository lacks that one too). None when the seed has
    no such block or the heading is not found exactly once."""
    seed = next((i for i in items(cfg) if i[0] == "seed" and i[1] == path), None)
    tmpl = template(seed[2]) if seed and path.endswith(".md") else None
    begin = markers(path)[0].format(name)
    if not tmpl or begin not in tmpl:
        return None
    before, _, after = tmpl.partition(begin)
    heads = re.findall(r"^## [^{}\n]*$", before, re.M)
    if not heads or not before.rstrip("\n").endswith(heads[-1]):
        return None  # only a block right under its heading
    head = heads[-1]
    block = wrap(name, want, path) + "\n"
    hits = list(re.finditer(rf"^{re.escape(head)}[ \t]*\n", cur, re.M))
    if len(hits) > 1:
        return None
    if hits:
        e = hits[0].end() + (cur[hits[0].end() :].startswith("\n"))
        rest = cur[e:]
        return cur[:e] + block + ("\n" + rest if rest.strip() else "")
    section = f"{head}\n\n{block}"
    nxt = re.search(r"^## [^{}\n]*$", after, re.M)
    m = nxt and list(re.finditer(rf"^{re.escape(nxt.group(0))}[ \t]*$", cur, re.M))
    if m and len(m) == 1:
        return cur[: m[0].start()] + section + "\n" + cur[m[0].start() :]
    return cur.rstrip("\n") + "\n\n" + section


def adopt_span(text, path, name):
    rule = ADOPT.get((path, name))
    if not rule:
        return None
    m = re.search(rule[0], text, re.M)
    if not m:
        return None
    n = re.search(rule[1], text[m.start() + 1 :], re.M)
    if not n and (path, name) in ADOPT_REPLACE:
        return None  # replaced only when recognised whole: never up to the end of the file
    end = m.start() + 1 + n.start() if n else len(text)
    return m.start(), end


def find_line_text(text, piece):
    """The offset of `piece` in `text` starting at a line start, or -1."""
    i = text.find(piece)
    while i > 0 and text[i - 1] != "\n":
        i = text.find(piece, i + 1)
    return i


def adopt_pieces(cur, path, name, want):
    """(status, new_text, detail) for a section of ADOPT_PIECES that has no
    markers yet: the org's unmarked pieces taken out, the block put in."""
    rule = ADOPT_PIECES[(path, name)]
    # the template's own pieces: its paragraphs, and a comment that opens a group
    pieces = [p + "\n" for p in re.split(r"\n\n+|\n(?=# make pre-push )", want.rstrip("\n"))]
    text, first, found = cur, None, 0
    for piece in sorted(set(pieces) | set(rule["old"]), key=len, reverse=True):
        i = find_line_text(text, piece)
        if i < 0:
            continue
        found += 1
        first = i if first is None or i < first else first
        e = i + len(piece)
        if rule["at"] == "end" and text[:i].endswith("\n\n") and text[e : e + 1] == "\n":
            e += 1  # the blank line that separated it goes with it
        text = text[:i] + text[e:]
    if not found and rule["optional"]:
        return "unchanged", None, "no org text to adopt: the repository's own"
    if rule["own"]:
        mine = re.findall(rule["own"] + r".*", text, re.M)
        if mine:
            return (
                "conflict",
                None,
                "the repository's own "
                + "; ".join(f"`{m.strip()}`" for m in mine)
                + " would clash with the org's block: rename or remove it, then apply",
            )
    block = wrap(name, want, path) + "\n"
    if rule["at"] == "first" and first is not None:
        new = text[:first] + block + text[first:]
    else:
        new = text.rstrip("\n") + "\n\n" + block if text.strip() else block
    detail = f"markers added; {found} org piece(s) replaced" if found else "inserted"
    return "adopt", new, detail


def wrap(name, body, path=""):
    begin, end = markers(path)
    return f"{begin.format(name)}\n{body}{end.format(name)}"


def render(cfg, repo_dir, item, v=None):
    """What the template and the config produce for this item today."""
    kind, path, src, name = item
    if name == "badges":
        want = badge_lines(cfg, repo_dir)
    elif name == "citing":
        want = citing_section(cfg, repo_dir)
    else:
        want = template(src) or "" if src else ""
    if name == "coderabbit-head" and cfg.get("coderabbit_path_filters"):
        # The repository's own path_filters (generated data, lockfiles) go after
        # the org's: the list sits inside the managed head, so a hand-added
        # entry would be drift and a second `path_filters:` key a YAML error.
        anchor = '  path_filters:\n    - "!**/*.pdf"\n'
        if anchor not in want:
            sys.exit("org-sync: templates/coderabbit/head.yaml lost its path_filters list")
        extra = "".join(f'    - "{f}"\n' for f in cfg["coderabbit_path_filters"])
        want = want.replace(anchor, anchor + extra)
    if name == "dependencies" and not calls_workflow(repo_dir, "reusable-ns3-ci.yml"):
        # A repository with its own ns-3 CI (AntHocNet) has no canary leg: the
        # bullet that says `canary-dependencies` names `@main` is untrue there
        # (swarm-routing/.github#411, #560).
        want = NS3_BULLET.sub(lambda _: template("agents/dependencies-ns3-own.md"), want)
    if kind == "seed":
        if path == "Makefile":
            want = render_makefile(cfg)
        elif path == "CITATION.cff":
            want = render_citation(cfg, repo_dir)
        elif path == ".github/dependabot.yml":
            want = render_dependabot(repo_dir)
        else:
            want = want.format_map(v or values(cfg))
    if path == ".github/workflows/backstop-tick.yml":
        want = want.replace("@MINUTE@", str(cfg["backstop_tick"]))  # #748
    if path == ".github/workflows/api-docs.yml":
        want = want.replace("@DOXYFILE@", cfg["doxyfile"])  # #883
    if kind == "file" and path.startswith(".github/workflows/"):
        want = pin_refs(want, cfg.get("pin"))  # #716
    return want


def evaluate(cfg, repo_dir, item):
    """Return (status, new_text_or_None, detail). status: create, update,
    unchanged, adopt, conflict, missing."""
    kind, path, src, name = item
    full = os.path.join(repo_dir, path)
    cur = read(full)
    if kind == "refs":
        if cur is None:
            return "unchanged", None, ""
        new = pin_refs(cur, cfg.get("pin"))
        if ref_key(new) == ref_key(cur):
            return "unchanged", None, ""
        return "update", new, "references to swarm-routing/.github not at the pinned commit"
    want = render(cfg, repo_dir, item)
    if kind == "targets":
        if cur is None:
            return "create", None, "with its file"
        have = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", cur, re.M))
        lack = [t for t in MAKE_TARGETS if t not in have]
        if not lack:
            return "unchanged", None, ""
        return "conflict", None, "missing standard target(s): " + " ".join(lack)
    if kind == "seed":
        return ("unchanged", None, "repo-owned") if cur is not None else ("create", want, "")
    if kind == "file":
        if cur == want or (cur is not None and ref_key(cur) == ref_key(want)):
            return "unchanged", None, ""
        return ("create" if cur is None else "update"), want, ""
    if kind == "json":
        doc = {}
        if cur is not None:
            try:
                doc = json.loads(cur)
            except json.JSONDecodeError as e:
                return "conflict", None, f"not valid JSON: {e}"
        new = json.loads(json.dumps(doc))
        tmpl = json.loads(want)
        for top, sub in tmpl.items():
            new.setdefault(top, {}).update(sub)
        # A plugin the org's own marketplace no longer ships is dropped (a
        # rename, e.g. org-repo -> swarm-routing); other marketplaces' plugins
        # and the repo's own keys are left alone.
        ours = tuple(f"@{m}" for m in tmpl.get("extraKnownMarketplaces", {}))
        plugins = new.get("enabledPlugins")
        if ours and isinstance(plugins, dict):
            for key in [k for k in plugins if k.endswith(ours)]:
                if key not in tmpl.get("enabledPlugins", {}):
                    del plugins[key]
        if new == doc and cur is not None:
            return "unchanged", None, ""
        return ("create" if cur is None else "update"), json.dumps(new, indent=2) + "\n", ""
    # section
    if cur is None:
        return "create", None, "with its file"
    span = find_section(cur, name, path)
    if span:
        s, e = span
        after = cur[e:].partition("\n")[2]
        if os.path.basename(path) == "CODEOWNERS" and any(
            ln.strip() and not ln.lstrip().startswith("#") for ln in after.splitlines()
        ):
            return "conflict", None, "rules after the org section override it: move them above"
        if cur[s:e] == want:
            return "unchanged", None, ""
        return "update", cur[:s] + want + cur[e:], ""
    if (path, name) in ADOPT_PIECES:
        return adopt_pieces(cur, path, name, want)
    span = adopt_span(cur, path, name)
    ins = INSERT_AFTER.get((path, name))
    if not span and ins and (m := re.search(ins, cur, re.M)):
        return (
            "adopt",
            cur[: m.end()] + "\n" + wrap(name, want, path) + "\n" + cur[m.end() :],
            "inserted",
        )
    if not span and (new := insert_seed_block(cfg, cur, path, name, want)):
        return "adopt", new, "inserted under its heading, as the seed has it"
    if not span:
        return (
            "conflict",
            None,
            f"no `{markers(path)[0].format(name)}` marker and no recognisable section to adopt",
        )
    s, e = span
    old = cur[s:e]
    trail = ""
    if old.rstrip("\n") + "\n" != old:  # keep the blank lines that separated it from the next block
        trail = old[len(old.rstrip("\n")) + 1 :]
    new = cur[:s] + wrap(name, want, path) + "\n" + trail + cur[e:]
    if old.rstrip("\n") + "\n" == want:
        return "adopt", new, "markers added; text identical"
    if (path, name) in ADOPT_REPLACE:
        return "adopt", new, "markers added; the old org text replaced by the template's"
    return "conflict", new, "existing text differs from the template"


# --- seeds ---------------------------------------------------------------------
# A seed belongs to the repository once written, so `check` never compares it
# again (#91). `seeds` reports how far each one is from today's render, for
# information; `reseed` takes today's render on request.


def with_sections(cfg, repo_dir, path, text):
    """`text` with each managed section of `path` set to its template body, so a
    seed is compared on the repository's own part only (sections are `check`'s)."""
    for item in items(cfg):
        if item[0] == "section" and item[1] == path:
            span = find_section(text, item[3], path)
            if span:
                text = text[: span[0]] + render(cfg, repo_dir, item) + text[span[1] :]
    return text


def fresh_seed(cfg, repo_dir, item, cur=None):
    """The seed as a fresh `init` would write it today, its sections filled in.
    A dated seed (the first ADR) keeps the date it already carries."""
    v = values(cfg)
    m = re.search(r"^- \*\*Date:\*\* (\d{4}-\d\d-\d\d)", cur or "", re.M)
    if m:
        v["date"] = m.group(1)
    return with_sections(cfg, repo_dir, item[1], render(cfg, repo_dir, item, v))


def changed_lines(old, new):
    d = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return sum(1 for x in d if x[:1] in "+-" and x[:3] not in ("+++", "---"))


def seed_report(cfg, repo_dir):
    """[(path, status, changed lines)], status same / differs / missing."""
    out = []
    for item in items(cfg):
        if item[0] != "seed":
            continue
        cur = read(os.path.join(repo_dir, item[1]))
        if cur is None:
            out.append((item[1], "missing", 0))
            continue
        n = changed_lines(
            with_sections(cfg, repo_dir, item[1], cur), fresh_seed(cfg, repo_dir, item, cur)
        )
        out.append((item[1], "differs" if n else "same", n))
    return out


# Untouched seeds (#615): a seed whose own text (its org-sync blocks emptied) is
# still exactly what the pinned templates (.github/org-sync.lock) rendered was
# never edited by the repository, so today's render can replace it in a reviewed
# refresh PR (`apply --reseed-untouched`, which org-bot passes). Any other seed
# that differs is the repository's own edit: listed by `seeds`, never written.
# The pinned render comes from that commit's own org_sync.py (`reseed`), run on
# a copy of the files a render reads; a pin it cannot render (no lock, a commit
# PIN_ORG cannot fetch, a seed that commit did not know) leaves the seed alone.
PIN_ORG = ORG  # the git repository that holds the pinned commits (the self-test's own)


def own_text(text, path):
    """`text` with every org-sync block's body emptied: the repository's part."""
    for name in block_names(text, path):
        s, e = find_section(text, name, path)
        text = text[:s] + text[e:]
    return text


def pinned_render(repo_dir, slug, sha, path):
    """The seed `path` as the templates at commit `sha` rendered it, or None."""

    def g(*args, **kw):
        return subprocess.run(["git", "-C", PIN_ORG, *args], capture_output=True, **kw)

    if g("cat-file", "-e", f"{sha}^{{commit}}").returncode:
        g("fetch", "-q", "--depth", "1", "origin", sha)  # a shallow checkout (org-bot's)
    tar = g("archive", "--format=tar", sha, "--", "templates", "tools/org-sync", "tools/fidelity")
    if tar.returncode:
        return None
    with tempfile.TemporaryDirectory(prefix="org-sync-pin-") as tmp:
        org, repo = os.path.join(tmp, "org"), os.path.join(tmp, "repo")
        with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(org, filter="data")
            else:  # Python 3.11 before 3.11.4
                t.extractall(org)  # our own git objects
        # the render's inputs, as base_drift reads them; never the rest of the tree
        for rel in (CONFIG, LOCK, path, ".cz.toml", "SECURITY.md", *RENDER_INPUTS):
            src = os.path.join(repo_dir, rel)
            if os.path.isfile(src) and not os.path.islink(src):
                write(repo, rel, read(src))
        wf = os.path.join(repo_dir, ".github", "workflows")
        for name in sorted(os.listdir(wf)) if os.path.isdir(wf) else ():
            if os.path.isfile(os.path.join(wf, name)):
                write(repo, f".github/workflows/{name}", read(os.path.join(wf, name)))
        # the copy is a checkout of the same origin, so the render names the same repository
        subprocess.run(["git", "init", "-q", repo], capture_output=True)
        subprocess.run(
            ["git", "-C", repo, "remote", "add", "origin", f"https://github.com/{slug}"],
            capture_output=True,
        )
        tool = os.path.join(org, "tools", "org-sync", "org_sync.py")
        r = subprocess.run(
            [sys.executable, "-I", tool, "reseed", path, repo], capture_output=True, text=True
        )
        return read(os.path.join(repo, path)) if r.returncode == 0 else None


def untouched_seeds(cfg, repo_dir):
    """[(path, today's render)] for each seed that differs from today's render
    but is, outside its org-sync blocks, what the pinned templates rendered."""
    sha = read_lock(repo_dir)
    if not sha:
        return []
    out = []
    for item in items(cfg):
        if item[0] != "seed":
            continue
        path = item[1]
        cur = read(os.path.join(repo_dir, path))
        if cur is None or os.path.islink(os.path.join(repo_dir, path)):
            continue
        new = fresh_seed(cfg, repo_dir, item, cur)
        if own_text(cur, path) == own_text(new, path):
            continue
        old = pinned_render(repo_dir, cfg["repo"], sha, path)
        if old is not None and own_text(cur, path) == own_text(old, path):
            out.append((path, new))
    return out


def plan(cfg, repo_dir):
    rows = []
    # seeds run before sections so a fresh repo gets the file, then its sections
    for item in items(cfg):
        status, new, detail = evaluate(cfg, repo_dir, item)
        rows.append((item, status, new, detail))
    rows += [(item, "orphan", new, detail) for item, new, detail in orphans(cfg, repo_dir)]
    return rows


def label(item):
    return item[1] + (f"#{item[3]}" if item[3] else "")


def write(repo_dir, path, text):
    full = os.path.join(repo_dir, path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def apply(cfg, repo_dir, force=(), prune=False, reseed=False):
    """Write every change; repeat until stable, since a badge can depend on a
    file a later item creates (at most three passes). An orphan block is removed
    only with `prune`; otherwise it is left and reported, like a conflict. With
    `reseed`, an untouched seed takes today's render first (#615)."""
    changed, conflicts = [], []
    if reseed:
        pin = (read_lock(repo_dir) or "")[:12]
        for path, new in untouched_seeds(cfg, repo_dir):
            write(repo_dir, path, new)
            changed.append(f"{'reseeded':9} {path} (untouched since the pinned templates {pin})")
    for _ in range(3):
        c, conflicts = apply_once(cfg, repo_dir, force)
        if not c:
            break
        changed += [x for x in c if x not in changed]
    for item, _, detail in orphans(cfg, repo_dir):
        if prune:
            # re-read: another orphan in the same file may just have gone
            text = read(os.path.join(repo_dir, item[1]))
            write(repo_dir, item[1], remove_block(text, item[3], item[1]))
            changed.append(f"{'removed':9} {label(item)} (orphan)")
        else:
            conflicts.append(f"orphan    {label(item)}: {detail}")
    return changed, conflicts


def apply_once(cfg, repo_dir, force):
    changed, conflicts = [], []
    for item in items(cfg):
        status, new, detail = evaluate(
            cfg, repo_dir, item
        )  # re-evaluated: a seed may have just created the file
        name = label(item)
        if status == "conflict" and (name in force or "all" in force) and new is not None:
            status = "adopt"
        if status in ("create", "update", "adopt") and new is not None:
            write(repo_dir, item[1], new)
            changed.append(f"{status:9} {name}")
        elif status == "conflict":
            conflicts.append(f"conflict  {name}: {detail}")
    return changed, conflicts


def org_commit():
    """(sha, why): the swarm-routing/.github commit these templates are, or
    (None, why) when it cannot be named: not a git checkout, a feature branch,
    or uncommitted changes to what renders (#586)."""

    def g(*args):
        return subprocess.run(["git", "-C", ORG, *args], capture_output=True, text=True)

    r = g("rev-parse", "HEAD")
    if r.returncode:
        return None, "the templates are not a git checkout"
    sha = r.stdout.strip()
    branch = g("symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    if branch and branch != "main":
        return None, f"the templates are on branch {branch}, not main"
    dirty = g("status", "--porcelain", "--", "templates", "tools/org-sync", "tools/fidelity")
    if dirty.returncode or dirty.stdout.strip():
        return None, "the templates have uncommitted changes"
    return sha, ""


def read_lock(repo_dir):
    """The pinned commit in .github/org-sync.lock, or None."""
    m = LOCK_LINE.search(read(os.path.join(repo_dir, LOCK)) or "")
    return m.group(1) if m else None


def target_pin(cfg, repo_dir, reseed=False):
    """The commit an apply renders the references at, and records in the lock
    (#716): the newest commit that changed what renders (content_pin), from a
    clean `main` or detached checkout; the lock's own commit when that
    renders nothing new and no workflow or action the references name
    changed since, so a commit here that renders nothing new opens no PR
    (#586); the lock's commit, unchanged, from a branch or a dirty tree."""
    old = read_lock(repo_dir)
    sha, _ = org_commit()
    if not sha:
        return old
    new = content_pin(sha)
    if not old or old == new or refs_moved(old, new):
        return new
    keep = dict(cfg, pin=old)
    if any(status != "unchanged" for _, status, _, _ in plan(keep, repo_dir)):
        return new
    if reseed and untouched_seeds(keep, repo_dir):
        return new
    return old


def write_lock(repo_dir, changed, pin=None):
    """Record the template commit (`pin`, else this checkout's) after an apply
    that changed a file, or when the lock is missing; a line for apply's
    output, or None."""
    old = read_lock(repo_dir)
    if not changed and old:
        return None
    sha, why = org_commit()
    if not sha:
        return f"{'kept':9} {LOCK}: {why}" if changed else None
    sha = pin or sha
    if sha == old:
        return None
    write(
        repo_dir,
        LOCK,
        "# The swarm-routing/.github commit this repository's org-managed files were\n"
        "# rendered from (swarm-routing/.github#586): `check / org-sync` checks them\n"
        "# against the templates at this commit. Written by tools/org-sync/org_sync.py\n"
        "# apply (org-bot's refresh PR), never by hand.\n"
        f'commit = "{sha}"\n',
    )
    return f"{'update' if old else 'create':9} {LOCK}"


# --- commands ----------------------------------------------------------------


def cmd_init(a):
    path = os.path.join(a.repo, CONFIG)
    if os.path.exists(path):
        sys.exit(f"org-sync: {CONFIG} exists; use `apply`")
    lines = [f'kind = "{a.kind}"']
    if a.title:
        lines.append(f'title = "{a.title}"')
    if a.dual is not None:
        lines.append("dual = [" + ", ".join(f'"{d}"' for d in a.dual) + "]")
    if a.dockerfile:
        lines.append(f'dockerfile = "{a.dockerfile}"')
    if a.kind not in ("site", "skills"):
        # a new repository has no page on the site until site/hub/projects.json lists it,
        # so its arena badge waits for the id (#96)
        lines += [
            "",
            "[docs]",
            f'arena_id = "{a.arena_id or ""}"'
            + (
                ""
                if a.arena_id
                else "  # its id in swarm-routing.github.io site/hub/projects.json, once listed"
            ),
        ]
    write(
        a.repo,
        CONFIG,
        "# org-sync configuration (swarm-routing/.github tools/org-sync).\n"
        + "\n".join(lines)
        + "\n",
    )
    print(f"created   {CONFIG}")
    return cmd_apply(a)


def cmd_plan(a):
    cfg = load_config(a.repo)
    rows = plan(cfg, a.repo)
    if a.json:
        out, same = [], 0
        for item, status, new, detail in rows:
            if status == "unchanged":
                same += 1
                continue
            r = {"item": label(item), "status": status}
            if new is not None and status in ("update", "adopt", "conflict", "orphan"):
                old = read(os.path.join(a.repo, item[1])) or ""
                d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0))
                r["lines"] = sum(1 for x in d if x[:1] in "+-" and x[:3] not in ("+++", "---"))
            if detail:
                r["detail"] = detail
            out.append(r)
        print(json.dumps({"unchanged": same, "changes": out}, separators=(",", ":")))
    else:
        for item, status, _, detail in rows:
            if status != "unchanged" or a.verbose:
                print(
                    f"{status:9} {label(item)}"
                    + (f": {detail}" if detail and status != "unchanged" else "")
                )
    return 0


def cmd_apply(a):
    cfg = load_config(a.repo)
    reseed = getattr(a, "reseed_untouched", False)
    cfg["pin"] = target_pin(cfg, a.repo, reseed)
    changed, conflicts = apply(
        cfg,
        a.repo,
        set(getattr(a, "force", None) or ()),
        prune=getattr(a, "prune_orphans", False),
        reseed=reseed,
    )
    pinned = write_lock(a.repo, changed, cfg["pin"])
    if pinned:
        changed.append(pinned)
    for line in changed + conflicts:
        print(line)
    if not changed and not conflicts:
        print("org-sync: nothing to do")
    return 1 if conflicts else 0


def cmd_refs(a):
    """swarm-routing/.github's own workflows and actions (#716): every reference
    to itself at `self_pin` of --rev (default HEAD; org-bot runs it on main).
    Inside a reusable workflow a local `./` path names the caller's checkout,
    so these stay full references, pinned. --check changes nothing, exit 1."""
    r = org_git("rev-parse", "--verify", f"{a.rev}^{{commit}}")
    if r.returncode:
        sys.exit(f"org-sync: refs: no commit {a.rev} in {ORG}")
    pin = self_pin(r.stdout.strip())
    drift = 0
    for path in ref_files(a.repo):
        cur = read(os.path.join(a.repo, path))
        new = pin_refs(cur, pin)
        if ref_key(new) == ref_key(cur):
            continue
        drift += 1
        if a.check:
            print(f"drift     {path}: references to swarm-routing/.github not at {pin[:12]}")
        else:
            write(a.repo, path, new)
            print(f"{'update':9} {path}")
    if not drift:
        print(f"org-sync: references at {pin[:12]}")
    return 1 if a.check and drift else 0


def cmd_conflicts(a):
    cfg = load_config(a.repo)
    n = 0
    for item, status, new, detail in plan(cfg, a.repo):
        if status != "conflict":
            continue
        n += 1
        print(f"== {label(item)}: {detail}")
        if new is not None:
            old = read(os.path.join(a.repo, item[1])) or ""
            sys.stdout.writelines(
                line + "\n"
                for line in difflib.unified_diff(
                    old.splitlines(), new.splitlines(), "repo", "org-sync", lineterm="", n=3
                )
            )
    if not n:
        print("org-sync: no conflicts")
    return 0


def pr_changes(repo_dir, base):
    """{path: [(first, last) new-side line ranges]} for what the change since
    `base` touched (`git diff base...HEAD`, no context). A pure deletion is the
    empty range (n+1, n): it sits after new line n. None means the whole file
    (created, deleted or renamed away)."""
    r = subprocess.run(
        [
            "git",
            "-C",
            repo_dir,
            "diff",
            "--no-color",
            "--no-ext-diff",
            "-U0",
            "--no-renames",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            f"{base}...HEAD",
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode:
        sys.exit(f"org-sync: git diff {base}...HEAD failed: {r.stderr.strip()}")
    out, path, old, in_hunk = {}, None, None, False
    for line in r.stdout.splitlines():
        if line.startswith("diff --git "):
            path, in_hunk = None, False
        elif not in_hunk and line.startswith("--- "):
            old = line[4:]
        elif not in_hunk and line.startswith("+++ "):
            new = line[4:]
            if new == "/dev/null":  # deleted: the old path, all of it
                out[old[2:]] = None
            else:
                path = new[2:]
                if old == "/dev/null":
                    out[path] = None
                else:
                    out.setdefault(path, [])
        elif line.startswith("@@"):
            in_hunk = True  # a `--- `/`+++ ` line from here on is content
            if not path or out.get(path) is None:
                continue
            m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
            first, n = int(m.group(1)), int(m.group(2) or 1)
            out[path].append((first, first + n - 1) if n else (first + 1, first))
    return out


def touched(repo_dir, item, changes):
    """Did the change edit this item by hand? A section counts only when a
    changed line (or a deletion) falls between its markers, markers included;
    a file without the markers counts when any of it changed; any other item
    counts when its file changed. A change to the config alone is not a hand
    edit: what it does to an item's render is judged against the base
    (`base_drift`)."""
    kind, path, _, name = item
    if path not in changes:
        return False
    ranges = changes[path]
    if ranges is None or kind not in ("section", "orphan"):
        return True
    cur = read(os.path.join(repo_dir, path)) or ""
    span = find_section(cur, name, path)
    if not span:
        return True
    b = cur.count("\n", 0, span[0])  # 1-based line of the begin marker
    e = cur.count("\n", 0, span[1]) + 1  # 1-based line of the end marker
    return any(
        first <= e and last >= b if first <= last else b < first <= e for first, last in ranges
    )


def git(repo_dir, *args, binary=False):
    r = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=not binary)
    if r.returncode:
        err = r.stderr if not binary else r.stderr.decode(errors="replace")
        sys.exit(f"org-sync: git {' '.join(args)} failed: {err.strip()}")
    return r.stdout


# files outside the managed items that decide what renders (the swarm-core mode
# of the dependencies section, the citing section, badges): the base's tree is
# rendered with them too, or its drift is misjudged as the change's own (#586)
RENDER_INPUTS = (
    "swarm-core.lock",
    "swarm-adapter-ns3.lock",
    "vcpkg.json",
    "core/CMakeLists.txt",
    "CMakeLists.txt",
    "CHANGELOG.md",
    "CITATION.cff",
    "docs/fidelity.md",
    "docs/ns3-bugs.md",
    BIB,
)


def base_drift(repo_dir, base, slug, pin=None):
    """The labels of the items that drift at `base`'s merge base with HEAD,
    judged with the same templates on that commit's own tree (its config, its
    managed files, its .github/ and SECURITY.md, which decide the badges).
    None when the base has no config org-sync manages: every drift is then the
    change's own."""
    rev = git(repo_dir, "merge-base", base, "HEAD").strip()
    with tempfile.TemporaryDirectory(prefix="org-sync-base-") as tmp:
        r = subprocess.run(
            ["git", "-C", repo_dir, "show", f"{rev}:{CONFIG}"], capture_output=True, text=True
        )
        if r.returncode:
            return None
        write(tmp, CONFIG, r.stdout)
        try:
            cfg = load_config(tmp, slug)
        except (SettingsOnly, SystemExit, tomllib.TOMLDecodeError):
            return None
        paths = sorted({i[1] for i in items(cfg)} | {".github", "SECURITY.md"} | set(RENDER_INPUTS))
        names = git(repo_dir, "ls-tree", "-r", "--name-only", rev, "--", *paths).splitlines()
        if names:
            data = git(repo_dir, "archive", "--format=tar", rev, "--", *names, binary=True)
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(tmp, filter="data")
                else:  # Python 3.11 before 3.11.4
                    tar.extractall(tmp)  # our own git objects, filtered by path above
        # the config was read before the tree was there: the mode it reads from the tree
        cfg["swarm_core_mode"] = swarm_core_mode(tmp)
        # the references, judged at the commit HEAD pins (the templates checked against)
        cfg["ref_files"] = ref_files(tmp)
        cfg["pin"] = pin
        return {
            drift_key(item, status)
            for item, status, _, _ in plan(cfg, tmp)
            if status != "unchanged"
        }


def drift_key(item, status):
    """An item's drift as `--changed-only` compares it with the base's: an
    orphan block is not the same drift as the managed section it once was."""
    return ("orphan " if status == "orphan" else "") + label(item)


def cmd_check(a):
    cfg = load_config(a.repo)
    drift = [
        (item, status, detail)
        for item, status, _, detail in plan(cfg, a.repo)
        if status != "unchanged"
    ]
    warned = 0
    if a.changed_only and drift:
        changes = pr_changes(a.repo, a.changed_only)
        before = base_drift(a.repo, a.changed_only, cfg["repo"], cfg["pin"])
        own = []
        for d in drift:
            item, status, detail = d
            if (
                before is None
                or drift_key(item, status) not in before
                or touched(a.repo, item, changes)
            ):
                own.append(d)
            else:
                warned += 1
                print(
                    f"::warning title=org-sync::{label(item)}: {status}"
                    + (f" ({detail})" if detail else "")
                    + f", already drifting at {a.changed_only} (a newer template); "
                    "the org-bot refresh PR, or `org_sync.py apply` on main, fixes it"
                )
        drift = own
    for item, status, detail in drift:
        print(f"drift     {label(item)}: {status}" + (f" ({detail})" if detail else ""))
    if drift:
        print(
            f"org-sync: {len(drift)} item(s) differ from swarm-routing/.github templates; "
            "run `org_sync.py apply` (or `make org-sync-check` to see this again)",
            file=sys.stderr,
        )
        pin = read_lock(a.repo)
        head = subprocess.run(
            ["git", "-C", ORG, "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        if pin and head and head != pin:
            print(
                f"org-sync: these templates are at {head[:12]}, but this repository pins "
                f"{pin[:12]} ({LOCK}), which CI checks against: compare with "
                f"`make org-sync-check ORG_REF={pin}`. Drift against newer templates is "
                "org-bot's refresh PR's to bring in, never a commit on an unrelated PR (#586)",
                file=sys.stderr,
            )
        return 1
    print(
        f"org-sync: no drift of this change's own; {warned} item(s) already drifting at the base"
        if a.changed_only and warned
        else "org-sync: in sync"
    )
    return 0


def cmd_seeds(a):
    cfg = load_config(a.repo)
    rows = seed_report(cfg, a.repo)
    if a.json:
        print(
            json.dumps(
                [{"file": f, "status": st, "lines": n} for f, st, n in rows],
                separators=(",", ":"),
            )
        )
        return 0
    for f, st, n in rows:
        print(f"{st:9} {f}" + (f" ({n} lines)" if st == "differs" else ""))
    if any(st != "same" for _, st, _ in rows):
        print(
            "org-sync: seeds are the repository's own; `org_sync.py reseed FILE` takes today's render"
        )
    return 0


def cmd_reseed(a):
    cfg = load_config(a.repo)
    path = os.path.normpath(a.file).replace(os.sep, "/")
    kinds = sorted({i[0] for i in items(cfg) if i[1] == path})
    if "seed" not in kinds:
        what = f"managed as {'/'.join(kinds)}" if kinds else "not an org-sync item"
        print(f"org-sync: {path} is not a seed ({what}); reseed only re-renders seeds")
        return 2
    # the seed path is the org's, but a symlink in the repo (the file or a parent
    # directory) could still point it outside: never read or write through one
    root = os.path.realpath(a.repo)
    target = os.path.realpath(os.path.join(a.repo, path))
    if os.path.commonpath([root, target]) != root:
        print(f"org-sync: {path} resolves outside the repository ({target}); not reseeded")
        return 2
    item = next(i for i in items(cfg) if i[0] == "seed" and i[1] == path)
    cur = read(os.path.join(a.repo, path))
    new = fresh_seed(cfg, a.repo, item, cur)
    if cur == new:
        print(f"org-sync: {path} already matches the template")
        return 0
    sys.stdout.writelines(
        line + "\n"
        for line in difflib.unified_diff(
            (cur or "").splitlines(), new.splitlines(), "repo", "org-sync", lineterm="", n=3
        )
    )
    write(a.repo, path, new)
    print(f"{'reseeded' if cur is not None else 'created':9} {path}")
    return 0


CITATION = "CITATION.cff"


def references_block(text):
    """(start, end) of CITATION.cff's top-level `references:` block, or None: its
    key line (a one-line flow value such as `[]` included), then every indented
    or list line, with the blank and top-level comment lines between them; it
    ends at the next top-level key, and trailing blank and comment lines stay
    outside."""
    m = re.search(r"^references:[ \t]*(?:\[.*\][ \t]*)?(?:#.*)?$", text, re.M)
    if not m:
        return None
    lines = text[m.end() + 1 :].splitlines(keepends=True) if m.end() < len(text) else []
    end = pos = min(m.end() + 1, len(text))
    for line in lines:
        pos += len(line)
        if not line.strip() or line.startswith("#"):
            continue  # inside the block only when an indented or list line follows
        if line[0] not in " \t-":
            break
        end = pos
    return m.start(), end


def citation_refs(repo_dir):
    """(new CITATION.cff text or None when nothing applies, why): CITATION.cff with
    only its `references:` block rendered from docs/references.bib."""
    path = os.path.join(repo_dir, CITATION)
    root = os.path.realpath(repo_dir)
    if os.path.commonpath([root, os.path.realpath(path)]) != root:
        sys.exit(f"org-sync: {CITATION} resolves outside the repository; not touched")
    cur = read(path)
    if cur is None:
        return None, f"no {CITATION}: nothing to render"
    refs = bib_references(repo_dir)
    if refs is None:
        return None, f"{BIB} is absent or has no entry: {CITATION} left as it is"
    block = cff_references(refs)
    span = references_block(cur)
    if span:
        return cur[: span[0]] + block + cur[span[1] :], None
    if not block:
        return cur, None
    return cur + ("" if cur.endswith("\n") or not cur else "\n") + block, None


def cmd_citation_refs(a):
    new, why = citation_refs(a.repo)
    if new is None:
        print(f"org-sync citation-refs: {why}")
        return 0
    cur = read(os.path.join(a.repo, CITATION))
    if new == cur:
        print(f"org-sync citation-refs: {CITATION} references: up to date with {BIB}")
        return 0
    if a.check:
        sys.stdout.writelines(
            line + "\n"
            for line in difflib.unified_diff(
                cur.splitlines(), new.splitlines(), CITATION, f"{BIB} render", lineterm="", n=1
            )
        )
        print(
            f"org-sync citation-refs: {CITATION} references: drifted from {BIB}; "
            "run `org_sync.py citation-refs REPO` and commit the result"
        )
        return 1
    write(a.repo, CITATION, new)
    print(f"org-sync citation-refs: {CITATION} references: rewritten from {BIB}")
    return 0


def cmd_profile(a):
    path = os.path.join(a.repo, PROFILE)
    cur = read(path)
    if cur is None:
        print(f"org-sync profile: no {PROFILE}")
        return 1
    pat = re.compile(r"(<!-- org-sync:begin badges -->\n).*?(<!-- org-sync:end badges -->)", re.S)
    if not pat.search(cur):
        print(f"org-sync profile: {PROFILE} has no org-sync badges markers")
        return 1
    new = pat.sub(lambda m: m.group(1) + profile_badge_lines() + m.group(2), cur, count=1)
    if new == cur:
        print(f"org-sync profile: {PROFILE} badges up to date")
        return 0
    if a.check:
        print(f"org-sync profile: {PROFILE} badges drifted; run `org_sync.py profile` and commit")
        return 1
    write(a.repo, PROFILE, new)
    print(f"org-sync profile: {PROFILE} badges rewritten")
    return 0


def cmd_settings(a):
    cfg = load_config(a.repo)
    repo = cfg["repo"]

    def gh(path):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if r.returncode:
            return {"error": (r.stderr.strip().splitlines() or ["gh api failed"])[-1]}
        return json.loads(r.stdout or "null")

    meta = gh(f"repos/{repo}")
    pvr = gh(f"repos/{repo}/private-vulnerability-reporting")
    rules = gh(f"repos/{repo}/rulesets")
    want = {
        "private_vulnerability_reporting": True,
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
    }
    have = {
        "private_vulnerability_reporting": pvr.get("enabled") if isinstance(pvr, dict) else None,
        "allow_squash_merge": meta.get("allow_squash_merge"),
        "allow_merge_commit": meta.get("allow_merge_commit"),
        "allow_rebase_merge": meta.get("allow_rebase_merge"),
        "rulesets": len(rules) if isinstance(rules, list) else rules,
    }
    report = {k: {"want": want.get(k), "have": have[k]} for k in have}
    print(
        json.dumps(report, separators=(",", ":"))
        if a.json
        else "\n".join(f"{k:32} have={v['have']} want={v['want']}" for k, v in report.items())
    )
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="org_sync.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in (
        "init",
        "plan",
        "apply",
        "conflicts",
        "check",
        "seeds",
        "reseed",
        "settings",
        "citation-refs",
        "profile",
        "refs",
    ):
        s = sub.add_parser(name)
        if name == "reseed":
            s.add_argument("file", help="the seed to re-render, as `seeds` prints it")
        s.add_argument("repo", nargs="?", default=".")
        if name == "init":
            s.add_argument("--kind", required=True, choices=KINDS)
            s.add_argument("--title")
            s.add_argument(
                "--arena-id",
                help="the project's id in the site's site/hub/projects.json; without it the "
                "arena badge waits until [docs] arena_id is set",
            )
            s.add_argument(
                "--dockerfile",
                help="container kind: the Dockerfile the seeded Makefile builds (default Dockerfile); "
                "the Makefile is seeded once, so set it here or edit DOCKERFILE in the Makefile later",
            )
            s.add_argument(
                "--dual",
                nargs="*",
                help="dual-licensed roots, e.g. core/ tools/ ('' = the whole repo)",
            )
        if name in ("profile", "refs"):
            s.add_argument("--check", action="store_true", help="change nothing; exit 1 on drift")
        if name == "refs":
            s.add_argument(
                "--rev",
                default="HEAD",
                help="the swarm-routing/.github commit whose history picks the pin (default HEAD)",
            )
        if name == "citation-refs":
            s.add_argument(
                "--check",
                action="store_true",
                help="change nothing; exit 1 when the references: block is not the bib's",
            )
        if name == "check":
            s.add_argument(
                "--changed-only",
                metavar="BASE",
                help="fail only on the drift the change since BASE brought in "
                "(`git diff BASE...HEAD`): an item that drifts at HEAD but not at BASE, "
                "or one the change edited by hand; drift already at BASE is a warning",
            )
        if name in ("plan", "seeds", "settings"):
            s.add_argument("--json", action="store_true")
        if name == "plan":
            s.add_argument("-v", "--verbose", action="store_true")
        if name == "apply":
            s.add_argument(
                "--force",
                nargs="+",
                metavar="ITEM",
                help="replace these conflicting sections with the template (ITEM as `plan` prints it, or all)",
            )
            s.add_argument(
                "--prune-orphans",
                action="store_true",
                help="remove org-sync blocks whose section is not one of this repository's items "
                "(skipped, or not enabled); without it they are left and reported",
            )
            s.add_argument(
                "--reseed-untouched",
                action="store_true",
                help="give each seed the repository never edited (its text is still the "
                "render of the templates .github/org-sync.lock pins) today's render; "
                "an edited seed is never written",
            )
    a = p.parse_args(argv)
    try:
        return globals()[f"cmd_{a.cmd.replace('-', '_')}"](a)
    except SettingsOnly:
        if getattr(a, "json", False):
            print(SETTINGS_ONLY_JSON[a.cmd])
        else:
            print(
                f"org-sync: {CONFIG} has [settings] and no kind: settings only, no templates managed"
            )
        return 0


if __name__ == "__main__":
    sys.exit(main())
