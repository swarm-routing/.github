#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Record reviewed SonarQube Cloud verdicts where the quality gate reads them.

Usage:
  sonar_triage.py validate [--file F]            the decisions file alone, offline
  sonar_triage.py plan  [--file F] [--repos A,B] read-only: every entry against the live issue
  sonar_triage.py apply [--file F] [--repos A,B] plan, then transition and comment each entry
  sonar_triage.py findings --repos A,B [--file F] [--branch B]
                                                 read-only: the open findings, and which are recorded
  sonar_triage.py entry KEY --reason R [--decision D] [--file F] [--branch B]
                                                 read-only: the entry for KEY, every field from the API
  sonar_triage.py --self-test                    against a fake SonarQube Cloud

The decisions file (default: decisions.toml beside this script) is the
reviewed record: one `[[issue]]` or `[[hotspot]]` per SonarQube Cloud key,
with the project, the rule, the file and line it was reviewed at, the
decision and a reason id from its `[reasons]` table (swarm-routing/.github#425).
Keys are read from the public API when an entry is written, never typed:
`findings` lists a repository's open issues and hotspots on the branch
(default main) with whether the file records each, and `entry` prints the
`[[issue]]` or `[[hotspot]]` block for one key, its project, rule, file and
line as the API returns them (`--decision` falsepositive, the default, or
wontfix for an issue; SAFE, the default, ACKNOWLEDGED or FIXED for a hotspot).
`entry` refuses a key already in the file and a reason id not in its
`[reasons]` (add the reason first). Both read without a token.

`plan` fetches each entry's issue (`api/issues/search?issues=KEY`) or hotspot
(`api/hotspots/show`) and refuses the whole run on any mismatch: the key is
gone, its project, rule, file or line differ from the entry, or it was
resolved some other way. A key already resolved as the entry says is `done`
(a re-run is a no-op). With a token it also reports whether the token may
make the transition (the issue's `transitions`); `apply` refuses when it may
not. `apply` runs `plan` first, then per open entry posts
`api/issues/do_transition` (`falsepositive`; `wontfix`, or `accept` where
SonarQube Cloud offers that instead) or `api/hotspots/change_status`
(REVIEWED + SAFE/ACKNOWLEDGED/FIXED), then `api/issues/add_comment` with the
reason (a hotspot takes the comment in the same call). An issue already
resolved as its entry says but without a comment linking the review (its
comment failed after the transition) gets that comment on the next apply,
once. Nothing outside the file is read for change or touched.

The token comes from the environment only (SONAR_TOKEN, sent as a Bearer
header, never printed). Transitions need a user token of a user with
"Administer Issues" (hotspots: "Administer Security Hotspots") on each
project; an HTTP 401/403 stops the run with that message. SONAR_HOST_URL
overrides https://sonarcloud.io (the self-test's fake); the token is only
sent over https, or to a loopback address. The summary is a
Markdown table on stdout (and appended to $GITHUB_STEP_SUMMARY when set).
Exit 0 on success, 1 on a refusal or a failed call, 2 on usage.
"""

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(HERE, "decisions.toml")
HOST = "https://sonarcloud.io"
ISSUE_DECISIONS = {"falsepositive": "FALSE-POSITIVE", "wontfix": "WONTFIX"}
HOTSPOT_DECISIONS = {"SAFE", "ACKNOWLEDGED", "FIXED"}
ISSUE_FIELDS = ("project", "key", "rule", "file", "line", "decision", "reason")
HOTSPOT_FIELDS = ("project", "key", "rule", "file", "line", "resolution", "reason")
TRACKER = "https://github.com/swarm-routing/.github/issues/425"
NO_RIGHTS = (
    "the token may not change this finding: SONAR_TOKEN must be a user token of a "
    "user with 'Administer Issues' (hotspots: 'Administer Security Hotspots') on the "
    "project, not an analysis token"
)


class Refusal(Exception):
    pass


# ---------------------------------------------------------------- the file


def load(path):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    errs = validate(data)
    if errs:
        raise Refusal(f"{path}:\n" + "\n".join(f"  - {e}" for e in errs))
    return data


def validate(data):
    """Every way the decisions file is malformed, as strings."""
    errs = []
    reasons = data.get("reasons", {})
    if not isinstance(reasons, dict) or not all(
        isinstance(v, str) and v.strip() for v in reasons.values()
    ):
        errs.append("[reasons] must map each reason id to its text")
        reasons = {}
    seen = set()
    for kind, fields in (("issue", ISSUE_FIELDS), ("hotspot", HOTSPOT_FIELDS)):
        for n, e in enumerate(data.get(kind, [])):
            where = f"[[{kind}]] #{n + 1} ({e.get('key', '?')})"
            missing = [k for k in fields if k not in e]
            if missing:
                errs.append(f"{where}: missing {', '.join(missing)}")
                continue
            extra = sorted(set(e) - set(fields) - {"branch"})
            if extra:
                errs.append(f"{where}: unknown field(s) {', '.join(extra)}")
            if not isinstance(e["line"], int) or e["line"] < 0:
                errs.append(f"{where}: line must be a non-negative integer (0: file-level)")
            if not str(e["project"]).startswith("swarm-routing_"):
                errs.append(f"{where}: project {e['project']!r} is not swarm-routing_<repo>")
            if kind == "issue" and e["decision"] not in ISSUE_DECISIONS:
                errs.append(f"{where}: decision must be one of {', '.join(ISSUE_DECISIONS)}")
            if kind == "hotspot" and e["resolution"] not in HOTSPOT_DECISIONS:
                errs.append(f"{where}: resolution must be one of {', '.join(HOTSPOT_DECISIONS)}")
            if e["reason"] not in reasons:
                errs.append(f"{where}: reason {e['reason']!r} is not in [reasons]")
            if e["key"] in seen:
                errs.append(f"{where}: key listed twice")
            seen.add(e["key"])
    if not seen:
        errs.append("no [[issue]] or [[hotspot]] entry")
    return errs


def entries(data, repos):
    out = [("issue", e) for e in data.get("issue", [])]
    out += [("hotspot", e) for e in data.get("hotspot", [])]
    if repos:
        want = {f"swarm-routing_{r.strip()}" for r in repos.split(",") if r.strip()}
        out = [(k, e) for k, e in out if e["project"] in want]
    return out


# ---------------------------------------------------------------- the API


class Sonar:
    def __init__(self, host=None, token=None):
        self.host = (host or os.environ.get("SONAR_HOST_URL") or HOST).rstrip("/")
        self.token = token if token is not None else os.environ.get("SONAR_TOKEN", "")
        u = urllib.parse.urlparse(self.host)
        loopback = u.hostname in ("127.0.0.1", "localhost", "::1")
        if self.token and u.scheme != "https" and not loopback:
            raise Refusal(f"{self.host}: the token is only sent over https")

    def call(self, method, path, params):
        data = urllib.parse.urlencode(params)
        url = f"{self.host}/{path}"
        body = None
        if method == "GET":
            url += "?" + data
        else:
            body = data.encode()
        req = urllib.request.Request(url, data=body, method=method)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise Refusal(f"{method} {path}: HTTP {e.code}: {NO_RIGHTS}") from None
            raise Refusal(f"{method} {path}: HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise Refusal(f"{method} {path}: {e.reason}") from None
        return json.loads(raw) if raw.strip() else {}

    def issue(self, key, branch):
        params = {"issues": key, "additionalFields": "_all", "ps": 1}
        if branch:
            params["branch"] = branch
        got = self.call("GET", "api/issues/search", params).get("issues", [])
        return got[0] if got else None

    def search(self, project, branch):
        """Every open issue and every hotspot to review of a project on a branch."""
        issues, hotspots = [], []
        for page in range(1, 51):
            got = self.call(
                "GET",
                "api/issues/search",
                {"componentKeys": project, "branch": branch, "resolved": "false",
                 "ps": 100, "p": page},
            )  # fmt: skip
            issues += got.get("issues", [])
            if page * 100 >= got.get("paging", {}).get("total", 0):
                break
        for page in range(1, 51):
            got = self.call(
                "GET",
                "api/hotspots/search",
                {"projectKey": project, "branch": branch, "status": "TO_REVIEW",
                 "ps": 100, "p": page},
            )  # fmt: skip
            hotspots += got.get("hotspots", [])
            if page * 100 >= got.get("paging", {}).get("total", 0):
                break
        return issues, hotspots

    def hotspot(self, key):
        try:
            return self.call("GET", "api/hotspots/show", {"hotspot": key})
        except Refusal as e:
            if "HTTP 404" in str(e):
                return None
            raise


# ---------------------------------------------------------------- plan / apply


def transition_for(entry, live):
    """The transition that records `entry` on `live`, or None if not offered."""
    offered = live.get("transitions") or []
    want = entry["decision"]
    if want in offered:
        return want
    if want == "wontfix" and "accept" in offered:
        return "accept"  # SonarQube Cloud renamed won't fix to accept
    return None


def check(kind, e, live, authed):
    """(state, transition): state is open, done; raises Refusal on a mismatch."""
    tag = f"{e['project']} {e['key']}"
    if live is None:
        raise Refusal(f"{tag}: no such {kind} (gone, or another branch)")
    if kind == "issue":
        project, component = live.get("project"), live.get("component", "")
        rule, line = live.get("rule"), live.get("line", 0)
    else:
        project = (live.get("project") or {}).get("key")
        component = (live.get("component") or {}).get("key", "")
        rule = (live.get("rule") or {}).get("key")
        line = live.get("line", 0)
    path = component.split(":", 1)[1] if ":" in component else component
    diffs = [
        f"{name} {got!r} != {want!r}"
        for name, got, want in (
            ("project", project, e["project"]),
            ("rule", rule, e["rule"]),
            ("file", path, e["file"]),
            ("line", line or 0, e["line"]),
        )
        if got != want
    ]
    if diffs:
        raise Refusal(f"{tag}: the live {kind} differs from the reviewed entry: {'; '.join(diffs)}")
    status = live.get("status")
    if kind == "issue":
        if status in ("RESOLVED", "CLOSED"):
            if live.get("resolution") == ISSUE_DECISIONS[e["decision"]]:
                return "done", None
            raise Refusal(f"{tag}: already {status}/{live.get('resolution')}, not {e['decision']}")
        if status not in ("OPEN", "CONFIRMED", "REOPENED", "ACCEPTED"):
            raise Refusal(f"{tag}: status {status}, not open")
        if status == "ACCEPTED" and e["decision"] == "wontfix":
            return "done", None
        t = transition_for(e, live) if authed else None
        return "open", t
    if status == "REVIEWED":
        if live.get("resolution") == e["resolution"]:
            return "done", None
        raise Refusal(f"{tag}: already REVIEWED/{live.get('resolution')}")
    if status != "TO_REVIEW":
        raise Refusal(f"{tag}: status {status}, not TO_REVIEW")
    can = (live.get("canChangeStatus") is not False) if authed else None
    return "open", ("REVIEWED" if can else None)


def run(data, repos, sonar, apply, out=print):
    authed = bool(sonar.token)
    rows, refusals = [], []
    for kind, e in entries(data, repos):
        live = (
            sonar.issue(e["key"], e.get("branch", "main"))
            if kind == "issue"
            else sonar.hotspot(e["key"])
        )
        try:
            state, t = check(kind, e, live, authed)
        except Refusal as r:
            refusals.append(str(r))
            rows.append((kind, e, "REFUSED", ""))
            continue
        rows.append((kind, e, state, t or ""))
    if refusals:
        table(rows, out)
        raise Refusal("plan refused, nothing changed:\n" + "\n".join(f"  - {r}" for r in refusals))
    if apply:
        if not authed:
            raise Refusal("apply needs SONAR_TOKEN in the environment")
        blocked = [r for r in rows if r[2] == "open" and not r[3]]
        if blocked:
            table(rows, out)
            keys = ", ".join(r[1]["key"] for r in blocked)
            raise Refusal(f"{NO_RIGHTS} (no transition offered for {keys}); nothing changed")
        for i, (kind, e, state, t) in enumerate(rows):
            if state != "open":
                continue
            text = f"{data['reasons'][e['reason']]} (reviewed: {TRACKER})"
            if kind == "issue":
                sonar.call("POST", "api/issues/do_transition", {"issue": e["key"], "transition": t})
                sonar.call("POST", "api/issues/add_comment", {"issue": e["key"], "text": text})
            else:
                sonar.call(
                    "POST",
                    "api/hotspots/change_status",
                    {
                        "hotspot": e["key"],
                        "status": "REVIEWED",
                        "resolution": e["resolution"],
                        "comment": text,
                    },
                )
            rows[i] = (kind, e, "applied", t)
        # A transition whose comment failed (the issue is resolved, the
        # reason missing): add the comment only, never twice.
        for i, (kind, e, state, t) in enumerate(rows):
            if kind == "issue" and state == "done" and not commented(sonar, e):
                text = f"{data['reasons'][e['reason']]} (reviewed: {TRACKER})"
                sonar.call("POST", "api/issues/add_comment", {"issue": e["key"], "text": text})
                rows[i] = (kind, e, "commented", t)
    table(rows, out)
    return rows


def commented(sonar, e):
    """True when the issue already carries a comment linking the review."""
    live = sonar.issue(e["key"], e.get("branch", "main")) or {}
    return any(
        TRACKER in (c.get("markdown") or "") + (c.get("htmlText") or "")
        for c in live.get("comments") or []
    )


def table(rows, out):
    lines = [
        "| Project | Key | Rule | Location | Decision | State | Transition |",
        "|---|---|---|---|---|---|---|",
    ]
    for kind, e, state, t in rows:
        decision = e.get("decision") or e.get("resolution")
        lines.append(
            f"| {e['project'].removeprefix('swarm-routing_')} | `{e['key']}` | `{e['rule']}` | "
            f"`{e['file']}:{e['line']}` | {decision} ({e['reason']}) | {state} | {t or '-'} |"
        )
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    lines.append("")
    lines.append(
        "Total: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        if counts
        else "Total: 0"
    )
    text = "\n".join(lines)
    out(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")


# ---------------------------------------------------------------- self-test


def fake_sonar(state, token):
    """A fake SonarQube Cloud on 127.0.0.1: issues, hotspots, transitions, comments."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, obj):
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authed(self):
            return self.headers.get("Authorization") == f"Bearer {token}"

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            state["calls"].append(("GET", u.path, q, self.headers.get("Authorization")))
            if u.path == "/api/issues/search" and "issues" in q:
                i = state["issues"].get(q.get("issues"))
                if i is not None:
                    i = dict(i)
                    if not self.authed():
                        i["transitions"] = []
                    elif i["status"] in ("OPEN", "CONFIRMED", "REOPENED"):
                        i["transitions"] = list(state["transitions"])
                return self.send(200, {"issues": [i] if i else []})
            if u.path == "/api/issues/search" and "componentKeys" in q:
                got = [
                    i
                    for i in state["issues"].values()
                    if i["project"] == q["componentKeys"]
                    and i["status"] in ("OPEN", "CONFIRMED", "REOPENED")
                ]
                p = int(q.get("p", 1))
                return self.send(
                    200, {"issues": got[100 * (p - 1) : 100 * p], "paging": {"total": len(got)}}
                )
            if u.path == "/api/hotspots/search":
                got = [
                    {
                        "key": h["key"],
                        "project": h["project"]["key"],
                        "component": h["component"]["key"],
                        "ruleKey": h["rule"]["key"],
                        "line": h["line"],
                        "status": h["status"],
                    }
                    for h in state["hotspots"].values()
                    if h["project"]["key"] == q["projectKey"] and h["status"] == q["status"]
                ]
                return self.send(200, {"hotspots": got, "paging": {"total": len(got)}})
            if u.path == "/api/hotspots/show":
                h = state["hotspots"].get(q.get("hotspot"))
                return (
                    self.send(200, h) if h else self.send(404, {"errors": [{"msg": "not found"}]})
                )
            self.send(404, {})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            q = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode()))
            state["calls"].append(("POST", u.path, q, self.headers.get("Authorization")))
            if not self.authed() or state.get("forbid"):
                return self.send(403, {"errors": [{"msg": "Insufficient privileges"}]})
            if u.path == "/api/issues/do_transition":
                i = state["issues"][q["issue"]]
                res = {"falsepositive": "FALSE-POSITIVE", "wontfix": "WONTFIX", "accept": None}[
                    q["transition"]
                ]
                if q["transition"] == "accept":
                    i.update(status="ACCEPTED")
                else:
                    i.update(status="RESOLVED", resolution=res)
                return self.send(200, {"issue": i})
            if u.path == "/api/issues/add_comment":
                if state.get("fail_comment"):
                    state["fail_comment"] = False
                    return self.send(500, {"errors": [{"msg": "boom"}]})
                state["comments"].append((q["issue"], q["text"]))
                state["issues"][q["issue"]].setdefault("comments", []).append(
                    {"markdown": q["text"]}
                )
                return self.send(200, {})
            if u.path == "/api/hotspots/change_status":
                h = state["hotspots"][q["hotspot"]]
                h.update(status=q["status"], resolution=q["resolution"])
                state["comments"].append((q["hotspot"], q["comment"]))
                return self.send(204, {})
            self.send(404, {})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def fields(kind, live):
    """(project, rule, file, line) of a live issue or hotspot."""
    if kind == "issue":
        project, component, rule = live.get("project"), live.get("component", ""), live.get("rule")
    else:
        project = live.get("project")
        project = project.get("key") if isinstance(project, dict) else project
        component = live.get("component")
        component = component.get("key", "") if isinstance(component, dict) else component or ""
        rule = live.get("rule")
        rule = rule.get("key") if isinstance(rule, dict) else live.get("ruleKey", rule)
    path = component.split(":", 1)[1] if ":" in component else component
    return project, rule, path, live.get("line") or 0


