# 0005. Agent sessions use a small, measured set of MCP servers and tools

- **Status:** proposed
- **Date:** 2026-11-22
- **Issue:** #141 (children #793, #794, swarm-routing/skills#186); swarm-routing/skills#175, swarm-routing/skills#185

## Context

The maintainer asked (2026-11-22) which tools would let the org's agents do
the same work on fewer tokens (code-graph tools, Obsidian, MCP servers), what
the agents need configured, and whether one MCP standard can live here and be
referenced from every AGENTS.md.

### What a session costs today (measured 2026-11-22)

`swarm-routing/skills` `tools/token-audit/token_audit.py files` on
`origin/main` (bytes exact; tokens are bytes / 3.5, an estimate):

| Repository | Loaded at session start | Org-managed |
|---|---:|---:|
| `.github` | 32,246 B (≈ 9,214 tokens) | hand-written |
| AntHocNet | 42,415 B (≈ 12,119) | 24,326 B (57 %) |
| ARA | 45,844 B (≈ 13,099) | 28,784 B (62 %) |
| sim-tools | 40,644 B (≈ 11,613) | 25,902 B (63 %) |
| swarm-routing.github.io | 39,499 B (≈ 11,286) | 25,902 B (65 %) |
| swarm-core | 27,699 B (≈ 7,914) | 25,902 B (93 %) |

- These six together: 228,347 B (≈ 65,000 tokens); 83,510 B (36 %) are
  sections byte for byte the same in several of them (`## Agent pitfalls`
  8,006 B × 5, `## Agent skills` 4,431 B × 5, …).
- A session with 13 repositories attached (an orchestrating cloud session):
  402,708 B, ≈ 115,000 tokens, 58 % org-managed, 30 % repeated sections.
