// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package ticketaudit

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

var now = time.Date(2026, 11, 23, 5, 0, 0, 0, time.UTC)

func ago(days int) time.Time { return now.Add(-time.Duration(days) * 24 * time.Hour) }

type fIssue struct {
	num     int
	title   string
	body    string
	labels  []string
	created time.Time
	isPR    bool
	reopen  time.Time // a reopened event at this time
	state   string
}

type fPull struct {
	num    int
	body   string
	merged time.Time // zero: closed unmerged
}

type fRepo struct {
	name     string
	private  bool
	archived bool
	issues   []*fIssue
	pulls    []fPull
	releases []string
}

type write struct {
	method, path string
	body         map[string]any
}

type fake struct {
	mu     sync.Mutex
	repos  []*fRepo
	writes []write
	gets   []string
}

func (f *fake) repo(name string) *fRepo {
	for _, r := range f.repos {
		if r.name == name {
			return r
		}
	}
	return nil
}

func pageOf[T any](w http.ResponseWriter, r *http.Request, items []T) {
	per, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
	pg, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if per <= 0 || pg <= 0 {
		http.Error(w, "paging", 400)
		return
	}
	lo, hi := (pg-1)*per, pg*per
	if lo > len(items) {
		lo = len(items)
	}
	if hi > len(items) {
		hi = len(items)
	}
	_ = json.NewEncoder(w).Encode(items[lo:hi])
}

func (f *fake) repoJSON(r *fRepo) map[string]any {
	return map[string]any{"name": r.name, "full_name": Org + "/" + r.name, "private": r.private,
		"archived": r.archived, "fork": false, "has_issues": true}
}

func (f *fake) issueJSON(i *fIssue) map[string]any {
	ls := []map[string]any{}
	for _, l := range i.labels {
		ls = append(ls, map[string]any{"name": l})
	}
	m := map[string]any{"number": i.num, "title": i.title, "body": i.body, "labels": ls, "created_at": i.created}
	if i.isPR {
		m["pull_request"] = map[string]any{}
	}
	return m
}

func (f *fake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if r.Method != "GET" {
		var b map[string]any
		data, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(data, &b)
		f.writes = append(f.writes, write{r.Method, r.URL.Path, b})
	} else {
		f.gets = append(f.gets, r.URL.Path)
	}
	switch {
	case r.Method == "GET" && len(p) == 3 && p[0] == "orgs":
		var out []map[string]any
		for _, x := range f.repos {
			out = append(out, f.repoJSON(x))
		}
		pageOf(w, r, out)
		return
	case len(p) >= 3 && p[0] == "repos" && p[1] == Org:
	default:
		http.NotFound(w, r)
		return
	}
	rp := f.repo(p[2])
	if rp == nil {
		http.NotFound(w, r)
		return
	}
	rest := p[3:]
	switch {
	case r.Method == "GET" && len(rest) == 0:
		_ = json.NewEncoder(w).Encode(f.repoJSON(rp))
	case r.Method == "GET" && len(rest) == 1 && rest[0] == "pulls":
		var out []map[string]any
		for _, x := range rp.pulls {
			m := map[string]any{"number": x.num, "body": x.body, "merged_at": nil}
			if !x.merged.IsZero() {
				m["merged_at"] = x.merged
			}
			out = append(out, m)
		}
		pageOf(w, r, out)
	case r.Method == "GET" && len(rest) == 1 && rest[0] == "issues":
		var out []map[string]any
		for _, i := range rp.issues {
			if i.state == "" {
				out = append(out, f.issueJSON(i))
			}
		}
		pageOf(w, r, out)
	case r.Method == "GET" && len(rest) == 3 && rest[0] == "issues" && rest[2] == "events":
		n, _ := strconv.Atoi(rest[1])
		var out []map[string]any
		for _, i := range rp.issues {
			if i.num == n && !i.reopen.IsZero() {
				out = append(out, map[string]any{"event": "reopened", "created_at": i.reopen})
			}
		}
		pageOf(w, r, out)
	case r.Method == "GET" && len(rest) == 3 && rest[0] == "releases" && rest[1] == "tags":
		for _, t := range rp.releases {
			if t == rest[2] {
				_ = json.NewEncoder(w).Encode(map[string]any{"tag_name": t, "draft": false})
				return
			}
		}
		http.NotFound(w, r)
	case r.Method == "POST" && len(rest) == 3 && rest[0] == "issues" && rest[2] == "comments":
		w.WriteHeader(201)
		_, _ = w.Write([]byte(`{"id":1}`))
	case r.Method == "PATCH" && len(rest) == 2 && rest[0] == "issues":
		n, _ := strconv.Atoi(rest[1])
		for _, i := range rp.issues {
			if i.num == n {
				last := f.writes[len(f.writes)-1].body
				if last["state"] == "closed" {
					i.state = "closed"
				}
				if v, ok := last["body"].(string); ok {
					i.body = v
				}
			}
		}
		_, _ = w.Write([]byte(`{}`))
	case r.Method == "POST" && len(rest) == 1 && rest[0] == "issues":
		last := f.writes[len(f.writes)-1].body
		n := 1000 + len(rp.issues)
		rp.issues = append(rp.issues, &fIssue{num: n, title: last["title"].(string), body: last["body"].(string), created: now})
		w.WriteHeader(201)
		_, _ = fmt.Fprintf(w, `{"number":%d}`, n)
	default:
		http.Error(w, "unexpected "+r.Method+" "+r.URL.Path, 500)
	}
}

