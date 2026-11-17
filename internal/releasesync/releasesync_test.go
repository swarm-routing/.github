// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package releasesync

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

var now = time.Date(2026, 11, 17, 14, 23, 0, 0, time.UTC)

func ago(d time.Duration) time.Time { return now.Add(-d) }

type fRel struct {
	tag               string
	published         time.Time
	draft, prerelease bool
}

type fRepo struct {
	name                    string
	private, archived, fork bool
	releases                []fRel
}

type fIssue struct {
	number  int
	title   string
	created time.Time
	pr      bool
}

// fakeGitHub serves the org's repositories and releases, the site's issues and
// runs, and records dispatches (each starts a queued run of its release's name).
type fakeGitHub struct {
	mu         sync.Mutex
	repos      []fRepo
	issues     []fIssue
	runs       []run
	dispatches []string
	refuse     bool
	calls      []string
	at         time.Time // the time of the current run: a dispatched run starts then
}

func page[T any](w http.ResponseWriter, r *http.Request, items []T, wrap string) {
	per, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
	pg, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if per <= 0 || pg <= 0 {
		http.Error(w, "paging", 400)
		return
	}
	lo := min((pg-1)*per, len(items))
	hi := min(lo+per, len(items))
	if wrap != "" {
		_ = json.NewEncoder(w).Encode(map[string]any{wrap: items[lo:hi]})
		return
	}
	_ = json.NewEncoder(w).Encode(items[lo:hi])
}

func (f *fakeGitHub) repoJSON(x fRepo) map[string]any {
	return map[string]any{"name": x.name, "full_name": Org + "/" + x.name, "private": x.private,
		"archived": x.archived, "fork": x.fork}
}

func (f *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, r.Method+" "+r.URL.Path)
	p := r.URL.Path
	switch {
	case p == "/orgs/swarm-routing/repos":
		if r.URL.Query().Get("type") != "public" {
			http.Error(w, "type", 400)
			return
		}
		var out []map[string]any
		for _, x := range f.repos {
			if !x.private {
				out = append(out, f.repoJSON(x))
			}
		}
		page(w, r, out, "")
	case p == "/repos/"+Site+"/issues":
		var out []map[string]any
		for _, i := range f.issues {
			m := map[string]any{"number": i.number, "title": i.title, "created_at": i.created.Format(time.RFC3339)}
			if i.pr {
				m["pull_request"] = map[string]any{"url": "x"}
			}
			out = append(out, m)
		}
		page(w, r, out, "")
	case p == "/repos/"+Site+"/actions/workflows/"+Workflow+"/runs":
		if !strings.HasPrefix(r.URL.Query().Get("created"), ">=") {
			http.Error(w, "created", 400)
			return
		}
		page(w, r, f.runs, "workflow_runs")
	case p == "/repos/"+Site+"/actions/workflows/"+Workflow+"/dispatches" && r.Method == "POST":
		if f.refuse {
			http.Error(w, `{"message": "Resource not accessible by integration"}`, http.StatusForbidden)
			return
		}
		b, _ := io.ReadAll(r.Body)
		var body struct {
			Ref    string            `json:"ref"`
			Inputs map[string]string `json:"inputs"`
		}
		_ = json.Unmarshal(b, &body)
		f.dispatches = append(f.dispatches, fmt.Sprintf("%s %s %s", body.Ref, body.Inputs["repository"], body.Inputs["tag"]))
		name := strings.TrimPrefix(body.Inputs["repository"], Org+"/")
		f.runs = append([]run{{ID: int64(9000 + len(f.dispatches)), Title: RunTitle(name, body.Inputs["tag"]),
			Status: "queued", CreatedAt: f.at}}, f.runs...)
		w.WriteHeader(204)
	case strings.HasPrefix(p, "/repos/swarm-routing/"):
		parts := strings.Split(strings.TrimPrefix(p, "/repos/swarm-routing/"), "/")
		for _, x := range f.repos {
			if x.name != parts[0] {
				continue
			}
			if len(parts) == 1 {
				_ = json.NewEncoder(w).Encode(f.repoJSON(x))
				return
			}
			if len(parts) == 2 && parts[1] == "releases" {
				var out []map[string]any
				for _, rel := range x.releases {
					m := map[string]any{"tag_name": rel.tag, "draft": rel.draft, "prerelease": rel.prerelease}
					if !rel.published.IsZero() {
						m["published_at"] = rel.published.Format(time.RFC3339)
					}
					out = append(out, m)
				}
				_ = json.NewEncoder(w).Encode(out)
				return
			}
		}
		http.Error(w, "not found", 404)
	default:
		http.Error(w, "unexpected "+r.Method+" "+p, 500)
	}
}

