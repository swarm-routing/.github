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

var now = time.Date(2026, 11, 16, 21, 7, 0, 0, time.UTC)

// fakeGitHub keeps, per workflow, the newest run's start, and records dispatches.
type fakeGitHub struct {
	mu         sync.Mutex
	last       map[string]time.Time // "repo workflow" -> newest run on main
	dispatches []string
	failOn     string
	auth       []string
	methods    []string
}

func (f *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.auth = append(f.auth, r.Header.Get("Authorization"))
	f.methods = append(f.methods, r.Method+" "+r.URL.Path)
	p := strings.TrimPrefix(r.URL.Path, "/repos/")
	parts := strings.Split(p, "/")
	repo := parts[0] + "/" + parts[1]
	switch {
	case len(parts) == 2:
		fmt.Fprint(w, `{"default_branch": "main"}`)
	case len(parts) == 6 && parts[5] == "runs":
		if r.URL.Query().Get("branch") != "main" {
			http.Error(w, "branch", 400)
			return
		}
		t, ok := f.last[repo+" "+parts[4]]
		if !ok {
			fmt.Fprint(w, `{"total_count": 0, "workflow_runs": []}`)
			return
		}
		fmt.Fprintf(w, `{"workflow_runs": [{"created_at": %q, "event": "workflow_dispatch"}]}`, t.Format(time.RFC3339))
	case len(parts) == 6 && parts[5] == "dispatches" && r.Method == "POST":
		if parts[4] == f.failOn {
			http.Error(w, `{"message": "Resource not accessible by integration"}`, http.StatusForbidden)
			return
		}
		b, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(b, &body)
		f.dispatches = append(f.dispatches, fmt.Sprintf("%s %s %v %v", repo, parts[4], body["ref"], body["inputs"]))
		f.last[repo+" "+parts[4]] = now
		w.WriteHeader(204)
	default:
		http.Error(w, "unexpected "+r.Method+" "+r.URL.Path, 500)
	}
}

const table = `
[[entry]]
repo = "swarm-routing/ns3-upstream-report"
workflow = "send.yml"
period = "1h"
inputs = { mode = "scheduled" }

[[entry]]
repo = "swarm-routing/ns3-upstream-report"
workflow = "read.yml"
period = "6h"
inputs = { mode = "scheduled" }

[[entry]]
repo = "swarm-routing/ns3-upstream-report"
workflow = "maintain.yml"
period = "24h"
inputs = { mode = "scheduled" }

[[entry]]
repo = "swarm-routing/ns3-upstream-report"
workflow = "rotate.yml"
period = "168h"
inputs = { mode = "scheduled" }
`

func run(t *testing.T, f *fakeGitHub, at time.Time, dry bool) string {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	entries, err := Load([]byte(table))
	if err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	_ = Run(GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}, entries, at, dry, &out)
	return out.String()
}

func TestBackstop(t *testing.T) {
	r := "swarm-routing/ns3-upstream-report "
	f := &fakeGitHub{last: map[string]time.Time{
		r + "send.yml":     now.Add(-3 * time.Hour),                 // missed slots: due
		r + "read.yml":     now.Add(-2 * time.Hour),                 // within 6 h: not due
		r + "maintain.yml": now.Add(-23*time.Hour - 55*time.Minute), // within the slack of 24 h: due
	}} // rotate.yml: never ran: due
	out := run(t, f, now, false)
	want := []string{
		r + "send.yml main map[mode:scheduled]",
		r + "maintain.yml main map[mode:scheduled]",
		r + "rotate.yml main map[mode:scheduled]",
	}
	if strings.Join(f.dispatches, "\n") != strings.Join(want, "\n") {
		t.Fatalf("dispatches:\n%s\nout:\n%s", strings.Join(f.dispatches, "\n"), out)
	}
	for _, line := range []string{
		r + "send.yml: last run 2026-11-16T18:07:00Z (workflow_dispatch, 3h0m0s ago): dispatched on main with mode=scheduled",
		r + "read.yml: last run 2026-11-16T19:07:00Z (workflow_dispatch, 2h0m0s ago), within 6h: nothing to do",
		r + "rotate.yml: no run yet: dispatched on main with mode=scheduled",
	} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("missing %q in\n%s", line, out)
		}
	}
	// idempotent: the same hour again dispatches nothing
	n := len(f.dispatches)
	out = run(t, f, now.Add(5*time.Minute), false)
	if len(f.dispatches) != n || strings.Count(out, "nothing to do") != 4 {
		t.Errorf("a second run in the period dispatches nothing:\n%s", out)
	}
	// the next hourly slot (a little early) dispatches the hourly one only
	_ = run(t, f, now.Add(52*time.Minute), false)
	if len(f.dispatches) != n+1 || !strings.HasPrefix(f.dispatches[n], r+"send.yml") {
		t.Errorf("an hourly workflow keeps an hourly cadence: %v", f.dispatches[n:])
	}
	for _, a := range f.auth {
		if a != "Bearer tok" {
			t.Errorf("token header: %q", a)
		}
	}
}

