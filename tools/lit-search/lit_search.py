#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Confirm a reference and find new papers, from free sources only.

  lit_search.py confirm DOI            Crossref's record, field by field (title, authors,
                                       year, venue, volume, issue, pages, type) against
                                       Semantic Scholar's and OpenAlex's; exit 1 on a
                                       `differ` in year, venue, authors or pages
  lit_search.py confirm --title TEXT [--year Y]
                                       a work without a DOI (a thesis, a tech report):
                                       Crossref's and Semantic Scholar's best matches,
                                       each line naming its source
  lit_search.py citing DOI [--since Y] [--until Y] [--sort cited|year] [--limit N]
                                       the works that cite it (OpenCitations, titles from
                                       one Semantic Scholar batch): follow-up work. The
                                       first path to new papers
  lit_search.py refs DOI [--sort year|cited] [--limit N]
                                       its reference list, the same way
  lit_search.py search QUERY [--since Y] [--until Y] [--type T] [--sort relevance|cited|year]
                       [--limit N] [--crossref] [--preprints] [--openalex]
                                       Semantic Scholar's search; --crossref adds Crossref's,
                                       --preprints arXiv's, --openalex OpenAlex's (needs a key)
  lit_search.py related DOI [--limit N]
                                       Semantic Scholar's recommendations: noisy and
                                       recency-biased, a last resort; sorted by citations
  lit_search.py --self-test            offline, on recorded responses of every source

After any command, --library FILE ... marks each work whose DOI a Markdown
file names: `[listed]` when the file's name says it is a download list (it
contains "download"), else `[saved]`; listed wins. --abstract (search, citing,
refs, related) adds the abstract, cut to about 60 words. --limit is 1 to 25
(default 10). Before the command, --no-cache skips the cache.

One line per work: year · title · venue · DOI · cited N · open access · source.

Every source is free and needs no key: Crossref (api.crossref.org), Semantic
Scholar's Graph and Recommendations APIs, the OpenCitations Index (v2), the
arXiv API, and OpenAlex's single-record lookups (/works/<id> costs nothing).
OpenAlex's search and list calls draw on a daily budget, so the tool makes them
only with a key (`--openalex`, OPENALEX_API_KEY; the key is free). Semantic
Scholar's keyless pool is shared and answers HTTP 429 when busy: calls to it
are spaced at least 1 s apart and retried once; a free key in S2_API_KEY (sent
as x-api-key) lifts the limit. A key never appears in the output, an error, the
cache key or a cache file. In `confirm`, a cross-check source that is down or
rate-limited is reported `unavailable` and the check goes on.

Requests carry a generic User-Agent and no contact address. Responses are
cached under $XDG_CACHE_HOME/swarm-routing-lit-search/ (default ~/.cache/):
single records for 30 days, searches and lists for 1 day. Exit codes: 0 done,
1 `confirm` found a differ that matters, 2 an error, 3 a source is rate-limited
or out of budget (try later; output printed so far stands). Stdlib only.
"""

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CROSSREF = "https://api.crossref.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper"
S2_REC = "https://api.semanticscholar.org/recommendations/v1/papers"
OC = "https://api.opencitations.net/index/v2"
ARXIV = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works"
UA = "swarm-routing-lit-search/1.0"
PAUSE = {"s2": 1.1, "crossref": 1.0, "oc": 0.5, "arxiv": 3.0, "openalex": 0.2}
NAMES = {
    "s2": "Semantic Scholar",
    "crossref": "Crossref",
    "oc": "OpenCitations",
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
}
BACKOFF = {"s2": 8, "crossref": 5, "oc": 5, "arxiv": 5, "openalex": 5}  # before the one retry
RECORD_AGE = 30 * 86400
LIST_AGE = 86400
MAX_LIMIT = 25
ABSTRACT_WORDS = 60
BATCH = 500  # Semantic Scholar's batch endpoint takes up to 500 ids
CRITICAL = ("year", "venue", "authors", "pages")  # a differ here is exit 1
S2_FIELDS = "title,year,venue,journal,citationCount,externalIds,openAccessPdf,publicationTypes"
S2_RECORD = S2_FIELDS + ",authors"
DOI_RX = re.compile(r"10\.\d{4,9}/[^\s|\]>\"'`*,;]+")
STATE = {
    "cache": os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
        "swarm-routing-lit-search",
    ),
    "fetch": None,  # the self-test's fake network; None is the real one
    "sleep": time.sleep,
    "err": lambda msg: print(msg, file=sys.stderr),
    "keys": {},  # {"openalex": ..., "s2": ...}, read from the environment in main()
}


class Failure(Exception):
    pass


class RateLimited(Failure):
    """A source answered HTTP 429 twice."""

    def __init__(self, source):
        if source == "openalex":
            msg = (
                "OpenAlex budget exhausted for today; its single-record lookups (confirm) "
                "still work"
            )
        elif source == "s2":
            msg = (
                "Semantic Scholar is rate-limited, try later (its keyless pool is shared; "
                "a free S2_API_KEY lifts the limit)"
            )
        else:
            msg = f"{NAMES[source]} is rate-limited, try later"
        super().__init__(msg)
        self.source = source


class HTTPStatus(Exception):
    """A non-200 answer. It carries no URL and no header: either could carry a key."""

    def __init__(self, code, retry_after=None):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.retry_after = retry_after


# --- the network ------------------------------------------------------------------------


def _source(url):
    for name, base in (
        ("s2", "https://api.semanticscholar.org/"),
        ("crossref", CROSSREF),
        ("oc", OC),
        ("arxiv", ARXIV),
        ("openalex", OPENALEX),
    ):
        if url.startswith(base):
            return name
    raise Failure(f"no source for {url}")


def _urlopen(method, url, headers, body):
    """The response text at url; None for a 404. Errors carry the status only."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise HTTPStatus(e.code, (e.headers or {}).get("Retry-After")) from None
    except urllib.error.URLError as e:
        raise Failure(f"network error: {e.reason}") from None
    except (OSError, http.client.HTTPException, UnicodeDecodeError) as e:
        # a read timeout, a dropped connection, a cut or undecodable body: the
        # source is unavailable, so its caller's per-source handling applies
        raise Failure(f"network error: {type(e).__name__}") from None