// org: a release for each case of the rule.
func org() *fakeGitHub {
	return &fakeGitHub{
		repos: []fRepo{
			{name: "ARA", releases: []fRel{{tag: "v0.2.0", published: ago(5 * time.Hour)}, {tag: "v0.1.0", published: ago(9 * 24 * time.Hour)}}},                                                   // synced
			{name: "BeeAdHoc", releases: []fRel{{tag: "v0.1.0", published: ago(2 * time.Hour)}}},                                                                                                   // no issue, no run: dispatched
			{name: "HOPNET", releases: []fRel{{tag: "v0.1.0", published: ago(30 * time.Minute)}}},                                                                                                  // too young
			{name: "Termite", releases: []fRel{{tag: "v0.1.0", published: ago(20 * 24 * time.Hour)}}},                                                                                              // too old
			{name: "benchmarks", releases: []fRel{{tag: "v0.2.0", published: ago(26 * time.Hour)}}},                                                                                                // issue, run failed 20 h ago: dispatched
			{name: "ns3-tools", releases: []fRel{{tag: "v1.2.0", published: ago(3 * time.Hour)}}},                                                                                                  // issue, run in progress: waiting
			{name: "skills", releases: []fRel{{tag: "v0.3.0", published: ago(4 * time.Hour)}, {tag: "v0.4.0-rc1", published: ago(2 * time.Hour), prerelease: true}, {tag: "v0.5.0", draft: true}}}, // newest real one is synced
			{name: "AntHocNet"}, // no release
			{name: "secret-lib", private: true, releases: []fRel{{tag: "v1.0.0", published: ago(2 * time.Hour)}}}, // private: never
			{name: "old", archived: true, releases: []fRel{{tag: "v1.0.0", published: ago(2 * time.Hour)}}},       // archived: never
		},
		issues: []fIssue{
			{number: 300, title: "[release-sync] ns3-tools v1.2.0", created: ago(2 * time.Hour)},
			{number: 299, title: "[release-sync] skills v0.3.0", created: ago(3 * time.Hour)},
			{number: 298, title: "[release-sync] ARA v0.2.0", created: ago(4 * time.Hour)},
			{number: 297, title: "[release-sync] BeeAdHoc v0.1.0", created: ago(time.Hour), pr: true}, // a PR is not the ticket
			{number: 296, title: "[release-sync] benchmarks v0.2.0", created: ago(25 * time.Hour)},
		},
		runs: []run{
			{ID: 7, Title: RunTitle("ns3-tools", "v1.2.0"), Status: "in_progress", CreatedAt: ago(10 * time.Minute)},
			{ID: 6, Title: RunTitle("skills", "v0.3.0"), Status: "completed", Conclusion: "success", CreatedAt: ago(3 * time.Hour)},
			{ID: 5, Title: RunTitle("ARA", "v0.2.0"), Status: "completed", Conclusion: "success", CreatedAt: ago(4 * time.Hour)},
			{ID: 4, Title: RunTitle("benchmarks", "v0.2.0"), Status: "completed", Conclusion: "failure", CreatedAt: ago(20 * time.Hour)},
			{ID: 3, Title: "Release sync (weekly)", Status: "completed", Conclusion: "success", CreatedAt: ago(30 * time.Hour)},
		},
	}
}

func watch(t *testing.T, f *fakeGitHub, at time.Time, dry bool, names ...string) (string, error) {
	t.Helper()
	f.at = at
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	err := Run(GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}, names, at, dry, &out)
	return out.String(), err
}

func TestWatch(t *testing.T) {
	f := org()
	out, err := watch(t, f, now, false)
	if err != nil {
		t.Fatalf("%v\n%s", err, out)
	}
	// one slot is taken by ns3-tools' running sync: one dispatch, the oldest release first
	want := "main swarm-routing/benchmarks v0.2.0"
	if strings.Join(f.dispatches, "\n") != want {
		t.Fatalf("dispatches %v\n%s", f.dispatches, out)
	}
	for _, line := range []string{
		"HOPNET v0.1.0: published 30m0s ago, under 1h0m0s: not yet",
		"benchmarks v0.2.0 (published 2026-11-16T12:23:00Z): issue #296 but no green run; dispatched release-sync.yml with repository=swarm-routing/benchmarks tag=v0.2.0",
		"ARA v0.2.0 (published 2026-11-17T09:23:00Z): synced: issue #298, run 5 green",
		"skills v0.3.0 (published 2026-11-17T10:23:00Z): synced: issue #299, run 6 green",
		"ns3-tools v1.2.0 (published 2026-11-17T11:23:00Z): issue #300 but no green run; run 7 (in_progress) started 10m0s ago, waiting",
		"BeeAdHoc v0.1.0 (published 2026-11-17T12:23:00Z): no issue and no green run; deferred: 2 release-sync runs active (at most 2)",
		"release-sync-watch: 5 recent releases, 3 not synced, 1 dispatched",
	} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
	for _, x := range []string{"Termite", "secret-lib", "private repository", "old", "AntHocNet v"} {
		if strings.Contains(out, x) {
			t.Errorf("%s must not be listed:\n%s", x, out)
		}
	}
	// the next hour: both syncs finished green (HOPNET leaves the picture)
	f.repos = append(f.repos[:2], f.repos[3:]...)
	f.runs[0].Status, f.runs[0].Conclusion = "completed", "success"
	f.runs[1].Status, f.runs[1].Conclusion = "completed", "success"
	out, err = watch(t, f, now.Add(time.Hour), false)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(f.dispatches, "\n") != want+"\nmain swarm-routing/BeeAdHoc v0.1.0" {
		t.Fatalf("the deferred release is dispatched within two hours: %v\n%s", f.dispatches, out)
	}
	// that run fails: nothing for Backoff, then once more
	f.runs[0].Status, f.runs[0].Conclusion = "completed", "failure"
	n := len(f.dispatches)
	for _, at := range []time.Duration{2 * time.Hour, 3 * time.Hour} {
		out, _ = watch(t, f, now.Add(at), false)
		if len(f.dispatches) != n || !strings.Contains(out, "BeeAdHoc v0.1.0 (published 2026-11-17T12:23:00Z): no issue and no green run; run 9002 (failure) started") {
			t.Fatalf("a release waits %s after its last run:\n%s", Backoff, out)
		}
	}
	out, _ = watch(t, f, now.Add(4*time.Hour+time.Minute), false)
	if len(f.dispatches) != n+1 {
		t.Fatalf("after the backoff the release is dispatched again:\n%s", out)
	}
	// green with its ticket: synced, nothing more, ever
	f.runs[0].Status, f.runs[0].Conclusion = "completed", "success"
	f.issues = append([]fIssue{{number: 301, title: "[release-sync] BeeAdHoc v0.1.0", created: now.Add(4 * time.Hour)}}, f.issues...)
	out, _ = watch(t, f, now.Add(9*time.Hour), false)
	if len(f.dispatches) != n+1 || !strings.Contains(out, "0 not synced, 0 dispatched") {
		t.Fatalf("a synced org dispatches nothing:\n%s", out)
	}
}