const (
	acDone  = "### Acceptance criteria\n\n- [x] one\n- [x] two\n"
	acOpen  = "### Acceptance criteria\n\n- [x] one\n- [x] two\n- [x] three\n- [x] four\n- [ ] five\n"
	acTwoOf = "### Acceptance criteria\n\n- [x] one\n- [ ] two\n"
)

func org() *fake {
	return &fake{repos: []*fRepo{
		{name: ".github", issues: []*fIssue{{num: 1, title: "a note", body: "no boxes", created: ago(9)}}},
		{name: "alpha", releases: []string{"v0.1.0"}, issues: []*fIssue{
			{num: 1, title: "done", body: acDone, created: ago(30)},
			{num: 2, title: "one box open", body: acOpen, created: ago(30)},
			{num: 3, title: "open boxes only in superseded text", body: acDone + "<details>\n- [ ] old\n</details>\n```\n- [ ] x\n```\n", created: ago(30)},
			{num: 4, title: "held", body: acDone, labels: []string{"hold"}, created: ago(30)},
			{num: 5, title: "release not cut", body: acDone, labels: []string{"release:v1.0.0"}, created: ago(30)},
			{num: 6, title: "release cut", body: acDone, labels: []string{"release:v0.1.0"}, created: ago(30)},
			{num: 7, title: "closed by a beta PR", body: "no boxes", created: ago(30)},
			{num: 8, title: "reopened after its PR", body: "no boxes", created: ago(30), reopen: ago(2)},
			{num: 9, title: "no boxes", body: "just text", created: ago(30)},
			{num: 10, title: "[handoff] old", body: "1. step\n", labels: []string{"handoff"}, created: ago(20)},
			{num: 11, title: "[handoff] new", body: "Supersedes #10\n\n1. step\n", labels: []string{"handoff"}, created: ago(10)},
			{num: 12, title: "an epic", body: acDone, labels: []string{"epic"}, created: ago(30)},
			{num: 13, title: "an rcapa", body: acDone, labels: []string{"rcapa"}, created: ago(30)},
			{num: 14, title: "a security ticket", body: acDone, labels: []string{"security", "bug"}, created: ago(30)},
			{num: 15, title: "unclosed details", body: acDone + "<details>\n- [ ] x\n", created: ago(30)},
			{num: 16, title: "a pull request", body: acDone, isPR: true, created: ago(30)},
			{num: 17, title: "an unmerged PR names it", body: "no boxes", created: ago(30)},
			{num: 18, title: "ticked, no acceptance heading", body: "- [x] a\n- [x] b\n", created: ago(30)},
			{num: 19, title: "opened after the PR merged", body: "no boxes", created: ago(1)},
			{num: 20, title: "a PR closes it, but a box is open", body: acTwoOf, created: ago(30)},
			{num: 22, title: "closed by a private PR", body: "no boxes", created: ago(30)},
			{num: 23, title: "[handoff] superseded, but held", body: "x", labels: []string{"handoff", "hold"}, created: ago(30)},
			{num: 24, title: "[handoff] newer, supersedes a held one", body: "Supersedes: #23", labels: []string{"handoff"}, created: ago(5)},
		}, pulls: []fPull{
			{num: 30, body: "Closes #8", merged: ago(5)},
			{num: 31, body: "Closes #17", merged: time.Time{}},
			{num: 32, body: "Fixes #19 and resolves #20", merged: ago(3)},
		}},
		{name: "beta", pulls: []fPull{{num: 5, body: "Fixes swarm-routing/alpha#7", merged: ago(4)}}},
		{name: "hidden-lab", private: true, issues: []*fIssue{
			{num: 1, title: "private done", body: acDone, created: ago(30)},
			{num: 2, title: "private none", body: "x", created: ago(30)},
		}, pulls: []fPull{{num: 9, body: "Closes swarm-routing/alpha#22", merged: ago(2)}}},
		{name: "papers", issues: []*fIssue{{num: 1, title: "nearly", body: acOpen, created: ago(30)}}},
		{name: "attic", archived: true, issues: []*fIssue{{num: 1, title: "archived done", body: acDone, created: ago(30)}}},
	}}
}

