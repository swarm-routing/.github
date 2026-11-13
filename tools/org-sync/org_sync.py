#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Apply the swarm-routing org templates to a repository, and check for drift.

Usage: org_sync.py {init,plan,apply,conflicts,check,seeds,settings} [REPO_DIR] [options]
       org_sync.py reseed FILE [REPO_DIR]

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
           over that one seed, and refuses any file that is not a seed
  json     only the named keys of a JSON file are the org's
  targets  a Makefile that is the repository's own, checked only for the
           org's standard target names (swarm-routing/.github#11)

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
bib as a seed: a commented header, no entry (#308).

Issue forms (`forms = true`): a repository with its own
`.github/ISSUE_TEMPLATE/` loses the org's default forms, so it keeps a copy.
With the opt-in each org form (every `ISSUE_TEMPLATE/*.yml` here but
`config.yml`) is a whole file there; `config.yml` and the repository's own
forms stay its own, and a changed org form is drift (#318).

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
KINDS = ("protocol", "c-cpp", "python", "container", "data", "site", "skills")
CXX_KINDS = ("protocol", "c-cpp")
MAKE_TARGETS = ("help", "build", "test", "lint", "format", "check", "clean", "shell", "ci")
BEGIN = "<!-- org-sync:begin {} -->"
END = "<!-- org-sync:end {} -->"
YAML_BEGIN = "# org-sync:begin {}"
YAML_END = "# org-sync:end {}"


def markers(path):
    """The (begin, end) marker formats for a managed section in this file."""
    if path.endswith((".yaml", ".yml")) or os.path.basename(path) == "CODEOWNERS":
        return YAML_BEGIN, YAML_END
    return BEGIN, END


# Badges per kind (swarm-routing/.github#8). Each appears only when its target
# exists (see badge_lines): `release` when a workflow calls reusable-release.yml,
# `doi` when the config names its `zenodo_concept` (read from Zenodo, never
# typed: the concept exists only after the first release is archived), `cite`
# when the repository has a CITATION.cff (`citation = true` seeds one);
# `scorecard` (OpenSSF Scorecard, #23) only where
# .github/workflows/scorecard.yml runs it, so a private repository, which skips
# that workflow (`skip = [".github/workflows/scorecard.yml"]`), never gets one.
# `sonar` is the four SonarQube Cloud badges (quality gate, bugs, security,
# maintainability); `sonar-gate`, `sonar-bugs`,
# `sonar-security` and `sonar-maintainability` pick one.
SONAR_METRICS = {
    "sonar-gate": ("Quality Gate Status", "alert_status"),
    "sonar-bugs": ("Bugs", "bugs"),
    "sonar-security": ("Security Rating", "security_rating"),
    "sonar-maintainability": ("Maintainability Rating", "sqale_rating"),
}
BASE_BADGES = ["ci", "release", "doi", "cite", "licence", "conventional", "arena", "scorecard"]
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
}
# Sections with nothing to adopt: inserted after the first match of the regex.
INSERT_AFTER = {
    ("README.md", "badges"): r"^# .*\n",
    # Releases & citing: before the first of Contributing, Epics or Licence
    ("README.md", "citing"): r"\n(?=\n?## (?:Contributing|Epics|Licen[cs]e)\b)",
    # new in every AGENTS.md: placed before the repository's own table
    # (with or without a blank line before the heading)
    ("AGENTS.md", "skills"): r"\n(?=\n?## Where to look\n)",
    # after the skills block, before the repository's own table (#277: what
    # CLAUDE.md held, so CLAUDE.md is only `@AGENTS.md`)
    ("AGENTS.md", "agent-defaults"): r"\n(?=\n?## Where to look\n)",
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


def template(name):
    return read(os.path.join(TEMPLATES, name))


def shield(label, message, color):
    def esc(s):
        return quote(s.replace("-", "--").replace("_", "__"), safe="")

    return f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{color}"


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


class SettingsOnly(Exception):
    """The config has `[settings]` and no `kind`: no templates are managed."""


# what each --json command prints for a settings-only config
SETTINGS_ONLY_JSON = {"plan": '{"unchanged":0,"changes":[]}', "seeds": "[]", "settings": "{}"}


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
    cfg["references"] = check_references(cfg.get("references", []))
    if cfg["references"] and bib_references(repo_dir) is not None:
        print(
            f"org-sync: warning: {BIB} gives the references (its implemented, tool and dataset "
            f"entries); [[references]] in {CONFIG} is now redundant: remove it",
            file=sys.stderr,
        )
    return cfg


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
        role = next((r for r in bib.roles(e) if r in BIB_ROLES), None)
        if role is None:
            continue
        f, where = e["fields"], f"org-sync: {BIB}: line {e['line']}: {e['key']}"
        for key in ("title", "author", "year"):
            if not bib.plain(f.get(key, "")):
                sys.exit(f"{where}: needs {key} to be cited (role {role})")
        year = bib.plain(f["year"])
        if not year.isdigit():
            sys.exit(f"{where}: year is a number")
        kind, venue = BIB_TYPES[e["type"]]
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
            " built by the org's release workflow and archived on [Zenodo](https://zenodo.org)"
            " with its own DOI.",
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
    else:
        out += [
            cite + ". It has no DOI yet: the concept DOI appears here and in the badge above"
            " once Zenodo archives its first release.",
        ]
    refs = references(cfg, repo_dir)
    if refs:
        out += ["", "Please also cite the work it builds on:", ""]
        out += [reference_line(r) for r in refs]
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
    """True when a workflow of the repository calls this reusable workflow."""
    wfdir = os.path.join(repo_dir, ".github/workflows")
    try:
        names = sorted(os.listdir(wfdir))
    except OSError:
        return False
    return any(reusable in (read(os.path.join(wfdir, n)) or "") for n in names)


def uploads_coverage(cfg, repo_dir):
    """True when a workflow of the repository sends coverage to Codecov (the
    reusable-codecov.yml job), so the badge never reads `unknown`."""
    return calls_workflow(repo_dir, "reusable-codecov.yml")


def zenodo_concept(cfg):
    """The Zenodo concept record id from `zenodo_concept`, digits only, else ''."""
    c = str(cfg.get("zenodo_concept", "")).strip()
    return c if c.isdigit() else ""


def check_runs_badge(repo, label, job, logo):
    """A live badge for one job's check run on main (shields.io check-runs)."""
    q = f"nameFilter={quote(job)}&label={quote(label)}&logo={logo}"
    return f"https://img.shields.io/github/check-runs/{repo}/main?{q}"


def badge_lines(cfg, repo_dir):
    repo, out = cfg["repo"], []
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
                out.append(f"[![CI]({url}/badge.svg)]({url})")
        elif b == "release" and calls_workflow(repo_dir, "reusable-release.yml"):
            out.append(
                f"[![Release](https://img.shields.io/github/v/release/{repo}?sort=semver&cacheSeconds=1800)]"
                f"(https://github.com/{repo}/releases)"
            )
        elif b == "doi" and zenodo_concept(cfg):
            doi = f"10.5281/zenodo.{zenodo_concept(cfg)}"
            out.append(f"[![DOI](https://zenodo.org/badge/DOI/{doi}.svg)](https://doi.org/{doi})")
        elif b == "cite" and os.path.exists(os.path.join(repo_dir, "CITATION.cff")):
            out.append(
                "[![Cite](https://img.shields.io/badge/cite-CITATION.cff-blue)](CITATION.cff)"
            )
        elif b == "licence":
            out.append(
                f"[![Licence: {licence_text(cfg)}]({shield('licence', licence_text(cfg), 'blue')})](LICENSING.md)"
            )
        elif b == "conventional":
            out.append(
                f"[![Conventional Commits]({shield('Conventional Commits', '1.0.0', 'yellow')})]"
                "(https://www.conventionalcommits.org)"
            )
        elif b == "cxx":
            cxx = cfg.get("cxx", "20")
            out.append(
                f"[![C++{cxx}]({shield('C++', str(cxx), 'blue')}?logo=cplusplus)](AGENTS.md)"
            )
        elif b == "ns3":
            out.append(
                f"[![Runs on ns-3]({shield('runs on', 'ns-3', 'informational')})](https://www.nsnam.org)"
            )
        elif b == "python":
            py = cfg.get("python", "3.10")
            out.append(
                f"[![Python {py}+]({shield('python', py + '+', 'blue')}?logo=python)](AGENTS.md)"
            )
        elif b == "ghcr" and cfg.get("image"):
            owner, name = repo.split("/")[0], cfg["image"]
            out.append(
                f"[![GHCR: {name}]({shield('ghcr.io', f'{owner}/{name}', 'blue')}?logo=docker)]"
                f"(https://github.com/orgs/{owner}/packages/container/package/{name})"
            )
        elif b == "cosign" and os.path.exists(os.path.join(repo_dir, "SECURITY.md")):
            out.append(
                f"[![Images signed: cosign]({shield('images signed', 'cosign', 'success')})]"
                "(SECURITY.md#verifying-what-it-ships)"
            )
        elif b == "docs" and cfg.get("docs_url"):
            out.append(f"[![Docs]({shield('docs', 'site', 'blue')})]({cfg['docs_url']})")
        elif b == "arena" and arena_id(cfg):
            # the project's page on the org site (Colony Arena), as in site/hub/projects.json
            url = f"https://swarm-routing.github.io/arena/{arena_id(cfg)}/"
            out.append(
                f"[![Colony Arena: {arena_id(cfg)}]({shield('Colony Arena', 'project page', 'orange')})]({url})"
            )
        elif b == "ns3dev":
            out.append(
                f"[![Built on: ns3-dev]({shield('built on', 'ns3-dev image', 'blue')}?logo=docker)]"
                "(https://github.com/orgs/swarm-routing/packages/container/package/ns3-dev)"
            )
        elif b in SONAR_METRICS:
            alt, metric = SONAR_METRICS[b]
            key = sonar_key(cfg)
            out.append(
                f"[![{alt}](https://sonarcloud.io/api/project_badges/measure?project={key}&metric={metric})]"
                f"(https://sonarcloud.io/summary/new_code?id={key})"
            )
        elif b == "codecov" and uploads_coverage(cfg, repo_dir):
            out.append(
                f"[![codecov](https://codecov.io/gh/{repo}/graph/badge.svg)](https://codecov.io/gh/{repo})"
            )
        elif b == "coderabbit":
            camp = quote(repo, safe="")
            out.append(
                f"[![CodeRabbit Pull Request Reviews](https://img.shields.io/coderabbit/prs/github/{repo}"
                f"?utm_source=oss&utm_medium=github&utm_campaign={camp}&labelColor=171717&color=FF570A"
                "&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit+Reviews)](https://coderabbit.ai)"
            )
        elif b == "container-security" and os.path.exists(
            os.path.join(repo_dir, ".github/workflows/container-security.yml")
        ):
            url = f"https://github.com/{repo}/actions/workflows/container-security.yml"
            out.append(f"[![Container Security (Hadolint & Trivy)]({url}/badge.svg)]({url})")
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
            out.append(f"[![{b.capitalize()}]({img})]({link})")
        elif b == "scorecard" and os.path.exists(
            os.path.join(repo_dir, ".github/workflows/scorecard.yml")
        ):
            # the score the workflow publishes to the public OpenSSF API
            out.append(
                f"[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/{repo}/badge)]"
                f"(https://scorecard.dev/viewer/?uri=github.com/{repo})"
            )
        elif b == "claude-plugin":
            out.append(
                f"[![Claude Code plugins]({shield('Claude Code', 'plugin marketplace', 'blueviolet')})]"
                "(https://docs.claude.com/en/docs/claude-code/plugin-marketplaces)"
            )
    return "\n".join(out) + "\n" if out else ""


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
    """check-headers.py flags from the repo's dual roots (the same list
    LICENSING.md is rendered from); a dual `core/` also gets the include check."""
    roots = [dual_root(d) for d in cfg["dual"]]
    args = [f"--dual {d}" if d else "--dual ''" for d in roots]
    if "" in roots or "core/" in roots:
        args.append("--core core/")
    return " ".join(args)


def dual_root(d):
    """A Git-relative directory prefix, as check-headers.py compares it:
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
    # slash would make check-headers.py's prefix test never match it
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
        ("file", "docs/adr/0000-template.md", "adr/0000-template.md", None),
        ("seed", "docs/adr/README.md", "adr/README.md", None),
        (
            "seed",
            "docs/adr/0001-record-architecture-decisions.md",
            "adr/0001-record-architecture-decisions.md",
            None,
        ),
        ("seed", "Makefile", "make/Makefile.in", None),
        ("targets", "Makefile", None, "targets"),
        ("file", ".github/workflows/org-sync.yml", "workflows/org-sync.yml", None),
        ("file", ".github/workflows/dco.yml", "workflows/dco.yml", None),
        ("file", ".github/workflows/review-gate.yml", "workflows/review-gate.yml", None),
        ("file", ".github/workflows/scorecard.yml", "workflows/scorecard.yml", None),
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
    ]
    if cfg["dual"]:
        out.insert(12, ("seed", "LICENSE-MIT", "LICENSE-MIT.in", None))
    if cfg["kind"] in CXX_KINDS:
        # Codecov and SonarQube Cloud settings for reusable-codecov.yml and the
        # reusable ns-3 CI's `sonar` input; the repository's own once written.
        # `[quality] sonar = false`: the repo has no SonarQube Cloud project.
        out.append(("seed", ".codecov.yml", "quality/codecov.yml", None))
        if cfg.get("quality", {}).get("sonar", True):
            out.append(
                ("seed", "sonar-project.properties", "quality/sonar-project.properties.in", None)
            )
    if cfg.get("citation"):
        # opt-in: citation metadata for a repository that releases (Zenodo, cite badge)
        out.append(("seed", "CITATION.cff", "CITATION.cff.in", None))
        out.append(("section", "README.md", None, "citing"))
    if cfg.get("forms"):
        # opt-in for a repository with its own .github/ISSUE_TEMPLATE/, which
        # hides the org's default forms: each org form is a whole file there;
        # config.yml and the repository's own forms stay its own (#318)
        for name in sorted(os.listdir(os.path.join(ORG, "ISSUE_TEMPLATE"))):
            if name.endswith(".yml") and name != "config.yml":
                out.append(
                    ("file", f".github/ISSUE_TEMPLATE/{name}", f"../ISSUE_TEMPLATE/{name}", None)
                )
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


def adopt_span(text, path, name):
    rule = ADOPT.get((path, name))
    if not rule:
        return None
    m = re.search(rule[0], text, re.M)
    if not m:
        return None
    n = re.search(rule[1], text[m.start() + 1 :], re.M)
    end = m.start() + 1 + n.start() if n else len(text)
    return m.start(), end


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
    if kind == "seed":
        if path == "Makefile":
            want = render_makefile(cfg)
        elif path == "CITATION.cff":
            want = render_citation(cfg, repo_dir)
        else:
            want = want.format_map(v or values(cfg))
    return want


def evaluate(cfg, repo_dir, item):
    """Return (status, new_text_or_None, detail). status: create, update,
    unchanged, adopt, conflict, missing."""
    kind, path, src, name = item
    full = os.path.join(repo_dir, path)
    cur = read(full)
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
        if cur == want:
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
    span = adopt_span(cur, path, name)
    ins = INSERT_AFTER.get((path, name))
    if not span and ins and (m := re.search(ins, cur, re.M)):
        return (
            "adopt",
            cur[: m.end()] + "\n" + wrap(name, want, path) + "\n" + cur[m.end() :],
            "inserted",
        )
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


def apply(cfg, repo_dir, force=(), prune=False):
    """Write every change; repeat until stable, since a badge can depend on a
    file a later item creates (at most three passes). An orphan block is removed
    only with `prune`; otherwise it is left and reported, like a conflict."""
    changed, conflicts = [], []
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
    changed, conflicts = apply(
        cfg,
        a.repo,
        set(getattr(a, "force", None) or ()),
        prune=getattr(a, "prune_orphans", False),
    )
    for line in changed + conflicts:
        print(line)
    if not changed and not conflicts:
        print("org-sync: nothing to do")
    return 1 if conflicts else 0


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


def base_drift(repo_dir, base, slug):
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
        paths = sorted({i[1] for i in items(cfg)} | {".github", "SECURITY.md"})
        names = git(repo_dir, "ls-tree", "-r", "--name-only", rev, "--", *paths).splitlines()
        if names:
            data = git(repo_dir, "archive", "--format=tar", rev, "--", *names, binary=True)
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(tmp, filter="data")
                else:  # Python 3.11 before 3.11.4
                    tar.extractall(tmp)  # our own git objects, filtered by path above
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
        before = base_drift(a.repo, a.changed_only, cfg["repo"])
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
    for name in ("init", "plan", "apply", "conflicts", "check", "seeds", "reseed", "settings"):
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
    a = p.parse_args(argv)
    try:
        return globals()[f"cmd_{a.cmd}"](a)
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