def request(url, max_age, body=None):
    """The text at url (None for a 404), from the cache while fresh. url and body carry
    no key: an OpenAlex key is added to the URL and a Semantic Scholar key to the
    headers only for the request itself."""
    source = _source(url)
    ident = ("POST " if body is not None else "GET ") + url
    if body is not None:
        ident += " " + json.dumps(body, sort_keys=True)
    path = None
    if STATE["cache"]:
        path = os.path.join(STATE["cache"], hashlib.sha256(ident.encode()).hexdigest() + ".json")
        try:
            with open(path, encoding="utf-8") as fh:
                hit = json.load(fh)
            if hit["request"] == ident and time.time() - hit["fetched"] < max_age:
                return hit["data"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    headers = {"User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = "application/json"
    sent = url
    key = STATE["keys"].get(source)
    if key and source == "s2":
        headers["x-api-key"] = key
    elif key and source == "openalex":
        sent += ("&" if "?" in url else "?") + "api_key=" + urllib.parse.quote(key)
    fetch = STATE["fetch"] or _urlopen
    for attempt in (1, 2):
        try:
            data = fetch("POST" if body is not None else "GET", sent, headers, body)
            break
        except HTTPStatus as e:
            if e.code == 429 and attempt == 1:
                wait = str(e.retry_after or "")
                STATE["sleep"](min(int(wait), 10) if wait.isdigit() else BACKOFF[source])
                continue
            if e.code == 429:
                raise RateLimited(source) from None
            if e.code == 403 and key:
                raise Failure(
                    f"{NAMES[source]}: HTTP 403 with its API key set (a key not yet "
                    "activated is refused); unset it to call without one"
                ) from None
            raise Failure(f"{NAMES[source]}: {e}") from None
    STATE["sleep"](PAUSE[source])
    if path:
        tmp = None
        try:  # the cache only saves requests: an unwritable one never fails the command
            os.makedirs(STATE["cache"], exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=STATE["cache"], suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"request": ident, "fetched": time.time(), "data": data}, fh)
            os.replace(tmp, path)
        except OSError:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    return data


def get_json(url, max_age, body=None):
    text = request(url, max_age, body)
    return json.loads(text) if text else None


# --- one shape for a work from any source -----------------------------------------------


def norm_doi(doi):
    d = (doi or "").strip()
    for p in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.lower().startswith(p):
            d = d[len(p) :]
    return d.lower()


def q(doi):
    return urllib.parse.quote(norm_doi(doi), safe="/:()")


def cut(text, words=ABSTRACT_WORDS):
    w = re.sub(r"<[^>]+>", " ", text or "").split()
    if not w:
        return None
    return " ".join(w[:words]) + (" …" if len(w) > words else "")


def from_s2(p):
    ids = p.get("externalIds") or {}
    oa = ((p.get("openAccessPdf") or {}).get("status") or "").lower()
    alt = f"arXiv:{ids['ArXiv']}" if ids.get("ArXiv") else f"S2 {p.get('paperId', '?')[:10]}"
    return {
        "year": p.get("year"),
        "title": p.get("title"),
        "venue": p.get("venue") or (p.get("journal") or {}).get("name"),
        "doi": norm_doi(ids.get("DOI")),
        "alt": alt,
        "cited": p.get("citationCount"),
        "oa": oa if oa and oa != "closed" else ("closed" if oa else None),
        "source": "S2",
        "abstract": p.get("abstract"),
    }


def _cr_year(item):
    for key in ("issued", "published-print", "published-online", "published"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return parts[0][0]
    return None


def from_crossref(item):
    return {
        "year": _cr_year(item),
        "title": " ".join(((item.get("title") or [""])[0]).split()) or None,
        "venue": (item.get("container-title") or [None])[0]
        or (item.get("institution") or [{}])[0].get("name"),
        "doi": norm_doi(item.get("DOI")),
        "alt": item.get("type"),
        "cited": item.get("is-referenced-by-count"),
        "oa": None,
        "source": "Crossref",
        "abstract": item.get("abstract"),
    }


def from_openalex(w):
    index = w.get("abstract_inverted_index") or {}
    words = [word for _, word in sorted((p, word) for word, ps in index.items() for p in ps)]
    return {
        "year": w.get("publication_year"),
        "title": w.get("display_name"),
        "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "doi": norm_doi(w.get("doi")),
        "alt": (w.get("id") or "").rsplit("/", 1)[-1],
        "cited": w.get("cited_by_count"),
        "oa": (w.get("open_access") or {}).get("oa_status"),
        "source": "OpenAlex",
        "abstract": " ".join(words) or None,
    }


ATOM = "{http://www.w3.org/2005/Atom}"


def from_arxiv(xml_text):
    out = []
    root = ET.fromstring(xml_text)
    for e in root.findall(f"{ATOM}entry"):
        aid = (e.findtext(f"{ATOM}id") or "").rsplit("/abs/", 1)[-1]
        doi = e.findtext("{http://arxiv.org/schemas/atom}doi")
        out.append(
            {
                "year": int((e.findtext(f"{ATOM}published") or "0")[:4]) or None,
                "title": " ".join((e.findtext(f"{ATOM}title") or "").split()),
                "venue": "arXiv",
                "doi": norm_doi(doi),
                "alt": f"arXiv:{aid}",
                "cited": None,
                "oa": "green",
                "source": "arXiv",
                "abstract": e.findtext(f"{ATOM}summary"),
            }
        )
    return out


def library_marks(paths):
    """{doi: 'saved'|'listed'} from the DOIs the Markdown files name."""
    marks = {}
    for path in paths or []:
        mark = "listed" if "download" in os.path.basename(path).lower() else "saved"
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in DOI_RX.finditer(text):
            d = m.group(0)
            while d and (d[-1] in ".:" or (d[-1] == ")" and d.count(")") > d.count("("))):
                d = d[:-1]
            d = d.lower()
            if marks.get(d) != "listed":
                marks[d] = mark
    return marks


def line(w, marks=None, with_abstract=False):
    """year · title · venue · DOI · cited N · open access · source [mark]"""
    cited = w.get("cited")
    parts = [
        str(w.get("year") or "—"),
        " ".join((w.get("title") or "(no title in any source)").split()),
        w.get("venue") or "—",
        w.get("doi") or f"no DOI ({w.get('alt') or '?'})",
        f"cited {cited}" if cited is not None else "cited ?",
        w.get("oa") or "oa ?",
        w["source"],
    ]
    out = " · ".join(parts)
    mark = (marks or {}).get(w.get("doi") or "")
    if mark:
        out += f" [{mark}]"
    if with_abstract:
        out += "\n    " + (cut(w.get("abstract")) or "(no abstract in this source)")
    return out


def order(works, sort):
    if sort == "cited":
        return sorted(works, key=lambda w: -(w.get("cited") or -1))
    if sort == "year":
        return sorted(works, key=lambda w: -(w.get("year") or 0))
    if sort == "oldest":
        return sorted(works, key=lambda w: (w.get("year") or 9999, w.get("title") or ""))
    return works


# --- confirm ----------------------------------------------------------------------------


def _fold(text):
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _words(text):
    return re.findall(r"[a-z0-9]+", _fold(text))


STOP = set("of the and for on in a an to proceedings conference international ieee acm".split())
# Crossref types in the others' words (OpenAlex files conference papers as articles)
TYPES = {
    "journal-article": {"article", "JournalArticle"},
    "proceedings-article": {"article", "Conference"},
    "posted-content": {"preprint"},
    "book-chapter": {"book-chapter", "BookSection"},
    "book": {"book", "Book"},
    "dissertation": {"dissertation"},
    "report": {"report"},
}


def same_venue(a, b):
    """Equal, mostly the same words, a shared acronym, or one an abbreviation of the
    other ("Eur. Trans. Telecommun." for European Transactions on Telecommunications)."""
    wa, wb = [w for w in _words(a) if w not in STOP], [w for w in _words(b) if w not in STOP]
    if wa == wb:
        return True
    sa, sb = set(wa), set(wb)
    if sa and sb and len(sa & sb) / min(len(sa), len(sb)) >= 0.6:
        return True
    acr = set(re.findall(r"\b[A-Z]{3,}\b", a)) & set(re.findall(r"\b[A-Z]{3,}\b", b))
    if acr - {"IEEE", "ACM"}:
        return True
    for short, full in ((wa, wb), (wb, wa)):
        if short and len(short) <= len(full):
            it = iter(full)
            if all(any(f.startswith(s) for f in it) for s in short):
                return True
    return False


def _authors_same(fams, names):
    if len(fams) != len(names):
        return False
    return all(" ".join(_words(f)) in " ".join(_words(n)) for f, n in zip(fams, names))


def _pages_same(a, b):
    a1, _, a2 = str(a).replace("–", "-").partition("-")
    b1, _, b2 = str(b).replace("–", "-").partition("-")
    return a1.strip() == b1.strip() and (not a2 or not b2 or a2.strip() == b2.strip())


def fields_crossref(m):
    fams = [a.get("family") or a.get("name") or "" for a in m.get("author", [])]
    return {
        "title": " ".join(((m.get("title") or [""])[0]).split()),
        "authors": fams,
        "year": _cr_year(m),
        "venue": (m.get("container-title") or [None])[0],
        "volume": m.get("volume"),
        "issue": m.get("issue"),
        "pages": m.get("page"),
        "type": m.get("type"),
    }


def fields_s2(p):
    j = p.get("journal") or {}
    venues = [v for v in (p.get("venue"), j.get("name")) if v]
    return {
        "title": p.get("title"),
        "authors": [a.get("name") or "" for a in p.get("authors", [])],
        "year": p.get("year"),
        "venue": venues,
        "volume": (j.get("volume") or "").strip() or None,
        "issue": None,  # Semantic Scholar has no issue field
        "pages": (j.get("pages") or "").strip() or None,
        "type": p.get("publicationTypes"),
    }


def fields_openalex(w):
    b = w.get("biblio") or {}
    first, last = b.get("first_page"), b.get("last_page")
    pages = (first or "") + (f"-{last}" if last and last != first else "")
    return {
        "title": w.get("display_name"),
        "authors": [
            au.get("raw_author_name") or (au.get("author") or {}).get("display_name") or ""
            for au in w.get("authorships", [])
        ],
        "year": w.get("publication_year"),
        "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "volume": b.get("volume"),
        "issue": b.get("issue"),
        "pages": pages or None,
        "type": w.get("type"),
    }


def agrees(field, ref, other):
    """Does `other` (one source's value) agree with Crossref's `ref`?"""
    if field == "title":
        return _words(ref) == _words(other)
    if field == "authors":
        return _authors_same(ref, other)
    if field == "venue":
        return any(same_venue(ref, v) for v in (other if isinstance(other, list) else [other]))
    if field == "pages":
        return _pages_same(ref, other)
    if field == "type":
        want = TYPES.get(ref, {ref})
        return any(t in want for t in (other if isinstance(other, list) else [other]))
    return str(ref).strip().lower() == str(other).strip().lower()


def show_value(field, v):
    if v in (None, "", []):
        return "—"
    if field == "authors":
        return f"{len(v)}: {', '.join(v)}"
    if isinstance(v, list):
        return " / ".join(str(x) for x in v)
    return str(v)


FIELDS = ("title", "authors", "year", "venue", "volume", "issue", "pages", "type")


def confirm_doi(doi):
    """(lines, exit code): Crossref's record, each field checked against the others."""
    doi = norm_doi(doi)
    try:
        cr = get_json(f"{CROSSREF}/{q(doi)}", RECORD_AGE)
    except RateLimited:
        raise  # exit 3, try later, as everywhere else
    except Failure as e:
        raise Failure(f"Crossref, the reference record, is unavailable ({e}); try later") from None
    others, notes = {}, []
    for name, url, fields in (
        ("Semantic Scholar", f"{S2}/DOI:{q(doi)}?fields={S2_RECORD}", fields_s2),
        ("OpenAlex", f"{OPENALEX}/https://doi.org/{q(doi)}", fields_openalex),
    ):
        try:
            rec = get_json(url, RECORD_AGE)
            others[name] = fields(rec) if rec else None
            if not rec:
                notes.append(f"  {name}: no record")
        except Failure as e:  # down or rate-limited: report it, check on
            others[name] = "unavailable"
            notes.append(f"  {name}: unavailable ({e})")
    if not cr and not any(isinstance(v, dict) for v in others.values()):
        raise Failure(f"no source has a record for DOI {doi}")
    ref = fields_crossref(cr["message"]) if cr else {}
    out = [f"confirm {doi}: Crossref's record against Semantic Scholar and OpenAlex"]
    if not cr:
        out.append("  Crossref: no record (a DataCite DOI, such as arXiv's 10.48550, has none)")
    out += notes
    bad, differ = [], []
    for field in FIELDS:
        rv = ref.get(field)
        verdicts, cells = [], [f"Crossref: {show_value(field, rv)}"]
        for name, rec in others.items():
            if not isinstance(rec, dict):
                cells.append(f"{name}: {rec or 'no record'}")
                continue
            ov = rec.get(field)
            if ov in (None, "", []):
                cells.append(f"{name}: —")
                continue
            if rv in (None, "", []):
                verdicts.append(f"{name.lower()} only")
                cells.append(f"{name}: {show_value(field, ov)}")
                continue
            ok = agrees(field, rv, ov)
            verdicts.append("agree" if ok else "differ")
            cells.append(f"{name}: {show_value(field, ov)}" + ("" if ok else " (differs)"))
        if "differ" in verdicts:
            verdict = "differ"
            differ.append(field)
            if field in CRITICAL:
                bad.append(field)
        elif "agree" in verdicts:
            verdict = "agree"
        elif verdicts:
            verdict = verdicts[0]
        elif rv not in (None, "", []):
            verdict = "crossref only"
        else:
            verdict = "neither"
        out.append(f"  {field:8} {verdict:22} " + " | ".join(cells))
    if bad:
        out.append(
            f"confirm: {', '.join(differ)} differ; resolve {', '.join(bad)} with the "
            "publisher's page, never by picking the convenient value"
        )
    else:
        out.append(
            "confirm: " + (", ".join(differ) + " differ (minor)" if differ else "no field differs")
        )
    return out, 1 if bad else 0


def confirm_title(title, year=None, marks=None):
    """A work without a DOI: each source's best matches, labelled with the source."""
    out, limited = [f"confirm --title {title!r}" + (f" --year {year}" if year else "")], None
    url = f"{CROSSREF}?rows=3&query.bibliographic=" + urllib.parse.quote(title)
    if year:
        url += f"&filter=from-pub-date:{year},until-pub-date:{year}"
    s2 = f"{S2}/search?query={urllib.parse.quote(title)}&limit=3&fields={S2_FIELDS}"
    if year:
        s2 += f"&year={year}"
    for name, u, read in (
        ("Crossref", url, lambda d: [from_crossref(i) for i in d["message"]["items"]]),
        ("Semantic Scholar", s2, lambda d: [from_s2(p) for p in d.get("data") or []]),
    ):
        try:
            found = read(get_json(u, LIST_AGE) or {"message": {"items": []}, "data": []})
        except RateLimited as e:
            limited = limited or e
            out.append(f"  {name}: unavailable ({e})")
            continue
        except Failure as e:
            out.append(f"  {name}: unavailable ({e})")
            continue
        out.append(f"  {name}: {len(found)} best match(es)")
        out += ["    " + line(w, marks) for w in found]
    out.append(
        "Each line's fields come from the source it names. A work without a DOI has no "
        "registry record: a match whose title differs is another work (a journal version, "
        "a namesake), and the fields of the work itself are confirmed on its institution's "
        "or publisher's page."
    )
    return out, limited


# --- finding ----------------------------------------------------------------------------


def _year_ok(y, since, until):
    return (not since or (y and y >= since)) and (not until or (y and y <= until))


def _oc_dois(rows, side):
    """[(doi, year)] from OpenCitations rows; the count of rows without a DOI."""
    out, nodoi = [], 0
    for r in rows or []:
        m = re.search(r"\bdoi:(\S+)", r.get(side) or "")
        if not m:
            nodoi += 1
            continue
        y = (r.get("creation") or "")[:4] if side == "citing" else None
        out.append((norm_doi(m.group(1)), int(y) if y and y.isdigit() else None))
    return out, nodoi


def s2_batch(dois, fields=S2_FIELDS):
    """{doi: work} from one Semantic Scholar batch call (up to 500)."""
    data = get_json(f"{S2}/batch?fields={fields}", RECORD_AGE, {"ids": [f"DOI:{d}" for d in dois]})
    found = {}
    for p in data or []:
        if p:
            w = from_s2(p)
            if w["doi"]:
                found[w["doi"]] = w
    return found


def graph(kind, a, marks):
    """citing or refs: OpenCitations for the DOIs, Semantic Scholar for the rest."""
    doi = norm_doi(a.doi)
    side = "citing" if kind == "citations" else "cited"
    out, limited, works = [], None, None
    s2_fields = S2_FIELDS + (",abstract" if a.abstract else "")
    try:
        rows = get_json(f"{OC}/{kind}/doi:{q(doi)}", LIST_AGE)
        pairs, nodoi = _oc_dois(rows, side)
        src = "OpenCitations"
    except Failure as e:
        out.append(f"  OpenCitations unavailable ({e}); Semantic Scholar instead")
        pairs = None
    if pairs is None or not pairs:
        # OpenCitations is down or has none: Semantic Scholar's own list, one call
        field = "citingPaper" if kind == "citations" else "citedPaper"
        data = get_json(f"{S2}/DOI:{q(doi)}/{kind}?limit=1000&fields={s2_fields}", LIST_AGE)
        works = [from_s2(x[field]) for x in (data or {}).get("data") or [] if x.get(field)]
        works = [w for w in works if w.get("title")]
        src, nodoi = "Semantic Scholar", 0
        if pairs is not None and not works:
            return [f"{a.cmd} {doi}: none in OpenCitations or Semantic Scholar"], None
    if works is None:
        total = len(pairs)
        if a.since or a.until:
            pairs = [(d, y) for d, y in pairs if y is None or _year_ok(y, a.since, a.until)]
        if len(pairs) > BATCH:  # the newest first, as follow-up work is what is wanted
            pairs = sorted(pairs, key=lambda p: -(p[1] or 0))[:BATCH]
        try:
            meta = s2_batch([d for d, _ in pairs], s2_fields)
        except RateLimited as e:
            limited, meta = e, {}
            out.append(f"  Semantic Scholar unavailable ({e}): DOIs and years only")
        except Failure as e:
            meta = {}
            out.append(f"  Semantic Scholar unavailable ({e}): DOIs and years only")
        works = []
        for d, y in pairs:
            w = meta.get(d) or {
                "year": y,
                "title": None,
                "venue": None,
                "doi": d,
                "cited": None,
                "oa": None,
                "source": "OpenCitations",
            }
            works.append(w)
        head = (
            f"{a.cmd} {doi}: {total + nodoi} in {src}"
            + (f" ({nodoi} without a DOI, left out)" if nodoi else "")
            + (f"; {len(pairs)} in the years asked" if a.since or a.until else "")
            + (f"; {len(meta)} described by Semantic Scholar" if meta else "")
        )
    else:
        head = f"{a.cmd} {doi}: {len(works)} in {src}"
    works = [w for w in works if _year_ok(w.get("year"), a.since, a.until)]
    shown = order(works, a.sort)[: a.limit]
    out.insert(0, f"{head}; showing {len(shown)} by {a.sort}")
    out += [line(w, marks, a.abstract) for w in shown]
    return out, limited


S2_TYPES = {
    "article": "JournalArticle",
    "journal-article": "JournalArticle",
    "proceedings-article": "Conference",
    "conference": "Conference",
    "review": "Review",
    "book": "Book",
    "book-chapter": "BookSection",
}


def _s2_years(since, until):
    if since or until:
        return f"&year={since or ''}-{until or ''}"
    return ""


def search(a, marks):
    out, limited, n = [], None, min(a.limit, MAX_LIMIT)
    blocks = []
    s2 = f"{S2}/search?query={urllib.parse.quote(a.query)}&limit={n}"
    s2 += f"&fields={S2_FIELDS}" + (",abstract" if a.abstract else "")
    s2 += _s2_years(a.since, a.until)
    if a.type:
        t = S2_TYPES.get(a.type, a.type)
        s2 += f"&publicationTypes={urllib.parse.quote(t)}"
    blocks.append(("Semantic Scholar", s2, lambda d: [from_s2(p) for p in d.get("data") or []]))
    if a.crossref:
        cr = f"{CROSSREF}?rows={n}&query.bibliographic=" + urllib.parse.quote(a.query)
        f = []
        if a.since:
            f.append(f"from-pub-date:{a.since}")
        if a.until:
            f.append(f"until-pub-date:{a.until}")
        if a.type:
            f.append(f"type:{a.type}")
        if f:
            cr += "&filter=" + ",".join(f)
        blocks.append(("Crossref", cr, lambda d: [from_crossref(i) for i in d["message"]["items"]]))
    if a.preprints:
        terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w-]+", a.query))
        if a.since or a.until:
            terms += f" AND submittedDate:[{a.since or 1990}01010000 TO {a.until or 2100}12312359]"
        ax = f"{ARXIV}?" + urllib.parse.urlencode(
            {"search_query": terms, "max_results": n, "sortBy": "relevance"}
        )
        blocks.append(("arXiv", ax, None))
    if a.openalex:
        if not STATE["keys"].get("openalex"):
            raise Failure(
                "--openalex needs OPENALEX_API_KEY (a free key from openalex.org/settings/api): "
                "OpenAlex's searches draw on a daily budget; the default sources need none"
            )
        flt = []
        if a.since:
            flt.append(f"publication_year:>{a.since - 1}")
        if a.until:
            flt.append(f"publication_year:<{a.until + 1}")
        params = {"search": a.query, "per_page": n}
        if flt:
            params["filter"] = ",".join(flt)
        oa = f"{OPENALEX}?" + urllib.parse.urlencode(params)
        blocks.append(
            ("OpenAlex", oa, lambda d: [from_openalex(w) for w in d.get("results") or []])
        )
    for name, url, read in blocks:
        try:
            text = request(url, LIST_AGE)
            found = from_arxiv(text) if read is None else read(json.loads(text) if text else {})
        except RateLimited as e:
            limited = limited or e
            out.append(f"{name}: unavailable ({e})")
            continue
        except Failure as e:
            out.append(f"{name}: unavailable ({e})")
            continue
        found = [w for w in found if _year_ok(w.get("year"), a.since, a.until)]
        out.append(f"{name}: {len(found)} match(es) for {a.query!r}, by {a.sort}")
        out += [line(w, marks, a.abstract) for w in order(found, a.sort)]
    return out, limited


def related(a, marks):
    doi = norm_doi(a.doi)
    p = get_json(f"{S2}/DOI:{q(doi)}?fields={S2_RECORD}", RECORD_AGE)
    if not p:
        raise Failure(f"Semantic Scholar has no record for DOI {doi}")
    fields = S2_FIELDS + (",abstract" if a.abstract else "")
    data = get_json(
        f"{S2_REC}?limit=100&fields={fields}", LIST_AGE, {"positivePaperIds": [p["paperId"]]}
    )
    works = [from_s2(x) for x in (data or {}).get("recommendedPapers") or []]
    shown = order(works, "cited")[: a.limit]
    out = [
        f"related {doi}: {len(works)} Semantic Scholar recommendation(s), showing {len(shown)} "
        "by citations (noisy and recency-biased: a last resort after citing, refs and search)"
    ]
    return out + [line(w, marks, a.abstract) for w in shown], None


# --- the command line -------------------------------------------------------------------


def parser():
    p = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        epilog="related is noisy and recency-biased: a last resort after citing, refs, search",
    )
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="skip the response cache")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("confirm", help="a reference against Crossref, Semantic Scholar, OpenAlex")
    c.add_argument("doi", nargs="?")
    c.add_argument("--title")
    c.add_argument("--year", type=int)
    c.add_argument("--library", nargs="+", metavar="FILE", help="Markdown files to mark DOIs from")

    def common(s, sorts, default, years=True):
        if years:
            s.add_argument("--since", type=int)
            s.add_argument("--until", type=int)
        s.add_argument("--sort", choices=sorts, default=default)
        s.add_argument("--limit", type=int, default=10)
        s.add_argument("--abstract", action="store_true")
        s.add_argument(
            "--library", nargs="+", metavar="FILE", help="Markdown files to mark DOIs from"
        )

    s = sub.add_parser("search", help="Semantic Scholar (+ Crossref, arXiv, OpenAlex)")
    s.add_argument("query")
    s.add_argument("--type", help="article, proceedings-article, review, book-chapter, …")
    s.add_argument("--crossref", action="store_true", help="also Crossref's search")
    s.add_argument("--preprints", action="store_true", help="also arXiv's search")
    s.add_argument("--openalex", action="store_true", help="also OpenAlex's (needs a key)")
    common(s, ["relevance", "cited", "year"], "relevance")
    ci = sub.add_parser("citing", help="the works that cite DOI (follow-up work)")
    ci.add_argument("doi")
    common(ci, ["cited", "year"], "cited")
    r = sub.add_parser("refs", help="DOI's reference list")
    r.add_argument("doi")
    common(r, ["oldest", "year", "cited"], "oldest")
    rel = sub.add_parser("related", help="recommendations: noisy, recency-biased, a last resort")
    rel.add_argument("doi")
    common(rel, ["cited"], "cited", years=False)
    return p


