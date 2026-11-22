// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package actionpins

import (
	"bytes"
	"crypto/sha1"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// fake serves the parts of the API the sweep reads and records its writes.
type fake struct {
	mu       sync.Mutex
	repos    []repo
	pulls    map[string][]map[string]any // full name -> open pulls
	blobs    map[string]string           // blob sha -> text
	trees    map[string][]map[string]any // commit sha -> tree entries
	files    map[string][]map[string]any // "full#n" -> changed files
	comments map[string][]string         // "full#n" -> bodies
	main     map[string]string           // "full:path" -> text on the default branch
	writes   []string
	bodies   []map[string]any
}

func blobSHA(text string) string {
	h := sha1.Sum([]byte(text))
	return hex.EncodeToString(h[:])
}

func (f *fake) blob(text string) string {
	s := blobSHA(text)
	f.blobs[s] = text
	return s
}

func b64(s string) string { return base64.StdEncoding.EncodeToString([]byte(s)) }

func (f *fake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := strings.TrimPrefix(r.URL.Path, "/")
	q := r.URL.Query()
	send := func(v any) { _ = json.NewEncoder(w).Encode(v) }
	page := func(items any) {
		if q.Get("page") != "1" {
			send([]any{})
			return
		}
		send(items)
	}
	if r.Method != "GET" {
		var body map[string]any
		data, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(data, &body)
		f.writes = append(f.writes, r.Method+" "+p)
		f.bodies = append(f.bodies, body)
		switch {
		case strings.HasSuffix(p, "/git/trees"):
			send(map[string]string{"sha": "newtree"})
		case strings.HasSuffix(p, "/git/commits"):
			send(map[string]string{"sha": "c0ffee0000000000000000000000000000000000"})
		default:
			send(map[string]string{})
		}
		return
	}
	parts := strings.Split(p, "/")
	switch {
	case p == "orgs/swarm-routing/repos":
		page(f.repos)
	case len(parts) == 3 && parts[0] == "repos":
		for _, x := range f.repos {
			if x.FullName == parts[1]+"/"+parts[2] {
				send(x)
				return
			}
		}
		http.Error(w, "no repo", 404)
	case len(parts) == 4 && parts[3] == "pulls":
		page(f.pulls[parts[1]+"/"+parts[2]])
	case len(parts) == 6 && parts[3] == "git" && parts[4] == "trees":
		send(map[string]any{"sha": "tree-" + parts[5], "truncated": false, "tree": f.trees[parts[5]]})
	case len(parts) == 6 && parts[3] == "git" && parts[4] == "blobs":
		text, ok := f.blobs[parts[5]]
		if !ok {
			http.Error(w, "no blob", 404)
			return
		}
		send(map[string]string{"content": b64(text), "encoding": "base64"})
	case len(parts) == 6 && parts[3] == "pulls" && parts[5] == "files":
		page(f.files[parts[1]+"/"+parts[2]+"#"+parts[4]])
	case len(parts) == 6 && parts[3] == "issues" && parts[5] == "comments":
		var cs []map[string]string
		for _, b := range f.comments[parts[1]+"/"+parts[2]+"#"+parts[4]] {
			cs = append(cs, map[string]string{"body": b})
		}
		page(cs)
	case len(parts) > 4 && parts[3] == "contents":
		text, ok := f.main[parts[1]+"/"+parts[2]+":"+strings.Join(parts[4:], "/")]
		if !ok || q.Get("ref") != "main" {
			http.Error(w, "not found", 404)
			return
		}
		send(map[string]string{"content": b64(text), "encoding": "base64"})
	default:
		http.Error(w, "unexpected "+p, 500)
	}
}

func newFake() *fake {
	return &fake{pulls: map[string][]map[string]any{}, blobs: map[string]string{}, trees: map[string][]map[string]any{},
		files: map[string][]map[string]any{}, comments: map[string][]string{}, main: map[string]string{}}
}

func pr(n int, full, ref, sha, user string) map[string]any {
	return map[string]any{"number": n, "user": map[string]string{"login": user},
		"head": map[string]any{"ref": ref, "sha": sha, "repo": map[string]string{"full_name": full}}}
}

func run(t *testing.T, f *fake, dry bool) (Result, string, error) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	res, err := Sweep(GitHub{API: srv.URL, Token: "t", Client: srv.Client()}, nil, dry, &out)
	return res, out.String(), err
}

