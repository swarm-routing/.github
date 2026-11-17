// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package branchsweep

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

var now = time.Date(2026, 11, 17, 4, 17, 0, 0, time.UTC)

func ago(d time.Duration) time.Time { return now.Add(-d) }

const day = 24 * time.Hour

type fBranch struct {
	name      string
	protected bool
	commit    time.Time
}

type fPull struct {
	number   int
	state    string // open or closed
	head     string
	headRepo string // "" = this repository
	base     string
	closed   time.Time
}

type fRepo struct {
	name, def string
	archived  bool
	private   bool
	branches  []fBranch
	pulls     []fPull
}

// fakeGitHub serves the org's repositories, their branches, PRs and commits, and records deletes.
type fakeGitHub struct {
	mu      sync.Mutex
	repos   []*fRepo
	deletes []string
	refuse  string // a branch whose delete is refused (403)
	gone    string // a branch already deleted (422)
	calls   []string
	auth    []string
}

// sha is a branch tip's commit id in the fake.
func sha(branch string) string { return "sha-" + strings.ReplaceAll(branch, "/", "_") }

func (f *fakeGitHub) repo(name string) *fRepo {
	for _, r := range f.repos {
		if r.name == name {
			return r
		}
	}
	return nil
}

func page[T any](w http.ResponseWriter, q url.Values, items []T) {
	per, _ := strconv.Atoi(q.Get("per_page"))
	pg, _ := strconv.Atoi(q.Get("page"))
	if per <= 0 || pg <= 0 {
		http.Error(w, "paging", 400)
		return
	}
	lo := (pg - 1) * per
	if lo > len(items) {
		lo = len(items)
	}
	hi := lo + per
	if hi > len(items) {
		hi = len(items)
	}
	_ = json.NewEncoder(w).Encode(items[lo:hi])
}

func (f *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, r.Method+" "+r.URL.Path)
	f.auth = append(f.auth, r.Header.Get("Authorization"))
	q := r.URL.Query()
	path := r.URL.EscapedPath()
	if path == "/orgs/swarm-routing/repos" && r.Method == "GET" {
		var out []map[string]any
		for _, x := range f.repos {
			out = append(out, map[string]any{"name": x.name, "full_name": "swarm-routing/" + x.name,
				"default_branch": x.def, "archived": x.archived, "private": x.private})
		}
		page(w, q, out)
		return
	}
	parts := strings.Split(strings.TrimPrefix(path, "/repos/swarm-routing/"), "/")
	rp := f.repo(parts[0])
	if rp == nil {
		http.Error(w, "no repo", 404)
		return
	}
	full := "swarm-routing/" + rp.name
	switch {
	case len(parts) == 1:
		_ = json.NewEncoder(w).Encode(map[string]any{"name": rp.name, "full_name": full,
			"default_branch": rp.def, "archived": rp.archived, "private": rp.private})
	case len(parts) == 2 && parts[1] == "branches":
		var out []map[string]any
		for _, b := range rp.branches {
			if q.Get("protected") == "false" && b.protected {
				continue
			}
			out = append(out, map[string]any{"name": b.name, "protected": b.protected,
				"commit": map[string]any{"sha": sha(b.name)}})
		}
		page(w, q, out)
	case len(parts) == 2 && parts[1] == "pulls":
		head := q.Get("head") // owner:branch matches a head in the owner's repositories
		var out []map[string]any
		for _, p := range rp.pulls {
			if q.Get("state") != "all" && p.state != q.Get("state") {
				continue
			}
			hr := p.headRepo
			if hr == "" {
				hr = full
			}
			if head != "" && (head != strings.Split(hr, "/")[0]+":"+p.head) {
				continue
			}
			pr := map[string]any{"number": p.number, "state": p.state,
				"head": map[string]any{"ref": p.head, "repo": map[string]any{"full_name": hr}},
				"base": map[string]any{"ref": p.base}}
			if p.state == "closed" {
				pr["closed_at"] = p.closed.Format(time.RFC3339)
			}
			out = append(out, pr)
		}
		page(w, q, out)
	case len(parts) == 3 && parts[1] == "commits":
		for _, b := range rp.branches {
			if sha(b.name) == parts[2] {
				fmt.Fprintf(w, `{"commit": {"committer": {"date": %q}}}`, b.commit.Format(time.RFC3339))
				return
			}
		}
		http.Error(w, "no commit", 404)
	case len(parts) >= 5 && parts[1] == "git" && parts[2] == "refs" && r.Method == "DELETE":
		ref, _ := url.PathUnescape(strings.Join(parts[3:], "/"))
		if ref == "heads/"+f.refuse {
			http.Error(w, `{"message": "Resource not accessible by integration"}`, http.StatusForbidden)
			return
		}
		if ref == "heads/"+f.gone {
			http.Error(w, `{"message": "Reference does not exist"}`, http.StatusUnprocessableEntity)
			return
		}
		f.deletes = append(f.deletes, rp.name+" "+ref)
		w.WriteHeader(204)
	default:
		http.Error(w, "unexpected "+r.Method+" "+path, 500)
	}
}

