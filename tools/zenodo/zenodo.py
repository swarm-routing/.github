#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Keep each org repository's Zenodo record in step with its GitHub releases.

Usage:
  zenodo.py repos [--org ORG] [--repos A,B]    the repos whose CITATION.cff names a Zenodo DOI
  zenodo.py status --repo OWNER/NAME [--concept ID] [--grace-hours H]
  zenodo.py sync   --repo OWNER/NAME [--concept ID] [--grace-hours H] [--dry-run] [--sandbox]
  zenodo.py orphans [--org ORG] [--repos A,B] [--grace-hours H] [--sandbox]
  zenodo.py create --repo OWNER/NAME --tag vX.Y.Z [--publish] [--sandbox]
  zenodo.py publish-release --repo OWNER/NAME --tag vX.Y.Z --files F... [--checkout DIR]
            [--concept ID] [--date YYYY-MM-DD] [--publish] [--sandbox]
  zenodo.py fake-zenodo --port-file F           the self-test's fake Zenodo, for release-selftest.yml
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
- `orphans` lists every repository with a published release but no concept:
  no DOI in CITATION.cff, no `zenodo_concept` in .github/org-sync.toml. `sync`
  cannot see those, because it only adds versions to a concept. One whose
  first release failed on Zenodo (benchmarks v0.1.0, swarm-routing/.github#226)
  is reported as `no concept`, and the exit code is 1 once its first release
  is older than --grace-hours. A release Zenodo already holds (found by its
  github.com/OWNER/NAME/tree/TAG link) is `unrecorded`: set `zenodo_concept`.
- `create` archives a tag as the FIRST version of a new concept, for such a
  repository: the tag's source zip and its CITATION.cff metadata, as `sync`
  does for a version, with `upload_type` dataset when CITATION.cff says
  `type: dataset` (else software). It refuses when a concept already exists
  (CITATION.cff, `zenodo_concept`, or a Zenodo record linking one of the
  repository's release tags), so it never makes a duplicate. A dry run unless
  --publish is given and ZENODO_TOKEN is set; it prints the concept and
  version DOIs. A draft a failed run left is reused.
- `publish-release` is the push path (swarm-routing/.github#232): the release
  job of reusable-release.yml (`zenodo: true`) archives the release it just
  published, with the release's own assets (--files: the dist files,
  SHA256SUMS, the SBOM, the provenance) instead of a source zip, so Zenodo
  never reads GitHub. With --checkout, CITATION.cff and .github/org-sync.toml
  come from the release commit's checkout. It is idempotent: a tag already
  archived (the token owner's published depositions, which Zenodo lists
  without the search index's lag, or a version of the concept) is reported
  and nothing is written. Otherwise the tag becomes a new version of the
  concept `create` would find (CITATION.cff, `zenodo_concept`, a Zenodo
  record linking one of the release tags), or, with none, the first version
  of a new concept with `create`'s metadata. The concept and version DOIs go
  to the output and the job summary. A dry run unless --publish is given;
  --publish without ZENODO_TOKEN is refused.

Every Zenodo call is retried with exponential backoff (5 s, doubling, 5
tries; Retry-After honoured): a 429 or 503 always, a 500, 502 or 504 or a
dropped connection only when the call is not a POST. Any other refusal stops
the command with a non-zero exit.

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
import time
import urllib.error
import urllib.parse
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


class Checkout(GitHub):
    """GitHub, with the repository's files read from a local checkout (the release commit)."""

    def __init__(self, root):
        self.root = root

    def file(self, repo, path, ref=None):
        p = os.path.join(self.root, path)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return fh.read()


# --- Zenodo, through urllib --------------------------------------------------


class Zenodo:
    # Retried with backoff: a rate limit (429) always, since Zenodo did not act
    # on the request; a gateway error or a dropped connection only for a call
    # that is safe to repeat (a POST may have acted: the next run's checks
    # find what it left, a draft or a published version).
    RETRY_ALWAYS = (429, 503)
    RETRY_IDEMPOTENT = (500, 502, 504)

    def __init__(self, base, token=None, tries=5, backoff=5.0):
        self.base = base.rstrip("/")
        self.token = token
        self.tries, self.backoff = tries, backoff

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
        where = f"zenodo: {method} {url.split('?')[0]}"
        for attempt in range(1, self.tries + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            wait = self.backoff * 2 ** (attempt - 1)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    text = r.read().decode()
                return json.loads(text) if text.strip() else {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                again = e.code in self.RETRY_ALWAYS or (
                    method != "POST" and e.code in self.RETRY_IDEMPOTENT
                )
                if not again or attempt == self.tries:
                    raise Failure(f"{where}: HTTP {e.code}: {detail}")
                after = (e.headers.get("Retry-After") or "").strip()
                if after.isdigit():
                    wait = max(wait, min(int(after), 300))
                print(f"{where}: HTTP {e.code}, retry {attempt}/{self.tries - 1} in {wait:g} s")
            except urllib.error.URLError as e:
                if method == "POST" or attempt == self.tries:
                    raise Failure(f"{where}: {e.reason}")
                print(f"{where}: {e.reason}, retry {attempt}/{self.tries - 1} in {wait:g} s")
            time.sleep(wait)
        raise Failure(f"{where}: no attempt left")  # unreachable: the last attempt raises

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
                    "conceptdoi": h.get("conceptdoi", ""),
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
            "resource_type": meta.get("upload_type") or "software",
            "scheme": "url",
        },
    )
    meta["related_identifiers"] = rel
    return meta


def zenodo_license(spdx):
    """Zenodo's licence id for CITATION.cff's SPDX licence (the first of an expression)."""
    if isinstance(spdx, list):
        spdx = spdx[0] if spdx else ""
    first = re.split(r"\s+(?:OR|AND|WITH)\s+", str(spdx or "").strip())[0].strip("() ")
    return re.sub(r"-only$", "", first.lower()) or None


def first_metadata(repo, tag, date, cff_text):
    """A new concept's metadata, from the tag's CITATION.cff alone."""
    try:
        import yaml
    except ImportError:
        raise Failure("create: PyYAML is needed to read CITATION.cff (pip install pyyaml)")
    cff = yaml.safe_load(cff_text) or {}
    base = {
        "upload_type": "dataset" if cff.get("type") == "dataset" else "software",
        "access_right": "open",
    }
    lic = zenodo_license(cff.get("license"))
    if lic:
        base["license"] = lic
    if cff.get("message"):
        base["notes"] = " ".join(str(cff["message"]).split())
    meta, _ = cff_overlay(release_metadata(base, repo, tag, date), cff_text)
    if not meta.get("title") or not meta.get("creators"):
        raise Failure(f"{repo} {tag}: CITATION.cff has no title or no authors; not created")
    meta.setdefault("description", meta["title"])
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
    return {
        "doi": doi,
        "id": rid,
        "concept": str(rec.get("conceptrecid") or concept),
        "conceptdoi": rec.get("conceptdoi") or "",
        "note": f"{note}; {meta_note}",
    }


def tree_link(repo, tag):
    return f"https://github.com/{repo}/tree/{tag}"


def links_of(meta):
    return [
        str(r.get("identifier", "")).lower() for r in (meta or {}).get("related_identifiers", [])
    ]


def create_concept(zen, repo, tag, meta, files):
    """Publish a tag as the first version of a new concept (a new deposition)."""
    link = tree_link(repo, tag).lower()
    drafts = zen.call("GET", "/deposit/depositions?status=draft&size=100") or []
    left = [d for d in drafts if link in links_of(d.get("metadata")) and not d.get("submitted")]
    if left:
        draft = zen.call("GET", f"/deposit/depositions/{left[0]['id']}")
        note = "reused the draft an earlier run left"
    else:
        draft = zen.call("POST", "/deposit/depositions", body={})
        note = "opened a new deposition"
    did = str(draft["id"])
    # the metadata first: a run that fails after it leaves a draft the next run finds
    zen.call("PUT", f"/deposit/depositions/{did}", body={"metadata": meta})
    for f in draft.get("files", []):
        zen.call("DELETE", f"/deposit/depositions/{did}/files/{f['id']}")
    for name, data in files:
        zen.call("PUT", f"{draft['links']['bucket']}/{name}", raw=data)
    rec = zen.call("POST", f"/deposit/depositions/{did}/actions/publish")
    concept = str(rec.get("conceptrecid") or draft.get("conceptrecid") or "")
    return {
        "doi": rec.get("doi") or rec.get("metadata", {}).get("doi", ""),
        "id": str(rec.get("record_id") or rec.get("id") or did),
        "concept": concept,
        "conceptdoi": rec.get("conceptdoi") or "",
        "note": note,
    }


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


def recorded_concept(gh, repo):
    """The concept the repository names: CITATION.cff, else org-sync's `zenodo_concept`."""
    c = concept_from(gh.file(repo, "CITATION.cff"))
    if c:
        return c, "CITATION.cff"
    toml = gh.file(repo, ".github/org-sync.toml") or ""
    m = re.search(r"^\s*zenodo_concept\s*=\s*[\"']?(\d+)", toml, re.M)
    return (m.group(1), ".github/org-sync.toml zenodo_concept") if m else (None, "")


def zenodo_concept_for(zen, repo, tags):
    """A Zenodo record that links one of the tags' github.com tree, as (concept, why)."""
    for tag in tags:
        link = tree_link(repo, tag)
        q = urllib.parse.urlencode(
            {"q": f'related.identifier:"{link}"', "all_versions": "true", "size": 10}
        )
        hits = zen.call("GET", f"/records?{q}").get("hits", {}).get("hits", [])
        for h in hits:  # the search is fuzzy: only an exact link counts
            if link.lower() in links_of(h.get("metadata")):
                why = f"Zenodo record {h['id']} links {link}"
                return str(h.get("conceptrecid") or h["id"]), why
    return None, ""


def cmd_create(args, gh, zen, now):
    repo, tag = args.repo, args.tag
    rels = gh.releases(repo)
    rel = next((r for r in rels if r["tag"] == tag), None)
    if not rel:
        raise Failure(f"{repo}: {tag} is not a published, non-prerelease GitHub release")
    concept, why = recorded_concept(gh, repo)
    if not concept:
        concept, why = zenodo_concept_for(zen, repo, [r["tag"] for r in rels])
    if concept:
        raise Failure(
            f"{repo}: concept {concept} already exists ({why}); `create` only makes a first "
            f"concept, so {tag} goes to that one through `sync`"
        )
    cff = gh.file(repo, "CITATION.cff", ref=tag)
    if not cff:
        raise Failure(f"{repo} {tag}: no CITATION.cff at the tag, so no metadata; not created")
    meta = first_metadata(repo, tag, rel["published"][:10], cff)
    fname = f"{repo.split('/', 1)[1]}-{tag}.zip"
    plan = (
        f"a new Zenodo concept from {tag} ({meta['upload_type']}, title {meta['title']!r}, "
        f"licence {meta.get('license') or '-'}, file {fname})"
    )
    if not (args.publish and zen.token):
        if args.publish:
            print(
                "warning: ZENODO_TOKEN is not set (scopes deposit:write, deposit:actions): dry run"
            )
        print(f"{repo} {tag}: would create {plan}")
        return {"state": "dry-run"}
    zipped = gh.zipball(repo, tag)
    if not zipped or not zipped.startswith(b"PK"):
        raise Failure(f"{repo} {tag}: the source zip download is empty or not a zip")
    got = create_concept(zen, repo, tag, meta, [(fname, zipped)])
    print(
        f"{repo} {tag}: created {plan}; concept {got['concept']} ({got['conceptdoi'] or 'DOI pending'}), "
        f"version {got['doi']} (record {got['id']}; {got['note']})"
    )
    print(
        f'next: zenodo_concept = "{got["concept"]}" in {repo}\'s .github/org-sync.toml, then '
        "`org_sync.py reseed CITATION.cff` (keep its `type:`)"
    )
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(
                f"### {repo} {tag}: new Zenodo concept\n\n| concept | concept DOI | version DOI |\n"
                f"|---|---|---|\n| {got['concept']} | {got['conceptdoi']} | {got['doi']} |\n\n"
            )
    return {"state": "created", **got}


def deposited(zen, repo, tag):
    """A published deposition of the token's owner that links the tag's tree.

    Zenodo's record search and version lists are an index that can lag a
    publish by minutes; the owner's own deposition list is not, so a re-run
    right after a publish still sees it and does not archive the tag twice.
    """
    link = tree_link(repo, tag).lower()
    q = urllib.parse.urlencode({"size": 100, "sort": "mostrecent", "all_versions": "true"})
    for d in zen.call("GET", f"/deposit/depositions?{q}") or []:
        if d.get("submitted") and link in links_of(d.get("metadata")):
            return d
    return None


def release_files(paths):
    files = []
    for p in paths:
        if not os.path.isfile(p):
            raise Failure(f"{p}: not a file; nothing archived")
        with open(p, "rb") as fh:
            files.append((os.path.basename(p), fh.read()))
    names = [n for n, _ in files]
    if not files or len(set(names)) != len(names):
        raise Failure(f"--files: none given, or two with one name ({', '.join(names)})")
    return files


def summarize(repo, tag, state, got):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a") as fh:
        fh.write(
            f"### {repo} {tag} on Zenodo: {state}\n\n"
            "| concept | concept DOI | version DOI |\n|---|---|---|\n"
            f"| {got.get('concept') or '-'} | {got.get('conceptdoi') or '-'} | "
            f"{got.get('doi') or '-'} |\n\n"
        )


def cmd_publish_release(args, gh, zen, now):
    """Archive one published release with its own assets (the release job's push, #232)."""
    repo, tag = args.repo, args.tag
    files = release_files(args.files)
    write = bool(args.publish and zen.token)
    if args.publish and not zen.token:
        raise Failure(
            "zenodo: --publish needs ZENODO_TOKEN (scopes deposit:write, deposit:actions)"
        )
    if write:
        d = deposited(zen, repo, tag)
        if d:
            got = {
                "concept": str(d.get("conceptrecid") or ""),
                "conceptdoi": d.get("conceptdoi") or "",
                "doi": d.get("doi") or "",
                "id": str(d.get("record_id") or d.get("id") or ""),
            }
            print(
                f"{repo} {tag}: already archived as {got['doi']} (record {got['id']}); nothing to do"
            )
            summarize(repo, tag, "already archived", got)
            return {"state": "archived", **got}
    rels = gh.releases(repo)
    rel = next((r for r in rels if r["tag"] == tag), None)
    date = args.date or (rel["published"][:10] if rel else now.date().isoformat())
    cff = gh.file(repo, "CITATION.cff", ref=tag)
    if args.concept:
        concept, why = str(args.concept), "--concept"
    else:
        concept, why = recorded_concept(gh, repo)
    if not concept:
        others = [r["tag"] for r in rels if r["tag"] != tag]
        concept, why = zenodo_concept_for(zen, repo, [tag, *others])
    listed = ", ".join(n for n, _ in files)
    if concept:
        versions, latest_id = zen.versions(concept)
        have = next((v for v in versions if norm(v["version"]) == norm(tag)), None)
        if have:
            got = {"concept": concept, "conceptdoi": have["conceptdoi"], **have}
            print(
                f"{repo} {tag}: already archived as {have['doi']} (concept {concept}); nothing to do"
            )
            summarize(repo, tag, "already archived", got)
            return {"state": "archived", **got}
        plan = f"a new version of concept {concept} ({why}), files {listed}"
    else:
        if not cff:
            raise Failure(f"{repo} {tag}: no CITATION.cff, so no metadata for a first concept")
        meta = first_metadata(repo, tag, date, cff)
        plan = (
            f"a new Zenodo concept ({meta['upload_type']}, title {meta['title']!r}, "
            f"licence {meta.get('license') or '-'}), files {listed}"
        )
    if not write:
        print(f"{repo} {tag}: would archive as {plan}")
        return {"state": "dry-run"}
    if concept:
        got = new_version(zen, latest_id, concept, repo, tag, date, files, cff)
        state = "new version"
    else:
        got = create_concept(zen, repo, tag, meta, files)
        state = "new concept"
    print(
        f"{repo} {tag}: archived as {plan}: version {got['doi']} (record {got['id']}), "
        f"concept {got['concept']} ({got['conceptdoi'] or 'DOI pending'}); {got['note']}"
    )
    if state == "new concept":
        print(
            f'next: zenodo_concept = "{got["concept"]}" in {repo}\'s .github/org-sync.toml, then '
            "`org_sync.py reseed CITATION.cff` (keep its `type:`)"
        )
    summarize(repo, tag, state, got)
    return {"state": state, **got}


def cmd_orphans(args, gh, zen, now):
    """Each repository with a published release and no concept: (repo, state, detail)."""
    names = args.repos.split(",") if args.repos else gh.org_repos(args.org)
    rows = []
    for n in names:
        repo = n if "/" in n else f"{args.org}/{n}"
        if recorded_concept(gh, repo)[0]:
            continue
        rels = gh.releases(repo)
        if not rels:
            continue
        tags = [r["tag"] for r in rels]
        concept, why = zenodo_concept_for(zen, repo, tags)
        first = datetime.datetime.fromisoformat(rels[0]["published"].replace("Z", "+00:00"))
        age = round((now - first).total_seconds() / 3600, 1)
        if concept:
            state = "unrecorded"
            detail = f"concept {concept} ({why}): set zenodo_concept and reseed CITATION.cff"
        elif age < args.grace_hours:
            state, detail = "pending", f"{tags[0]} is {age} h old"
        else:
            state = "no concept"
            detail = (
                f"{len(tags)} release(s) since {tags[0]}, none on Zenodo; recover with "
                f"`zenodo.py create --repo {repo} --tag {tags[0]} --publish` (zenodo.yml, mode create)"
            )
        rows.append((repo, state, detail))
        print(f"{repo}: {state}: {detail}")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path and rows:
        with open(path, "a") as fh:
            fh.write("### Released repositories without a Zenodo concept\n\n")
            fh.write("| repository | state | detail |\n|---|---|---|\n")
            fh.writelines(f"| {r} | {s} | {d} |\n" for r, s, d in rows)
            fh.write("\n")
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
    o = sub.add_parser("orphans")
    o.add_argument("--org", default="swarm-routing")
    o.add_argument("--repos", default="")
    o.add_argument("--grace-hours", type=float, default=12.0)
    o.add_argument("--sandbox", action="store_true")
    c = sub.add_parser("create")
    c.add_argument("--repo", required=True)
    c.add_argument("--tag", required=True)
    c.add_argument(
        "--publish", action="store_true", help="write (needs ZENODO_TOKEN); else a dry run"
    )
    c.add_argument("--sandbox", action="store_true")
    pr = sub.add_parser("publish-release")
    pr.add_argument("--repo", required=True)
    pr.add_argument("--tag", required=True)
    pr.add_argument(
        "--files", nargs="+", required=True, help="the release's assets, uploaded as they are"
    )
    pr.add_argument(
        "--checkout", help="read CITATION.cff and .github/org-sync.toml here, not through gh"
    )
    pr.add_argument(
        "--concept", help="the concept to add a version to (default: as `create` finds it)"
    )
    pr.add_argument("--date", help="publication date, YYYY-MM-DD (default: the release's)")
    pr.add_argument(
        "--publish", action="store_true", help="write (needs ZENODO_TOKEN); else a dry run"
    )
    pr.add_argument("--sandbox", action="store_true")
    pr.add_argument("--api", help=argparse.SUPPRESS)  # another Zenodo API base (the fake)
    f = sub.add_parser("fake-zenodo")
    f.add_argument("--port-file", required=True)
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        p.error("a command is required")
    if args.cmd == "fake-zenodo":
        srv, _ = fake_zenodo()
        with open(args.port_file, "w") as fh:
            fh.write(f"{srv.server_port}\n")
        print(f"fake Zenodo on http://127.0.0.1:{srv.server_port}/api (token t0k)", flush=True)
        while True:
            time.sleep(3600)
    gh = Checkout(args.checkout) if getattr(args, "checkout", None) else GitHub()
    if args.cmd == "repos":
        found = cmd_repos(args, gh)
        if args.json:
            print(json.dumps(found))
        return 0
    zen = Zenodo(
        getattr(args, "api", None) or ZENODO[args.sandbox], os.environ.get("ZENODO_TOKEN") or None
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    if args.cmd == "orphans":
        rows = cmd_orphans(args, gh, zen, now)
        return 1 if any(s == "no concept" for _, s, _ in rows) else 0
    cmds = {
        "status": cmd_status,
        "sync": cmd_sync,
        "create": cmd_create,
        "publish-release": cmd_publish_release,
    }
    cmds[args.cmd](args, gh, zen, now)
    return 0


# --- the fake Zenodo: the self-test's, and `fake-zenodo` for release-selftest.yml --


def fake_zenodo():
    """A fake Zenodo on 127.0.0.1, serving in a thread: (server, state). Token: t0k."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
            self.search = []  # what the fake's record search returns, whatever the query
            self.published = []  # the owner's published depositions, as the deposit list shows them
            self.fail_next = []  # HTTP codes the next requests get, one each, before any route

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
            if st.fail_next:
                return self.send(st.fail_next.pop(0), {"message": "fake: told to fail"})
            base = f"http://127.0.0.1:{self.server.server_port}/api"
            newest = st.versions[-1]
            if method == "GET" and path == f"/api/records/{st.concept}":
                return self.send(200, {"id": int(newest["id"]), "conceptrecid": st.concept})
            if method == "GET" and path == "/api/records/101":
                return self.send(200, {"id": 101, "conceptrecid": st.concept})
            if method == "GET" and path.endswith("/versions"):
                page = int(dict(x.split("=") for x in query.split("&"))["page"])
                return self.send(200, {"hits": {"hits": st.versions[(page - 1) * 25 : page * 25]}})
            if method == "GET" and path == "/api/records":
                return self.send(200, {"hits": {"hits": st.search}})
            if not authed:
                return self.send(403, {"message": "no token"})
            if method == "GET" and path == "/api/deposit/depositions":
                new = st.draft and st.draft.get("new")
                listed = {"id": st.draft["id"], "metadata": st.meta or {}} if new else None
                return self.send(200, ([listed] if listed else []) + st.published)
            if method == "POST" and path == "/api/deposit/depositions":
                st.draft = {"id": st.next_id, "files": [], "new": True}
                st.next_id += 1
                return self.send(
                    201,
                    {
                        "id": st.draft["id"],
                        "conceptrecid": "500",
                        "files": [],
                        "links": {"bucket": f"{base}/files/b{st.draft['id']}"},
                    },
                )
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
                cid = "500" if st.draft.get("new") else st.concept
                st.versions.append(
                    {
                        "id": str(rid),
                        "metadata": {"version": st.meta["version"]},
                        "doi": f"10.0/z.{rid}",
                    }
                )
                st.published.append(
                    {
                        "id": rid,
                        "record_id": rid,
                        "submitted": True,
                        "doi": f"10.0/z.{rid}",
                        "conceptrecid": cid,
                        "conceptdoi": f"10.0/z.{cid}",
                        "metadata": st.meta,
                    }
                )
                st.draft = None
                return self.send(
                    202,
                    {
                        "id": rid,
                        "record_id": rid,
                        "doi": f"10.0/z.{rid}",
                        "conceptrecid": cid,
                        "conceptdoi": f"10.0/z.{cid}",
                    },
                )
            return self.send(404, {"message": f"fake: no route {method} {path}"})

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PUT(self):
            self.route("PUT")

        def do_DELETE(self):
            self.route("DELETE")

    st.reset()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st


# --- self-test: fake GitHub and a fake Zenodo on 127.0.0.1 -----------------


def self_test():
    import contextlib
    import io
    import tempfile

    CFF = (
        'cff-version: 1.2.0\ntitle: "New Title"\nabstract: >-\n  One line\n  two lines.\n'
        'authors:\n  - family-names: Doe\n    given-names: Jane\n    orcid: "https://orcid.org/0000-0001"\n'
        'keywords:\n  - ants\ndoi: "10.5281/zenodo.100"\n'
    )

    class FakeGitHub:
        def __init__(self, releases, cff=CFF, toml=None):
            self.rel, self.cff, self.reads, self.zip = releases, cff, [], None
            self.toml = toml

        def releases(self, repo):
            return sorted(self.rel, key=lambda r: r["published"])

        def file(self, repo, path, ref=None):
            self.reads.append((path, ref))
            return self.toml if path == ".github/org-sync.toml" else self.cff

        def org_repos(self, org):
            return ["R"]

        def zipball(self, repo, tag):
            return self.zip if self.zip is not None else f"PK zip of {tag}".encode()

    srv, st = fake_zenodo()
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
    # create: the first concept of a repository Zenodo never archived
    NEW = (
        'cff-version: 1.2.0\nmessage: "Cite the dataset."\ntitle: "R data"\ntype: dataset\n'
        "license: GPL-2.0-only\nauthors:\n  - family-names: Doe\n    given-names: Jane\n"
    )

    def go(fn, gh, token="t0k", **kw):
        ns = argparse.Namespace(
            repo="org/R", tag="v1.2.0", publish=True, org="org", repos="R", grace_hours=12.0
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                got, err = fn(ns, gh, Zenodo(base, token), now), None
            except Failure as e:
                got, err = None, str(e)
        return got, err, out.getvalue()

    def only_reads():
        return all(c[0] == "GET" for c in st.calls)

    st.reset()
    got, err, out = go(cmd_create, FakeGitHub(rel, NEW), token=None)
    check(
        "create without a token is a dry run",
        err is None and "would create" in out and "dataset" in out and only_reads(),
    )
    st.reset()
    got, err, out = go(cmd_create, FakeGitHub(rel, NEW), publish=False)
    check("create without --publish is a dry run", err is None and "would" in out and only_reads())
    st.reset()
    gh = FakeGitHub(rel, NEW)
    got, err, out = go(cmd_create, gh)
    m = st.meta or {}
    check(
        "create ok",
        err is None
        and got["concept"] == "500"
        and got["doi"] == "10.0/z.200"
        and "concept 500 (10.0/z.500)" in out
        and "version 10.0/z.200" in out,
    )
    check(
        "create metadata",
        m.get("upload_type") == "dataset"
        and m.get("license") == "gpl-2.0"
        and m.get("version") == "v1.2.0"
        and m.get("publication_date") == "2026-10-29"
        and m.get("title") == "R data"
        and m.get("notes") == "Cite the dataset."
        and m.get("creators") == [{"name": "Doe, Jane"}]
        and m.get("related_identifiers", [{}])[0].get("resource_type") == "dataset",
    )
    check("create uploaded the tag's zip", st.uploads == {"R-v1.2.0.zip": b"PK zip of v1.2.0"})
    check("create read CITATION.cff at the tag", ("CITATION.cff", "v1.2.0") in gh.reads)
    check(
        "create is a new deposition, not a version",
        ("POST", "/api/deposit/depositions", True) in st.calls
        and not any(c[1].endswith("/newversion") for c in st.calls)
        and st.calls[-1][1].endswith("/actions/publish"),
    )
    # a draft an earlier create left is reused
    st.reset()
    st.draft = {"id": 400, "new": True, "files": [{"id": "h", "filename": "half"}]}
    st.meta = {"related_identifiers": [{"identifier": "https://github.com/org/R/tree/v1.2.0"}]}
    got, err, out = go(cmd_create, FakeGitHub(rel, NEW))
    check(
        "create reuses its draft",
        err is None
        and got["doi"] == "10.0/z.400"
        and "reused" in out
        and ("POST", "/api/deposit/depositions", True) not in st.calls
        and any(c[0] == "DELETE" and c[1].endswith("/files/h") for c in st.calls),
    )
    # an existing concept refuses, before any write: CITATION.cff, zenodo_concept, a Zenodo record
    for name, gh, search in (
        ("CITATION.cff doi", FakeGitHub(rel), []),
        ("zenodo_concept", FakeGitHub(rel, NEW, toml='kind = "data"\nzenodo_concept = "42"\n'), []),
        (
            "a Zenodo record of a release",
            FakeGitHub(rel, NEW),
            [
                {
                    "id": 77,
                    "conceptrecid": "76",
                    "metadata": {
                        "related_identifiers": [
                            {"identifier": "https://github.com/org/R/tree/v1.0.0"}
                        ]
                    },
                }
            ],
        ),
    ):
        st.reset()
        st.search = search
        got, err, out = go(cmd_create, gh)
        check(f"create refused: {name}", err and "already exists" in err and only_reads())
    # the search is fuzzy: a record linking another repository is not a concept of this one
    st.reset()
    st.search = [
        {
            "id": 9,
            "conceptrecid": "8",
            "metadata": {
                "related_identifiers": [{"identifier": "https://github.com/x/R2/tree/v1.0.0"}]
            },
        }
    ]
    got, err, out = go(cmd_create, FakeGitHub(rel, NEW), token=None)
    check("create ignores another repository's record", err is None and "would create" in out)
    st.reset()
    got, err, out = go(cmd_create, FakeGitHub(rel, NEW), tag="v9.9.9")
    check("create refuses a tag that is not a release", err and "not a published" in err)
    # orphans: released repositories without a concept
    st.reset()
    got, err, out = go(cmd_orphans, FakeGitHub(rel, NEW), token=None)
    check(
        "orphan past grace",
        err is None
        and [s for _, s, _ in got] == ["no concept"]
        and "zenodo.py create --repo org/R --tag v1.0.0" in out
        and only_reads(),
    )
    young1 = [{"tag": "v0.1.0", "published": "2026-11-08T06:00:00Z"}]
    got, err, out = go(cmd_orphans, FakeGitHub(young1, NEW), token=None)
    check("orphan within grace is pending", [s for _, s, _ in got] == ["pending"])
    st.search = [
        {
            "id": 77,
            "conceptrecid": "76",
            "metadata": {
                "related_identifiers": [{"identifier": "https://github.com/org/R/tree/v1.1.0"}]
            },
        }
    ]
    got, err, out = go(cmd_orphans, FakeGitHub(rel, NEW), token=None)
    check("archived but unrecorded", [s for _, s, _ in got] == ["unrecorded"] and "76" in out)
    got, err, out = go(cmd_orphans, FakeGitHub(rel), token=None)
    check("a repository with a concept is no orphan", got == [])
    got, err, out = go(cmd_orphans, FakeGitHub([], NEW), token=None)
    check("a repository without a release is no orphan", got == [])
    check(
        "licence ids",
        zenodo_license("MIT OR GPL-2.0-only") == "mit" and zenodo_license(None) is None,
    )
    # publish-release: the release job's push path (#232), with the release's own assets
    tmp = tempfile.mkdtemp()
    assets = []
    for name, body in (("r-1.2.0.tar.gz", b"tarball"), ("SHA256SUMS", b"sums\n")):
        assets.append(os.path.join(tmp, name))
        with open(assets[-1], "wb") as fh:
            fh.write(body)
    summary = os.path.join(tmp, "summary.md")

    def push(gh, token="t0k", tries=5, **kw):
        ns = argparse.Namespace(
            repo="org/R", tag="v1.2.0", files=assets, concept=None, date=None, publish=True
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        out = io.StringIO()
        old = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = summary
        with contextlib.redirect_stdout(out):
            try:
                got, err = cmd_publish_release(ns, gh, Zenodo(base, token, tries, 0), now), None
            except Failure as e:
                got, err = None, str(e)
        if old is None:
            os.environ.pop("GITHUB_STEP_SUMMARY")
        else:
            os.environ["GITHUB_STEP_SUMMARY"] = old
        return got, err, out.getvalue()

    # a first release: a new concept, the assets as they are, metadata from CITATION.cff
    st.reset()
    got, err, out = push(FakeGitHub(rel, NEW))
    m = st.meta or {}
    check(
        "push: first release is a new concept",
        err is None
        and got["state"] == "new concept"
        and got["concept"] == "500"
        and got["doi"] == "10.0/z.200"
        and ("POST", "/api/deposit/depositions", True) in st.calls
        and not any(c[1].endswith("/newversion") for c in st.calls),
    )
    check(
        "push: the release's assets uploaded, no source zip",
        st.uploads == {"r-1.2.0.tar.gz": b"tarball", "SHA256SUMS": b"sums\n"},
    )
    check(
        "push: first metadata",
        m.get("title") == "R data"
        and m.get("version") == "v1.2.0"
        and m.get("upload_type") == "dataset",
    )
    with open(summary) as fh:
        text = fh.read()
    check("push: DOIs in the summary", "| 500 | 10.0/z.500 | 10.0/z.200 |" in text)
    # the same release again: found among the owner's depositions, nothing written
    st.calls = []
    got, err, out = push(FakeGitHub(rel, NEW))
    check(
        "push: a re-run is a no-op",
        err is None and got["state"] == "archived" and got["doi"] == "10.0/z.200" and only_reads(),
    )
    # the next version of an existing concept (CITATION.cff names it)
    st.reset()
    gh = FakeGitHub(rel)
    got, err, out = push(gh)
    check(
        "push: next release is a new version",
        err is None
        and got["state"] == "new version"
        and got["doi"] == "10.0/z.200"
        and got["concept"] == "100"
        and any(c[1].endswith("/newversion") for c in st.calls)
        and ("POST", "/api/deposit/depositions", True) not in st.calls,
    )
    check(
        "push: version files and metadata",
        set(st.uploads) == {"r-1.2.0.tar.gz", "SHA256SUMS"}
        and (st.meta or {}).get("version") == "v1.2.0"
        and (st.meta or {}).get("publication_date") == "2026-10-29"
        and (st.meta or {}).get("title") == "New Title"
        and not any(c[0] == "PUT" and c[1].endswith("/old.zip") for c in st.calls),
    )
    st.calls = []
    got, err, out = push(FakeGitHub(rel))
    check(
        "push: a re-run of the version is a no-op",
        got and got["state"] == "archived" and only_reads(),
    )
    # a version Zenodo already holds (archived by the GitHub integration): no write
    st.reset()
    got, err, out = push(FakeGitHub(rel), tag="v1.1.0")
    check(
        "push: a version already on the concept is a no-op",
        err is None and got["state"] == "archived" and got["doi"] == "10.0/z.102" and only_reads(),
    )
    # a dry run reads only; --publish without a token is refused
    st.reset()
    got, err, out = push(FakeGitHub(rel), publish=False)
    check("push: dry run", err is None and "would archive as a new version" in out and only_reads())
    st.reset()
    got, err, out = push(FakeGitHub(rel), token=None)
    check("push: no token refused", err and "ZENODO_TOKEN" in err and st.calls == [])
    # a refusal stops the run (a wrong token: 403), nothing written
    st.reset()
    got, err, out = push(FakeGitHub(rel), token="wrong")
    check("push: a refusal fails", err and "HTTP 403" in err and only_reads())
    # a missing asset is refused before Zenodo is called
    st.reset()
    got, err, out = push(FakeGitHub(rel), files=[os.path.join(tmp, "nope")])
    check("push: a missing asset is refused", err and "not a file" in err and st.calls == [])
    # retries: a 429 and a 503 are retried; a 502 on a POST and a 400 are not
    st.reset()
    st.fail_next = [429, 503]
    got, err, out = push(FakeGitHub(rel))
    check(
        "push: 429 and 503 retried",
        err is None and got["state"] == "new version" and "retry 2/4" in out,
    )
    st.reset()
    st.fail_next = [429, 429, 429]
    got, err, out = push(FakeGitHub(rel), tries=3)
    check("push: retries run out", err and "HTTP 429" in err and only_reads())
    st.reset()
    st.fail_next = [400]
    got, err, out = push(FakeGitHub(rel))
    check("push: a 400 is not retried", err and "HTTP 400" in err and len(st.calls) == 1)
    zen = Zenodo(base, "t0k", 5, 0)
    st.reset()
    st.fail_next = [502]
    try:
        zen.call("POST", "/deposit/depositions/101/actions/newversion")
        err = None
    except Failure as e:
        err = str(e)
    check("push: a 502 on a POST is not retried", err and "HTTP 502" in err and len(st.calls) == 1)
    # a local checkout's files
    with open(os.path.join(tmp, "CITATION.cff"), "w") as fh:
        fh.write(NEW)
    check(
        "checkout reads local files",
        Checkout(tmp).file("org/R", "CITATION.cff", ref="v1") == NEW
        and Checkout(tmp).file("org/R", ".github/org-sync.toml") is None,
    )
    srv.shutdown()
    for f in failures:
        print(f"FAIL: {f}")
    print(f"self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