func TestSweepCompletesHomePull(t *testing.T) {
	f := newFake()
	f.repos = []repo{{Name: ".github", FullName: Home, DefaultBranch: "main"}}
	f.pulls[Home] = []map[string]any{
		pr(5, Home, "dependabot/github_actions/actions-abc", "head5", Bot),
		pr(6, Home, "claude/x", "head6", "someone"),
	}
	f.trees["head5"] = []map[string]any{
		{"path": ".github/workflows/ci.yml", "mode": "100644", "type": "blob", "sha": f.blob(wf(newSHA, "v2.24.0"))},
		{"path": "templates/workflows/x.yml", "mode": "100644", "type": "blob", "sha": f.blob(tpl(oldSHA, "v2.23.0"))},
		{"path": "README.md", "mode": "100644", "type": "blob", "sha": "unread"},
	}
	res, out, err := run(t, f, false)
	if err != nil || res.Committed != 1 {
		t.Fatalf("res %+v err %v\n%s", res, err, out)
	}
	want := []string{"POST repos/swarm-routing/.github/git/trees", "POST repos/swarm-routing/.github/git/commits",
		"PATCH repos/swarm-routing/.github/git/refs/heads/dependabot/github_actions/actions-abc"}
	if strings.Join(f.writes, "|") != strings.Join(want, "|") {
		t.Fatalf("writes %v", f.writes)
	}
	tree := f.bodies[0]["tree"].([]any)[0].(map[string]any)
	if tree["path"] != "templates/workflows/x.yml" || tree["content"] != tpl(newSHA, "v2.24.0") || f.bodies[0]["base_tree"] != "tree-head5" {
		t.Fatalf("tree body %v", f.bodies[0])
	}
	if ps := f.bodies[1]["parents"].([]any); len(ps) != 1 || ps[0] != "head5" {
		t.Fatalf("commit body %v", f.bodies[1])
	}
	if f.bodies[2]["sha"] != "c0ffee0000000000000000000000000000000000" || f.bodies[2]["force"] != false {
		t.Fatalf("ref body %v", f.bodies[2])
	}
	if !strings.Contains(out, ".github#5: committed c0ffee000000: move 1 files") {
		t.Fatalf("out:\n%s", out)
	}
}

func TestSweepHomeInStepAndDryRun(t *testing.T) {
	f := newFake()
	f.repos = []repo{{Name: ".github", FullName: Home, DefaultBranch: "main"}}
	f.pulls[Home] = []map[string]any{pr(5, Home, "dependabot/x", "head5", Bot)}
	f.trees["head5"] = []map[string]any{
		{"path": ".github/workflows/ci.yml", "mode": "100644", "type": "blob", "sha": f.blob(wf(newSHA, "v2.24.0"))},
		{"path": "templates/workflows/x.yml", "mode": "100644", "type": "blob", "sha": f.blob(tpl(oldSHA, "v2.23.0"))},
	}
	res, out, err := run(t, f, true)
	if err != nil || res.Committed != 1 || len(f.writes) != 0 || !strings.Contains(out, "dry run: would move 1 files") {
		t.Fatalf("dry: res %+v err %v writes %v\n%s", res, err, f.writes, out)
	}
	f.trees["head5"][1]["sha"] = f.blob(tpl(newSHA, "v2.24.0"))
	res, out, err = run(t, f, false)
	if err != nil || res.Committed != 0 || len(f.writes) != 0 || !strings.Contains(out, "templates at the workflows' pins") {
		t.Fatalf("in step: res %+v err %v writes %v\n%s", res, err, f.writes, out)
	}
}

const staleEnv = "# Copyright\n# the versions\nRUFF_VERSION=0.17.5\nCOVERAGE_VERSION=7.17.3\nSTATICCHECK_VERSION=2026.2.2\n"