func run(t *testing.T, f *fake, args ...string) (string, string, int) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out, errb bytes.Buffer
	env := func(k string) string {
		if k == "GH_TOKEN" {
			return "tok"
		}
		return ""
	}
	code := Main(append(args, "--now", now.Format(time.RFC3339)), env, srv.Client(), srv.URL, &out, &errb)
	return out.String(), errb.String(), code
}

func closed(f *fake) []string {
	var out []string
	for _, w := range f.writes {
		if w.method == "PATCH" && w.body["state"] == "closed" {
			out = append(out, strings.TrimPrefix(w.path, "/repos/"+Org+"/")+" "+w.body["state_reason"].(string))
		}
	}
	sort.Strings(out)
	return out
}

func TestRun(t *testing.T) {
	f := org()
	out, errs, code := run(t, f)
	if code != 0 {
		t.Fatalf("exit %d: %s\n%s", code, errs, out)
	}
	want := []string{
		"alpha/issues/1 completed",    // every acceptance box ticked
		"alpha/issues/10 not_planned", // superseded by #11
		"alpha/issues/22 completed",   // a private repository's merged PR closes it
		"alpha/issues/3 completed",    // open boxes only inside <details> and a fence
		"alpha/issues/6 completed",    // its release is cut
		"alpha/issues/7 completed",    // beta's merged PR says Fixes swarm-routing/alpha#7
		"hidden-lab/issues/1 completed",
	}
	if got := closed(f); strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("closed:\n%s\nwant:\n%s\nlog:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"), out)
	}
	// each close is a comment then the close
	comments := map[string]string{}
	for _, w := range f.writes {
		if w.method == "POST" && strings.HasSuffix(w.path, "/comments") {
			comments[strings.TrimSuffix(strings.TrimPrefix(w.path, "/repos/"+Org+"/"), "/comments")] = w.body["body"].(string)
		}
	}
	if len(comments) != len(want) {
		t.Errorf("%d comments for %d closes", len(comments), len(want))
	}
	for k, c := range comments {
		if !strings.HasSuffix(c, Footer) {
			t.Errorf("%s: no footer", k)
		}
	}
	if c := comments["alpha/issues/7"]; !strings.Contains(c, "swarm-routing/beta#5 (merged ") {
		t.Errorf("alpha#7 comment: %s", c)
	}
	if c := comments["alpha/issues/10"]; !strings.Contains(c, "#11") {
		t.Errorf("alpha#10 comment: %s", c)
	}
	if c := comments["alpha/issues/22"]; !strings.Contains(c, "a private org repository") {
		t.Errorf("alpha#22 comment: %s", c)
	}
	// the report: opened once in .github, the private repositories masked
	var report string
	for _, w := range f.writes {
		if w.method == "POST" && w.path == "/repos/"+Org+"/.github/issues" {
			report = w.body["body"].(string)
			if w.body["title"] != ReportTitle {
				t.Errorf("report title %v", w.body["title"])
			}
		}
	}
	for _, s := range []string{
		"swarm-routing/alpha#2: 4 of 5 ticked (80%)",
		"swarm-routing/alpha#18: 2 of 2 ticked (100%)",
		"private repository 2: 1 issues", // papers, masked whatever its visibility
		"private repository 1 (1 issues)",
		"swarm-routing/alpha#9", "swarm-routing/.github#1",
		"### Closed this run (7)",
	} {
		if !strings.Contains(report, s) {
			t.Errorf("report misses %q:\n%s", s, report)
		}
	}
	// a private repository is never named, in the log, the report or a comment
	all := out + report
	for _, c := range comments {
		all += c
	}
	for _, bad := range []string{"hidden-lab", "papers", "attic"} {
		if strings.Contains(all, bad) {
			t.Errorf("%q appears:\n%s", bad, all)
		}
	}
	for _, s := range []string{"alpha#12", "alpha#16"} { // an epic, a pull request: not audited
		if strings.Contains(all, s+":") || strings.Contains(all, s+",") {
			t.Errorf("%s listed:\n%s", s, all)
		}
	}
	if !strings.Contains(out, "ticket-audit: 5 repositories, ") || !strings.Contains(out, "closed 7;") ||
		!strings.Contains(out, "report: opened #") {
		t.Errorf("summary line:\n%s", out)
	}
	// a second run closes nothing more and updates the report in place; a third writes nothing
	f.writes = nil
	out, _, code = run(t, f)
	if code != 0 || len(f.writes) != 1 || f.writes[0].method != "PATCH" || !strings.Contains(out, "closed 0;") ||
		!strings.Contains(out, "report: updated #") {
		t.Errorf("second run: exit %d, %d writes:\n%s", code, len(f.writes), out)
	}
	f.writes = nil
	out, _, code = run(t, f)
	if code != 0 || len(f.writes) != 0 || !strings.Contains(out, "unchanged") {
		t.Errorf("second run: exit %d, %d writes:\n%s", code, len(f.writes), out)
	}
}

