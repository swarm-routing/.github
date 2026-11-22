// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package backstop

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeRun is one run of org-bot.yml as the listing shows it.
type fakeRun struct {
	title, event, status, conclusion string
	created, ended                   time.Time
}

// titledGitHub serves one workflow's run listing (newest first, paged), the
// dispatches and the issues of swarm-routing/.github.
type titledGitHub struct {
	mu         sync.Mutex
	runs       []fakeRun // newest first
	dispatches []string
	issues     []map[string]any // open issues here
	writes     []string
	queries    []string
}

func (f *titledGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	p := strings.TrimPrefix(r.URL.Path, "/repos/")
	parts := strings.Split(p, "/")
	switch {
	case len(parts) == 2 && r.Method == "GET":
		fmt.Fprint(w, `{"default_branch": "main", "private": false}`)
	case len(parts) == 6 && parts[5] == "runs":
		q := r.URL.Query()
		f.queries = append(f.queries, q.Get("created"))
		since, err := time.Parse(time.RFC3339, strings.TrimPrefix(q.Get("created"), ">="))
		if q.Get("branch") != "main" || q.Get("per_page") != "100" || err != nil {
			http.Error(w, "query", 400)
			return
		}
		var page int
		fmt.Sscan(q.Get("page"), &page)
		var out []map[string]any
		for _, run := range f.runs {
			if run.created.Before(since) {
				continue
			}
			out = append(out, map[string]any{
				"created_at": run.created.Format(time.RFC3339), "run_started_at": run.created.Format(time.RFC3339),
				"updated_at": run.ended.Format(time.RFC3339), "event": run.event, "status": run.status,
				"conclusion": run.conclusion, "display_title": run.title,
			})
		}
		lo, hi := (page-1)*100, page*100
		if lo > len(out) {
			lo = len(out)
		}
		if hi > len(out) {
			hi = len(out)
		}
		b, _ := json.Marshal(map[string]any{"workflow_runs": out[lo:hi]})
		w.Write(b)
	case len(parts) == 6 && parts[5] == "dispatches" && r.Method == "POST":
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(b, &body)
		f.dispatches = append(f.dispatches, fmt.Sprintf("%s %v", parts[4], body["inputs"]))
		f.runs = append([]fakeRun{{title: "org-bot hourly (schedule)", event: "workflow_dispatch", status: "queued", created: now}}, f.runs...)
		w.WriteHeader(204)
	case p == "swarm-routing/.github/issues" && r.Method == "GET":
		if r.URL.Query().Get("labels") != "ci" || r.URL.Query().Get("state") != "open" {
			http.Error(w, "query", 400)
			return
		}
		b, _ := json.Marshal(f.issues)
		w.Write(b)
	case strings.HasPrefix(p, "swarm-routing/.github/issues") && (r.Method == "POST" || r.Method == "PATCH"):
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(b, &body)
		f.writes = append(f.writes, r.Method+" "+p)
		switch {
		case p == "swarm-routing/.github/issues":
			f.issues = append(f.issues, map[string]any{"number": 90, "title": body["title"], "body": body["body"]})
			fmt.Fprint(w, `{"number": 90}`)
		case r.Method == "PATCH" && body["state"] == "closed":
			f.issues = nil
			fmt.Fprint(w, `{}`)
		case r.Method == "PATCH":
			f.issues[0]["body"] = body["body"]
			fmt.Fprint(w, `{}`)
		default:
			fmt.Fprint(w, `{}`)
		}
	default:
		http.Error(w, "unexpected "+r.Method+" "+r.URL.Path, 500)
	}
}

const titledTable = `
[[entry]]
repo = "swarm-routing/.github"
workflow = "org-bot.yml"
title = "org-bot hourly (schedule)"
period = "1h"
alarm = "3h"
inputs = { task = "hourly", scheduled = "true" }
`

func titledRun(t *testing.T, f *titledGitHub, at time.Time, dry bool) ([]string, string) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	entries, err := Load([]byte(titledTable))
	if err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	stalled, err := Run(GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}, entries, at, dry, &out)
	if err != nil {
		t.Fatalf("%v\n%s", err, out.String())
	}
	return stalled, out.String()
}