// A pip bump of tools/requirements/*.in with a stale tools/versions.env gets
// exactly the key line changed, and nothing else (#809).
func TestSweepSyncsVersionsEnv(t *testing.T) {
	f := newFake()
	f.repos = []repo{{Name: ".github", FullName: Home, DefaultBranch: "main"}}
	f.pulls[Home] = []map[string]any{pr(804, Home, "dependabot/pip/tools/requirements/ruff-0.17.6", "head804", Bot)}
	f.trees["head804"] = []map[string]any{
		{"path": ".github/workflows/ci.yml", "mode": "100644", "type": "blob", "sha": f.blob(wf(newSHA, "v2.24.0"))},
		{"path": "templates/workflows/x.yml", "mode": "100644", "type": "blob", "sha": f.blob(tpl(newSHA, "v2.24.0"))},
		{"path": "tools/requirements/python-ci.in", "mode": "100644", "type": "blob", "sha": f.blob("# lock\nruff==0.17.6\ncoverage==7.17.3\n")},
		{"path": "tools/requirements/ci.in", "mode": "100644", "type": "blob", "sha": f.blob("shellcheck-py==0.11.0.1\n")},
		{"path": "tools/versions.env", "mode": "100644", "type": "blob", "sha": f.blob(staleEnv)},
	}
	res, out, err := run(t, f, false)
	if err != nil || res.Committed != 1 {
		t.Fatalf("res %+v err %v\n%s", res, err, out)
	}
	entries := f.bodies[0]["tree"].([]any)
	if len(entries) != 1 {
		t.Fatalf("tree %v", entries)
	}
	e := entries[0].(map[string]any)
	want := strings.Replace(staleEnv, "RUFF_VERSION=0.17.5", "RUFF_VERSION=0.17.6", 1)
	if e["path"] != "tools/versions.env" || e["content"] != want || e["mode"] != "100644" {
		t.Fatalf("entry %v", e)
	}
	if !strings.Contains(out, "tools/versions.env: RUFF_VERSION 0.17.5 -> 0.17.6 (tools/requirements/python-ci.in)") {
		t.Fatalf("out:\n%s", out)
	}
	// once committed, the next run finds nothing to do
	f.trees["head804"][4]["sha"] = f.blob(want)
	f.writes, f.bodies = nil, nil
	res, out, err = run(t, f, false)
	if err != nil || res.Committed != 0 || len(f.writes) != 0 {
		t.Fatalf("in step: res %+v err %v writes %v\n%s", res, err, f.writes, out)
	}
}

func TestSyncVersions(t *testing.T) {
	text, notes, err := SyncVersions(staleEnv, map[string]string{
		"tools/requirements/python-ci.in": "ruff==0.17.6\ncoverage==7.18.0  # a comment\n# ruff==9.9.9\nunpinned>=1\n",
	})
	want := strings.NewReplacer("RUFF_VERSION=0.17.5", "RUFF_VERSION=0.17.6", "COVERAGE_VERSION=7.17.3", "COVERAGE_VERSION=7.18.0").Replace(staleEnv)
	if err != nil || text != want || len(notes) != 2 {
		t.Fatalf("text %q notes %v err %v", text, notes, err)
	}
	if text, notes, err := SyncVersions(staleEnv, map[string]string{"a.in": "ruff==0.17.5\n"}); err != nil || text != staleEnv || notes != nil {
		t.Fatalf("in step: %q %v %v", text, notes, err)
	}
	if _, _, err := SyncVersions(staleEnv, map[string]string{"a.in": "ruff==1\n", "b.in": "ruff==2\n"}); err == nil {
		t.Fatal("two inputs disagreeing on ruff: no error")
	}
	for path, want := range map[string]bool{
		"tools/requirements/ci.in": true, "tools/requirements/ci.txt": false,
		"tools/requirements/x/y.in": false, "requirements/ci.in": false,
	} {
		if Requirement(path) != want {
			t.Errorf("Requirement(%q) != %v", path, want)
		}
	}
}

