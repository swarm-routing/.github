// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package citoolsdigest

import (
	"bytes"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"sync"
	"testing"
)

func sum(b []byte) string {
	s := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(s[:])
}

func rev(c byte) string { return strings.Repeat(string(c), 40) }

// fake is GHCR (under /reg) and the GitHub API (the rest) in one server.
type fake struct {
	mu      sync.Mutex
	objects map[string][]byte            // registry digest -> manifest or config
	repos   []repo                       // the org's repositories
	files   map[string]map[string]string // full name -> path -> text on main
	compare map[string]string            // "old...new" -> status
	pulls   map[string][]map[string]any  // full name -> open pulls
	pfiles  map[string][]map[string]any  // "full#n" -> changed files
	branch  map[string]bool              // full name -> org-bot/ci-tools-digest exists
	writes  []string
	bodies  []map[string]any
}

func newFake() *fake {
	return &fake{objects: map[string][]byte{}, files: map[string]map[string]string{}, compare: map[string]string{},
		pulls: map[string][]map[string]any{}, pfiles: map[string][]map[string]any{}, branch: map[string]bool{}}
}

// image stores an image built from commit r (label empty: no label) and
// returns its digest; index wraps it in an index.
func (f *fake) image(r string, index bool) string {
	labels := map[string]string{}
	if r != "" {
		labels[RevisionLabel] = r
	}
	cfg, _ := json.Marshal(map[string]any{"config": map[string]any{"Labels": labels}})
	f.objects[sum(cfg)] = cfg
	man, _ := json.Marshal(map[string]any{"schemaVersion": 2, "config": map[string]string{"digest": sum(cfg)}})
	f.objects[sum(man)] = man
	if !index {
		return sum(man)
	}
	idx, _ := json.Marshal(map[string]any{"schemaVersion": 2, "manifests": []map[string]any{
		{"digest": sum(cfg), "platform": map[string]string{"os": "linux", "architecture": "arm64"}},
		{"digest": sum(man), "platform": map[string]string{"os": "linux", "architecture": "amd64"}},
	}})
	f.objects[sum(idx)] = idx
	return sum(idx)
}

func blobSHA(full, path string) string {
	h := sha1.Sum([]byte(full + ":" + path))
	return hex.EncodeToString(h[:])
}

func (f *fake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	send := func(v any) { _ = json.NewEncoder(w).Encode(v) }
	p := strings.TrimPrefix(r.URL.Path, "/")
	if strings.HasPrefix(p, "reg/") {
		if p == "reg/token" {
			send(map[string]string{"token": "anon"})
			return
		}
		if r.Header.Get("Authorization") != "Bearer anon" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		i := strings.LastIndex(p, "/")
		if obj, ok := f.objects[p[i+1:]]; ok {
			_, _ = w.Write(obj)
			return
		}
		w.WriteHeader(http.StatusNotFound)
		return
	}
	q := r.URL.Query()
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
			send(map[string]string{"sha": "c0ffee"})
		case strings.HasSuffix(p, "/pulls"):
			send(map[string]any{"number": 7, "node_id": "PR_7"})
		case strings.Contains(p, "/pulls/"):
			send(map[string]any{"number": 5, "node_id": "PR_5"})
		default:
			send(map[string]any{})
		}
		return
	}
	if p == "orgs/swarm-routing/repos" {
		page(f.repos)
		return
	}
	if c, ok := strings.CutPrefix(p, "repos/"+Home+"/compare/"); ok {
		if s, ok := f.compare[c]; ok {
			send(map[string]string{"status": s})
			return
		}
		w.WriteHeader(http.StatusNotFound)
		return
	}
	for _, rp := range f.repos {
		full := rp.FullName
		pre := "repos/" + full
		switch {
		case p == pre:
			send(rp)
		case p == pre+"/git/ref/heads/main":
			send(map[string]any{"object": map[string]string{"sha": "head-" + rp.Name}})
		case p == pre+"/git/ref/heads/"+Branch:
			if !f.branch[full] {
				http.Error(w, `{"message":"Not Found"}`, http.StatusNotFound)
				return
			}
			send(map[string]any{"object": map[string]string{"sha": "bot-" + rp.Name}})
		case p == pre+"/git/commits/head-"+rp.Name:
			send(map[string]any{"tree": map[string]string{"sha": "tree-" + rp.Name}})
		case p == pre+"/git/commits/bot-"+rp.Name:
			send(map[string]any{"tree": map[string]string{"sha": "oldtree"}, "parents": []map[string]string{{"sha": "head-" + rp.Name}}})
		case p == pre+"/git/trees/tree-"+rp.Name:
			var entries []map[string]string
			for path := range f.files[full] {
				entries = append(entries, map[string]string{"path": path, "mode": "100644", "type": "blob", "sha": blobSHA(full, path)})
			}
			entries = append(entries, map[string]string{"path": ".github/workflows", "mode": "040000", "type": "tree", "sha": "t"})
			sort.Slice(entries, func(i, j int) bool { return entries[i]["path"] < entries[j]["path"] })
			send(map[string]any{"tree": entries})
		case strings.HasPrefix(p, pre+"/git/blobs/"):
			for path, text := range f.files[full] {
				if strings.HasSuffix(p, blobSHA(full, path)) {
					send(map[string]string{"encoding": "base64", "content": base64.StdEncoding.EncodeToString([]byte(text))})
					return
				}
			}
			w.WriteHeader(http.StatusNotFound)
		case p == pre+"/pulls":
			var out []map[string]any
			for _, pr := range f.pulls[full] {
				if h := q.Get("head"); h == "" || h == Org+":"+pr["head"].(map[string]any)["ref"].(string) {
					out = append(out, pr)
				}
			}
			page(out)
		case strings.HasPrefix(p, pre+"/pulls/") && strings.HasSuffix(p, "/files"):
			n := strings.TrimSuffix(strings.TrimPrefix(p, pre+"/pulls/"), "/files")
			page(f.pfiles[full+"#"+n])
		default:
			continue
		}
		return
	}
	w.WriteHeader(http.StatusNotFound)
}