// The starvation of swarm-routing/.github#748: the workflow runs every few
// minutes for other reasons, and the scheduled run that was queued was
// replaced (cancelled, no job). A titled row sees through both.
func TestTitledRowIgnoresOtherAndCancelledRuns(t *testing.T) {
	var runs []fakeRun
	for i := 1; i <= 150; i++ { // other runs: more than a page
		at := now.Add(-time.Duration(i) * 2 * time.Minute)
		runs = append(runs, fakeRun{title: "org-bot bestpractices (repository_dispatch)", event: "repository_dispatch",
			status: "completed", conclusion: "success", created: at, ended: at.Add(time.Minute)})
	}
	runs = append(runs,
		fakeRun{title: "org-bot hourly (schedule)", event: "schedule", status: "completed", conclusion: "cancelled",
			created: now.Add(-200 * time.Minute), ended: now.Add(-190 * time.Minute)},
		fakeRun{title: "org-bot hourly (schedule)", event: "schedule", status: "completed", conclusion: "success",
			created: now.Add(-230 * time.Minute), ended: now.Add(-220 * time.Minute)},
	)
	f := &titledGitHub{runs: runs}
	stalled, out := titledRun(t, f, now, false)
	name := `swarm-routing/.github org-bot.yml "org-bot hourly (schedule)"`
	for _, line := range []string{
		name + ": stalled: no run completed within 3h (the last ended 2026-11-16T17:27:00Z, 3h40m0s ago)\n",
		name + ": last run 2026-11-16T17:17:00Z (schedule, 3h50m0s ago): dispatched on main with scheduled=true task=hourly\n",
	} {
		if !strings.Contains(out, line) {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
	if len(stalled) != 1 || len(f.dispatches) != 1 || f.dispatches[0] != "org-bot.yml map[scheduled:true task:hourly]" {
		t.Errorf("stalled %v, dispatches %v", stalled, f.dispatches)
	}
	if f.queries[0] != ">=2026-11-16T17:07:00Z" {
		t.Errorf("the listing looks back the alarm and an hour: %v", f.queries)
	}
	// the dispatched run is queued: the next check waits for it, still stalled
	stalled, out = titledRun(t, f, now.Add(10*time.Minute), false)
	if len(f.dispatches) != 1 || len(stalled) != 1 || !strings.Contains(out, "(workflow_dispatch, 10m0s ago), within 1h: nothing to do") {
		t.Errorf("a queued catch-up is waited for: %v\n%s", f.dispatches, out)
	}
	// it completes: nothing stalled, nothing to do
	f.runs[0].status, f.runs[0].conclusion, f.runs[0].ended = "completed", "success", now.Add(20*time.Minute)
	if stalled, out = titledRun(t, f, now.Add(25*time.Minute), false); len(stalled) != 0 || strings.Contains(out, "stalled") {
		t.Errorf("a completed run clears the alarm:\n%s", out)
	}
}

func TestStalledIssue(t *testing.T) {
	f := &titledGitHub{}
	srv := httptest.NewServer(f)
	defer srv.Close()
	g := GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}
	lines := []string{`x org-bot.yml "a": stalled: no run completed within 3h (none within 3h)`}
	if got, err := KeepIssue(g, nil, now, false); err != nil || got != "issue: none open, nothing stalled" || len(f.writes) != 0 {
		t.Errorf("healthy, no issue: %q %v %v", got, err, f.writes)
	}
	if got, _ := KeepIssue(g, lines, now, true); got != "issue: dry run: would open it" || len(f.writes) != 0 {
		t.Errorf("dry run: %q %v", got, f.writes)
	}
	if got, err := KeepIssue(g, lines, now, false); err != nil || got != "issue: opened #90" {
		t.Errorf("open: %q %v", got, err)
	}
	if b := f.issues[0]["body"].(string); !strings.Contains(b, "- "+lines[0]+"\n") || !strings.Contains(b, "swarm-routing/.github#748") {
		t.Errorf("body:\n%s", b)
	}
	// a later check with the same rows changes nothing (the time is not news)
	if got, _ := KeepIssue(g, lines, now.Add(time.Hour), false); got != "issue: #90 unchanged" || len(f.writes) != 1 {
		t.Errorf("unchanged: %q %v", got, f.writes)
	}
	if got, _ := KeepIssue(g, append(lines, "y: stalled"), now, false); got != "issue: updated #90" {
		t.Errorf("update: %q", got)
	}
	if got, err := KeepIssue(g, nil, now, false); err != nil || got != "issue: closed #90" ||
		strings.Join(f.writes, ",") != "POST swarm-routing/.github/issues,PATCH swarm-routing/.github/issues/90,POST swarm-routing/.github/issues/90/comments,PATCH swarm-routing/.github/issues/90" {
		t.Errorf("close: %q %v %v", got, err, f.writes)
	}
}

// Main exits 1 while a row is stalled, after keeping the issue.
func TestMainStalled(t *testing.T) {
	f := &titledGitHub{}
	srv := httptest.NewServer(f)
	defer srv.Close()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "t.toml"), []byte(titledTable), 0o644); err != nil {
		t.Fatal(err)
	}
	wd, _ := os.Getwd()
	defer os.Chdir(wd)
	_ = os.Chdir(dir)
	tok := func(k string) string { return map[string]string{"GH_TOKEN": "tok"}[k] }
	var out, errb bytes.Buffer
	code := Main([]string{"--config", "t.toml", "--issue", "--now", now.Format(time.RFC3339)}, tok, srv.Client(), srv.URL, &out, &errb)
	if code != 1 || !strings.Contains(out.String(), "issue: opened #90\n") || errb.String() != "backstop: 1 row(s) stalled\n" || len(f.dispatches) != 1 {
		t.Errorf("stalled: %d %q %q", code, out.String(), errb.String())
	}
}