// A green run whose ticket is missing is dispatched again (the site opens the ticket).
func TestGreenWithoutIssue(t *testing.T) {
	f := org()
	f.issues = f.issues[1:] // ns3-tools' ticket gone
	f.runs[0] = run{ID: 7, Title: RunTitle("ns3-tools", "v1.2.0"), Status: "completed", Conclusion: "success", CreatedAt: ago(4 * time.Hour)}
	out, err := watch(t, f, now, true, "ns3-tools")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "ns3-tools v1.2.0 (published 2026-11-17T11:23:00Z): no issue (run 7 was green); dry run: would dispatch release-sync.yml with repository=swarm-routing/ns3-tools tag=v1.2.0\n") {
		t.Fatal(out)
	}
	for _, c := range f.calls {
		if !strings.HasPrefix(c, "GET ") || strings.HasPrefix(c, "GET /orgs/") {
			t.Errorf("a dry run with --repos only GETs the named repository: %s", c)
		}
	}
}

func TestRefused(t *testing.T) {
	f := org()
	f.refuse = true
	out, err := watch(t, f, now, false)
	if err == nil || !strings.Contains(out, "dispatch refused (the token needs Actions: write on swarm-routing/swarm-routing.github.io)") {
		t.Fatalf("a refused dispatch fails the run: %v\n%s", err, out)
	}
}

func TestNothingRecent(t *testing.T) {
	f := &fakeGitHub{repos: []fRepo{{name: "ARA", releases: []fRel{{tag: "v0.1.0", published: ago(40 * 24 * time.Hour)}}}}}
	out, err := watch(t, f, now, false)
	if err != nil || out != "release-sync-watch: no release between 1h0m0s and 336h0m0s old\n" {
		t.Fatalf("%v\n%q", err, out)
	}
	for _, c := range f.calls {
		if strings.Contains(c, Site) {
			t.Errorf("nothing recent: the site is not read: %s", c)
		}
	}
}

func TestCommand(t *testing.T) {
	f := org()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out, errb bytes.Buffer
	env := func(string) string { return "" }
	if rc := Main([]string{"--now", now.Format(time.RFC3339)}, env, srv.Client(), srv.URL, &out, &errb); rc != 0 {
		t.Fatalf("rc %d: %s %s", rc, out.String(), errb.String())
	}
	if !strings.HasPrefix(out.String(), "release-sync-watch: no GH_TOKEN: dry run\n") || len(f.dispatches) != 0 ||
		!strings.Contains(out.String(), "dry run: would dispatch") {
		t.Errorf("no token is a dry run:\n%s", out.String())
	}
	if rc := Main([]string{"--bogus"}, env, srv.Client(), srv.URL, &out, &errb); rc != 2 {
		t.Errorf("usage: rc %d", rc)
	}
	if rc := Main([]string{"--repos", "a/b"}, env, srv.Client(), srv.URL, &out, &errb); rc != 1 {
		t.Errorf("a bad repository name: rc %d", rc)
	}
}

// A private repository is never named in the output, which a public log holds
// (swarm-routing/.github#622): the listing leaves it out, and named with
// --repos it is printed masked.
func TestPrivateNeverNamed(t *testing.T) {
	out, err := watch(t, org(), now, true, "secret-lib", "BeeAdHoc")
	if err != nil {
		t.Fatalf("%v\n%s", err, out)
	}
	if strings.Contains(out, "secret-lib") || !strings.Contains(out, "private repository 1: private, skipped\n") ||
		!strings.Contains(out, "BeeAdHoc v0.1.0") {
		t.Errorf("output:\n%s", out)
	}
}