func (f *fake) run(t *testing.T, args ...string) (int, string, string) {
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
	code := Main(args, env, srv.Client(), srv.URL, srv.URL+"/reg", &out, &errb)
	return code, out.String(), errb.String()
}

func (f *fake) addRepo(name string, files map[string]string) string {
	full := Org + "/" + name
	f.repos = append(f.repos, repo{Name: name, FullName: full, DefaultBranch: "main"})
	f.files[full] = files
	return full
}

func TestRewrite(t *testing.T) {
	old, cur, keep := "sha256:"+strings.Repeat("a", 64), "sha256:"+strings.Repeat("b", 64), "sha256:"+strings.Repeat("c", 64)
	in := "      IMG: " + Image + "@" + old + "  # promoted from 29c9ad4: the alarm (#751)\n" +
		"      IMG: " + Image + "@" + old + "\n" +
		"      IMG: " + Image + "@" + cur + "  # promoted from 1234567: why\n" +
		"  CI_TOOLS: " + Image + "@" + keep + "  # promoted from 7654321\n" +
		"look-alikes: evil." + Image + "@" + old + " " + Image + "@" + old + "ff " + Image + "-dev@" + old + "\n" +
		"no newline: " + Image + "@" + old
	got := Rewrite(in, cur, "def5678", func(d string) bool { return d == old })
	want := "      IMG: " + Image + "@" + cur + "  # promoted from def5678\n" +
		"      IMG: " + Image + "@" + cur + "\n" +
		"      IMG: " + Image + "@" + cur + "  # promoted from 1234567: why\n" +
		"  CI_TOOLS: " + Image + "@" + keep + "  # promoted from 7654321\n" +
		"look-alikes: evil." + Image + "@" + old + " " + Image + "@" + old + "ff " + Image + "-dev@" + old + "\n" +
		"no newline: " + Image + "@" + cur
	if got != want {
		t.Fatalf("Rewrite:\n%s\nwant:\n%s", got, want)
	}
	if p := Pins(in); len(p) != 3 || p[0] != old || p[2] != keep {
		t.Fatalf("Pins: %v", p)
	}
}

func TestRevision(t *testing.T) {
	f := newFake()
	plain, idx, nolabel := f.image(rev('a'), false), f.image(rev('b'), true), f.image("", false)
	srv := httptest.NewServer(f)
	defer srv.Close()
	reg := &Registry{Base: srv.URL + "/reg", Client: srv.Client()}
	if r, err := reg.Revision(plain); err != nil || r != rev('a') {
		t.Fatalf("plain manifest: %q %v", r, err)
	}
	if r, err := reg.Revision(idx); err != nil || r != rev('b') {
		t.Fatalf("index: %q %v", r, err)
	}
	if _, err := reg.Revision(nolabel); err == nil || !strings.Contains(err.Error(), RevisionLabel) {
		t.Fatalf("no label: %v", err)
	}
	// an answer that is not the object asked for is refused
	f.objects[sum([]byte("x"))] = []byte("y")
	if _, err := reg.Revision(sum([]byte("x"))); err == nil || !strings.Contains(err.Error(), "registry answered") {
		t.Fatalf("content mismatch: %v", err)
	}
	if _, err := reg.Revision("sha256:nope"); err == nil {
		t.Fatal("a malformed digest must be refused")
	}
}