func consumerFake() *fake {
	f := newFake()
	const ara = "swarm-routing/ARA"
	const priv = "swarm-routing/secret"
	f.repos = []repo{{Name: "ARA", FullName: ara, DefaultBranch: "main"}, {Name: "secret", FullName: priv, DefaultBranch: "main", Private: true}}
	managedNew := tpl(newSHA, "v2.24.0")
	f.pulls[ara] = []map[string]any{
		pr(1, ara, "dependabot/a", "h1", Bot), // managed only
		pr(2, ara, "dependabot/b", "h2", Bot), // mixed, main caught up
		pr(3, ara, "dependabot/c", "h3", Bot), // mixed, refresh pending
		pr(4, ara, "dependabot/d", "h4", Bot), // own files only
	}
	f.pulls[priv] = []map[string]any{pr(9, priv, "dependabot/e", "h9", Bot)}
	f.files[ara+"#1"] = []map[string]any{{"filename": ".github/workflows/settings-apply.yml", "status": "modified", "sha": f.blob(managedNew)}}
	f.files[ara+"#2"] = []map[string]any{
		{"filename": ".github/workflows/epics-changed.yml", "status": "modified", "sha": f.blob(managedNew)},
		{"filename": ".github/workflows/core.yml", "status": "modified", "sha": f.blob(wf(newSHA, "v2.24.0"))},
	}
	f.main[ara+":.github/workflows/epics-changed.yml"] = managedNew
	f.files[ara+"#3"] = []map[string]any{
		{"filename": ".github/workflows/settings-apply.yml", "status": "modified", "sha": f.blob(managedNew)},
		{"filename": ".github/workflows/ns3.yml", "status": "modified", "sha": f.blob(wf(newSHA, "v2.24.0") + "#ns3\n")},
	}
	f.main[ara+":.github/workflows/settings-apply.yml"] = tpl(oldSHA, "v2.23.0")
	f.files[ara+"#4"] = []map[string]any{{"filename": ".github/workflows/core.yml", "status": "modified", "sha": f.blob(wf(newSHA, "v2.24.0"))}}
	f.files[priv+"#9"] = []map[string]any{{"filename": ".github/workflows/settings-apply.yml", "status": "modified", "sha": f.blob(managedNew)}}
	return f
}

func TestSweepConsumers(t *testing.T) {
	f := consumerFake()
	res, out, err := run(t, f, false)
	if err != nil {
		t.Fatalf("%v\n%s", err, out)
	}
	if res != (Result{Closed: 2, Rebased: 1, Waiting: 1}) {
		t.Fatalf("res %+v\n%s", res, out)
	}
	want := []string{
		"POST repos/swarm-routing/ARA/issues/1/comments", "PATCH repos/swarm-routing/ARA/pulls/1",
		"POST repos/swarm-routing/ARA/issues/2/comments",
		"POST repos/swarm-routing/secret/issues/9/comments", "PATCH repos/swarm-routing/secret/pulls/9",
	}
	if strings.Join(f.writes, "|") != strings.Join(want, "|") {
		t.Fatalf("writes %v", f.writes)
	}
	if b := f.bodies[0]["body"].(string); !strings.HasPrefix(b, CloseText) || !strings.Contains(b, marker("h1")) {
		t.Fatalf("close body %q", b)
	}
	if f.bodies[1]["state"] != "closed" {
		t.Fatalf("close %v", f.bodies[1])
	}
	if b := f.bodies[2]["body"].(string); !strings.HasPrefix(b, "@dependabot rebase\n") || !strings.Contains(b, marker("h2")) {
		t.Fatalf("rebase body %q", b)
	}
	if strings.Contains(out, "secret") || !strings.Contains(out, "private repository 1#9: closed") {
		t.Fatalf("a private repository was named:\n%s", out)
	}
	if !strings.Contains(out, "ARA#3: waiting: .github/workflows/settings-apply.yml on main") {
		t.Fatalf("out:\n%s", out)
	}
}

func TestSweepConsumersOncePerHead(t *testing.T) {
	f := consumerFake()
	f.comments["swarm-routing/ARA#1"] = []string{"x\n" + marker("h1")}
	f.comments["swarm-routing/ARA#2"] = []string{"x\n" + marker("old-head")}
	res, out, err := run(t, f, true)
	if err != nil || len(f.writes) != 0 {
		t.Fatalf("err %v writes %v", err, f.writes)
	}
	if res != (Result{Closed: 1, Rebased: 1, Waiting: 1}) || !strings.Contains(out, "ARA#1: already handled at h1") {
		t.Fatalf("res %+v\n%s", res, out)
	}
}

func TestMainSweepWithoutTokenIsDry(t *testing.T) {
	f := consumerFake()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out, errb bytes.Buffer
	rc := Main([]string{"sweep", "--repos", "ARA"}, func(string) string { return "" }, srv.Client(), srv.URL, &out, &errb)
	if rc != 0 || len(f.writes) != 0 || !strings.Contains(out.String(), "no GH_TOKEN: dry run") {
		t.Fatalf("rc %d writes %v\n%s%s", rc, f.writes, out.String(), errb.String())
	}
}
