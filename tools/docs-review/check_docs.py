#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A repository's README, AI files and docs/ against the org standard.

    check_docs.py [REPO_DIR] [--json] [--online]   PASS/WARN/FAIL per check; exit 1 on a FAIL
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

The AI-files pass (#142) also checks the facts that AGENTS.md, CLAUDE.md and
CONTEXT.md state, outside the org-sync managed sections; each finding is a
WARN, so a stale fact never blocks CI:

    (a) a repo-relative path in backticks (or a CLAUDE.md link) exists, unless
        its line says planned or it names another repository's file;
    (b) a path marked planned that exists is stale;
    (c) --online: an issue written as open or blocking ("open #N", "blocked by",
        "until #N", "waits on", "Depends on", "exception (#N", "when #N closes",
        "#N (open)") is still open (`gh api`);
    (d) no hand-written rule contradicts an org rule (CONTRADICTIONS, each
        with its source);
    (e) a check called required is in `[settings] required_checks` or is a
        workflow job.

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
import subprocess
import sys
import tempfile
import tomllib

SITE = "https://swarm-routing.github.io/"
IMAGE = (
    "ghcr.io/swarm-routing/ns3-dev",
    "packages/container/package/ns3-dev",
    "swarm-routing/ns3-containers",
)
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
    # (as org-sync's arena badge: the skills repo has no page; the site is the site)
    default_id = {".github": "org-commons", "swarm-routing.github.io": ""}.get(
        cfg.get("title", name), cfg.get("title", name)
    )
    if cfg.get("kind") == "skills":
        default_id = None
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


def check(repo, online=False, fetch=None):
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
        if cfg["arena_id"] is None:
            pass  # no project page on the site (the skills repo)
        elif arena in readme or (cfg["arena_id"] and game in readme):
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
    check_ai_facts(repo, r, online, fetch)
    return r


# --- AI files: their facts against the repository (#142) ------------------------

AI_FILES = ("AGENTS.md", "CLAUDE.md", "CONTEXT.md")
MANAGED = re.compile(r"<!-- org-sync:begin (\S+) -->.*?<!-- org-sync:end \1 -->", re.S)
TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates")
# the org's repositories: a path next to another one's name is that repository's
ORG_REPOS = (
    "AntHocNet",
    "ARA",
    "BeeAdHoc",
    "HOPNET",
    "Termite",
    "benchmarks",
    "ns3-containers",
    "ns3-swarm-core",
    "ns3-tools",
    "papers",
    "skills",
    "swarm-routing.github.io",
    ".github",
)
FOREIGN = re.compile(
    r"\b(?:swarm-routing|danieljoppi)/|\bns-3(?:'s|-dev)?\b|"
    r"\b(?:that|each|every|a|the|its|another) (?:site |protocol |other )?(?:repo|repository|protocol)'s"
    r"|\bthe site's\b|\b(?:"
    + "|".join(re.escape(r) for r in ORG_REPOS if not r.startswith("."))
    + r")\b"
)
# top-level directories a repo path may start with even when the directory is gone
KNOWN_TOP = {
    ".github",
    ".claude",
    "core",
    "ns3",
    "tools",
    "docs",
    "site",
    "python",
    "docker",
    "skills",
    "templates",
}
PLANNED_MARK = re.compile(r"\(planned|planned\)|\bplanned:", re.I)
NEGATED = re.compile(r"\b(?:no|never|not|cannot|can't|nothing)\b", re.I)
PLANNED = re.compile(r"planned|not yet|not tracked|will be|once \S+ exists|\(future", re.I)
# an issue reference written as open or blocking: right after one of these words
# (a list of references may sit between), or followed by "(open)" / "is open".
# The list is stripped token by token (opened_before), not by one regex: a
# repeated group over references backtracks exponentially (CodeQL).
OPEN_WORD = re.compile(
    r"(?:\bblocked (?:by|on)|\buntil|\bwaits? (?:on|for)|\bwaiting (?:on|for)|\bdepends on:?"
    r"|\bopen:?|\bgated (?:by|on)|\bexception|\bwhen)$",
    re.I,
)
LIST_SEP = re.compile(r"([\s,/*(]+)")
LIST_TOKEN = re.compile(
    r"#\d+|[\w.-]+#\d+|and|or|"
    + "|".join(re.escape(r) for r in ORG_REPOS if not r.startswith(".")),
    re.I,
)
# issue states are read only from the org's public repositories
PRIVATE_REPOS = {"papers"}
SLUG = re.compile(r"^swarm-routing/[A-Za-z0-9_][\w-]*(?:\.[\w-]+)*$")
OPEN_AFTER = re.compile(
    r"^[\s)*]*(?:\(open\)|(?:is|stays|remains|still) open\b|(?:closes|is closed|is fixed|lands)\b)",
    re.I,
)
ISSUE_REF = re.compile(
    r"(?:\b(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#|\b(?P<name>"
    + "|".join(re.escape(r) for r in ORG_REPOS if not r.startswith("."))
    + r")\s?#|(?<![\w/&])#)(?P<n>\d+)\b"
)
# hand-written text that an org rule has replaced: (pattern, what the org says, its source)
CONTRADICTIONS = (
    (
        re.compile(r"do not open a pull request unless", re.I),
        "every change goes through a PR to main, opened as soon as the branch is pushed",
        "CONTRIBUTING.md § Pull requests; templates/agents/git-workflow.md",
    ),
    (
        re.compile(
            r"\b(?:bot|org-bot|release|commitizen|workflow)s?\b[^.|;\n]{0,80}\bpush(?:es|ed|ing)?"
            r"(?: [\w`-]+){0,3}? (?:to|on) `?main`?|\bpush(?:es|ed|ing)?(?: [\w`-]+){0,3}? (?:to|on)"
            r" `?main`?[^.|;\n]{0,80}\b(?:bot|org-bot|release|commitizen)s?\b",
            re.I,
        ),
        "main takes no direct push, from a bot or a release either: the bump is a PR, the tag follows the merge",
        "CONTRIBUTING.md § Cutting a release; templates/rulesets/",
    ),
    (
        re.compile(
            r"\b(?:merge commit|rebase[- ]and[- ]merge|rebase[- ]merge)s? (?:is|are) (?:used|allowed|enabled)",
            re.I,
        ),
        "PRs are squash-merged, the only merge method enabled",
        "CONTRIBUTING.md § Pull requests",
    ),
)


def template_lines():
    """Every non-blank line of the org-sync templates: text copied from one is managed,
    even in a repository whose copy lost its markers."""
    out = set()
    for root, _, files in os.walk(TEMPLATES):
        for f in files:
            if f.endswith((".md", ".in")):
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    out.update(x.strip() for x in fh if len(x.strip()) > 20)
    return out


def hand_written(text, tlines):
    """`text` without the org-sync managed sections and template lines, line numbers kept."""
    text = MANAGED.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return "\n".join("" if line.strip() in tlines else line for line in text.splitlines())


def repo_slug(repo):
    try:
        url = subprocess.run(
            ["git", "-C", os.path.abspath(repo), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        url = ""
    m = re.search(r"[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
    if m and m.group(1) in ("swarm-routing", "danieljoppi"):
        return f"swarm-routing/{m.group(2)}"
    return f"swarm-routing/{os.path.basename(os.path.abspath(repo))}"


def opened_before(prefix):
    """Whether `prefix` (a clause up to an issue reference) ends in an OPEN_WORD,
    with only other references, `and`/`or` and separators after it."""
    words = LIST_SEP.split(prefix)
    while words and (
        not words[-1] or LIST_SEP.fullmatch(words[-1]) or LIST_TOKEN.fullmatch(words[-1])
    ):
        words.pop()
    return OPEN_WORD.search("".join(words)) is not None


def segments(line):
    """A line split into clauses (table cells, sentences, semicolons)."""
    return [s for s in re.split(r"\s\|\s|\|\s|\s\||(?<=[.;])\s+", line) if s.strip()]


def path_like(token):
    if not token or any(c in token for c in " <>{}*$…,:@=|\\\"'()") or "..." in token:
        return False
    if token.startswith(("/", "~", "-", "#", "http")) or "/" not in token:
        return False
    return bool(re.match(r"^\.?[A-Za-z0-9_][\w.-]*(/[\w.@+-]+)*/?$", token))


def stem_exists(repo, path):
    """`core/ant_message_codec`: a file with that stem somewhere under its top directory."""
    if "." in os.path.basename(path):
        return False
    stem, top = os.path.basename(path), os.path.join(repo, path.split("/")[0])
    if not os.path.isdir(top) or "/" not in path:
        return False
    for _, _, files in os.walk(top):
        if any(os.path.splitext(x)[0] == stem for x in files):
            return True
    return False


def job_names(repo):
    """Workflow job ids and `name:` values, read without a YAML parser."""
    names = set()
    wf = os.path.join(repo, ".github", "workflows")
    if not os.path.isdir(wf):
        return names
    for f in os.listdir(wf):
        text = read(repo, os.path.join(".github", "workflows", f)) or ""
        names.update(re.findall(r"^  ([\w-]+):\s*$", text, re.M))
        names.update(
            n.strip().strip("'\"") for n in re.findall(r"^[ \t]+name:[ \t]*(\S.*)$", text, re.M)
        )
    return names


def gh_issue(slug, n):
    """(state, closed_at) of an issue or PR, or None if it cannot be read."""
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{slug}/issues/{n}", "--jq", "[.state, .closed_at]"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode:
        return None
    try:
        state, closed = json.loads(out.stdout)
    except ValueError:
        return None
    return state, closed


def check_ai_facts(repo, r, online=False, fetch=None):
    fetch = fetch or gh_issue
    tlines = template_lines()
    name = os.path.basename(os.path.abspath(repo))
    slug = repo_slug(repo)
    texts = {f: read(repo, f) for f in AI_FILES}
    whole_plan = any(
        re.search(r"layout below is the plan|is the plan;", t or "") for t in texts.values()
    )
    missing, stale, refs, contra, checks = [], [], [], [], []
    cfg_text = read(repo, ".github/org-sync.toml")
    required = set()
    if cfg_text:
        required = set(tomllib.loads(cfg_text).get("settings", {}).get("required_checks", []))
    jobs = job_names(repo)

    # directories a layout block marks planned or untracked: paths under them are exempt
    exempt, layout_all = [], []
    for t in texts.values():
        for d, planned in layout_dirs(t or ""):
            layout_all.append(d)
            if planned:
                exempt.append(d)

    for f, text in texts.items():
        if not text:
            continue
        body = hand_written(text, tlines)
        para, fenced = "", False
        for no, line in enumerate(body.splitlines(), 1):
            if line.startswith("```"):
                fenced, para = not fenced, ""
                continue
            if not line.strip() or line.lstrip().startswith(("|", "#", "- ", "* ")) or fenced:
                para = ""  # a new paragraph, table row, heading or list item
            planned_line = PLANNED.search(line) is not None
            # (a)/(b): paths in backticks, a CLAUDE.md link, a layout line
            cands = [(m.start(), m.group(1).strip()) for m in re.finditer(r"`([^`\n]+)`", line)]
            if f == "CLAUDE.md":
                for m in LINK.finditer(line):
                    t = m.group(1).split("#")[0]
                    if t and not re.match(r"^[a-z]+:", t):
                        cands.append((m.start(), t))
            lay = LAYOUT.match(line) if fenced else None
            if lay:
                cands.append((0, lay.group(1)))
            for pos, tok in cands:
                if not (lay and tok == lay.group(1)) and not path_like(tok):
                    continue
                window = re.split(r"\s\|\s|\|\s|(?<=[.!?])\s+", para + " " + line[:pos])[-1]
                if any(m.group(0) != name for m in FOREIGN.finditer(window)):
                    continue  # another repository's (or ns-3's) file
                path = tok.rstrip("/")
                top = path.split("/")[0]
                exists = os.path.exists(os.path.join(repo, path)) or stem_exists(repo, path)
                if planned_line:
                    sub = any(x != tok and x.startswith(tok) for x in layout_all)
                    # the marker next to this path, not a sentence about markers
                    after = line[pos + len(tok) + 2 : pos + len(tok) + 47]
                    near = line[max(0, pos - 15) : pos] + re.split(r"[.;:](?:\*\*)?\s", after)[0]
                    if exists and (lay or PLANNED_MARK.search(near)) and not sub:
                        stale.append(f"{f}:{no}: `{tok}` is marked planned but exists")
                    continue
                if exists or any(path.startswith(e.rstrip("/")) for e in exempt):
                    continue
                top_exists = os.path.exists(os.path.join(repo, top))
                if not (top_exists or top in KNOWN_TOP):
                    continue
                if whole_plan and not top_exists:
                    continue  # the status says the layout is the plan
                missing.append(f"{f}:{no}: `{tok}`")
            for seg in segments(line):
                # (c): issues written as open or blocking
                qual = slug
                for m in ISSUE_REF.finditer(seg):
                    if m.group("owner"):
                        qual = f"{m.group('owner')}/{m.group('repo')}"
                    elif m.group("name"):
                        qual = f"swarm-routing/{m.group('name')}"
                    qual = qual.replace("danieljoppi/", "swarm-routing/")
                    if not SLUG.match(qual) or qual.split("/")[1] in PRIVATE_REPOS:
                        continue  # never read, or report, another owner's or a private issue
                    if opened_before(seg[: m.start()]) or OPEN_AFTER.match(seg[m.end() :]):
                        refs.append((f, no, qual, int(m.group("n")), seg.strip()))
                # (e): checks called required, named in the same clause
                if re.search(r"\brequired (?:status )?checks?\b|\bis (?:a )?required\b", seg, re.I):
                    for m in re.finditer(r"`([^`\n]+)`", seg):
                        c = m.group(1)
                        if (
                            path_like(c)
                            or not re.match(r"^[A-Za-z][\w .:/()-]*$", c)
                            or len(c) > 60
                        ):
                            continue
                        known = (
                            c in required
                            or c in jobs
                            or any(x.strip() in jobs for x in c.split("/"))
                        )
                        if not known and (required or jobs):
                            checks.append(f"{f}:{no}: `{c}`")
            # (d): contradictions with org rules
            for pat, says, source in CONTRADICTIONS:
                m = pat.search(line)
                if m and not (
                    pat is not CONTRADICTIONS[0][0]
                    and NEGATED.search(line[max(0, m.start() - 12) : m.end()])
                ):
                    contra.append(f"{f}:{no}: {line.strip()[:100]} — the org: {says} ({source})")
            para = (para + " " + line).strip()

    if missing:
        r.add(
            "WARN", "AI files", "paths that do not exist (fix them, or mark them planned)", missing
        )
    if stale:
        r.add("WARN", "AI files", "planned paths that exist (drop the planned marker)", stale)
    if contra:
        r.add("WARN", "AI files", "text that contradicts an org rule", contra)
    if checks:
        r.add(
            "WARN",
            "AI files",
            "checks called required that are neither in required_checks nor a workflow job",
            checks,
        )
    if not online:
        if refs:
            r.add(
                "INFO",
                "AI files",
                f"{len(refs)} issue reference(s) written as open not checked (offline; pass --online)",
            )
    else:
        closed, unread, seen = [], [], {}
        for f, no, qual, n, seg in refs:
            key = (qual, n)
            if key not in seen:
                seen[key] = fetch(qual, n)
            got = seen[key]
            ref = f"#{n}" if qual == slug else f"{qual}#{n}"
            if got is None:
                unread.append(f"{f}:{no}: {ref}")
            elif got[0] == "closed":
                closed.append(f"{f}:{no}: {ref} closed {(got[1] or '')[:10]} — {seg[:90]}")
        if closed:
            r.add("WARN", "AI files", "issues written as open or blocking that are closed", closed)
        if unread:
            r.add("INFO", "AI files", "issue references that could not be read", unread)
    if not (missing or stale or contra or checks):
        r.add("PASS", "AI files", "every path, planned marker, rule and check name holds")


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

    def repo(changes=None, drop=(), **kw):
        d = tempfile.mkdtemp()
        files = {**base, **(changes or {})}
        for p, t in files.items():
            if p in drop:
                continue
            os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
            with open(os.path.join(d, p), "w") as f:
                f.write(t)
        return check(d, **kw)

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
    r = repo(drop=("README.md",))
    expect("no README fails", has(r, "FAIL", "no README.md"))
    r = repo({"README.md": "ARA\n\n" + readme_ok})
    expect("a README not starting with a title fails", has(r, "FAIL", "`# Title`"))
    r = repo(drop=("AGENTS.md",))
    expect(
        "no AGENTS.md fails",
        any(
            x["level"] == "FAIL" and x["area"] == "AGENTS.md" and x["msg"] == "missing"
            for x in r.rows
        ),
    )
    r = repo(drop=("CLAUDE.md",))
    expect("no CLAUDE.md fails", has(r, "FAIL", "@AGENTS.md"))
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

    # --- AI files: facts (#142) ---
    def ai(extra, **kw):
        return repo({"AGENTS.md": agents_ok + "\n" + extra + "\n", **kw.pop("files", {})}, **kw)

    expect("the AI-files pass reports PASS on the base", has(ok, "PASS", "every path"))
    r = ai("Run `tools/gone.py` first.")
    expect("(a) a missing path warns", has(r, "WARN", "paths that do not exist"))
    r = ai("Read `core/a.cc` first.")
    expect("(a) an existing path does not warn", not has(r, "WARN", "paths that do not exist"))
    r = ai("Then `ns3/model/x.cc` (planned) will hold it.")
    expect("(a) a planned path does not warn", not has(r, "WARN", "paths that do not exist"))
    r = ai("The source is AntHocNet `tools/bench/x.py`.")
    expect("(a) another repository's path does not warn", not has(r, "WARN", "do not exist"))
    r = ai("<!-- org-sync:begin rules -->\nRun `tools/gone.py`.\n<!-- org-sync:end rules -->")
    expect("(a) a managed section is not checked", not has(r, "WARN", "do not exist"))
    r = repo({"CLAUDE.md": "@AGENTS.md\n\nSee [the ADR](docs/adr/0009-gone.md).\n"})
    expect("(a) a CLAUDE.md link to a missing file warns", has(r, "WARN", "do not exist"))
    r = ai("`core/` (planned) holds the algorithm.")
    expect("(b) a planned path that exists warns", has(r, "WARN", "planned paths that exist"))
    r = ai(
        "**Status: `core/` in progress.** Directories marked (planned) do not exist yet: "
        "update this file in the PR that creates each."
    )
    expect("(b) a marker far from the path does not warn", not has(r, "WARN", "planned paths"))
    r = ai("`ns3/` (planned) holds the module.")
    expect("(b) a planned path that is missing does not warn", not has(r, "WARN", "planned paths"))

    calls = []

    def fake(state):
        def fetch(slug, n):
            calls.append((slug, n))
            return (state, "2026-10-01T00:00:00Z" if state == "closed" else None)

        return fetch

    extra = "The image move is blocked by #5 and swarm-routing/ns3-tools#7."
    r = ai(extra, online=True, fetch=fake("closed"))
    expect("(c) a closed blocker warns", has(r, "WARN", "closed"))
    expect(
        "(c) each reference is fetched once, cross-repo ones in their repo",
        len(calls) == 2 and calls[1] == ("swarm-routing/ns3-tools", 7),
    )
    r = ai(extra, online=True, fetch=fake("open"))
    expect("(c) an open blocker does not warn", not has(r, "WARN", "closed"))
    calls.clear()
    r = ai(extra)
    expect(
        "(c) offline: not checked, with a note",
        not calls and has(r, "INFO", "pass --online"),
    )
    calls.clear()
    r = ai("The idea came from #5, now history.", online=True, fetch=fake("closed"))
    expect("(c) a reference not written as open is not fetched", not calls)

    calls.clear()
    r = ai("Blocked by papers #12 and other/repo#3.", online=True, fetch=fake("closed"))
    expect("(c) a private or another owner's issue is never read", not calls)
    calls.clear()
    r = ai(
        "Temporary exception (AntHocNet #843, option A); revert it when #9 closes.",
        online=True,
        fetch=fake("open"),
    )
    expect(
        "(c) an exception and a when-closes reference are read",
        sorted(n for _, n in calls) == [9, 843] and ("swarm-routing/AntHocNet", 843) in calls,
    )
    import time

    t0 = time.monotonic()
    ai(
        "Depends on "
        + " ".join(f"{i}#{i}#" for i in range(40))
        + "x "
        + "#1, " * 40
        + "for details."
    )
    ai("until " + "\t#9" * 60 + " x #13 and " + "90#" * 60)
    expect("(c) a long reference list ends in plain text quickly", time.monotonic() - t0 < 2)

    r = ai("- Do not open a pull request unless explicitly asked.")
    expect("(d) a rule the org replaced warns", has(r, "WARN", "contradicts an org rule"))
    r = ai("The release bot pushes the bump to `main`.")
    expect("(d) a bot pushing to main warns", has(r, "WARN", "contradicts an org rule"))
    r = ai("The release bot opens a PR; no workflow pushes to `main`.")
    expect("(d) a negated push does not warn", not has(r, "WARN", "contradicts"))
    r = ai("- **Always open a PR to `main`** once the branch is pushed — every change is")
    expect("(d) the org's own wording does not warn", not has(r, "WARN", "contradicts"))

    wf = {
        ".github/workflows/ci.yml": "name: ci\njobs:\n  gate:\n    name: CI gate\n"
        "  other:\n    name:\n      Not a name\n"
    }
    cfg = 'kind = "protocol"\ntitle = "ARA"\n[settings]\nrequired_checks = ["lint"]\n'
    r = ai(
        "The one required check is `CI gate`.",
        files={**wf, ".github/org-sync.toml": cfg},
    )
    expect("(e) a required check that is a job does not warn", not has(r, "WARN", "required"))
    r = ai(
        "The one required check is `CI gaet`.",
        files={**wf, ".github/org-sync.toml": cfg},
    )
    expect("(e) a required check that does not exist warns", has(r, "WARN", "called required"))
    r = ai("The one required check is `Not a name`.", files={**wf, ".github/org-sync.toml": cfg})
    expect("(e) a `name:` value on the next line is not a job name", has(r, "WARN", "required"))
    r = ai("The required check is `lint`.", files={".github/org-sync.toml": cfg})
    expect("(e) a check in required_checks does not warn", not has(r, "WARN", "called required"))

    for f in failures:
        print(f"FAIL: {f}")
    print(f"check_docs self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--online", action="store_true", help="check issue references with gh api (GH_TOKEN)"
    )
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    rep = check(a.repo, online=a.online)
    print(json.dumps(rep.rows, indent=1) if a.json else rep.text())
    return 1 if rep.fail else 0


if __name__ == "__main__":
    sys.exit(main())
