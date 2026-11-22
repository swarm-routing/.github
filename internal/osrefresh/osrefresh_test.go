// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package osrefresh

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const repo = "swarm-routing/sim-containers"
const bot = "swarm-routing-bot[bot]"

var now = time.Date(2026, 11, 22, 4, 47, 0, 0, time.UTC)

type fIssue struct {
	Number   int
	Title    string
	Body     string
	State    string
	Labels   []string
	Comments []string
}

// fakeGitHub serves the image workflow's runs and the repository's issues, and
// records every write.
type fakeGitHub struct {
	mu       sync.Mutex
	runs     []map[string]any
	issues   []*fIssue
	refuse   bool
	writes   []string
	dispatch map[string]any
	noUser   bool
}

func (f *fakeGitHub) run(id int64, event, status, conclusion, actor string, created time.Time) {
	f.runs = append(f.runs, map[string]any{"id": id, "event": event, "status": status, "conclusion": conclusion,
		"created_at": created.Format(time.RFC3339), "html_url": "https://github.com/" + repo + "/actions/runs/" + strconv.FormatInt(id, 10),
		"triggering_actor": map[string]string{"login": actor}})
}

func page[T any](w http.ResponseWriter, r *http.Request, items []T, wrap string) {
	per, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
	pg, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if per <= 0 || pg <= 0 {
		http.Error(w, "paging", http.StatusBadRequest)
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

func (f *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := r.URL.Path
	base := "/repos/" + repo
	var body map[string]any
	if r.Body != nil {
		_ = json.NewDecoder(r.Body).Decode(&body)
	}
	if r.Method != "GET" {
		f.writes = append(f.writes, r.Method+" "+p)
	}
	switch {
	case r.Method == "GET" && p == "/user":
		if f.noUser {
			http.Error(w, `{"message":"Resource not accessible by integration"}`, http.StatusForbidden)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"login": bot})
	case r.Method == "GET" && p == base+"/actions/workflows/"+Workflow+"/runs":
		if r.URL.Query().Get("branch") != Branch || !strings.HasPrefix(r.URL.Query().Get("created"), ">=") {
			http.Error(w, "filters", http.StatusBadRequest)
			return
		}
		page(w, r, f.runs, "workflow_runs")
	case r.Method == "POST" && p == base+"/actions/workflows/"+Workflow+"/dispatches":
		if f.refuse {
			http.Error(w, `{"message":"Resource not accessible by integration"}`, http.StatusForbidden)
			return
		}
		f.dispatch = body
		w.WriteHeader(http.StatusNoContent)
	case r.Method == "GET" && p == base+"/issues":
		var out []map[string]any
		for _, is := range f.issues {
			if is.State == r.URL.Query().Get("state") && strings.Contains(strings.Join(is.Labels, ","), r.URL.Query().Get("labels")) {
				out = append(out, map[string]any{"number": is.Number, "title": is.Title, "body": is.Body})
			}
		}
		page(w, r, out, "")
	case r.Method == "POST" && p == base+"/issues":
		is := &fIssue{Number: 100 + len(f.issues), Title: body["title"].(string), Body: body["body"].(string), State: "open"}
		for _, l := range body["labels"].([]any) {
			is.Labels = append(is.Labels, l.(string))
		}
		f.issues = append(f.issues, is)
		_ = json.NewEncoder(w).Encode(map[string]any{"number": is.Number})
	case strings.HasPrefix(p, base+"/issues/"):
		rest := strings.TrimPrefix(p, base+"/issues/")
		num, _ := strconv.Atoi(strings.TrimSuffix(rest, "/comments"))
		var is *fIssue
		for _, x := range f.issues {
			if x.Number == num {
				is = x
			}
		}
		if is == nil {
			http.Error(w, "no issue", http.StatusNotFound)
			return
		}
		switch {
		case r.Method == "GET" && strings.HasSuffix(rest, "/comments"):
			var out []map[string]string
			for _, c := range is.Comments {
				out = append(out, map[string]string{"body": c})
			}
			page(w, r, out, "")
		case r.Method == "POST" && strings.HasSuffix(rest, "/comments"):
			is.Comments = append(is.Comments, body["body"].(string))
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write([]byte("{}"))
		case r.Method == "PATCH":
			is.State = body["state"].(string)
			_, _ = w.Write([]byte("{}"))
		default:
			http.Error(w, "unexpected", http.StatusBadRequest)
		}
	default:
		http.Error(w, "unexpected "+r.Method+" "+p, http.StatusBadRequest)
	}
}

func load(t *testing.T, name string) Image {
	t.Helper()
	fh, err := os.Open("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	defer fh.Close()
	img, err := Parse(fh, name)
	if err != nil {
		t.Fatal(err)
	}
	return img
}

func scan(t *testing.T, f *fakeGitHub, dry bool, actor string, images ...Image) (string, error) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	err := Scan(GitHub{API: srv.URL, Token: "t", Client: srv.Client()}, images,
		Options{Repo: repo, Actor: actor, Dry: dry, Now: now}, &out)
	return out.String(), err
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimSpace(s), "\n")
	return lines[len(lines)-1]
}