// org is one repository with a branch for every rule and exclusion, and an archived one.
func org() *fakeGitHub {
	old := ago(30 * day)
	return &fakeGitHub{repos: []*fRepo{
		{name: "ARA", def: "trunk", branches: []fBranch{
			{name: "trunk", commit: old},       // the default branch
			{name: "main", commit: old},        // main, even when not the default
			{name: "bot/release", commit: old}, // the release PR's branch
			{name: "gh-readonly-queue/main/pr-9-abc", commit: old},
			{name: "release/v1", commit: old}, // a release branch
			{name: "claude/protected", protected: true, commit: old},
			{name: "claude/open-head", commit: old},                     // an open PR's head
			{name: "claude/stack-base", commit: old},                    // an open PR's base
			{name: "claude/closed-recent", commit: old},                 // PR closed a day ago
			{name: "claude/closed-old", commit: old},                    // PR closed 3 days ago: deleted
			{name: "feature/merged-old", commit: old},                   // merged 5 days ago, any prefix: deleted
			{name: "claude/closed-then-pushed", commit: ago(time.Hour)}, // a commit after the close
			{name: "claude/validate-x", commit: ago(8 * day)},           // no PR, idle 8 days: deleted
			{name: "org-bot/org-sync-old", commit: ago(10 * day)},       // no PR, idle: deleted
			{name: "claude/idle-recent", commit: ago(6 * day)},          // no PR, 6 days: kept
			{name: "feature/no-pr", commit: old},                        // no PR, not an agent's: kept
			{name: "claude/fork-name", commit: ago(day)},                // only a fork's PR shares the name
		}, pulls: []fPull{
			{number: 1, state: "open", head: "claude/open-head", base: "trunk"},
			{number: 2, state: "open", head: "claude/stacked", base: "claude/stack-base"},
			{number: 3, state: "closed", head: "claude/closed-recent", base: "trunk", closed: ago(day)},
			{number: 4, state: "closed", head: "claude/closed-old", base: "trunk", closed: ago(3 * day)},
			{number: 5, state: "closed", head: "claude/closed-old", base: "trunk", closed: ago(9 * day)},
			{number: 6, state: "closed", head: "feature/merged-old", base: "trunk", closed: ago(5 * day)},
			{number: 7, state: "closed", head: "claude/closed-then-pushed", base: "trunk", closed: ago(4 * day)},
			{number: 8, state: "closed", head: "claude/fork-name", headRepo: "someone/ARA", base: "trunk", closed: ago(9 * day)},
			{number: 9, state: "closed", head: "bot/release", base: "trunk", closed: ago(9 * day)},
		}},
		{name: "old-thing", def: "main", archived: true, branches: []fBranch{{name: "claude/x", commit: old}}},
	}}
}

func sweep(t *testing.T, f *fakeGitHub, dry bool, names ...string) (string, error) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	_, err := Run(GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}, names, now, dry, true, &out)
	return out.String(), err
}