func TestDryRunWritesNothing(t *testing.T) {
	f := org()
	out, errs, code := run(t, f, "--dry-run")
	if code != 0 || len(f.writes) != 0 {
		t.Fatalf("exit %d, writes %v: %s\n%s", code, f.writes, errs, out)
	}
	if !strings.Contains(out, "would close 7;") || !strings.Contains(out, "report: would open it") ||
		!strings.Contains(out, "swarm-routing/alpha#1: every acceptance-criteria box ticked (2 of 2); dry run: would close") ||
		!strings.Contains(out, "nearly done: swarm-routing/alpha#2 (4/5)") {
		t.Errorf("dry run:\n%s", out)
	}
	if strings.Contains(out, "hidden-lab") || strings.Contains(out, "papers") {
		t.Errorf("a private repository named:\n%s", out)
	}
	// no token: a dry run too
	srv := httptest.NewServer(f)
	defer srv.Close()
	var o bytes.Buffer
	if c := Main([]string{"--repos", "alpha"}, func(string) string { return "" }, srv.Client(), srv.URL, &o, io.Discard); c != 0 ||
		len(f.writes) != 0 || !strings.Contains(o.String(), "no GH_TOKEN: dry run") {
		t.Errorf("no token: %d %s", c, o.String())
	}
}

func TestBudget(t *testing.T) {
	r := &fRepo{name: "many"}
	for n := 1; n <= MaxCloses+5; n++ {
		r.issues = append(r.issues, &fIssue{num: n, title: "done", body: acDone, created: ago(30)})
	}
	f := &fake{repos: []*fRepo{{name: ".github"}, r}}
	out, _, code := run(t, f)
	if code != 0 || len(closed(f)) != MaxCloses || !strings.Contains(out, "5 deferred to the next run") {
		t.Fatalf("exit %d, %d closed:\n%s", code, len(closed(f)), out)
	}
	f.writes = nil
	if _, _, code := run(t, f); code != 0 || len(closed(f)) != 5 {
		t.Errorf("second run closed %d", len(closed(f)))
	}
}

func TestUsage(t *testing.T) {
	var o, e bytes.Buffer
	if c := Main([]string{"--bogus"}, func(string) string { return "" }, nil, "", &o, &e); c != 2 {
		t.Errorf("exit %d", c)
	}
	if c := Main([]string{"--repos", "../x", "--dry-run"}, func(string) string { return "" }, http.DefaultClient, "http://127.0.0.1:1", &o, &e); c != 1 {
		t.Errorf("bad name: exit %d", c)
	}
	if c := Main([]string{"--help"}, nil, nil, "", &o, &e); c != 0 {
		t.Errorf("help: exit %d", c)
	}
}