- The org sections are 25,902 B, over `check_docs.py`'s 23,200 B budget
  (warn-only); the same text was 17,363 B on 2026-11-12 (#277): +49 % in ten
  days.

`token_audit.py transcript` on one finished 13-repository session
(aggregates only, no content):

- Main session: 5,494 requests, first request **141,050** tokens (the
  agent files above are most of it), largest context 901,163; input
  13,544 uncached + 25,687,094 cache-written + 2,394,410,138 cache-read;
  output 3,862,552.
- 327 subagents, 28,596 requests: first-request context median **186,120**
  tokens (p10 137,673, p90 208,085); `first context × requests` is **56 %**
  of their input tokens. Each subagent loads every agent file the main session
  loads, though most edit one repository.
- Tool results, main session: `Read` 4.04 MB in 21 calls (whole reads of
  outputs persisted to a file), `Bash` 3.94 MB in 3,123 calls,
  `ReadNotifications` (watched PRs) 1.51 MB in 151 calls. Subagents: `Bash`
  48.6 MB in 25,411 calls.
- GitHub MCP tools and the other deferred tools cost almost nothing at start:
  Claude Code's tool search loads a schema only when a tool is first used.

So the start-up prefix (agent files of every attached repository) and large
tool results dominate. MCP tool definitions do not, as long as they stay
deferred.

### What the candidates offer

| Tool | What it gives | Token effect | Fit and cost here |
|---|---|---|---|
| `swarm-mcp` (swarm-routing/skills#185) | the org scripts' verdicts (fidelity, invariants, release readiness, locks) as read-only tools | unmeasured; same principle as script-first skills (AntHocNet ADR-0014): the model reads a summary, not raw files | org code, reviewed under the skills trust boundary; stdio, no account, no token of its own |
| GitHub's MCP server | issues, PRs, checks, logs | the hosted sessions already have it; read-only mode and toolsets narrow it for local use | first-party; REST semantics; schemas deferred |
| Claude Code LSP plugins (`clangd-lsp`, `gopls-lsp`, `pyright-lsp`, official marketplace) | diagnostics after each edit, an `LSP` tool for definitions and references instead of text search | unmeasured (swarm-routing/skills#175 measures it); saves compile round trips on C++ | **not started in cloud sessions** (Claude Code docs, "Code intelligence plugins"), where most org agent work runs; clangd needs `compile_commands.json` (ns-3's CMake writes one) |
| clangd over MCP (mcp-language-server, clangd-mcp-server) | the same, as MCP tools | unmeasured | third-party, one maintainer each; superseded by the official LSP plugin where that runs |
| Serena | LSP-backed symbol read and edit tools | no published measurement; its maintainers say small tasks gain little | third-party, many tools, its own memory files beside our record |
| Code graphs (codebase-memory-mcp, code-review-graph) | a tree-sitter graph in SQLite, queried by structure | author-run benchmarks: about 82× (code-review-graph, median per question) and about 120× (codebase-memory-mcp) against reading the corpus, a generous baseline; a port reports 8.2× | third-party code with session permissions; an index to keep current; our cores are a few thousand lines each, where grep already finds a symbol in one call |
| repomix / repo maps | the whole repository packed into one file | more tokens, not fewer, for work inside the repository | useful only to hand a repository to an outside reviewer |
| Obsidian vaults over MCP | notes as a searchable, linked vault | none against what we have; the vault's text is sent to the model all the same | a second record beside issues, `docs/` and ADRs (AntHocNet ADR-0013: the record is the issue), private to one machine, read and written by an agent with no review |
| Container MCP (swarm-routing/skills#175) | build and test inside `ns3-dev` | unmeasured | the sessions already run `docker` through Bash |

Claude Code features that cut tokens with no new code (Claude Code docs,
"Memory", "Subagents", "Tool search"):

- a subagent definition with `omitClaudeMd: true` starts without the CLAUDE.md
  and AGENTS.md files; `skills:` preloads only the skills it needs; the
  built-in Explore and Plan agents already skip CLAUDE.md;
- subdirectory CLAUDE.md files load on demand in a terminal session (only the
  repositories attached to a cloud session load at start, all of them);
- `claudeMdExcludes` (absolute-path globs, any settings layer) skips named
  CLAUDE.md files;
- `.claude/rules/` with `paths:` frontmatter loads a rule only when a matching
  file is read;
- tool search keeps MCP tool schemas out of the prompt until used; an MCP tool
  can force itself in with `_meta["anthropic/alwaysLoad"]`;
- prompt caching: a stable prefix is read back at the cache rate, so agent
  files that change rarely cost less than their size suggests, and every
  template refresh starts a new cache for every session after it.

## Decision

1. **Standard (every session that can run it):**
   - `swarm-mcp`, once swarm-routing/skills#185 ships it, bundled in the
     `swarm-routing` plugin (a plugin `.mcp.json`), so the committed
     `.claude/settings.json` that enables the plugin enables it; nothing to
     configure per repository.
   - GitHub's MCP server where the host provides it (hosted sessions do); in a
     local session, GitHub's own server with `--read-only` unless the task
     writes, and the `gh` CLI otherwise.
2. **Optional (a person enables it for a local terminal session):** the
   official `clangd-lsp`, `gopls-lsp` and `pyright-lsp` plugins, recommended
   or not by swarm-routing/skills#175's measurement. Never a committed setting,
   since cloud sessions do not run them.
3. **Ruled out:** Obsidian or any second notes store (it duplicates the
   issue, `docs/` and ADR record); Serena and third-party clangd MCP bridges
   (third-party, unmeasured, superseded by the official LSP plugins);
   code-graph servers until a measurement on our own repositories beats grep
   (their published numbers are against whole-corpus reads); repo packers for
   in-repository work; any hosted MCP endpoint (swarm-routing/swarm-routing.github.io#238).
4. **Configuration is committed and reviewed.** An MCP server reaches a
   session only through the `swarm-routing` plugin or a repository's committed
   `.mcp.json`, by PR. No server is configured by a skill step (skills golden
   rule 10); a third-party server is pinned by version or digest, runs
   locally over stdio, needs no account, and sends nothing anywhere but the
   model. No server sets `alwaysLoad`.
5. **Every addition is measured.** A server, plugin or agent-file change
   states its effect from `token_audit.py` (`files` for what loads,
   `transcript` for a task run with and without it) in its PR.
6. **What to cut, in order** (the measured costs above):
   1. Worker subagents that skip the agent files of repositories they do not
      touch (`omitClaudeMd`, reading only their own AGENTS.md): about 100,000
      tokens less per subagent request in a 13-repository session
      (swarm-routing/skills#186).
   2. Attach only the repositories the task needs (already a session habit):
      each one costs 8,000 to 13,000 tokens on every request.
   3. Large tool results: a persisted output is searched, not read whole; PR
      activity through `pr_status.py`, not raw notifications (#794).
   4. Keep the org sections under their budget and make it a gate (#793):
      about 770 tokens per request per repository; the sections stay in full
      (maintainer decision 2026-11-12 on #277).
   5. Scripts for the loops a model repeats by hand (#286).
   6. The MCP servers of item 1, which help by returning verdicts in place of
      files, not by their own size.

The standard is summarised for agents in [`docs/agents.md`](../agents.md),
which the org-managed "Session habits" section of every AGENTS.md links.

## Consequences

- Every AGENTS.md gains one link (≈ 200 B); the standard itself is read on
  demand.
- A new tool is weighed against a number, not a claim; the published 80–120×
  figures for code graphs are not evidence for this org until measured here.
- C++ sessions in the cloud keep compiling to see their errors; the LSP gain
  is local-only until Claude Code starts language servers in cloud sessions.
- Ruling out a notes vault keeps one record; a session's lessons still go to
  issues (the Handoff form's lessons field, #144).
- Revisit when swarm-routing/skills#175 or swarm-routing/skills#186 report their measurements, or
  when Claude Code runs plugins' language servers in cloud sessions.

## References

- Claude Code docs: [memory and AGENTS.md](https://code.claude.com/docs/en/memory),
  [subagents](https://code.claude.com/docs/en/sub-agents),
  [code intelligence plugins](https://code.claude.com/docs/en/plugins/code-intelligence),
  [tool search](https://code.claude.com/docs/en/agent-sdk/tool-search).
- GitHub MCP server: [server configuration](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)
  (toolsets, read-only, dynamic toolsets).
- codebase-memory-mcp: [arXiv:2603.27277](https://arxiv.org/abs/2603.27277);
  code-review-graph's own benchmarks (its README).
- #277 (the 2026-11-12 audit and the decision to keep the org sections in
  full), #286, #141; swarm-routing/skills#175, swarm-routing/skills#185,
  swarm-routing/skills#186;
  swarm-routing/swarm-routing.github.io#238.