def run(args):
    """(output lines, exit code); the exit code is 3 when a source was rate-limited."""
    marks = library_marks(args.library)
    if args.cmd == "confirm":
        if args.title:
            out, limited = confirm_title(args.title, args.year, marks)
            return out + ([f"lit_search.py: {limited}"] if limited else []), 3 if limited else 0
        if not args.doi:
            raise Failure("confirm needs a DOI or --title")
        return confirm_doi(args.doi)
    if not 1 <= args.limit <= MAX_LIMIT:
        raise Failure(f"--limit is 1 to {MAX_LIMIT}")
    if args.cmd in ("citing", "refs"):
        out, limited = graph("citations" if args.cmd == "citing" else "references", args, marks)
    elif args.cmd == "search":
        out, limited = search(args, marks)
    else:
        out, limited = related(args, marks)
    if limited:
        out.append(f"lit_search.py: {limited}")
    return out, 3 if limited else 0


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        p.print_help()
        return 2
    STATE["keys"] = {
        k: v
        for k, v in (
            ("openalex", os.environ.get("OPENALEX_API_KEY")),
            ("s2", os.environ.get("S2_API_KEY")),
        )
        if v
    }
    if args.no_cache:
        STATE["cache"] = None
    try:
        out, code = run(args)
    except RateLimited as e:
        print(f"lit_search.py: {e}", file=sys.stderr)
        return 3
    except (Failure, OSError, ValueError, ET.ParseError) as e:
        print(f"lit_search.py: {e}", file=sys.stderr)
        return 2
    print("\n".join(out))
    return code


