# Agent tooling: MCP servers, plugins and token habits

The org standard for what an AI agent session runs and how it keeps its
context small. The decision and its measurements are
[ADR-0005](adr/0005-the-mcp-and-agent-tooling-standard.md); this page is the
short form. Every repository's AGENTS.md links it from "Session habits".

## MCP servers

| Server | Status | How it reaches a session |
|---|---|---|
| `swarm-mcp` (read-only verdicts of the org scripts; swarm-routing/skills#185) | standard, once released | bundled in the `swarm-routing` plugin, which every repository's committed `.claude/settings.json` enables |
| GitHub's MCP server | standard where the host provides it (hosted sessions) | the host; in a local session, GitHub's own server with `--read-only` unless the task writes, or the `gh` CLI |
| `clangd-lsp`, `gopls-lsp`, `pyright-lsp` (Claude Code's official LSP plugins) | optional, local terminal sessions only (cloud sessions do not start language servers); swarm-routing/skills#175 measures them | a person installs the plugin and the language server; never a committed setting |
| Obsidian or any notes vault, Serena, third-party clangd bridges, code-graph indexes, repo packers, hosted MCP endpoints | ruled out (ADR-0005, Decision 3) | — |

Rules for any server:

- It arrives only through the plugin or a committed `.mcp.json`, by a
  reviewed PR. No skill installs or configures one (skills golden rule 10).
- Local, stdio, pinned by version or digest, no account, nothing sent
  anywhere but the model. No `_meta["anthropic/alwaysLoad"]`: its tools stay
  deferred until used.
- Its PR states its effect, measured with `token_audit.py` (below).

## Habits that save the most

In the order the 2026-11-22 audit ranked them:

1. **Attach only the repositories the task needs.** Each attached repository's
   agent files cost 8,000 to 13,000 tokens on every request of the session and
   of every subagent.
2. **Delegate single-repository work to a worker that skips the others'
   agent files** (`omitClaudeMd: true`; the `org-worker` agent,
   swarm-routing/skills#186), and read-only searches to the built-in Explore
   agent, which skips them too.
3. **Search large outputs, never read them whole**: an output the harness
   saved to a file goes through `grep`, `head` or a section reader. Wait on a
   PR with `tools/pr-status/pr_status.py` rather than raw activity (#794).
4. **Run the script, read its verdict** (AntHocNet ADR-0014; #286 adds the
   issue index and readers).
5. **Keep agent files under their budget** (`check_docs.py`; #793).

## Measure

```bash
# what a session loads, per repository and with all of them attached (estimate)
python3 -I ../skills/tools/token-audit/token_audit.py files . ../ARA ../AntHocNet
# where a finished session's tokens went (measured usage; sizes only, no content)
python3 -I ../skills/tools/token-audit/token_audit.py transcript ~/.claude/projects/<dir>/<session>.jsonl
```

Compare a task with and without the change: the first request's context, the
totals, and the calls and bytes per tool.
