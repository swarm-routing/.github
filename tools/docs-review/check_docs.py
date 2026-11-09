#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A repository's README, AI files and docs/ against the org standard.

    check_docs.py [REPO_DIR] [--json]    PASS/WARN/FAIL per check; exit 1 on a FAIL
    check_docs.py --self-test

The standard is AntHocNet's README and docs map (#94): a title and the
org-sync badge row; an explanation near the top; a link to the project's page
on the site (https://swarm-routing.github.io/arena/<id>/), and to the ns-3
image when the repo builds with it; a layout block that matches the tree;
Epics, License and how-to-work-here sections; AGENTS.md with the org's
sections; CLAUDE.md importing it; CONTEXT.md past its seed; a docs/ map
when docs/ holds more than ADRs; no broken relative link. The checks are what
a script can decide; whether the explanation is good is the reviewer's
(the docs-review skill).

A repository tunes it in `.github/org-sync.toml`, all keys optional:

    [docs]
    arena_id = "ARA"        # its id in the site's projects.json (default: the repo name)
    uses_image = true       # links ghcr.io/swarm-routing/ns3-dev (default: protocol/c-cpp kinds)

Stdlib only.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import tomllib

SITE = "https://swarm-routing.github.io/"
IMAGE = ("ghcr.io/swarm-routing/ns3-dev", "swarm-routing/ns3-containers")
AGENTS_HEADINGS = (
    "What this repo is",
    "Build & verify",
    "Golden rules",
    "Conventions",
    "Git workflow",
    "Agent skills",
    "Where to look",
)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
LAYOUT = re.compile(r"^([A-Za-z0-9_.][\w./-]*/)\s{2,}\S")


def read(repo, rel):
    try:
        with open(os.path.join(repo, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def config(repo):
    cfg = {}
    text = read(repo, ".github/org-sync.toml")
    if text:
        cfg = tomllib.loads(text)
    d = cfg.get("docs", {})
    name = os.path.basename(os.path.abspath(repo))
    # the site's ids (site/hub/projects.json) where they differ from the title
    default_id = {".github": "org-commons", "swarm-routing.github.io": ""}.get(
        cfg.get("title", name), cfg.get("title", name)
    )
    return {
        "kind": cfg.get("kind", ""),
        "arena_id": d.get("arena_id", default_id),
        "uses_image": d.get("uses_image", cfg.get("kind") in ("protocol", "c-cpp")),
    }


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, area, msg, items=()):
        self.rows.append({"level": level, "area": area, "msg": msg, "items": list(items)})

    @property
    def fail(self):
        return any(r["level"] == "FAIL" for r in self.rows)

    def text(self):
        out = []
        for r in self.rows:
            out.append(f"{r['level']:5} {r['area']}: {r['msg']}")
            out += [f"        {i}" for i in r["items"][:12]]
            if len(r["items"]) > 12:
                out.append(f"        … and {len(r['items']) - 12} more")
        out.append("----")
        if self.fail:
            out.append("FAIL  fix before the docs PR")
        elif any(r["level"] == "WARN" for r in self.rows):
            out.append("WARN  review the warnings above")
        else:
            out.append("PASS  docs match the org standard")
        return "\n".join(out)


def layout_dirs(text):
    """Directories named in fenced layout blocks, with whether the line says planned
    (or the text declares the whole layout a plan, or the path untracked)."""
    whole_plan = re.search(r"layout below is the plan|is the plan;", text or "") is not None
    out, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        m = LAYOUT.match(line) if fenced else None
        if m:
            low = line.lower()
            out.append(
                (
                    m.group(1),
                    whole_plan or "planned" in low or "(not yet" in low or "not tracked" in low,
                )
            )
    return out


def status(text):
    """The first word of a `**Status: …**` line, lower-cased, without punctuation."""
    m = re.search(r"\*\*Status:\*?\*?\s*([A-Za-z-]+)", text or "")
    return m.group(1).lower() if m else None


def check(repo):
    cfg = config(repo)
    r = Report()
    readme = read(repo, "README.md")
    agents = read(repo, "AGENTS.md")
    claude = read(repo, "CLAUDE.md")
    context = read(repo, "CONTEXT.md")

    # --- README -----------------------------------------------------------------
    if readme is None:
        r.add("FAIL", "README", "no README.md")
    else:
        lines = readme.splitlines()
        if not lines or not lines[0].startswith("# "):
            r.add("FAIL", "README", "the first line is not a `# Title`")
        m = re.search(
            r"<!-- org-sync:begin badges -->\n(.*?)<!-- org-sync:end badges -->", readme, re.S
        )
        if not m or "[![" not in m.group(1):
            r.add("FAIL", "README", "no org-sync badge row (run org_sync.py apply)")
        else:
            r.add("PASS", "README", f"badge row with {m.group(1).count('[![')} badge(s)")
        after = readme[m.end() :] if m else readme
        prose = [
            p
            for p in re.split(r"\n\s*\n", "\n".join(after.splitlines()[:30]))
            if p.strip() and not p.lstrip().startswith(("#", "```", "![", "<!--", "|", ">"))
        ]
        if not any(len(re.findall(r"[.!?](\s|$)", p)) >= 2 for p in prose):
            r.add("WARN", "README", "no explanation (a paragraph of 2+ sentences) near the top")
        arena = f"{SITE}arena/{cfg['arena_id']}/" if cfg["arena_id"] else SITE
        game = f"{SITE}{cfg['arena_id']}/"
        if arena in readme or (cfg["arena_id"] and game in readme):
            r.add("PASS", "README", "links its page on the site")
        else:
            r.add("WARN", "README", f"no link to its page on the site: {arena}")
        if cfg["uses_image"]:
            if any(i in readme for i in IMAGE):
                r.add("PASS", "README", "links the ns-3 image")
            else:
                r.add(
                    "WARN",
                    "README",
                    "builds with the org's ns-3 image but does not link it",
                    IMAGE[:1],
                )
        heads = [h.strip().lower() for h in re.findall(r"^#{2,3}\s+(.+)$", readme, re.M)]
        missing = []
        if not any(h.startswith("epics") for h in heads):
            missing.append("## Epics (epics.py readme)")
        if "LICENSING.md" not in readme and not any("licen" in h for h in heads):
            missing.append("a licence section linking LICENSING.md")
        if "AGENTS.md" not in readme and "CONTRIBUTING" not in readme:
            missing.append("how to work here (a link to AGENTS.md or CONTRIBUTING.md)")
        if missing:
            r.add("WARN", "README", "missing", missing)
        bad = [
            d
            for d, planned in layout_dirs(readme)
            if not planned and not os.path.isdir(os.path.join(repo, d))
        ]
        if bad:
            r.add(
                "WARN",
                "README",
                "layout names directories that do not exist (mark them planned)",
                bad,
            )
        s_readme, s_agents = status(readme), status(agents)
        if s_readme and s_agents and s_readme != s_agents:
            r.add("WARN", "README", f"status `{s_readme}` disagrees with AGENTS.md `{s_agents}`")

    # --- AI files ------------------------------------------------------------------
    if agents is None:
        r.add("FAIL", "AGENTS.md", "missing")
    else:
        heads = re.findall(r"^##\s+(.+)$", agents, re.M)
        lack = [h for h in AGENTS_HEADINGS if not any(x.strip().startswith(h) for x in heads)]
        if lack:
            r.add("FAIL", "AGENTS.md", "missing the org's sections", lack)
        else:
            r.add("PASS", "AGENTS.md", "has the org's sections")
        bad = [
            d
            for d, planned in layout_dirs(agents)
            if not planned and not os.path.isdir(os.path.join(repo, d))
        ]
        if bad:
            r.add(
                "WARN",
                "AGENTS.md",
                "layout names directories that do not exist (mark them planned)",
                bad,
            )
    if claude is None or "@AGENTS.md" not in claude:
        r.add("FAIL", "CLAUDE.md", "does not import @AGENTS.md")
    has_work = any(
        os.path.isdir(os.path.join(repo, d))
        for d in ("core", "ns3", "model", "python", "site", "docker", "tools", "skills", "runs")
    )
    if context and "Describe the repository here" in context and has_work:
        r.add("WARN", "CONTEXT.md", "still the seed placeholder although the repo has content")

    # --- docs/ ------------------------------------------------------------------
    docs = os.path.join(repo, "docs")
    pages = []
    if os.path.isdir(docs):
        for root, _, files in os.walk(docs):
            for f in files:
                if f.endswith(".md"):
                    pages.append(os.path.relpath(os.path.join(root, f), repo))
    non_adr = [p for p in pages if not p.startswith("docs/adr/")]
    docs_map = read(repo, "docs/README.md")
    if len([p for p in non_adr if p != "docs/README.md"]) > 1 and docs_map is None:
        r.add("WARN", "docs/", "more than one page and no docs/README.md map")
    linked = (docs_map or "") + (readme or "") + (agents or "")
    orphans = [
        p
        for p in non_adr
        if p != "docs/README.md"
        and os.path.basename(p) not in linked
        and p.removeprefix("docs/") not in linked
        and "/" not in p.removeprefix("docs/")
    ]
    if orphans:
        r.add(
            "WARN",
            "docs/",
            "pages linked from neither docs/README.md, README.md nor AGENTS.md",
            orphans,
        )
    adr_index = read(repo, "docs/adr/README.md")
    adrs = sorted(
        os.path.basename(p) for p in pages if re.match(r"docs/adr/\d{4}-", p) and "0000-" not in p
    )
    if adr_index is not None:
        lack = [a for a in adrs if a not in adr_index]
        if lack:
            r.add("WARN", "docs/adr", "ADRs missing from docs/adr/README.md", lack)

    # --- relative links -----------------------------------------------------------
    broken = []
    # the ADR template's links are placeholders (NNNN-title.md)
    for rel in [
        "README.md",
        "AGENTS.md",
        "CONTEXT.md",
        *(p for p in pages if not p.endswith("0000-template.md")),
    ]:
        text = read(repo, rel)
        if not text:
            continue
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        # the badge row is checked on its own; its nested image links are URLs
        text = re.sub(
            r"<!-- org-sync:begin badges -->.*?<!-- org-sync:end badges -->", "", text, flags=re.S
        )
        for target in LINK.findall(text):
            if re.match(r"^[a-z]+:|^#|^mailto:", target):
                continue
            path = target.split("#")[0]
            if not path:
                continue
            full = os.path.normpath(os.path.join(repo, os.path.dirname(rel), path))
            if not os.path.exists(full):
                broken.append(f"{rel}: {target}")
    if broken:
        r.add("FAIL", "links", "relative links to missing files", broken)
    else:
        r.add("PASS", "links", "every relative link resolves")
    return r


# --- self-test -------------------------------------------------------------------------


def self_test():
    failures = []

    def expect(name, cond):
        if not cond:
            failures.append(name)

    agents_ok = "# AGENTS.md\n\n" + "".join(f"## {h}\n\ntext\n\n" for h in AGENTS_HEADINGS)
    agents_ok = agents_ok.replace(
        "## What this repo is\n\ntext",
        "## What this repo is\n\n**Status: building.**\n\n```\ncore/   the core\nns3/   (planned) module\n```",
    )
    readme_ok = (
        "# ARA\n\n<!-- org-sync:begin badges -->\n[![CI](https://x/b.svg)](https://x/a)\n<!-- org-sync:end badges -->\n\n"
        "ARA is an ant-colony routing protocol for MANETs. It runs on ns-3 and in the browser. "
        "**Status: building.**\n\n"
        "See [its space](https://swarm-routing.github.io/arena/ARA/), the image "
        "`ghcr.io/swarm-routing/ns3-dev` and [AGENTS.md](AGENTS.md)\n\n"
        "```\ncore/   the core\n```\n\n## Epics\n\nx\n\n## License\n\n[LICENSING.md](LICENSING.md)\n"
    )
    base = {
        "README.md": readme_ok,
        "AGENTS.md": agents_ok,
        "CLAUDE.md": "@AGENTS.md\n",
        "CONTEXT.md": "# CONTEXT\n\n## Current state\n\nBuilding.\n",
        "LICENSING.md": "x\n",
        ".github/org-sync.toml": 'kind = "protocol"\ntitle = "ARA"\n',
        "core/a.cc": "x\n",
        "docs/README.md": "# Map\n\n[fidelity](fidelity.md)\n",
        "docs/fidelity.md": "# F\n",
        "docs/adr/README.md": "| [0001](0001-x.md) | x |\n",
        "docs/adr/0001-x.md": "# x\n",
    }

    def repo(changes=None, drop=()):
        d = tempfile.mkdtemp()
        files = {**base, **(changes or {})}
        for p, t in files.items():
            if p in drop:
                continue
            os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
            with open(os.path.join(d, p), "w") as f:
                f.write(t)
        return check(d)

    def has(rep, level, needle):
        return any(x["level"] == level and needle in x["msg"] for x in rep.rows)

    ok = repo()
    expect(
        "a standard repo passes clean",
        not ok.fail and not any(x["level"] == "WARN" for x in ok.rows),
    )
    r = repo(
        {
            "README.md": readme_ok.replace(
                "<!-- org-sync:begin badges -->\n[![CI](https://x/b.svg)](https://x/a)\n<!-- org-sync:end badges -->\n",
                "",
            )
        }
    )
    expect("no badge row fails", has(r, "FAIL", "badge row"))
    r = repo(
        {
            "README.md": readme_ok.replace(
                "ARA is an ant-colony routing protocol for MANETs. It runs on ns-3 and in the browser. ",
                "",
            )
        }
    )
    expect("no explanation warns", has(r, "WARN", "no explanation"))
    r = repo(
        {
            "README.md": readme_ok.replace(
                "https://swarm-routing.github.io/arena/ARA/", "https://example.org"
            )
        }
    )
    expect("no site link warns", has(r, "WARN", "page on the site"))
    r = repo({"README.md": readme_ok.replace("`ghcr.io/swarm-routing/ns3-dev`", "the image")})
    expect("a protocol repo without the image link warns", has(r, "WARN", "ns-3 image"))
    r = repo(
        {
            ".github/org-sync.toml": 'kind = "data"\ntitle = "ARA"\n',
            "README.md": readme_ok.replace("`ghcr.io/swarm-routing/ns3-dev`", "x"),
        }
    )
    expect("a data repo needs no image link", not has(r, "WARN", "ns-3 image"))
    r = repo(
        {"README.md": readme_ok.replace("core/   the core", "core/   the core\nweb/   the site")}
    )
    expect("a layout dir that does not exist warns", has(r, "WARN", "layout names"))
    r = repo({"AGENTS.md": agents_ok.replace("ns3/   (planned) module", "ns3/   module")})
    expect("an unmarked missing AGENTS layout dir warns", has(r, "WARN", "layout names"))
    expect("…and a planned one does not (base)", not has(ok, "WARN", "layout names"))
    r = repo({"README.md": readme_ok.replace("## Epics\n\nx\n\n", "")})
    expect("a missing Epics section warns", has(r, "WARN", "missing"))
    r = repo({"README.md": readme_ok.replace("**Status: building.**", "**Status: empty.**")})
    expect("a status that disagrees with AGENTS.md warns", has(r, "WARN", "disagrees"))
    r = repo({"AGENTS.md": agents_ok.replace("## Agent skills", "## Skills")})
    expect("a missing AGENTS section fails", has(r, "FAIL", "org's sections"))
    r = repo({"CLAUDE.md": "nothing\n"})
    expect("CLAUDE.md without @AGENTS.md fails", has(r, "FAIL", "@AGENTS.md"))
    r = repo({"CONTEXT.md": "**Status: empty.** Describe the repository here.\n"})
    expect("a seed CONTEXT.md in a repo with code warns", has(r, "WARN", "seed placeholder"))
    r = repo({"docs/extra.md": "# E\n"})
    expect("an orphan docs page warns", has(r, "WARN", "linked from neither"))
    r = repo({"docs/second.md": "# S\n"}, drop=("docs/README.md",))
    expect("two docs pages and no map warns", has(r, "WARN", "no docs/README.md"))
    r = repo({"docs/adr/0002-y.md": "# y\n"})
    expect("an ADR missing from the index warns", has(r, "WARN", "missing from docs/adr"))
    r = repo({"README.md": readme_ok + "\n[gone](docs/gone.md)\n"})
    expect("a broken relative link fails", has(r, "FAIL", "relative links"))
    r = repo({"README.md": readme_ok + "\n```\n[not a link](nowhere.md)\n```\n"})
    expect("a link inside a code block is ignored", not has(r, "FAIL", "relative links"))

    r = repo(
        {
            "AGENTS.md": agents_ok.replace("ns3/   (planned) module", "ns3/   module").replace(
                "**Status: building.**", "**Status: building.** The layout below is the plan."
            )
        }
    )
    expect("a layout the text calls the plan does not warn", not has(r, "WARN", "layout names"))
    r = repo(
        {
            "AGENTS.md": agents_ok.replace(
                "ns3/   (planned) module", "web/   (not tracked) fetched by CI"
            )
        }
    )
    expect("an untracked layout dir does not warn", not has(r, "WARN", "layout names"))
    r = repo(
        {"README.md": readme_ok.replace("**Status: building.**", "**Status: building;** more soon")}
    )
    expect("status punctuation does not count as a disagreement", not has(r, "WARN", "disagrees"))
    r = repo({"docs/adr/0000-template.md": "Name it [NNNN-title.md](NNNN-title.md)\n"})
    expect("the ADR template's placeholder link is ignored", not has(r, "FAIL", "relative links"))

    for f in failures:
        print(f"FAIL: {f}")
    print(f"check_docs self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    rep = check(a.repo)
    print(json.dumps(rep.rows, indent=1) if a.json else rep.text())
    return 1 if rep.fail else 0


if __name__ == "__main__":
    sys.exit(main())