# --- self-test --------------------------------------------------------------------------

OA_KEY, S2_KEY = "SECRET-openalex-key-0000", "SECRET-s2-key-1111"


def _fixtures():
    """Responses recorded from each source, trimmed to the fields the tool reads; the
    DOIs are made up (10.1000/...), so nothing here names a real library."""
    cr_seed = {
        "message": {
            "DOI": "10.1000/seed.1",
            "title": ["An adaptive nature‐inspired algorithm for routing"],
            "author": [
                {"given": "Gianni", "family": "Di Caro"},
                {"given": "Frederick", "family": "Ducatelle"},
                {"given": "Luca Maria", "family": "Gambardella"},
            ],
            "container-title": ["European Transactions on Telecommunications"],
            "volume": "16",
            "issue": "5",
            "page": "443-455",
            "issued": {"date-parts": [[2005, 8]]},
            "type": "journal-article",
        }
    }
    s2_seed = {
        "paperId": "35b7c31be7",
        "externalIds": {"DOI": "10.1000/seed.1"},
        "title": "An adaptive nature-inspired algorithm for routing",
        "venue": "Transactions on Emerging Telecommunications Technologies",
        "year": 2005,
        "citationCount": 649,
        "openAccessPdf": {"url": "http://example.org/a.pdf", "status": "GREEN"},
        "publicationTypes": ["JournalArticle"],
        "journal": {"name": "Eur. Trans. Telecommun.", "pages": "443-455", "volume": "16"},
        "authors": [
            {"name": "G. D. Di Caro"},
            {"name": "F. Ducatelle"},
            {"name": "L. Gambardella"},
        ],
    }
    oa_seed = {
        "id": "https://openalex.org/W100",
        "doi": "https://doi.org/10.1000/seed.1",
        "display_name": "An adaptive nature‐inspired algorithm for routing",
        "publication_year": 2005,
        "type": "article",
        "cited_by_count": 581,
        "open_access": {"oa_status": "closed"},
        "primary_location": {
            "source": {"display_name": "European Transactions on Telecommunications"}
        },
        "authorships": [
            {"raw_author_name": "Gianni Di Caro", "author": {"display_name": "Gianni A. Di"}},
            {"raw_author_name": "Frederick Ducatelle"},
            {"raw_author_name": "Luca Maria Gambardella"},
        ],
        "biblio": {"volume": "16", "issue": "5", "first_page": "443", "last_page": "455"},
    }
    # the same paper where Semantic Scholar has another year and other pages
    s2_bad = dict(s2_seed, year=2006, externalIds={"DOI": "10.1000/bad.2"})
    s2_bad["journal"] = dict(s2_seed["journal"], pages="445-455")
    cr_bad = {"message": dict(cr_seed["message"], DOI="10.1000/bad.2")}
    oa_bad = dict(oa_seed, doi="https://doi.org/10.1000/bad.2")

    def s2w(pid, year, title, doi=None, cited=0, venue="Ad Hoc Networks", status="CLOSED", ab=None):
        return {
            "paperId": pid,
            "externalIds": {"DOI": doi} if doi else {"CorpusId": 1},
            "title": title,
            "venue": venue,
            "year": year,
            "citationCount": cited,
            "openAccessPdf": {"url": "", "status": status},
            "abstract": ab,
        }

    oc_citations = [
        {"citing": "omid:br/1 doi:10.1000/new.11 openalex:W11", "creation": "2024-03-01"},
        {"citing": "omid:br/2 doi:10.1000/listed.12", "creation": "2009"},
        {"citing": "omid:br/3 doi:10.1000/gone.13", "creation": "2021-05"},
        {"citing": "omid:br/4 openalex:W14", "creation": "2022"},
    ]
    batch = [
        s2w(
            "a11",
            2024,
            "Swarm routing for UAV swarms",
            "10.1000/new.11",
            12,
            status="GOLD",
            ab="Follow-up work on swarm routing.",
        ),
        s2w("a12", 2009, "A hybrid ant routing", "10.1000/listed.12", 300),
        None,  # Semantic Scholar does not know 10.1000/gone.13
    ]
    oc_refs = [
        {"cited": "omid:br/5 doi:10.1000/saved.2", "creation": "2005"},
        {"cited": "omid:br/6 doi:10.1000/ref.1", "creation": "2005"},
    ]
    batch_refs = [
        s2w("b2", 1999, "Ant colony optimization", "10.1000/saved.2", 9000, status="GREEN"),
        s2w("b1", 1998, "AntNet", "10.1000/ref.1", 2000),
    ]
    long_ab = "Ants " + " ".join(f"w{i}" for i in range(1, 80))
    s2_search = {
        "total": 321,
        "data": [
            s2w("c1", 2023, "Ant colony routing for FANETs", "10.1000/fanet.21", 4, ab=long_ab),
            s2w("c2", 2025, "Bio-inspired UAV routing", "10.1000/uav.22", 40),
        ],
    }
    cr_search = {
        "message": {
            "items": [
                dict(
                    cr_seed["message"],
                    DOI="10.1000/journal.9",
                    title=["HOPNET: A hybrid ant colony optimization routing algorithm"],
                    **{"is-referenced-by-count": 151, "issued": {"date-parts": [[2009, 6]]}},
                )
            ]
        }
    }
    s2_title = {
        "data": [s2w("d1", 2009, "HOPNET: A hybrid ant colony optimization", "10.1000/journal.9")]
    }
    recs = {
        "recommendedPapers": [
            s2w("e1", 2026, "A review of congestion control", None, 0, venue=""),
            s2w("e2", 2026, "Restricted flooding", "10.1000/rf.31", 3, venue="Some Journal"),
        ]
    }
    arxiv = (
        '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>'
        "<id>http://arxiv.org/abs/2512.00001v2</id><published>2025-12-16T11:41:39Z</published>"
        "<title>Ant colony\n  routing for UAV relays</title><summary>An abstract.</summary>"
        "<arxiv:doi>10.1000/AX.41</arxiv:doi></entry></feed>"
    )
    oa_search = {"results": [dict(oa_seed, id="https://openalex.org/W51", publication_year=2024)]}
    return {
        "crossref:10.1000/seed.1": cr_seed,
        "crossref:10.1000/bad.2": cr_bad,
        "s2:DOI:10.1000/seed.1": s2_seed,
        "s2:DOI:10.1000/bad.2": s2_bad,
        "openalex:10.1000/seed.1": oa_seed,
        "openalex:10.1000/bad.2": oa_bad,
        "oc:citations": oc_citations,
        "oc:references": oc_refs,
        "s2:batch:citing": batch,
        "s2:batch:refs": batch_refs,
        "s2:search": s2_search,
        "s2:title": s2_title,
        "crossref:search": cr_search,
        "s2:recs": recs,
        "arxiv": arxiv,
        "openalex:search": oa_search,
    }