def findings(data, repos, sonar, branch="main", out=print):
    """A line per open finding of each repository, and the entry that records it, if any."""
    recorded = {e["key"]: (k, e) for k, e in entries(data, "")}
    rows = []
    for repo in [r.strip() for r in repos.split(",") if r.strip()]:
        project = f"swarm-routing_{repo}"
        issues, hotspots = sonar.search(project, branch)
        for kind, live in [("issue", i) for i in issues] + [("hotspot", h) for h in hotspots]:
            _, rule, path, line = fields(kind, live)
            k = recorded.get(live["key"])
            note = "-"
            if k:
                e = k[1]
                note = f"recorded: {e.get('decision') or e.get('resolution')} ({e['reason']})"
            rows.append((repo, kind, live["key"], rule, f"{path}:{line}", note))
    out("| repo | kind | key | rule | at | decisions.toml |")
    out("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        out("| " + " | ".join(f"`{c}`" if i in (2, 3, 4) else c for i, c in enumerate(r)) + " |")
    todo = sum(1 for r in rows if r[5] == "-")
    out(f"\nTotal: {len(rows)} open, {len(rows) - todo} recorded, {todo} not recorded")
    return rows


def entry(data, key, reason, decision, sonar, branch="main"):
    """The TOML block that records KEY, every field read from the API."""
    if key in {e["key"] for _, e in entries(data, "")}:
        raise Refusal(f"{key}: already in the decisions file")
    if reason not in data.get("reasons", {}):
        raise Refusal(f"reason {reason!r} is not in [reasons]: add its text there first")
    live, kind = sonar.issue(key, branch), "issue"
    if live is None:
        live, kind = sonar.hotspot(key), "hotspot"
    if live is None:
        raise Refusal(f"{key}: no such issue or hotspot on {branch}")
    project, rule, path, line = fields(kind, live)
    if kind == "issue":
        decision = decision or "falsepositive"
        if decision not in ISSUE_DECISIONS:
            raise Refusal(f"an issue's decision is one of {', '.join(ISSUE_DECISIONS)}")
        last = f'decision = "{decision}"'
    else:
        decision = decision or "SAFE"
        if decision not in HOTSPOT_DECISIONS:
            raise Refusal(
                f"a hotspot's resolution is one of {', '.join(sorted(HOTSPOT_DECISIONS))}"
            )
        last = f'resolution = "{decision}"'
    return "\n".join(
        [
            f"[[{kind}]]",
            f'project = "{project}"',
            f'key = "{key}"',
            f'rule = "{rule}"',
            f'file = "{path}"',
            f"line = {line}",
            last,
            f'reason = "{reason}"',
        ]
    )


def self_test():
    import copy

    def check_(cond, msg):
        if not cond:
            print("FAIL:", msg)
            sys.exit(1)

    token = "squ_selftest_secret_value"
    issue = lambda key, rule, path, line: {  # noqa: E731
        "key": key, "project": "swarm-routing_demo", "component": f"swarm-routing_demo:{path}",
        "rule": rule, "line": line, "status": "OPEN",
    }  # fmt: skip
    base = {
        "issues": {
            "K1": issue("K1", "pythonsecurity:S8707", "tools/a.py", 10),
            "K2": issue("K2", "docker:S6471", "docker/Dockerfile", 3),
            "K9": issue("K9", "pythonsecurity:S2083", "tools/z.py", 5),  # not in the file
        },
        "hotspots": {
            "H1": {"key": "H1", "project": {"key": "swarm-routing_demo"},
                   "component": {"key": "swarm-routing_demo:tools/b.py"}, "rule": {"key": "python:S4507"},
                   "line": 7, "status": "TO_REVIEW", "canChangeStatus": True},
        },
        "transitions": ["confirm", "falsepositive", "accept"],
        "calls": [], "comments": [],
    }  # fmt: skip
    data = {
        "reasons": {"FP-cli": "the invoker's own argument", "FP-root": "a build image run as root"},
        "issue": [
            {"project": "swarm-routing_demo", "key": "K1", "rule": "pythonsecurity:S8707",
             "file": "tools/a.py", "line": 10, "decision": "falsepositive", "reason": "FP-cli"},
            {"project": "swarm-routing_demo", "key": "K2", "rule": "docker:S6471",
             "file": "docker/Dockerfile", "line": 3, "decision": "wontfix", "reason": "FP-root"},
        ],
        "hotspot": [
            {"project": "swarm-routing_demo", "key": "H1", "rule": "python:S4507",
             "file": "tools/b.py", "line": 7, "resolution": "SAFE", "reason": "FP-cli"},
        ],
    }  # fmt: skip

    # validate
    check_(validate(data) == [], f"a good file validates: {validate(data)}")
    bad = copy.deepcopy(data)
    bad["issue"][0]["decision"] = "ignore"
    bad["issue"][1]["reason"] = "FP-nope"
    bad["hotspot"][0]["key"] = "K1"
    errs = validate(bad)
    check_(
        len(errs) == 3 and "decision" in errs[0] and "FP-nope" in errs[1] and "twice" in errs[2],
        errs,
    )
    print("ok   validate: a good file; a bad decision, an unknown reason, a key twice")

    def go(state, apply, tok=token, repos=""):
        srv = fake_sonar(state, token)
        buf = []
        try:
            sonar = Sonar(f"http://127.0.0.1:{srv.server_address[1]}", tok)
            return run(data, repos, sonar, apply, out=buf.append), "\n".join(buf)
        finally:
            srv.shutdown()

    # plan: read-only, transitions known, the token never printed
    st = copy.deepcopy(base)
    rows, text = go(st, False)
    check_([r[2] for r in rows] == ["open", "open", "open"], rows)
    check_([r[3] for r in rows] == ["falsepositive", "accept", "REVIEWED"], [r[3] for r in rows])
    check_(not [c for c in st["calls"] if c[0] == "POST"], "plan posts nothing")
    check_(token not in text and "K9" not in text, "no token, no foreign key in the output")
    print("ok   plan: read-only; falsepositive, wontfix -> accept where offered, hotspot REVIEWED")

    # apply: transitions + comments, only the file's keys
    st = copy.deepcopy(base)
    rows, text = go(st, True)
    check_([r[2] for r in rows] == ["applied"] * 3, rows)
    check_(st["issues"]["K1"]["resolution"] == "FALSE-POSITIVE", st["issues"]["K1"])
    check_(st["issues"]["K2"]["status"] == "ACCEPTED", st["issues"]["K2"])
    check_(st["hotspots"]["H1"]["resolution"] == "SAFE", st["hotspots"]["H1"])
    check_(st["issues"]["K9"]["status"] == "OPEN", "a key outside the file is untouched")
    touched = {c[2].get("issue") or c[2].get("hotspot") for c in st["calls"] if c[0] == "POST"}
    check_(touched == {"K1", "K2", "H1"}, touched)
    check_([c[0] for c in st["comments"]] == ["K1", "K2", "H1"], st["comments"])
    check_(all(TRACKER in c[1] for c in st["comments"]), "each comment links the review")
    check_(all(c[3] == f"Bearer {token}" for c in st["calls"]), "Bearer auth on every call")
    print("ok   apply: K1 false positive, K2 accepted, H1 SAFE, each with its reason; K9 untouched")

    # re-run: done, nothing posted
    st["calls"].clear()
    rows, _ = go(st, True)
    check_([r[2] for r in rows] == ["done"] * 3, rows)
    check_(not [c for c in st["calls"] if c[0] == "POST"], "a re-run posts nothing")
    print("ok   re-run: every entry done, nothing posted")

    # mismatches refuse the whole run before any change
    for mutate, want in (
        (lambda s: s["issues"]["K1"].update(line=11), "line 11 != 10"),
        (lambda s: s["issues"]["K1"].update(rule="pythonsecurity:S2083"), "rule"),
        (lambda s: s["issues"].pop("K2"), "no such issue"),
        (
            lambda s: s["issues"]["K1"].update(status="RESOLVED", resolution="FIXED"),
            "already RESOLVED/FIXED",
        ),
    ):
        st = copy.deepcopy(base)
        mutate(st)
        try:
            go(st, True)
            check_(False, f"refusal expected: {want}")
        except Refusal as e:
            check_(want in str(e), f"{want!r} in {e}")
        check_(
            not [c for c in st["calls"] if c[0] == "POST"], f"nothing posted on a refusal ({want})"
        )
    print(
        "ok   refusals: a moved line, another rule, a gone key, another resolution; nothing posted"
    )

    # no rights: no transitions offered -> refuse with the token message; HTTP 403 too
    st = copy.deepcopy(base)
    st["transitions"] = []
    try:
        go(st, True)
        check_(False, "refusal expected without rights")
    except Refusal as e:
        check_("Administer Issues" in str(e) and token not in str(e), str(e))
    st = copy.deepcopy(base)
    st["forbid"] = True
    try:
        go(st, True)
        check_(False, "refusal expected on 403")
    except Refusal as e:
        check_("HTTP 403" in str(e) and "user token" in str(e), str(e))
    print("ok   no rights: no transition offered, or HTTP 403 -> the token message")

    # no token: plan works read-only, apply refuses
    st = copy.deepcopy(base)
    rows, _ = go(st, False, tok="")
    check_([r[3] for r in rows] == ["", "", ""], rows)
    try:
        go(copy.deepcopy(base), True, tok="")
        check_(False, "apply without a token must refuse")
    except Refusal as e:
        check_("SONAR_TOKEN" in str(e), str(e))
    print("ok   no token: plan read-only, apply refuses")

    # a comment that failed after its transition is added on the re-run, once
    st = copy.deepcopy(base)
    st["fail_comment"] = True
    try:
        go(st, True)
        check_(False, "the failed comment must stop the run")
    except Refusal:
        pass
    check_(st["issues"]["K1"]["resolution"] == "FALSE-POSITIVE", "K1 transitioned")
    rows, _ = go(st, True)
    states = {r[1]["key"]: r[2] for r in rows}
    check_(states["K1"] == "commented", states)
    rows, _ = go(st, True)
    check_({r[2] for r in rows} == {"done"}, rows)
    k1 = [c for c in st["comments"] if c[0] == "K1"]
    check_(len(k1) == 1, f"one comment on K1: {k1}")
    print("ok   a comment lost after its transition: added on the re-run, never twice")

    # the token only over https (loopback excepted, for this self-test)
    try:
        Sonar("http://sonar.example", token)
        check_(False, "plain http with a token must refuse")
    except Refusal as e:
        check_("https" in str(e) and token not in str(e), str(e))
    Sonar("http://sonar.example", "")  # read-only, no token: allowed
    print("ok   the token is only sent over https")

    # --repos filters
    st = copy.deepcopy(base)
    rows, _ = go(st, False, repos="other")
    check_(rows == [], rows)
    print("ok   --repos: another repository's entries only")

    # the real file validates
    # findings and entry: read-only, every field from the API
    st = copy.deepcopy(base)
    for n in range(120):  # a second page of issues
        st["issues"][f"P{n}"] = issue(f"P{n}", "python:S1244", "tools/p.py", n + 1)
    srv = fake_sonar(st, token)
    try:
        sonar = Sonar(f"http://127.0.0.1:{srv.server_address[1]}", "")
        buf = []
        rows = findings(data, "demo", sonar, out=buf.append)
        by = {r[2]: r for r in rows}
        check_(len(rows) == 124, f"every page read: {len(rows)}")
        check_(by["K1"][5] == "recorded: falsepositive (FP-cli)" and by["K9"][5] == "-", by["K9"])
        check_(by["H1"][1] == "hotspot" and by["H1"][4] == "tools/b.py:7", by["H1"])
        check_(buf[-1].endswith("124 open, 3 recorded, 121 not recorded"), buf[-1])
        block = entry(data, "K9", "FP-cli", None, sonar)
        parsed = tomllib.loads(block)["issue"][0]
        check_(
            parsed
            == {"project": "swarm-routing_demo", "key": "K9", "rule": "pythonsecurity:S2083",
                "file": "tools/z.py", "line": 5, "decision": "falsepositive", "reason": "FP-cli"},
            parsed,
        )  # fmt: skip
        merged = copy.deepcopy(data)
        merged["issue"].append(parsed)
        check_(validate(merged) == [], "the printed entry validates in the file")
        for args, want in (
            (("K1", "FP-cli", None), "already in the decisions file"),
            (("K9", "FP-new", None), "not in [reasons]"),
            (("K9", "FP-cli", "ignore"), "decision is one of"),
            (("NOPE", "FP-cli", None), "no such issue or hotspot"),
        ):
            try:
                entry(data, *args, sonar)
                check_(False, f"entry {args} should refuse")
            except Refusal as e:
                check_(want in str(e), f"{args}: {e}")
        check_(not [c for c in st["calls"] if c[0] == "POST"], "findings and entry post nothing")
    finally:
        srv.shutdown()
    print("ok   findings: every page, recorded or not; entry: the API's fields, refusals")

    with open(DEFAULT_FILE, "rb") as f:
        real = tomllib.load(f)
    errs = validate(real)
    check_(not errs, f"decisions.toml: {errs}")
    print(
        f"ok   decisions.toml: {len(real.get('issue', []))} issue(s), {len(real.get('hotspot', []))} hotspot(s), valid"
    )
    print("sonar_triage: all ok")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--self-test"]:
        self_test()
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("command", choices=("validate", "plan", "apply", "findings", "entry"))
    ap.add_argument("key", nargs="?", help="entry: the finding's key, from findings")
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--repos", default="", help="comma-separated repository names")
    ap.add_argument("--branch", default="main", help="findings, entry: the branch (default main)")
    ap.add_argument("--reason", help="entry: a reason id of the file's [reasons]")
    ap.add_argument(
        "--decision",
        help="entry: falsepositive (default) or wontfix; a hotspot: SAFE (default), ACKNOWLEDGED, FIXED",
    )
    a = ap.parse_args(argv)
    if a.command == "findings" and not a.repos:
        ap.error("findings needs --repos")
    if a.command == "entry" and not (a.key and a.reason):
        ap.error("entry needs KEY and --reason")
    try:
        data = load(a.file)
        if a.command == "validate":
            n = len(data.get("issue", [])) + len(data.get("hotspot", []))
            print(f"{a.file}: {n} entries, valid")
            return 0
        if a.command == "findings":
            findings(data, a.repos, Sonar(token=""), a.branch)
            return 0
        if a.command == "entry":
            print(entry(data, a.key, a.reason, a.decision, Sonar(token=""), a.branch))
            return 0
        run(data, a.repos, Sonar(), a.command == "apply")
    except Refusal as e:
        print(f"sonar_triage: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
