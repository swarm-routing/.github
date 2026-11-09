#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Apply the swarm-routing org templates to a repository, and check for drift.

Usage: org_sync.py {init,plan,apply,conflicts,check,settings} [REPO_DIR] [options]

The repository describes itself in `.github/org-sync.toml` (`init` writes it).
Each managed item is one of:

  section  the text between `<!-- org-sync:begin NAME -->` and
           `<!-- org-sync:end NAME -->` in a Markdown file (`# org-sync:begin
           NAME` / `# org-sync:end NAME` in a YAML file); the rest of the file
           is the repository's own
  file     the whole file is the org's
  seed     created once from a template, then the repository's own
  json     only the named keys of a JSON file are the org's
  targets  a Makefile that is the repository's own, checked only for the
           org's standard target names (swarm-routing/.github#11)

Output is a summary, never file contents, so an agent reads a few lines per
run (AntHocNet ADR-0014). Only `conflicts` prints text: the hunks that need a
person's judgement. Stdlib only; Python 3.11+ (tomllib).
"""

import argparse
import datetime
import difflib
import json
import os
import re
import subprocess
import sys
import tomllib
from urllib.parse import quote

ORG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = os.path.join(ORG, "templates")
CONFIG = ".github/org-sync.toml"
KINDS = ("protocol", "c-cpp", "python", "container", "data", "site", "skills")
MAKE_TARGETS = ("help", "build", "test", "lint", "format", "check", "clean", "shell", "ci")
BEGIN = "<!-- org-sync:begin {} -->"
END = "<!-- org-sync:end {} -->"
YAML_BEGIN = "# org-sync:begin {}"
YAML_END = "# org-sync:end {}"


def markers(path):
    """The (begin, end) marker formats for a managed section in this file."""
    if path.endswith((".yaml", ".yml")):
        return YAML_BEGIN, YAML_END
    return BEGIN, END


# Badges per kind (swarm-routing/.github#8). Each appears only when its target
# exists (see badge_lines).
BASE_BADGES = ["ci", "licence", "conventional", "arena"]
KIND_BADGES = {
    "protocol": ["cxx", "ns3", "ns3dev"],
    "c-cpp": ["cxx", "ns3dev"],
    "python": ["python"],
    "container": ["ghcr", "cosign"],
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
    ("CLAUDE.md", "org"): (r"^\*\*Handoffs are always a ticket\.\*\*", r"\Z"),
    ("SECURITY.md", "reporting"): (r"^## Reporting a vulnerability\n", r"^## "),
}
# Sections with nothing to adopt: inserted after the first match of the regex.
INSERT_AFTER = {
    ("README.md", "badges"): r"^# .*\n",
    # new in every AGENTS.md: placed before the repository's own table
    # (with or without a blank line before the heading)
    ("AGENTS.md", "skills"): r"\n(?=\n?## Where to look\n)",
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


def load_config(repo_dir):
    text = read(os.path.join(repo_dir, CONFIG))
    if text is None:
        sys.exit(f"org-sync: no {CONFIG} in {repo_dir}; run `org_sync.py init --kind KIND`")
    cfg = tomllib.loads(text)
    if cfg.get("kind") not in KINDS:
        sys.exit(f"org-sync: {CONFIG}: kind must be one of {', '.join(KINDS)}")
    cfg.setdefault(
        "repo", git_slug(repo_dir) or "swarm-routing/" + os.path.basename(os.path.abspath(repo_dir))
    )
    cfg.setdefault("title", cfg["repo"].split("/")[1])
    cfg.setdefault("description", "**Status: empty.** Describe the repository here.")
    cfg.setdefault("ci_workflow", "ci.yml")
    cfg.setdefault("dual", [])
    cfg.setdefault("badges", BASE_BADGES + KIND_BADGES[cfg["kind"]])
    cfg.setdefault("manage", [])
    return cfg


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


def badge_lines(cfg, repo_dir):
    repo, out = cfg["repo"], []
    for b in cfg["badges"]:
        if b == "ci":
            wf = cfg["ci_workflow"]
            if os.path.exists(os.path.join(repo_dir, ".github/workflows", wf)):
                url = f"https://github.com/{repo}/actions/workflows/{wf}"
                out.append(f"[![CI]({url}/badge.svg)]({url})")
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
        ("seed", "CLAUDE.md", "claude/CLAUDE.md.in", None),
        ("section", "CLAUDE.md", "claude/org.md", "org"),
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
        ("json", ".claude/settings.json", "claude-settings.json", None),
        ("seed", ".coderabbit.yaml", "coderabbit/coderabbit.yaml.in", None),
        ("section", ".coderabbit.yaml", "coderabbit/head.yaml", "coderabbit-head"),
        ("section", ".coderabbit.yaml", "coderabbit/tail.yaml", "coderabbit-tail"),
    ]
    if cfg["dual"]:
        out.insert(12, ("seed", "LICENSE-MIT", "LICENSE-MIT.in", None))
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


def evaluate(cfg, repo_dir, item):
    """Return (status, new_text_or_None, detail). status: create, update,
    unchanged, adopt, conflict, missing."""
    kind, path, src, name = item
    full = os.path.join(repo_dir, path)
    cur = read(full)
    v = values(cfg)
    want = badge_lines(cfg, repo_dir) if name == "badges" else (template(src) or "" if src else "")
    if kind == "seed":
        want = render_makefile(cfg) if path == "Makefile" else want.format_map(v)
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


def plan(cfg, repo_dir):
    rows = []
    # seeds run before sections so a fresh repo gets the file, then its sections
    for item in items(cfg):
        status, new, detail = evaluate(cfg, repo_dir, item)
        rows.append((item, status, new, detail))
    return rows


def label(item):
    return item[1] + (f"#{item[3]}" if item[3] else "")


def write(repo_dir, path, text):
    full = os.path.join(repo_dir, path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def apply(cfg, repo_dir, force=()):
    """Write every change; repeat until stable, since a badge can depend on a
    file a later item creates (at most three passes)."""
    changed, conflicts = [], []
    for _ in range(3):
        c, conflicts = apply_once(cfg, repo_dir, force)
        if not c:
            break
        changed += [x for x in c if x not in changed]
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
            if new is not None and status in ("update", "adopt", "conflict"):
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
    changed, conflicts = apply(cfg, a.repo, set(getattr(a, "force", None) or ()))
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


def cmd_check(a):
    cfg = load_config(a.repo)
    drift = [
        (item, status, detail)
        for item, status, _, detail in plan(cfg, a.repo)
        if status != "unchanged"
    ]
    for item, status, detail in drift:
        print(f"drift     {label(item)}: {status}" + (f" ({detail})" if detail else ""))
    if drift:
        print(
            f"org-sync: {len(drift)} item(s) differ from swarm-routing/.github templates; "
            "run `org_sync.py apply` (or `make org-sync-check` to see this again)",
            file=sys.stderr,
        )
        return 1
    print("org-sync: in sync")
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
    for name in ("init", "plan", "apply", "conflicts", "check", "settings"):
        s = sub.add_parser(name)
        s.add_argument("repo", nargs="?", default=".")
        if name == "init":
            s.add_argument("--kind", required=True, choices=KINDS)
            s.add_argument("--title")
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
        if name in ("plan", "settings"):
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
    a = p.parse_args(argv)
    return globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    sys.exit(main())