def self_test():
    saved = dict(STATE)
    try:
        return _self_test()
    finally:
        STATE.update(saved)


def _self_test():
    failures = []

    def expect(name, cond):
        if not cond:
            failures.append(name)

    fx = _fixtures()
    calls, down = [], {}  # down: {source: the HTTP status it answers}

    def fake(method, url, headers, body):
        calls.append((method, url, dict(headers), body))
        src = _source(url)
        if src in down:
            raise HTTPStatus(down[src])
        u = urllib.parse.unquote(url)
        if src == "crossref":
            if "query.bibliographic" in u:
                return json.dumps(fx["crossref:search"])
            return json.dumps(fx.get("crossref:" + u.split("/works/", 1)[1]))
        if src == "openalex":
            if "search=" in u:
                return json.dumps(fx["openalex:search"])
            return json.dumps(fx.get("openalex:" + u.split("doi.org/", 1)[1].split("?")[0]))
        if src == "oc":
            return json.dumps(fx["oc:" + u.split("/index/v2/", 1)[1].split("/")[0]])
        if src == "arxiv":
            return fx["arxiv"]
        if "/batch" in u:
            key = "citing" if "DOI:10.1000/new.11" in body["ids"] else "refs"
            return json.dumps(fx["s2:batch:" + key])
        if "/recommendations/" in u:
            return json.dumps(fx["s2:recs"])
        if "/search?" in u:
            return json.dumps(fx["s2:title" if "HOPNET" in u else "s2:search"])
        hit = fx.get("s2:" + u.split("/paper/", 1)[1].split("?")[0])
        return json.dumps(hit) if hit else None

    def go(*argv):
        args = parser().parse_args(list(argv))
        try:
            out, code = run(args)
        except RateLimited as e:
            return str(e), 3
        except Failure as e:
            return str(e), 2
        return "\n".join(out), code

    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        STATE.update(
            cache=os.path.join(tmp, "cache"),
            fetch=fake,
            sleep=lambda s: None,
            err=errs.append,
            keys={"openalex": OA_KEY, "s2": S2_KEY},
        )
        lib = os.path.join(tmp, "README.md")
        dl = os.path.join(tmp, "MANUAL-DOWNLOADS.md")
        with open(lib, "w", encoding="utf-8") as fh:
            fh.write(
                "| f | X, *T*, 1999, DOI 10.1000/SAVED.2 (9 pp). |\n"
                "Prose naming 10.1000/listed.12. and (DOI 10.1000/seed.1)\n"
            )
        with open(dl, "w", encoding="utf-8") as fh:
            fh.write(
                "| f | Y, 2009, DOI 10.1000/listed.12 | [DOI](https://doi.org/10.1000/seed.1) |\n"
            )
        marks = library_marks([lib, dl])
        expect("marks: saved", marks.get("10.1000/saved.2") == "saved")
        expect("marks: a download list wins", marks.get("10.1000/listed.12") == "listed")
        expect("marks: trailing ')' and '.' dropped", "10.1000/seed.1" in marks)
        expect("marks: none without --library", library_marks(None) == {})

        # confirm DOI: three sources agree (an abbreviated venue, a mangled display name)
        out, code = go("confirm", "https://doi.org/10.1000/SEED.1")
        expect("confirm agree: exit 0", code == 0)
        for field in ("title", "authors", "year", "venue", "volume", "pages", "type"):
            expect(f"confirm agree: {field}", re.search(rf"\n  {field} +agree ", out) is not None)
        expect("confirm agree: issue from two sources", re.search(r"issue +agree", out) is not None)
        expect("confirm agree: summary", out.endswith("confirm: no field differs"))
        n = len(calls)
        go("confirm", "10.1000/seed.1")
        expect("confirm: the second run is cached", len(calls) == n)

        # confirm DOI: Semantic Scholar's year and pages differ: exit 1, named
        out, code = go("confirm", "10.1000/bad.2")
        expect("confirm differ: exit 1", code == 1)
        expect(
            "confirm differ: year",
            re.search(r"year +differ +Crossref: 2005 \| Semantic Scholar: 2006 \(differs\)", out)
            is not None,
        )
        expect("confirm differ: pages", re.search(r"pages +differ", out) is not None)
        expect(
            "confirm differ: says what to do",
            "resolve year, pages with the publisher's page" in out,
        )

        # confirm DOI: Semantic Scholar rate-limited and OpenAlex down: unavailable, not fatal
        STATE["cache"] = None
        down.update({"s2": 429, "openalex": 503})
        out, code = go("confirm", "10.1000/seed.1")
        expect("confirm unavailable: exit 0", code == 0)
        expect(
            "confirm unavailable: S2 named",
            "Semantic Scholar: unavailable (Semantic Scholar is rate-limited" in out,
        )
        expect(
            "confirm unavailable: OpenAlex named",
            "OpenAlex: unavailable (OpenAlex: HTTP 503)" in out,
        )
        expect(
            "confirm unavailable: crossref only", re.search(r"year +crossref only", out) is not None
        )
        down.clear()
        STATE["cache"] = os.path.join(tmp, "cache")

        # confirm --title: Crossref and Semantic Scholar, each line labelled
        out, code = go(
            "confirm", "--title", "HOPNET hybrid ant thesis", "--year", "2007", "--library", lib, dl
        )
        expect(
            "confirm --title: both sources",
            "  Crossref: 1 best match(es)" in out and "  Semantic Scholar: 1 best" in out,
        )
        expect("confirm --title: labelled", "· Crossref" in out and "· S2" in out)
        expect("confirm --title: says a match may be another work", "another work" in out)
        expect(
            "confirm --title: year filter",
            any("from-pub-date:2007" in urllib.parse.unquote(c[1]) for c in calls),
        )

        # citing: OpenCitations + one Semantic Scholar batch; sorted by citations; marks
        before = len(calls)
        out, code = go("citing", "10.1000/seed.1", "--library", lib, dl)
        new = calls[before:]
        expect("citing: two calls", [_source(c[1]) for c in new] == ["oc", "s2"])
        expect("citing: one batch POST", new[1][0] == "POST" and len(new[1][3]["ids"]) == 3)
        expect(
            "citing: header",
            out.startswith(
                "citing 10.1000/seed.1: 4 in OpenCitations (1 without a DOI, left out); 2 described"
            ),
        )
        expect(
            "citing: by citations", out.index("A hybrid ant routing") < out.index("Swarm routing")
        )
        expect(
            "citing: one line per work",
            "2024 · Swarm routing for UAV swarms · Ad Hoc Networks · 10.1000/new.11 · cited 12 · gold · S2"
            in out,
        )
        expect("citing: listed mark", "cited 300 · closed · S2 [listed]" in out)
        expect(
            "citing: unknown to S2 kept",
            "2021 · (no title in any source) · — · 10.1000/gone.13 · cited ? · oa ? · OpenCitations"
            in out,
        )
        out, code = go("citing", "10.1000/seed.1", "--since", "2020", "--sort", "year")
        expect(
            "citing --since: older ones dropped",
            "A hybrid ant routing" not in out and out.index("2024 ·") < out.index("2021 ·"),
        )

        # citing with Semantic Scholar rate-limited: the OpenCitations lines, then exit 3
        STATE["cache"] = None
        down["s2"] = 429
        out, code = go("citing", "10.1000/seed.1")
        expect("citing limited: exit 3", code == 3)
        expect(
            "citing limited: DOIs still shown",
            "10.1000/new.11" in out and "Semantic Scholar is rate-limited, try later" in out,
        )
        # OpenCitations down: Semantic Scholar's own citations instead
        down.clear()
        down["oc"] = 503
        fx["s2:DOI:10.1000/seed.1/citations"] = {
            "data": [{"citingPaper": fx["s2:batch:citing"][0]}]
        }
        out, code = go("citing", "10.1000/seed.1")
        expect(
            "citing fallback: S2",
            code == 0 and "OpenCitations unavailable" in out and "1 in Semantic Scholar" in out,
        )
        down.clear()
        STATE["cache"] = os.path.join(tmp, "cache")

        # confirm DOI: Crossref, the reference, rate-limited: exit 3 (try later), not 2
        STATE["cache"] = None
        down["crossref"] = 429
        msg, code = go("confirm", "10.1000/seed.1")
        expect("confirm: Crossref rate-limited is exit 3", code == 3 and "Crossref" in msg)
        down.clear()

        # --abstract reaches citing's batch call and its lines
        before = len(calls)
        out, code = go("citing", "10.1000/seed.1", "--abstract")
        batch = [c for c in calls[before:] if "/batch" in c[1]]
        expect("citing --abstract: asked for", batch and batch[0][1].endswith(",abstract"))
        expect("citing --abstract: printed", "\n    Follow-up work on swarm routing." in out)
        STATE["cache"] = os.path.join(tmp, "cache")

        # refs: oldest first; saved mark
        out, code = go("refs", "10.1000/seed.1", "--library", lib, dl)
        expect("refs: oldest first", out.index("1998 · AntNet") < out.index("1999 · Ant colony"))
        expect("refs: saved mark", "cited 9000 · green · S2 [saved]" in out)

        # related: POST with the paperId, sorted by citations, labelled noisy
        before = len(calls)
        out, code = go("related", "10.1000/seed.1")
        rec = [c for c in calls[before:] if "/recommendations/" in c[1]]
        expect(
            "related: POST paperId",
            rec and rec[0][0] == "POST" and rec[0][3] == {"positivePaperIds": ["35b7c31be7"]},
        )
        expect("related: noisy label", "noisy and recency-biased" in out)
        expect("related: by citations", out.index("Restricted flooding") < out.index("congestion"))

        # search: Semantic Scholar, Crossref, arXiv, OpenAlex (with its key); abstracts
        before = len(calls)
        out, code = go(
            "search",
            "ant colony UAV",
            "--since",
            "2023",
            "--type",
            "proceedings-article",
            "--crossref",
            "--preprints",
            "--openalex",
            "--abstract",
        )
        srcs = [_source(c[1]) for c in calls[before:]]
        expect("search: four sources", srcs == ["s2", "crossref", "arxiv", "openalex"])
        expect(
            "search: S2 filters",
            any("year=2023-&publicationTypes=Conference" in c[1] for c in calls[before:]),
        )
        expect(
            "search: arXiv years",
            any("submittedDate" in urllib.parse.unquote_plus(c[1]) for c in calls[before:]),
        )
        expect(
            "search: abstract cut to 60 words",
            "\n    Ants w1 w2" in out and " w59 …" in out and "w60" not in out,
        )
        expect(
            "search: arXiv line",
            "2025 · Ant colony routing for UAV relays · arXiv · 10.1000/ax.41 · cited ? · green · arXiv"
            in out,
        )
        expect("search: years filter drops 2009", "Crossref: 0 match(es)" in out)
        expect(
            "search: OpenAlex",
            "2024 · An adaptive nature‐inspired algorithm for routing" in out
            and "· OpenAlex" in out,
        )
        out, code = go("search", "x", "--limit", "26")
        expect("search: --limit capped", code == 2)
        STATE["keys"] = {"s2": S2_KEY}
        out, code = go("search", "x", "--openalex")
        expect(
            "search: --openalex without a key refuses",
            code == 2 and "needs OPENALEX_API_KEY" in out,
        )
        STATE["keys"] = {"openalex": OA_KEY, "s2": S2_KEY}

        # the keys: sent where they belong, never anywhere else
        oa = [c for c in calls if _source(c[1]) == "openalex"]
        s2 = [c for c in calls if _source(c[1]) == "s2"]
        expect("keys: OpenAlex key in its URL", oa and all(f"api_key={OA_KEY}" in c[1] for c in oa))
        expect(
            "keys: S2 key in its header", s2 and all(c[2].get("x-api-key") == S2_KEY for c in s2)
        )
        expect(
            "keys: never sent to another source",
            not any(
                OA_KEY in c[1] or S2_KEY in json.dumps(c[2])
                for c in calls
                if _source(c[1]) not in ("openalex", "s2")
            ),
        )
        blob = ""
        for name in os.listdir(STATE["cache"]):
            with open(os.path.join(STATE["cache"], name), encoding="utf-8") as fh:
                blob += name + fh.read()
        expect(
            "keys: not in the cache",
            OA_KEY not in blob and S2_KEY not in blob and "api_key" not in blob,
        )
        expect(
            "keys: no generic User-Agent contact", all("@" not in c[2]["User-Agent"] for c in calls)
        )

        # 429 twice from OpenAlex: retried once (capped wait), then the budget message, exit 3
        waits = []

        def refuse(method, url, headers, body):
            calls.append((method, url, dict(headers), body))
            raise HTTPStatus(429, "86000")

        STATE.update(fetch=refuse, cache=None, sleep=waits.append)
        n = len(calls)
        msg, code = go("search", "x", "--openalex")
        expect("429: each source retried once", len(calls) - n == 4 and waits[:1] == [10])
        expect("429: every source unavailable, exit 3", code == 3)
        expect(
            "429: OpenAlex budget message",
            "OpenAlex budget exhausted for today; its single-record lookups (confirm) still work"
            in msg,
        )
        expect(
            "429: no key in any message",
            OA_KEY not in msg
            and S2_KEY not in msg
            and not any(OA_KEY in e or S2_KEY in e for e in errs),
        )

        # another error carries no key and no URL
        def broken(method, url, headers, body):
            raise HTTPStatus(500)

        STATE["fetch"] = broken
        msg, code = go("refs", "10.1000/seed.1")
        expect(
            "500: exit 2 or 3, no key", code in (2, 3) and OA_KEY not in msg and "http" not in msg
        )

        # transport errors below HTTP (a read timeout, a dropped connection, a cut or
        # undecodable body) are Failures, so each caller's per-source handling applies
        real = urllib.request.urlopen
        for exc in (
            TimeoutError("timed out"),
            http.client.RemoteDisconnected("closed"),
            http.client.IncompleteRead(b"x"),
        ):

            def boom(*_a, _e=exc, **_k):
                raise _e

            urllib.request.urlopen = boom
            try:
                _urlopen("GET", CROSSREF, {}, None)
                expect(f"transport: {type(exc).__name__} is a Failure", False)
            except Failure as e:
                expect(f"transport: {type(exc).__name__} named", type(exc).__name__ in str(e))
            except Exception:
                expect(f"transport: {type(exc).__name__} is a Failure", False)
            finally:
                urllib.request.urlopen = real

        # an unwritable cache never fails a lookup
        STATE.update(fetch=fake, cache=lib, sleep=lambda s: None)
        out, code = go("confirm", "10.1000/seed.1")
        expect("cache: unwritable is ignored", code == 0)

    for name in failures:
        print(f"FAIL: {name}")
    print(f"lit_search.py self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