func TestDryRunAndFailure(t *testing.T) {
	f := &fakeGitHub{last: map[string]time.Time{}, failOn: "read.yml"}
	out := run(t, f, now, true)
	if len(f.dispatches) != 0 || strings.Count(out, "dry run: would dispatch on main with mode=scheduled") != 4 {
		t.Errorf("a dry run dispatches nothing:\n%s", out)
	}
	for _, m := range f.methods {
		if !strings.HasPrefix(m, "GET ") {
			t.Errorf("a dry run only reads: %s", m)
		}
	}
	srv := httptest.NewServer(f)
	defer srv.Close()
	entries, _ := Load([]byte(table))
	var b bytes.Buffer
	err := Run(GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}, entries, now, false, &b)
	if err == nil || err.Error() != "1 of 4 entries failed" || len(f.dispatches) != 3 ||
		!strings.Contains(b.String(), "read.yml: no run yet: dispatch failed:") || !strings.Contains(b.String(), "HTTP 403") {
		t.Errorf("a failed dispatch is reported, the others still run: %v\n%s", err, b.String())
	}
}

func TestLoad(t *testing.T) {
	for _, c := range []struct{ name, text, want string }{
		{"empty", ``, "1 to 64"},
		{"repo", "[[entry]]\nrepo = \"other/x\"\nworkflow = \"a.yml\"\nperiod = \"1h\"\n", "not swarm-routing/<name>"},
		{"workflow", "[[entry]]\nrepo = \"swarm-routing/x\"\nworkflow = \"../a\"\nperiod = \"1h\"\n", "not a workflow file name"},
		{"period", "[[entry]]\nrepo = \"swarm-routing/x\"\nworkflow = \"a.yml\"\nperiod = \"5m\"\n", "from 1h to 744h"},
		{"input", "[[entry]]\nrepo = \"swarm-routing/x\"\nworkflow = \"a.yml\"\nperiod = \"1h\"\ninputs = { \"a b\" = \"x\" }\n", "plain name"},
		{"unknown", "[[entry]]\nrepo = \"swarm-routing/x\"\nworkflow = \"a.yml\"\nperiod = \"1h\"\ncron = \"x\"\n", "unknown key"},
		{"twice", strings.Repeat("[[entry]]\nrepo = \"swarm-routing/x\"\nworkflow = \"a.yml\"\nperiod = \"1h\"\n", 2), "listed twice"},
	} {
		if _, err := Load([]byte(c.text)); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v", c.name, err)
		}
	}
}

// The repository's own table loads.
func TestRepositoryTable(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", ".github", "backstop.toml"))
	if err != nil {
		t.Fatal(err)
	}
	entries, err := Load(data)
	if err != nil || len(entries) != 4 {
		t.Fatalf("%v %d", err, len(entries))
	}
}

func TestMain_(t *testing.T) {
	f := &fakeGitHub{last: map[string]time.Time{}}
	srv := httptest.NewServer(f)
	defer srv.Close()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "t.toml"), []byte(table), 0o644); err != nil {
		t.Fatal(err)
	}
	wd, _ := os.Getwd()
	defer os.Chdir(wd)
	_ = os.Chdir(dir)
	var out, errb bytes.Buffer
	env := func(k string) string { return "" }
	if code := Main([]string{"--config", "t.toml", "--now", "2026-11-16T21:07:00Z"}, env, srv.Client(), srv.URL, &out, &errb); code != 0 ||
		!strings.HasPrefix(out.String(), "backstop: no GH_TOKEN: dry run\n") || len(f.dispatches) != 0 {
		t.Errorf("no token: a dry run: %d %q %q", code, out.String(), errb.String())
	}
	for _, args := range [][]string{{"--config", "../x.toml"}, {"--config", "/etc/x"}, {"--bogus"}, {"--now", "x", "--config", "t.toml"}} {
		if code := Main(args, env, srv.Client(), srv.URL, &out, &errb); code != 2 {
			t.Errorf("%v: exit %d", args, code)
		}
	}
	tok := func(k string) string { return map[string]string{"GH_TOKEN": "tok"}[k] }
	out.Reset()
	if code := Main([]string{"--config", "t.toml"}, tok, srv.Client(), srv.URL, &out, &errb); code != 0 || len(f.dispatches) != 4 {
		t.Errorf("with a token it dispatches: %d %q", code, out.String())
	}
}