func TestRules(t *testing.T) {
	f := org()
	out, err := sweep(t, f, false)
	if err != nil {
		t.Fatalf("%v\n%s", err, out)
	}
	want := []string{
		"ARA heads/claude/closed-old",
		"ARA heads/claude/validate-x",
		"ARA heads/feature/merged-old",
		"ARA heads/org-bot/org-sync-old",
	}
	got := append([]string(nil), f.deletes...)
	sort.Strings(got)
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("deleted:\n%s\nwant:\n%s\nout:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"), out)
	}
	for _, line := range []string{
		"ARA claude/closed-old: PR #4 closed 72h0m0s ago; deleted",
		"ARA claude/validate-x: no PR, last commit 192h0m0s ago; deleted",
		"ARA trunk: kept: the default branch",
		"ARA main: kept: main",
		"ARA bot/release: kept: the release PR's branch",
		"ARA gh-readonly-queue/main/pr-9-abc: kept: a merge-queue branch",
		"ARA release/v1: kept: a release branch",
		"ARA claude/open-head: kept: open PR #1",
		"ARA claude/stack-base: kept: open PR #2",
		"ARA claude/closed-recent: kept: PR #3 closed 24h0m0s ago",
		"ARA claude/closed-then-pushed: kept: PR #7 closed, but a commit 1h0m0s ago",
		"ARA claude/idle-recent: kept: no PR, last commit 144h0m0s ago",
		"ARA feature/no-pr: kept: no PR, not claude/* or org-bot/*",
		"ARA claude/fork-name: kept: no PR, last commit 24h0m0s ago",
		"ARA: 16 branches, deleted 4, kept 12",
		"old-thing: archived, skipped",
		"branch-sweep: 2 repositories, deleted 4 branches, kept 12",
	} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
	for _, c := range f.calls {
		if strings.Contains(c, "/claude/protected") || strings.Contains(c, "old-thing/") {
			t.Errorf("a protected branch or an archived repository was read: %s", c)
		}
		if strings.HasPrefix(c, "DELETE") && !strings.Contains(c, "/git/refs/heads/") {
			t.Errorf("only branch refs are deleted, never tags: %s", c)
		}
	}
	for _, a := range f.auth {
		if a != "Bearer tok" {
			t.Errorf("token header: %q", a)
		}
	}
	// idempotent: what is left is kept
	f.repos[0].branches = keep(f.repos[0].branches, want)
	n := len(f.deletes)
	out, _ = sweep(t, f, false)
	if len(f.deletes) != n || !strings.Contains(out, "deleted 0 branches") {
		t.Errorf("a second run deletes nothing:\n%s", out)
	}
}

func keep(bs []fBranch, deleted []string) []fBranch {
	var out []fBranch
	for _, b := range bs {
		gone := false
		for _, d := range deleted {
			if d == "ARA heads/"+b.name {
				gone = true
			}
		}
		if !gone {
			out = append(out, b)
		}
	}
	return out
}

// The protected branch is refused by name too, when a listing returns it.
func TestProtectedFlag(t *testing.T) {
	g := GitHub{}
	b := branch{Name: "claude/p", Protected: true}
	d, err := g.decide(Repo{FullName: "swarm-routing/x", DefaultBranch: "main"}, b, nil, now)
	if err != nil || d.Delete || d.Why != "kept: a protected branch" {
		t.Fatalf("%+v %v", d, err)
	}
	for _, n := range []string{"main", "bot/release", "gh-readonly-queue/main/pr-1-x", "release/1.x", "releases/2", "release"} {
		if Protected(n, "trunk") == "" {
			t.Errorf("%s must be protected", n)
		}
	}
	for _, n := range []string{"bot/hub-data", "claude/release-notes", "org-bot/release-lock", "mainline"} {
		if Protected(n, "trunk") != "" {
			t.Errorf("%s must not be protected by name", n)
		}
	}
}

func TestDryRunOnlyReads(t *testing.T) {
	f := org()
	out, err := sweep(t, f, true)
	if err != nil {
		t.Fatal(err)
	}
	if len(f.deletes) != 0 {
		t.Fatalf("a dry run deleted %v", f.deletes)
	}
	for _, c := range f.calls {
		if !strings.HasPrefix(c, "GET ") {
			t.Errorf("a dry run only reads: %s", c)
		}
	}
	for _, line := range []string{
		"ARA claude/closed-old: PR #4 closed 72h0m0s ago; dry run: would delete",
		"ARA: 16 branches, would delete 4, kept 12",
		"branch-sweep: 2 repositories, would delete 4 branches, kept 12",
	} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
}