func TestParseNoFixable(t *testing.T) {
	img := load(t, "no-fixable.json")
	if img.Name != "ghcr.io/swarm-routing/ns3-dev:latest-debug" || img.Fixable() != 0 || len(img.CVEs) != 0 || img.Other != 1 {
		t.Fatalf("got %+v", img)
	}
}

func TestParseFixable(t *testing.T) {
	img := load(t, "fixable.json")
	if img.OS["MEDIUM"] != 3 || img.OS["HIGH"] != 1 || img.OS["CRITICAL"] != 0 || img.Other != 0 {
		t.Fatalf("counts %+v", img.OS)
	}
	want := map[string]string{"CVE-2026-1001": "MEDIUM", "CVE-2026-1002": "MEDIUM", "CVE-2026-1003": "HIGH"}
	if len(img.CVEs) != len(want) {
		t.Fatalf("CVEs %v", img.CVEs)
	}
	for id, sev := range want {
		if img.CVEs[id] != sev {
			t.Fatalf("%s: %q, want %q", id, img.CVEs[id], sev)
		}
	}
}

func TestParseRejects(t *testing.T) {
	if _, err := Parse(strings.NewReader("not json"), "x"); err == nil {
		t.Fatal("accepted a non-JSON report")
	}
	img, err := Parse(strings.NewReader(`{"Results":null}`), "fallback.json")
	if err != nil || img.Name != "fallback.json" {
		t.Fatalf("%v %+v", err, img)
	}
}

func TestDistinctTakesHighestSeverity(t *testing.T) {
	a := Image{CVEs: map[string]string{"CVE-1": "MEDIUM"}}
	b := Image{CVEs: map[string]string{"CVE-1": "HIGH", "CVE-2": "MEDIUM"}}
	d := Distinct([]Image{a, b})
	if len(d) != 2 || d["CVE-1"] != "HIGH" {
		t.Fatalf("%v", d)
	}
}

func TestNoFixableFindings(t *testing.T) {
	f := &fakeGitHub{}
	out, err := scan(t, f, false, bot, load(t, "no-fixable.json"))
	if err != nil {
		t.Fatal(err)
	}
	if f.dispatch != nil || len(f.writes) != 0 {
		t.Fatalf("wrote %v", f.writes)
	}
	want := "os-refresh: 1 images, 0 fixable OS CVEs (CRITICAL 0, HIGH 0, MEDIUM 0); nothing to refresh: no fixable OS vulnerability of MEDIUM or higher"
	if got := lastLine(out); got != want {
		t.Fatalf("got %q", got)
	}
	if !strings.Contains(out, "1 fixable findings are outside OS packages") || !strings.Contains(out, "| `ghcr.io/swarm-routing/ns3-dev:latest-debug` | 0 | 0 | 0 | 1 |") {
		t.Fatalf("summary:\n%s", out)
	}
}