func wf(d, comment string) string {
	return "jobs:\n  x:\n    env:\n      IMG: " + Image + "@" + d + comment + "\n"
}

func TestRun(t *testing.T) {
	f := newFake()
	newD := f.image(rev('9'), false)
	oldD := f.image(rev('1'), false)
	newerD := f.image(rev('8'), false) // a pin to an image newer than the one promoted (e.g. a race)
	unknownD := "sha256:" + strings.Repeat("e", 64)
	f.compare[rev('1')+"..."+rev('9')] = "ahead"
	f.compare[rev('8')+"..."+rev('9')] = "behind"

	home := f.addRepo(".github", map[string]string{
		".github/workflows/a.yml":      wf(oldD, "  # promoted from 1111111: why"),
		".github/workflows/b.yml":      wf(newD, ""),
		".github/workflows/c.yml":      wf(newerD, ""),
		".github/workflows/u.yml":      wf(unknownD, ""),
		"templates/x/ci.yml":           wf(oldD, ""),
		"docs/tools.md":                Image + "@" + oldD,
		".github/actions/x/action.yml": "runs: {}\n",
	})
	current := f.addRepo("ARA", map[string]string{".github/workflows/ci.yml": wf(newD, "")})
	managed := f.addRepo("BeeAdHoc", map[string]string{".github/workflows/m.yml": ManagedMarker + "\n" + wf(oldD, "")})
	held := f.addRepo("HOPNET", map[string]string{".github/workflows/ci.yml": wf(oldD, "")})
	f.pulls[held] = []map[string]any{{"number": 3, "node_id": "PR_3", "head": map[string]any{"ref": "claude/bump", "sha": "x"}}}
	f.pfiles[held+"#3"] = []map[string]any{{"filename": ".github/workflows/ci.yml", "patch": "-IMG: ci-tools@sha256:" + strings.Repeat("1", 64)}}
	stale := f.addRepo("Termite", map[string]string{".github/workflows/ci.yml": wf(newD, "")})
	f.pulls[stale] = []map[string]any{{"number": 5, "node_id": "PR_5", "head": map[string]any{"ref": Branch, "sha": "bot-Termite"}}}
	f.branch[stale] = true

	// dry run: everything read, nothing written
	code, out, errs := f.run(t, "--digest", newD, "--dry-run")
	if code != 0 || len(f.writes) != 0 {
		t.Fatalf("dry run: exit %d, writes %v\n%s%s", code, f.writes, out, errs)
	}
	for _, want := range []string{
		home + `: would open "chore(deps): bump ci-tools to sha-9999999" on ` + Branch + ": .github/workflows/a.yml, templates/x/ci.yml",
		"keep " + newerD + " (from 8888888): 9999999 is behind of it, never moved back",
		"keep " + unknownD + ": its commit is unknown",
		held + ": held: #3 bumps the same pin by hand",
		stale + ": would close #5: every pin is current",
		"1 opened, 0 updated, 2 current, 1 held by a hand PR, 1 closed, 2 pins kept, 0 deferred, 0 failed (dry run: nothing written)",
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("dry run output lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, current) || strings.Contains(out, managed) {
		t.Fatalf("a current or org-managed repository must say nothing:\n%s", out)
	}

	// the real run writes exactly the commit, branch, pull request and auto-merge here
	code, out, errs = f.run(t, "--digest", newD)
	if code != 0 {
		t.Fatalf("run: exit %d\n%s%s", code, out, errs)
	}
	want := []string{
		"POST repos/" + home + "/git/trees",
		"POST repos/" + home + "/git/commits",
		"POST repos/" + home + "/git/refs",
		"POST repos/" + home + "/pulls",
		"POST graphql",
		"POST repos/" + stale + "/issues/5/comments",
		"PATCH repos/" + stale + "/pulls/5",
	}
	if fmt.Sprint(f.writes) != fmt.Sprint(want) {
		t.Fatalf("writes %v, want %v", f.writes, want)
	}
	tree := f.bodies[0]["tree"].([]any)
	if len(tree) != 2 {
		t.Fatalf("tree entries: %v", tree)
	}
	for _, e := range tree {
		m := e.(map[string]any)
		text := m["content"].(string)
		if strings.Contains(text, oldD) || !strings.Contains(text, newD) {
			t.Fatalf("%s not moved:\n%s", m["path"], text)
		}
		if m["path"] == ".github/workflows/a.yml" && !strings.Contains(text, "# promoted from 9999999\n") {
			t.Fatalf("comment not renewed:\n%s", text)
		}
	}
	if parents := f.bodies[1]["parents"].([]any); len(parents) != 1 || parents[0] != "head-.github" {
		t.Fatalf("parents: %v", parents)
	}
	pr := f.bodies[3]
	if pr["head"] != Branch || pr["base"] != "main" || pr["title"] != "chore(deps): bump ci-tools to sha-9999999" ||
		!strings.Contains(pr["body"].(string), "compare/1111111...9999999") {
		t.Fatalf("pull request: %v", pr)
	}
	if f.bodies[4]["variables"].(map[string]any)["pr"] != "PR_7" {
		t.Fatalf("auto-merge: %v", f.bodies[4])
	}
	if f.bodies[6]["state"] != "closed" {
		t.Fatalf("close: %v", f.bodies[6])
	}
	if !strings.Contains(out, home+`: opened #7 "chore(deps): bump ci-tools to sha-9999999"`) || !strings.Contains(out, "auto-merge on") {
		t.Fatalf("run output:\n%s", out)
	}
}

func TestRunUpdatesItsBranch(t *testing.T) {
	f := newFake()
	newD, oldD := f.image(rev('9'), true), f.image(rev('1'), false)
	f.compare[rev('1')+"..."+rev('9')] = "ahead"
	full := f.addRepo("ARA", map[string]string{".github/workflows/ci.yml": wf(oldD, "")})
	f.pulls[full] = []map[string]any{{"number": 5, "node_id": "PR_5", "head": map[string]any{"ref": Branch, "sha": "bot-ARA"}}}
	f.branch[full] = true
	code, out, errs := f.run(t, "--digest", newD, "--repos", "ARA")
	want := []string{
		"POST repos/" + full + "/git/trees",
		"POST repos/" + full + "/git/commits",
		"PATCH repos/" + full + "/git/refs/heads/" + Branch,
		"PATCH repos/" + full + "/pulls/5",
		"POST graphql",
	}
	if code != 0 || fmt.Sprint(f.writes) != fmt.Sprint(want) {
		t.Fatalf("exit %d, writes %v, want %v\n%s%s", code, f.writes, want, out, errs)
	}
	if f.bodies[2]["force"] != true || !strings.Contains(out, full+": updated #5") {
		t.Fatalf("ref update %v\n%s", f.bodies[2], out)
	}
}

func TestAnUnplacedPinLeavesThePullRequestOpen(t *testing.T) {
	f := newFake()
	newD := f.image(rev('9'), false)
	unknownD := "sha256:" + strings.Repeat("e", 64)
	full := f.addRepo("ARA", map[string]string{".github/workflows/ci.yml": wf(unknownD, "")})
	f.pulls[full] = []map[string]any{{"number": 5, "node_id": "PR_5", "head": map[string]any{"ref": Branch, "sha": "bot-ARA"}}}
	code, out, errs := f.run(t, "--digest", newD)
	if code != 0 || len(f.writes) != 0 || !strings.Contains(out, full+": #5 left open: a pin's image could not be placed") {
		t.Fatalf("exit %d, writes %v\n%s%s", code, f.writes, out, errs)
	}
}

func TestRunRefusesAnUnplacedImage(t *testing.T) {
	f := newFake()
	nolabel := f.image("", false)
	f.addRepo("ARA", map[string]string{".github/workflows/ci.yml": wf(nolabel, "")})
	code, _, errs := f.run(t, "--digest", nolabel)
	if code != 1 || !strings.Contains(errs, "the new image") || len(f.writes) != 0 {
		t.Fatalf("exit %d, writes %v: %s", code, f.writes, errs)
	}
	if code, _, _ := f.run(t); code != 2 {
		t.Fatalf("no --digest: exit %d", code)
	}
	if code, _, _ := f.run(t, "--digest", "sha256:x", "--repos", "../x"); code != 1 {
		t.Fatalf("a bad digest: exit %d", code)
	}
}

func TestNoTokenIsADryRun(t *testing.T) {
	f := newFake()
	newD, oldD := f.image(rev('9'), false), f.image(rev('1'), false)
	f.compare[rev('1')+"..."+rev('9')] = "ahead"
	f.addRepo("ARA", map[string]string{".github/workflows/ci.yml": wf(oldD, "")})
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	code := Main([]string{"--digest", newD}, func(string) string { return "" }, srv.Client(), srv.URL, srv.URL+"/reg", &out, io.Discard)
	if code != 0 || len(f.writes) != 0 || !strings.Contains(out.String(), "no GH_TOKEN: dry run") {
		t.Fatalf("exit %d, writes %v\n%s", code, f.writes, out.String())
	}
}