func TestRefusedAndGone(t *testing.T) {
	f := org()
	f.refuse, f.gone = "claude/closed-old", "claude/validate-x"
	out, err := sweep(t, f, false)
	if err == nil || !strings.Contains(err.Error(), "1 of 2 repositories failed") {
		t.Fatalf("a refused delete fails the run: %v\n%s", err, out)
	}
	for _, line := range []string{
		"ARA claude/closed-old: delete refused (the token needs Contents: write)",
		"ARA claude/validate-x: no PR, last commit 192h0m0s ago; already gone",
		"ARA: 16 branches, deleted 2, kept 12, 1 failed",
	} {
		if !strings.Contains(out, line) {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
	if len(f.deletes) != 2 {
		t.Errorf("the other deletions still run: %v", f.deletes)
	}
}

func TestBudget(t *testing.T) {
	f := &fakeGitHub{repos: []*fRepo{{name: "Termite", def: "main"}}}
	for i := 0; i < MaxDeletes+3; i++ {
		f.repos[0].branches = append(f.repos[0].branches, fBranch{name: fmt.Sprintf("claude/v-%03d", i), commit: ago(9 * day)})
	}
	out, err := sweep(t, f, false, "Termite")
	if err != nil {
		t.Fatal(err)
	}
	if len(f.deletes) != MaxDeletes || !strings.Contains(out, "deleted 200 branches, kept 3, 3 deferred to the next run") {
		t.Fatalf("%d deletes\n%s", len(f.deletes), out[len(out)-300:])
	}
	for _, c := range f.calls {
		if strings.HasPrefix(c, "GET /orgs/") {
			t.Errorf("--repos reads the named repositories only: %s", c)
		}
	}
}

func TestCommand(t *testing.T) {
	f := org()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out, errb bytes.Buffer
	env := func(string) string { return "" }
	if rc := Main([]string{"--now", now.Format(time.RFC3339), "--repos", "ARA"}, env, srv.Client(), srv.URL, &out, &errb); rc != 0 {
		t.Fatalf("rc %d: %s %s", rc, out.String(), errb.String())
	}
	if !strings.HasPrefix(out.String(), "branch-sweep: no GH_TOKEN: dry run\n") || len(f.deletes) != 0 {
		t.Errorf("no token is a dry run:\n%s", out.String())
	}
	if rc := Main([]string{"--bogus"}, env, srv.Client(), srv.URL, &out, &errb); rc != 2 {
		t.Errorf("usage: rc %d", rc)
	}
	if rc := Main([]string{"--repos", "../x"}, env, srv.Client(), srv.URL, &out, &errb); rc != 1 {
		t.Errorf("a bad repository name: rc %d", rc)
	}
}

// A private repository's name and branch names never reach the output, which a
// public workflow log holds; its deletions still happen.
func TestPrivateNeverNamed(t *testing.T) {
	f := &fakeGitHub{repos: []*fRepo{
		{name: "secretlib", def: "main", private: true, branches: []fBranch{
			{name: "claude/hidden-topic", commit: ago(9 * day)},
			{name: "claude/hidden-fail", commit: ago(9 * day)},
			{name: "feature/hidden-kept", commit: ago(9 * day)},
		}},
		{name: "ARA", def: "main", branches: []fBranch{{name: "claude/v", commit: ago(9 * day)}}},
	}}
	f.refuse = "claude/hidden-fail"
	out, _ := sweep(t, f, false)
	for _, x := range []string{"secretlib", "hidden"} {
		if strings.Contains(out, x) {
			t.Fatalf("%q printed:\n%s", x, out)
		}
	}
	for _, line := range []string{
		"private repository 1 branch 2: no PR, last commit 216h0m0s ago; deleted",
		"private repository 1 branch 1: delete refused (the token needs Contents: write): DELETE repos/<private>/git/refs/heads/<branch>: HTTP 403",
		"private repository 1: 3 branches, deleted 1, kept 1, 1 failed",
		"ARA claude/v: no PR, last commit 216h0m0s ago; deleted",
	} {
		if !strings.Contains(out, line) {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
	if len(f.deletes) != 2 {
		t.Errorf("deletes: %v", f.deletes)
	}
}