func TestFixableFindingsDispatch(t *testing.T) {
	f := &fakeGitHub{}
	f.run(1, "push", "completed", "success", "someone", now.Add(-30*time.Hour))
	out, err := scan(t, f, false, bot, load(t, "no-fixable.json"), load(t, "fixable.json"))
	if err != nil {
		t.Fatal(err)
	}
	if f.dispatch == nil || f.dispatch["ref"] != "main" || f.dispatch["inputs"].(map[string]any)["refresh"] != "true" {
		t.Fatalf("dispatch %v", f.dispatch)
	}
	want := "os-refresh: 2 images, 3 fixable OS CVEs (CRITICAL 0, HIGH 1, MEDIUM 2); dispatched publish-images.yml with refresh=true on main"
	if got := lastLine(out); got != want {
		t.Fatalf("got %q", got)
	}
	for _, s := range []string{"- HIGH CVE-2026-1003\n- MEDIUM CVE-2026-1001\n- MEDIUM CVE-2026-1002\n", "No automated refresh in the last 7 days."} {
		if !strings.Contains(out, s) {
			t.Fatalf("no %q in:\n%s", s, out)
		}
	}
}

func TestDryRunPrintsWhatItWouldDo(t *testing.T) {
	f := &fakeGitHub{}
	out, err := scan(t, f, true, bot, load(t, "fixable.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(f.writes) != 0 {
		t.Fatalf("a dry run wrote %v", f.writes)
	}
	if got := lastLine(out); !strings.HasSuffix(got, "; dry run: would dispatch publish-images.yml with refresh=true on main") {
		t.Fatalf("got %q", got)
	}
	again, _ := scan(t, &fakeGitHub{}, true, bot, load(t, "fixable.json"))
	if again != out {
		t.Fatal("two runs on the same input differ")
	}
}

func TestWaitsForAnActiveRun(t *testing.T) {
	f := &fakeGitHub{}
	f.run(7, "push", "in_progress", "", "someone", now.Add(-time.Hour))
	out, err := scan(t, f, false, bot, load(t, "fixable.json"))
	if err != nil || f.dispatch != nil {
		t.Fatalf("%v, dispatch %v", err, f.dispatch)
	}
	if got := lastLine(out); !strings.Contains(got, "waiting: publish-images.yml run 7 on main is in_progress") {
		t.Fatalf("got %q", got)
	}
}

func TestAtMostOneRefreshADay(t *testing.T) {
	f := &fakeGitHub{}
	f.run(8, "workflow_dispatch", "completed", "success", "maintainer", now.Add(-2*time.Hour)) // 02:47 today
	out, err := scan(t, f, false, bot, load(t, "fixable.json"))
	if err != nil || f.dispatch != nil {
		t.Fatalf("%v, dispatch %v", err, f.dispatch)
	}
	if got := lastLine(out); !strings.Contains(got, "waiting: a dispatch of publish-images.yml already ran today, run 8") {
		t.Fatalf("got %q", got)
	}
	// yesterday's dispatch does not hold today's
	g := &fakeGitHub{}
	g.run(9, "workflow_dispatch", "completed", "success", "maintainer", now.Add(-5*time.Hour))
	if _, err := scan(t, g, false, bot, load(t, "fixable.json")); err != nil || g.dispatch == nil {
		t.Fatalf("%v: yesterday's dispatch held today's", err)
	}
}

func TestFailedRefreshOpensThenUpdatesOneIssue(t *testing.T) {
	f := &fakeGitHub{}
	f.run(20, "workflow_dispatch", "completed", "failure", bot, now.Add(-26*time.Hour))
	out, err := scan(t, f, false, bot, load(t, "fixable.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(f.issues) != 1 || f.issues[0].Title != IssueTitle || !strings.Contains(f.issues[0].Body, "/actions/runs/20") ||
		strings.Join(f.issues[0].Labels, ",") != "bug,packaging,priority:P2" {
		t.Fatalf("issues %+v", f.issues)
	}
	if !strings.Contains(out, "Opened issue #100.") || f.dispatch == nil {
		t.Fatalf("out:\n%s", out)
	}
	// the same failure again: nothing new on the issue
	f.dispatch = nil
	f.runs = f.runs[:1]
	out, err = scan(t, f, false, bot, load(t, "fixable.json"))
	if err != nil || len(f.issues) != 1 || len(f.issues[0].Comments) != 0 || !strings.Contains(out, "already names this run") {
		t.Fatalf("%v %+v\n%s", err, f.issues[0], out)
	}
	// a newer failure: one comment with its link
	f.run(21, "workflow_dispatch", "completed", "timed_out", bot, now.Add(-3*time.Hour))
	out, err = scan(t, f, false, bot, load(t, "fixable.json"))
	if err != nil || len(f.issues) != 1 || len(f.issues[0].Comments) != 1 || !strings.Contains(f.issues[0].Comments[0], "/actions/runs/21") {
		t.Fatalf("%v %+v\n%s", err, f.issues[0], out)
	}
}

func TestSuccessfulRefreshClosesTheIssue(t *testing.T) {
	f := &fakeGitHub{issues: []*fIssue{{Number: 5, Title: IssueTitle, State: "open", Labels: []string{"bug"}}}}
	f.run(30, "workflow_dispatch", "completed", "success", bot, now.Add(-20*time.Hour))
	f.run(29, "workflow_dispatch", "completed", "failure", "maintainer", now.Add(-10*time.Hour)) // not the bot's
	out, err := scan(t, f, false, bot, load(t, "no-fixable.json"))
	if err != nil {
		t.Fatal(err)
	}
	if f.issues[0].State != "closed" || len(f.issues[0].Comments) != 1 || !strings.Contains(out, "Closed issue #5.") {
		t.Fatalf("%+v\n%s", f.issues[0], out)
	}
}

func TestActorFromTheToken(t *testing.T) {
	f := &fakeGitHub{}
	f.run(40, "workflow_dispatch", "completed", "failure", bot, now.Add(-20*time.Hour))
	if _, err := scan(t, f, true, "", load(t, "no-fixable.json")); err != nil {
		t.Fatal(err)
	}
	g := &fakeGitHub{noUser: true}
	out, err := scan(t, g, true, "", load(t, "no-fixable.json"))
	if err != nil || !strings.Contains(out, "The bot's login is unknown") {
		t.Fatalf("%v\n%s", err, out)
	}
}

func TestDispatchRefused(t *testing.T) {
	f := &fakeGitHub{refuse: true}
	out, err := scan(t, f, false, bot, load(t, "fixable.json"))
	if err == nil || !strings.HasSuffix(lastLine(out), "dispatch refused (the token needs Actions: write)") {
		t.Fatalf("%v\n%s", err, out)
	}
}

func TestMainCommand(t *testing.T) {
	f := &fakeGitHub{}
	srv := httptest.NewServer(f)
	defer srv.Close()
	run := func(env map[string]string, args ...string) (int, string, string) {
		var o, e bytes.Buffer
		code := Main(args, func(k string) string { return env[k] }, srv.Client(), srv.URL, &o, &e)
		return code, o.String(), e.String()
	}
	if c, _, _ := run(nil); c != 2 {
		t.Fatalf("no arguments: %d", c)
	}
	if c, _, _ := run(nil, "--repo", "bad", "testdata/fixable.json"); c != 2 {
		t.Fatalf("bad repo: %d", c)
	}
	if c, _, _ := run(nil, "--repo", repo, "--bogus", "testdata/fixable.json"); c != 2 {
		t.Fatalf("unknown flag: %d", c)
	}
	if c, _, e := run(nil, "--repo", repo, "testdata/missing.json"); c != 1 || !strings.Contains(e, "missing.json") {
		t.Fatalf("missing report: %d %s", c, e)
	}
	c, o, e := run(nil, "--repo", repo, "--now", now.Format(time.RFC3339), "testdata/fixable.json")
	if c != 0 || !strings.Contains(e, "no GH_TOKEN: dry run") || !strings.Contains(o, "dry run: would dispatch") || len(f.writes) != 0 {
		t.Fatalf("%d %q %q %v", c, o, e, f.writes)
	}
	c, o, _ = run(map[string]string{"GH_TOKEN": "t"}, "--repo", repo, "--actor", bot, "--now", now.Format(time.RFC3339), "testdata/fixable.json")
	if c != 0 || f.dispatch == nil || !strings.Contains(o, "dispatched") {
		t.Fatalf("%d %q", c, o)
	}
	if c, o, _ := run(nil, "--help"); c != 0 || !strings.HasPrefix(o, "usage:") {
		t.Fatal("help")
	}
}
