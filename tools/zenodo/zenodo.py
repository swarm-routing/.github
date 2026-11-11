#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Keep each org repository's Zenodo record in step with its GitHub releases.

Usage:
  zenodo.py repos [--org ORG] [--repos A,B]    the repos whose CITATION.cff names a Zenodo DOI
  zenodo.py status --repo OWNER/NAME [--concept ID] [--grace-hours H]
  zenodo.py sync   --repo OWNER/NAME [--concept ID] [--grace-hours H] [--dry-run] [--sandbox]
  zenodo.py --self-test

Zenodo's GitHub integration archives each published release and mints its DOI.
This is the check behind it, and the repair when a release was missed (as
AntHocNet's v2.6.1 was):

- The concept comes from the repository's CITATION.cff (`doi:` or an
  `identifiers:` DOI of the form 10.5281/zenodo.N) unless --concept is given.
- `status` lists every published, non-prerelease GitHub release against every
  version of the concept on Zenodo:
  - archived (with its DOI);
  - pending: younger than --grace-hours (default 12), so the integration may
    still be working on it;
  - missing: older than that, and newer than the newest archived release;
  - stranded: missing but older than the newest archived release. Adding it now
    would make it the concept's newest version, so it is left to the maintainer;
  - predates: older than the first archived release, from before the record
    existed (AntHocNet's v0.1.0). Reported, never an error.
- `sync` archives each missing release, oldest first, as a new version of the
  concept:
  - the files are GitHub's source zip of the tag, as the integration archives it;
  - the metadata is the previous version's, updated from the tag's
    CITATION.cff (title, abstract, authors, keywords), with the tag as
    `version`, the release's date, and the github.com/OWNER/NAME/tree/TAG link,
    so the new version names where the code lives now.
  A record of another concept is refused. A failed run leaves a draft that the
  next run reuses. Publishing makes a DOI permanent: there is no undo.
  --dry-run reads only and needs no token.

GitHub is read through `gh api` (the caller's login, or GH_TOKEN in a
workflow); Zenodo writes need ZENODO_TOKEN (scopes deposit:write and
deposit:actions), never passed on the command line. The CITATION.cff overlay
needs PyYAML; without it the previous version's metadata is kept, and the
output says so. Output is a summary line per release (AntHocNet ADR-0014);
with GITHUB_STEP_SUMMARY set, the table goes there too. Otherwise stdlib only.
"""

import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ZENODO = {False: "https://zenodo.org/api", True: "https://sandbox.zenodo.org/api"}
DOI_RE = re.compile(r"10\.5281/zenodo\.(\d+)")


class Failure(SystemExit):
    pass


# --- GitHub, through gh ------------------------------------------------------


class GitHub:
    def run(self, path, raw=False):
        r = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", path], capture_output=True
        )
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace").strip()
            if "HTTP 404" in err:
                return None
            raise Failure(f"gh api {path}: {err}")
        return r.stdout if raw else json.loads(r.stdout or b"null")

    def paged(self, path):
        sep = "&" if "?" in path else "?"
        out, page = [], 1
        while True:
            items = self.run(f"{path}{sep}per_page=100&page={page}") or []
            out += items
            if len(items) < 100:
                return out
            page += 1

    def releases(self, repo):
        rels = [
            r
            for r in self.paged(f"repos/{repo}/releases")
            if not r.get("draft") and not r.get("prerelease") and r.get("published_at")
        ]
        return sorted(
            ({"tag": r["tag_name"], "published": r["published_at"]} for r in rels),
            key=lambda r: r["published"],
        )

    def file(self, repo, path, ref=None):
        q = f"?ref={ref}" if ref else ""
        got = self.run(f"repos/{repo}/contents/{path}{q}")
        if not got or "content" not in got:
            return None
        return base64.b64decode(got["content"]).decode()

    def zipball(self, repo, tag):
        return self.run(f"repos/{repo}/zipball/{tag}", raw=True)

    def org_repos(self, org):
        return [
            r["name"]
            for r in self.paged(f"orgs/{org}/repos?type=public")
            if not r.get("archived") and not r.get("fork") and not r.get("private")
        ]


# --- Zenodo, through urllib --------------------------------------------------


class Zenodo:
    def __init__(self, base, token=None):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method, url, body=None, raw=None):
        if not url.startswith("http"):
            url = self.base + url
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif raw is not None:
            data, headers["Content-Type"] = raw, "application/octet-stream"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise Failure(f"zenodo: {method} {url.split('?')[0]}: HTTP {e.code}: {detail}")
        return json.loads(text) if text.strip() else {}

    def versions(self, concept):
        """Every published version of the concept, oldest first, and the newest one's id."""
        latest = self.call("GET", f"/records/{concept}")  # the concept redirects to its newest
        if str(latest.get("conceptrecid", "")) != str(concept):
            raise Failure(
                f"zenodo: {concept} is not a concept record "
                f"(it belongs to concept {latest.get('conceptrecid')})"
            )
        out, page = [], 1
        while True:
            hits = self.call("GET", f"/records/{latest['id']}/versions?size=25&page={page}")
            batch = hits.get("hits", {}).get("hits", [])
            out += [
                {
                    "id": str(h["id"]),
                    "version": h.get("metadata", {}).get("version", ""),
                    "doi": h.get("doi", ""),
                }
                for h in batch
            ]
            if len(batch) < 25:
                break
            page += 1
        return out, str(latest["id"])


# --- the plan ---------------------------------------------------------------


def norm(tag):
    return tag[1:] if tag[:1] in "vV" else tag


def concept_from(cff_text):
    if not cff_text:
        return None
    # the work's own DOI: top-level `doi:` or `identifiers:`, never a cited
    # work's under `references:` (another repository's concept, swarm-routing/.github#228)
    own = re.split(r"^references:", cff_text, maxsplit=1, flags=re.M)[0]
    m = re.search(r"^doi:\s*[\"']?10\.5281/zenodo\.(\d+)", own, re.M) or DOI_RE.search(own)
    return m.group(1) if m else None


def classify(releases, versions, now, grace_hours):
    """Each release with its state: archived, pending, missing, stranded or predates."""
    archived = {norm(v["version"]): v for v in versions}
    dates = [r["published"] for r in releases if norm(r["tag"]) in archived]
    newest_archived, oldest_archived = max(dates, default=""), min(dates, default="")
    rows = []
    for r in releases:
        v = archived.get(norm(r["tag"]))
        published = datetime.datetime.fromisoformat(r["published"].replace("Z", "+00:00"))
        age = (now - published).total_seconds() / 3600
        if v:
            state = "archived"
        elif age < grace_hours:
            state = "pending"
        elif r["published"] > newest_archived:
            state = "missing"
        elif r["published"] < oldest_archived:
            state = "predates"
        else:
            state = "stranded"
        rows.append({**r, "state": state, "doi": v["doi"] if v else "", "age_h": round(age, 1)})
    return rows


def cff_overlay(meta, cff_text):
    """Title, abstract, authors and keywords from CITATION.cff onto Zenodo metadata."""
    try:
        import yaml
    except ImportError:
        return meta, "PyYAML not installed: metadata copied from the previous version"
    cff = yaml.safe_load(cff_text) or {}
    meta = dict(meta)
    if cff.get("title"):
        meta["title"] = cff["title"]
    if cff.get("abstract"):
        meta["description"] = " ".join(str(cff["abstract"]).split())
    if cff.get("keywords"):
        meta["keywords"] = list(cff["keywords"])
    creators = []
    for a in cff.get("authors") or []:
        name = ", ".join(x for x in (a.get("family-names"), a.get("given-names")) if x) or a.get(
            "name"
        )
        if not name:
            continue
        c = {"name": name}
        if a.get("orcid"):
            c["orcid"] = str(a["orcid"]).rsplit("/", 1)[-1]
        if a.get("affiliation"):
            c["affiliation"] = a["affiliation"]
        creators.append(c)
    if creators:
        meta["creators"] = creators
    return meta, "metadata from CITATION.cff (title, abstract, authors, keywords)"


def release_metadata(old, repo, tag, date):
    meta = {k: v for k, v in old.items() if k not in ("doi", "prereserve_doi")}
    meta["version"] = tag
    meta["publication_date"] = date
    rel = [
        r
        for r in meta.get("related_identifiers", [])
        if not (r.get("relation") == "isSupplementTo" and "github.com/" in r.get("identifier", ""))
    ]
    rel.insert(
        0,
        {
            "identifier": f"https://github.com/{repo}/tree/{tag}",
            "relation": "isSupplementTo",
            "resource_type": "software",
            "scheme": "url",
        },
    )
    meta["related_identifiers"] = rel
    return meta


# --- archive one release ----------------------------------------------------


def new_version(zen, latest_id, concept, repo, tag, date, files, cff_text):
    dep = zen.call("GET", f"/deposit/depositions/{latest_id}")
    link = dep.get("links", {}).get("latest_draft", "")
    if link and not link.rstrip("/").endswith("/" + latest_id):
        note = "reused the draft an earlier run left"
    else:
        link = zen.call("POST", f"/deposit/depositions/{latest_id}/actions/newversion")["links"][
            "latest_draft"
        ]
        note = "opened a draft"
    draft = zen.call("GET", link)
    did = str(draft["id"])
    if str(draft.get("conceptrecid", concept)) != str(concept):
        raise Failure(f"zenodo: draft {did} is not under concept {concept}; not published")
    for f in draft.get("files", []):
        zen.call("DELETE", f"/deposit/depositions/{did}/files/{f['id']}")
    for name, data in files:
        zen.call("PUT", f"{draft['links']['bucket']}/{name}", raw=data)
    meta = release_metadata(draft.get("metadata", {}), repo, tag, date)
    meta_note = "metadata copied from the previous version (no CITATION.cff at the tag)"
    if cff_text:
        meta, meta_note = cff_overlay(meta, cff_text)
    zen.call("PUT", f"/deposit/depositions/{did}", body={"metadata": meta})
    rec = zen.call("POST", f"/deposit/depositions/{did}/actions/publish")
    doi = rec.get("doi") or rec.get("metadata", {}).get("doi", "")
    rid = str(rec.get("record_id") or rec.get("id") or did)
    return {"doi": doi, "id": rid, "note": f"{note}; {meta_note}"}


# --- commands ---------------------------------------------------------------


def resolve_concept(gh, repo, concept):
    if concept:
        return str(concept)
    c = concept_from(gh.file(repo, "CITATION.cff"))
    if not c:
        raise Failure(f"{repo}: no Zenodo DOI in CITATION.cff; pass --concept")
    return c


def report(repo, concept, rows, summary_path=None):
    for r in rows:
        extra = r["doi"] or (f"{r['age_h']} h old" if r["state"] == "pending" else "")
        print(f"{repo} {r['tag']}: {r['state']}{(' ' + extra) if extra else ''}")
    if summary_path:
        with open(summary_path, "a") as fh:
            fh.write(
                f"### {repo} (Zenodo concept {concept})\n\n| release | published | Zenodo |\n|---|---|---|\n"
            )
            for r in rows:
                fh.write(f"| {r['tag']} | {r['published'][:10]} | {r['state']} {r['doi']} |\n")
            fh.write("\n")


def cmd_status(args, gh, zen, now):
    concept = resolve_concept(gh, args.repo, args.concept)
    versions, _ = zen.versions(concept)
    rows = classify(gh.releases(args.repo), versions, now, args.grace_hours)
    report(args.repo, concept, rows, os.environ.get("GITHUB_STEP_SUMMARY"))
    return rows


def cmd_sync(args, gh, zen, now):
    concept = resolve_concept(gh, args.repo, args.concept)
    versions, latest_id = zen.versions(concept)
    rows = classify(gh.releases(args.repo), versions, now, args.grace_hours)
    if any(r["state"] == "missing" for r in rows) and not any(
        r["state"] == "archived" for r in rows
    ):
        # No release matches a Zenodo version (an empty `version`, another naming
        # scheme): every release would look missing, and each publish is permanent.
        raise Failure(
            f"{args.repo}: no release matches any of the {len(versions)} Zenodo versions of "
            f"concept {concept}; refusing to archive any (check the versions' `version` field)"
        )
    name = args.repo.split("/", 1)[1]
    for r in rows:
        if r["state"] != "missing":
            continue
        if args.dry_run:
            print(f"{args.repo} {r['tag']}: would archive as a new version of concept {concept}")
            continue
        if not zen.token:
            raise Failure("zenodo: ZENODO_TOKEN is not set (scopes deposit:write, deposit:actions)")
        zipped = gh.zipball(args.repo, r["tag"])
        if not zipped or not zipped.startswith(b"PK"):
            raise Failure(f"{args.repo} {r['tag']}: the source zip download is empty or not a zip")
        files = [(f"{name}-{r['tag']}.zip", zipped)]
        cff = gh.file(args.repo, "CITATION.cff", ref=r["tag"])
        got = new_version(
            zen, latest_id, concept, args.repo, r["tag"], r["published"][:10], files, cff
        )
        latest_id = got["id"]
        r.update(state="archived", doi=got["doi"])
        print(
            f"{args.repo} {r['tag']}: archived as {got['doi']} (record {got['id']}; {got['note']})"
        )
    report(args.repo, concept, rows, os.environ.get("GITHUB_STEP_SUMMARY"))
    stranded = [r["tag"] for r in rows if r["state"] == "stranded"]
    if stranded:
        raise Failure(
            f"{args.repo}: {', '.join(stranded)} missing on Zenodo but older than the newest "
            "archived release; adding one now would make it the newest version, so the "
            "maintainer decides (Zenodo's upload form can add an older version)"
        )
    return rows


def cmd_repos(args, gh):
    names = args.repos.split(",") if args.repos else gh.org_repos(args.org)
    found = []
    for n in names:
        c = concept_from(gh.file(f"{args.org}/{n}", "CITATION.cff"))
        if c:
            found.append(n)
            print(f"{args.org}/{n}: concept {c}")
    return found


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("repos")
    r.add_argument("--org", default="swarm-routing")
    r.add_argument("--repos", default="")
    r.add_argument("--json", action="store_true", help="print the names as a JSON list (a matrix)")
    for name in ("status", "sync"):
        s = sub.add_parser(name)
        s.add_argument("--repo", required=True)
        s.add_argument("--concept")
        s.add_argument("--grace-hours", type=float, default=12.0)
        s.add_argument("--sandbox", action="store_true")
        if name == "sync":
            s.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        p.error("a command is required")
    gh = GitHub()
    if args.cmd == "repos":
        found = cmd_repos(args, gh)
        if args.json:
            print(json.dumps(found))
        return 0
    zen = Zenodo(ZENODO[args.sandbox], os.environ.get("ZENODO_TOKEN") or None)
    now = datetime.datetime.now(datetime.timezone.utc)
    (cmd_status if args.cmd == "status" else cmd_sync)(args, gh, zen, now)
    return 0


# --- self-test: fake GitHub and a fake Zenodo on 127.0.0.1 -----------------


def self_test():
    import contextlib
    import io
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    CFF = (
        'cff-version: 1.2.0\ntitle: "New Title"\nabstract: >-\n  One line\n  two lines.\n'
        'authors:\n  - family-names: Doe\n    given-names: Jane\n    orcid: "https://orcid.org/0000-0001"\n'
        'keywords:\n  - ants\ndoi: "10.5281/zenodo.100"\n'
    )

    class FakeGitHub:
        def __init__(self, releases, cff=CFF):
            self.rel, self.cff, self.reads, self.zip = releases, cff, [], None

        def releases(self, repo):
            return sorted(self.rel, key=lambda r: r["published"])

        def file(self, repo, path, ref=None):
            self.reads.append((path, ref))
            return self.cff

        def zipball(self, repo, tag):
            return self.zip if self.zip is not None else f"PK zip of {tag}".encode()

    class State:
        def reset(self, versions=("v1.0.0", "v1.1.0"), concept="100", leftover=False):
            self.calls, self.uploads, self.meta, self.concept = [], {}, None, concept
            self.versions = [
                {"id": str(101 + i), "metadata": {"version": v}, "doi": f"10.0/z.{101 + i}"}
                for i, v in enumerate(versions)
            ]
            self.draft = (
                {"id": 300, "files": [{"id": "h", "filename": "half"}]} if leftover else None
            )
            self.next_id = 200

    st = State()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def route(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b""
            authed = self.headers.get("Authorization") == "Bearer t0k"
            path, _, query = self.path.partition("?")
            st.calls.append((method, path, authed))
            base = f"http://127.0.0.1:{self.server.server_port}/api"
            newest = st.versions[-1]
            if method == "GET" and path == f"/api/records/{st.concept}":
                return self.send(200, {"id": int(newest["id"]), "conceptrecid": st.concept})
            if method == "GET" and path == "/api/records/101":
                return self.send(200, {"id": 101, "conceptrecid": st.concept})
            if method == "GET" and path.endswith("/versions"):
                page = int(dict(x.split("=") for x in query.split("&"))["page"])
                return self.send(200, {"hits": {"hits": st.versions[(page - 1) * 25 : page * 25]}})
            if not authed:
                return self.send(403, {"message": "no token"})
            if method == "GET" and path == f"/api/deposit/depositions/{newest['id']}":
                own = st.draft["id"] if st.draft else newest["id"]
                return self.send(
                    200, {"links": {"latest_draft": f"{base}/deposit/depositions/{own}"}}
                )
            if method == "POST" and path.endswith("/actions/newversion"):
                st.draft = {"id": st.next_id, "files": [{"id": "f1", "filename": "old.zip"}]}
                st.next_id += 1
                return self.send(
                    201, {"links": {"latest_draft": f"{base}/deposit/depositions/{st.draft['id']}"}}
                )
            if st.draft and path == f"/api/deposit/depositions/{st.draft['id']}":
                if method == "GET":
                    return self.send(
                        200,
                        {
                            "id": st.draft["id"],
                            "conceptrecid": st.concept,
                            "files": st.draft["files"],
                            "links": {"bucket": f"{base}/files/b{st.draft['id']}"},
                            "metadata": {
                                "title": "Old Title",
                                "upload_type": "software",
                                "license": "gpl-2.0",
                                "prereserve_doi": {"doi": "x"},
                                "creators": [{"name": "Old"}],
                                "related_identifiers": [
                                    {
                                        "identifier": "https://github.com/old/R/tree/v1.1.0",
                                        "relation": "isSupplementTo",
                                        "scheme": "url",
                                    },
                                    {
                                        "identifier": "10.1/paper",
                                        "relation": "cites",
                                        "scheme": "doi",
                                    },
                                ],
                            },
                        },
                    )
                if method == "PUT":
                    st.meta = json.loads(data)["metadata"]
                    return self.send(200, {})
            if method == "DELETE" and st.draft and "/files/" in path:
                st.draft["files"] = [
                    f for f in st.draft["files"] if f["id"] != path.rsplit("/", 1)[1]
                ]
                return self.send(204, {})
            if method == "PUT" and path.startswith("/api/files/b"):
                st.uploads[path.rsplit("/", 1)[1]] = data
                return self.send(201, {})
            if (
                method == "POST"
                and st.draft
                and path.endswith(f"/{st.draft['id']}/actions/publish")
            ):
                rid = st.draft["id"]
                st.versions.append(
                    {
                        "id": str(rid),
                        "metadata": {"version": st.meta["version"]},
                        "doi": f"10.0/z.{rid}",
                    }
                )
                st.draft = None
                return self.send(202, {"id": rid, "record_id": rid, "doi": f"10.0/z.{rid}"})
            return self.send(404, {"message": f"fake: no route {method} {path}"})

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PUT(self):
            self.route("PUT")

        def do_DELETE(self):
            self.route("DELETE")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/api"
    now = datetime.datetime(2026, 11, 8, 12, tzinfo=datetime.timezone.utc)
    rel = [
        {"tag": "v1.0.0", "published": "2026-10-01T00:00:00Z"},
        {"tag": "v1.1.0", "published": "2026-10-10T00:00:00Z"},
        {"tag": "v1.2.0", "published": "2026-10-29T21:51:04Z"},
    ]
    failures = []

    def check(name, cond):
        if not cond:
            failures.append(name)

    def run(cmd, releases=rel, token="t0k", cff=CFF, **kw):
        ns = argparse.Namespace(
            repo="org/R", concept=None, grace_hours=12.0, dry_run=False, sandbox=False
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        gh = FakeGitHub(releases, cff)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                rows, err = (
                    (cmd_status if cmd == "status" else cmd_sync)(ns, gh, Zenodo(base, token), now),
                    None,
                )
            except Failure as e:
                rows, err = None, str(e)
        return rows, err, out.getvalue(), gh

    # concept from CITATION.cff: the `doi:` field wins over an identifiers DOI
    check(
        "concept from doi",
        concept_from('identifiers:\n  - value: "10.5281/zenodo.7"\ndoi: "10.5281/zenodo.100"\n')
        == "100",
    )
    check(
        "concept from identifiers",
        concept_from('identifiers:\n  - value: "10.5281/zenodo.7"\n') == "7",
    )
    check("no concept", concept_from("title: x\n") is None and concept_from(None) is None)
    check(
        "a cited work's Zenodo DOI is never the concept",
        concept_from('title: x\nreferences:\n  - type: software\n    doi: "10.5281/zenodo.9"\n')
        is None,
    )
    # status: archived, missing, pending and stranded
    st.reset()
    rows, err, out, _ = run("status")
    check(
        "status ok",
        err is None and [r["state"] for r in rows] == ["archived", "archived", "missing"],
    )
    check("status read only", all(c[0] == "GET" for c in st.calls))
    young = rel[:2] + [{"tag": "v1.2.0", "published": "2026-11-08T06:00:00Z"}]
    st.reset()
    rows, err, out, _ = run("status", releases=young)
    check("pending within grace", rows[-1]["state"] == "pending")
    st.reset(versions=("v1.0.0", "v1.2.0"))
    rows, err, out, _ = run("status")
    check("stranded", [r["state"] for r in rows] == ["archived", "stranded", "archived"])
    st.reset(versions=("v1.1.0", "v1.2.0"))
    rows, err, out, _ = run("status")
    check("predates the record", [r["state"] for r in rows] == ["predates", "archived", "archived"])
    st.reset(versions=("v1.1.0",))
    rows, err, out, _ = run("sync", token=None, dry_run=True)
    check("predates is not an error", err is None and "would archive" in out)
    st.reset(versions=("1.0.0", "1.1.0"))
    rows, err, out, _ = run("status")
    check("tags match without the v", [r["state"] for r in rows][:2] == ["archived", "archived"])
    # sync: the missing release becomes a new version, metadata from CITATION.cff
    st.reset()
    rows, err, out, gh = run("sync")
    check(
        "sync ok",
        err is None and rows[-1]["state"] == "archived" and rows[-1]["doi"] == "10.0/z.200",
    )
    check("sync uploaded the tag's zip", st.uploads == {"R-v1.2.0.zip": b"PK zip of v1.2.0"})
    check("CITATION.cff read at the tag", ("CITATION.cff", "v1.2.0") in gh.reads)
    m = st.meta or {}
    check(
        "version and release date",
        m.get("version") == "v1.2.0" and m.get("publication_date") == "2026-10-29",
    )
    check("cff title", m.get("title") == "New Title")
    check("cff abstract folded", m.get("description") == "One line two lines.")
    check("cff authors", m.get("creators") == [{"name": "Doe, Jane", "orcid": "0000-0001"}])
    check("cff keywords", m.get("keywords") == ["ants"])
    check("licence kept", m.get("license") == "gpl-2.0")
    check("prereserve dropped", "prereserve_doi" not in m)
    rel_ids = [r["identifier"] for r in m.get("related_identifiers", [])]
    check(
        "github link moved",
        rel_ids[0] == "https://github.com/org/R/tree/v1.2.0"
        and not any("github.com/old" in i for i in rel_ids)
        and "10.1/paper" in rel_ids,
    )
    check(
        "inherited file removed",
        not any(c[0] == "PUT" and c[1].endswith("/old.zip") for c in st.calls),
    )
    check("publish last", st.calls[-1][1].endswith("/actions/publish"))
    # sync again: nothing to do, read only
    st.calls = []
    rows, err, out, _ = run("sync")
    check("second sync is a no-op", err is None and all(c[0] == "GET" for c in st.calls))
    # two missing releases are archived oldest first, each on top of the last
    st.reset(versions=("v1.0.0",))
    rows, err, out, _ = run("sync")
    check(
        "two archived in order",
        [v["metadata"]["version"] for v in st.versions] == ["v1.0.0", "v1.1.0", "v1.2.0"],
    )
    # dry run: no token, read only
    st.reset()
    rows, err, out, _ = run("sync", token=None, dry_run=True)
    check(
        "dry run", err is None and "would archive" in out and all(c[0] == "GET" for c in st.calls)
    )
    # no token: refused before any write
    st.reset()
    rows, err, out, _ = run("sync", token=None)
    check(
        "missing token refused",
        err and "ZENODO_TOKEN" in err and all(c[0] == "GET" for c in st.calls),
    )
    # a stranded release fails the run without writing
    st.reset(versions=("v1.0.0", "v1.2.0"))
    rows, err, out, _ = run("sync")
    check(
        "stranded fails, no write", err and "v1.1.0" in err and all(c[0] == "GET" for c in st.calls)
    )
    # a draft left by a failed run is reused
    st.reset(leftover=True)
    rows, err, out, _ = run("sync")
    check(
        "leftover draft reused",
        err is None
        and rows[-1]["doi"] == "10.0/z.300"
        and not any(c[1].endswith("/newversion") for c in st.calls),
    )
    # no release matches any Zenodo version: refused, nothing written
    st.reset(versions=("release-1", "release-2"))
    rows, err, out, _ = run("sync")
    check(
        "no match refused",
        err and "no release matches" in err and all(c[0] == "GET" for c in st.calls),
    )
    st.reset(versions=("release-1",))
    rows, err, out, _ = run("sync", token=None, dry_run=True)
    check("no match refused in a dry run too", err and "no release matches" in err)
    # an empty or non-zip download is refused before the draft is touched
    for bad in (b"", None, b"<html>not found</html>"):
        st.reset()
        gh_bad = FakeGitHub(rel)
        gh_bad.zip = bad if bad is not None else b""
        ns = argparse.Namespace(
            repo="org/R", concept=None, grace_hours=12.0, dry_run=False, sandbox=False
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_sync(ns, gh_bad, Zenodo(base, "t0k"), now)
            err = None
        except Failure as e:
            err = str(e)
        check(
            f"bad zip {bad!r} refused",
            err and "not a zip" in err and all(c[0] == "GET" for c in st.calls),
        )
    # a version record passed as --concept is refused
    st.reset()
    rows, err, out, _ = run("status", concept="101")
    check("version id is not a concept", err and "not a concept record" in err)
    # no CITATION.cff at the tag: metadata kept from the previous version
    st.reset()
    rows, err, out, _ = run("sync", cff=None, concept="100")
    check(
        "no cff: previous title kept",
        err is None
        and (st.meta or {}).get("title") == "Old Title"
        and "copied from the previous version" in out,
    )
    srv.shutdown()
    for f in failures:
        print(f"FAIL: {f}")
    print(f"self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
