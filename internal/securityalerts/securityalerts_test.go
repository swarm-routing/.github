// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package securityalerts

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/swarm-routing/.github/internal/repomask"
)

var now = time.Date(2026, 11, 17, 0, 0, 0, 0, time.UTC)

// fakeOrg serves repositories, their alerts and their issues.
type fakeOrg struct {
	mu     sync.Mutex
	repos  []map[string]any
	alerts map[string][]map[string]any // "repo kind-path" -> alerts
	status map[string]int              // "repo kind-path" -> HTTP status
	issues map[string][]map[string]any // repo -> issues (open)
	pulls  map[string][]map[string]any
	writes []string
	next   int
}

func (f *fakeOrg) server(t *testing.T) GitHub {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		send := func(v any) { _ = json.NewEncoder(w).Encode(v) }
		p := r.URL.Path
		if p == "/orgs/swarm-routing/repos" {
			send(f.repos)
			return
		}
		parts := strings.SplitN(strings.TrimPrefix(p, "/repos/swarm-routing/"), "/", 2)
		repo := parts[0]
		rest := ""
		if len(parts) > 1 {
			rest = parts[1]
		}
		var body map[string]any
		if r.Method != "GET" {
			_ = json.NewDecoder(r.Body).Decode(&body)
			b, _ := json.Marshal(body)
			f.writes = append(f.writes, fmt.Sprintf("%s %s %s", r.Method, strings.TrimPrefix(p, "/repos/swarm-routing/"), b))
		}
		switch {
		case rest == "" && r.Method == "GET":
			for _, x := range f.repos {
				if x["name"] == repo {
					send(x)
					return
				}
			}
			http.Error(w, "{}", 404)
		case strings.HasSuffix(rest, "/alerts"):
			k := repo + " " + rest
			if s := f.status[k]; s != 0 {
				http.Error(w, `{"message":"no"}`, s)
				return
			}
			send(append([]map[string]any{}, f.alerts[k]...))
		case rest == "issues" && r.Method == "GET":
			label := r.URL.Query().Get("labels")
			var out []map[string]any
			for _, i := range f.issues[repo] {
				for _, l := range i["labels"].([]any) {
					if l.(map[string]any)["name"] == label {
						out = append(out, i)
						break
					}
				}
			}
			send(out)
		case rest == "issues" && r.Method == "POST":
			f.next++
			n := 100 + f.next
			var ls []any
			for _, l := range body["labels"].([]any) {
				ls = append(ls, map[string]any{"name": l})
			}
			f.issues[repo] = append(f.issues[repo], map[string]any{"number": n, "title": body["title"], "body": body["body"], "labels": ls})
			send(map[string]any{"number": n})
		case strings.HasPrefix(rest, "issues/") && r.Method == "PATCH":
			send(map[string]any{})
		case strings.HasPrefix(rest, "issues/") && strings.HasSuffix(rest, "/comments"):
			send(map[string]any{})
		case rest == "pulls":
			send(f.pulls[repo])
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL)
			http.Error(w, "{}", 500)
		}
	}))
	t.Cleanup(srv.Close)
	return GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}
}

func cs(repo string, n int, tool, sev string, created string) map[string]any {
	return map[string]any{"number": n, "html_url": fmt.Sprintf("https://github.com/swarm-routing/%s/security/code-scanning/%d", repo, n),
		"created_at": created, "tool": map[string]any{"name": tool},
		"rule": map[string]any{"id": "py/sql-injection", "description": "SQL `query` built from @user input", "security_severity_level": sev}}
}

func labelsOf(names ...string) []any {
	var out []any
	for _, n := range names {
		out = append(out, map[string]any{"name": n})
	}
	return out
}

func TestSeverityPriorityAndSLA(t *testing.T) {
	day := 24 * time.Hour
	cases := []struct {
		a    Alert
		prio string
		past bool
	}{
		{Alert{Kind: CodeScanning, Severity: "critical", Created: now.Add(-10 * day)}, "P1", false},
		{Alert{Kind: CodeScanning, Severity: "critical", Created: now.Add(-15 * day)}, "P1", true},
		{Alert{Kind: CodeScanning, Severity: "high", Created: now.Add(-1 * day)}, "P1", false},
		{Alert{Kind: Dependabot, Severity: "medium", Created: now.Add(-30 * day)}, "P2", false},
		{Alert{Kind: Dependabot, Severity: "medium", Created: now.Add(-46 * day)}, "P1", true},
		{Alert{Kind: CodeScanning, Severity: "low", Created: now.Add(-400 * day)}, "P3", false},
		{Alert{Kind: SecretScanning, Created: now}, "P1", false},
	}
	for i, c := range cases {
		if p := c.a.Priority(now); p != c.prio || c.a.PastSLA(now) != c.past {
			t.Errorf("case %d: %s past=%v, want %s past=%v", i, p, c.a.PastSLA(now), c.prio, c.past)
		}
	}
	for in, want := range map[string]string{"moderate": "medium", "error": "high", "note": "low", "CRITICAL": "critical", "x": ""} {
		if normSeverity(in) != want {
			t.Errorf("normSeverity(%s)", in)
		}
	}
}

func TestSyncOpensUpdatesAdoptsCloses(t *testing.T) {
	base := "https://github.com/swarm-routing/X/security/"
	f := &fakeOrg{
		repos: []map[string]any{{"name": "X"}},
		alerts: map[string][]map[string]any{
			"X code-scanning/alerts": {
				cs("X", 1, "CodeQL", "high", "2026-11-10T00:00:00Z"),
				cs("X", 10, "Scorecard", "", "2026-11-01T00:00:00Z"),
				cs("X", 3, "CodeQL", "medium", "2026-09-01T00:00:00Z"), // past its SLA
			},
			"X dependabot/alerts": {{"number": 2, "html_url": base + "dependabot/2", "created_at": "2026-11-15T00:00:00Z",
				"security_advisory": map[string]any{"severity": "low", "ghsa_id": "GHSA-x", "summary": "a bug"},
				"dependency":        map[string]any{"package": map[string]any{"name": "lib"}}}},
		},
		status: map[string]int{"X secret-scanning/alerts": 404},
		issues: map[string][]map[string]any{"X": {
			// alert 1's ticket, current except its priority label
			{"number": 5, "title": "[security] code scanning alert #1: py/sql-injection", "labels": labelsOf("security", "bug", "priority:P3", "keep-me"),
				"body": ""},
			// a former bestpractices bug naming alert 3: adopted
			{"number": 6, "title": "[bestpractices] open code scanning alert #3", "labels": labelsOf("bug", "priority:P2"),
				"body": "- code scanning alert #3: " + base + "code-scanning/3\n"},
			// a ticket whose alert closed: closed
			{"number": 7, "title": "old", "labels": labelsOf("security", "bug"), "body": Marker(base + "code-scanning/99")},
			// a ticket for a secret alert, its listing unreadable: left open
			{"number": 8, "title": "s", "labels": labelsOf("security", "bug"), "body": Marker(base + "secret-scanning/4")},
		}},
	}
	f.issues["X"][0]["body"] = Body(cs1(), now)
	g := f.server(t)
	res, err := Sync(g, Repo{Name: "X"}, now, false)
	if err != nil {
		t.Fatal(err)
	}
	if res.Opened != 2 || res.Updated != 2 || res.Adopted != 1 || res.Closed != 1 || len(res.Unread) != 1 {
		t.Fatalf("opened %d updated %d adopted %d closed %d unread %v\n%s", res.Opened, res.Updated, res.Adopted, res.Closed,
			res.Unread, strings.Join(res.Messages, "\n"))
	}
	w := strings.Join(f.writes, "\n")
	for _, want := range []string{
		`PATCH X/issues/5 {"body"`, `"keep-me"`, `"priority:P1"`, // alert 1: high is P1, own labels kept
		`PATCH X/issues/6`,       // alert 3 adopted
		`code scanning alert #3`, //
		`Past its SLA`,           // and past its SLA
		`POST X/issues {"body":"\u003c!-- security-alert: https://github.com/swarm-routing/X/security/code-scanning/10 --\u003e`,
		`posts a proposal here`, // the policy finding's ticket
		`POST X/issues/7/comments`, `PATCH X/issues/7 {"state":"closed","state_reason":"completed"}`,
	} {
		if !strings.Contains(w, want) {
			t.Errorf("writes lack %q:\n%s", want, w)
		}
	}
	if strings.Contains(w, "issues/8") || strings.Contains(w, "`query`") || strings.Contains(w, "@user") {
		t.Errorf("an unread kind's ticket is left alone; alert text is neutralised:\n%s", w)
	}
	// a second run on the state the first left: nothing to do for the new tickets
	f.writes = nil
	f.issues["X"] = f.issues["X"][2:] // 5, 6 dropped; 7 still listed by this fake (closed by the run)
	f.issues["X"] = f.issues["X"][2:]
	res, err = Sync(g, Repo{Name: "X"}, now, true)
	if err != nil || len(f.writes) != 0 || res.Opened != 2 {
		t.Errorf("a dry run writes nothing: %v %v", f.writes, err)
	}
}

func cs1() Alert {
	var r rawAlert
	b, _ := json.Marshal(cs("X", 1, "CodeQL", "high", "2026-11-10T00:00:00Z"))
	_ = json.Unmarshal(b, &r)
	return r.alert(CodeScanning)
}

func TestNamesURLBoundary(t *testing.T) {
	u := "https://github.com/swarm-routing/X/security/code-scanning/1"
	if namesURL(u+"0", u) || !namesURL(u+"0 and "+u+".", u) || !namesURL(u, u) {
		t.Error("namesURL boundary")
	}
	if markerURL("x\n"+Marker(u)+"\n") != u || markerURL("none") != "" {
		t.Error("markerURL")
	}
}

func TestMainAndReport(t *testing.T) {
	f := &fakeOrg{
		repos: []map[string]any{{"name": "pub"}, {"name": "secretproj", "private": true}, {"name": "old", "archived": true},
			{"name": ".github"}},
		alerts: map[string][]map[string]any{
			"secretproj code-scanning/alerts": {cs("secretproj", 4, "CodeQL", "critical", "2026-10-01T00:00:00Z")},
			"pub secret-scanning/alerts": {{"number": 1, "html_url": "https://github.com/swarm-routing/pub/security/secret-scanning/1",
				"created_at": "2026-11-16T00:00:00Z", "secret_type_display_name": "Token"}},
		},
		status: map[string]int{},
		issues: map[string][]map[string]any{},
		pulls: map[string][]map[string]any{"pub": {{"merged_at": "2026-11-15T00:00:00Z", "head": map[string]any{"ref": "claude/security-fix-code-scanning-2"}},
			{"merged_at": "2026-11-15T00:00:00Z", "head": map[string]any{"ref": "other"}}}},
	}
	g := f.server(t)
	env := func(k string) string {
		if k == "GH_TOKEN" {
			return "tok"
		}
		return ""
	}
	var out, errb bytes.Buffer
	rc := Main([]string{"--report", "--now", "2026-11-17T00:00:00Z"}, env, g.Client, g.API, &out, &errb)
	o := out.String()
	if rc != 0 || strings.Contains(o, "secretproj") || !strings.Contains(o, "private repository 1: code scanning alert #4: opened") ||
		!strings.Contains(o, "pub: secret scanning alert #1: opened") || strings.Contains(o, "old:") ||
		!strings.Contains(o, "security-alerts: 3 repositories, 2 open alerts; opened 2, updated 0, closed 0 tickets") ||
		!strings.Contains(o, "report: opened #") {
		t.Errorf("rc %d\n%s\n%s", rc, o, errb.String())
	}
	var report string
	for _, i := range f.issues[".github"] {
		if i["title"] == ReportTitle {
			report = i["body"].(string)
		}
	}
	if strings.Contains(report, "secretproj") || !strings.Contains(report, "| private repository 1 | 1 | 0 | 0 | 0 | 0 | 47 | 1 | 0 | 0 |") ||
		!strings.Contains(report, "| pub | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 |") {
		t.Errorf("report:\n%s", report)
	}
	// the report again, unchanged
	out.Reset()
	if rc := Main([]string{"--report", "--now", "2026-11-17T00:00:00Z"}, env, g.Client, g.API, &out, &errb); rc != 0 ||
		!strings.Contains(out.String(), "unchanged") {
		t.Errorf("second report: %s", out.String())
	}
	out.Reset()
	if rc := Main([]string{"--repos", "bad/name"}, env, g.Client, g.API, &out, &errb); rc != 1 {
		t.Error("a bad --repos name fails")
	}
	if rc := Main([]string{"--bogus"}, env, g.Client, g.API, &out, &errb); rc != 2 {
		t.Error("usage")
	}
	out.Reset()
	if rc := Main([]string{"--repos", "pub"}, func(string) string { return "" }, g.Client, g.API, &out, &errb); rc != 0 ||
		!strings.HasPrefix(out.String(), "security-alerts: no GH_TOKEN: dry run") {
		t.Errorf("no token: %s", out.String())
	}
	var m repomask.Masker
	if b := ReportBody(nil, nil, &m, now); !strings.Contains(b, "(none)") {
		t.Error("an empty report")
	}
}

// The Dependabot listing refuses `page`: every listing follows the Link header.
func TestListFollowsLink(t *testing.T) {
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("page") != "" {
			http.Error(w, `{"message":"Pagination using the page parameter is not supported."}`, 400)
			return
		}
		if r.URL.Query().Get("after") == "" {
			w.Header().Set("Link", `<`+srv.URL+`/repos/x/dependabot/alerts?state=open&per_page=100&after=abc>; rel="next"`)
			_, _ = w.Write([]byte(`[{"number":1}]`))
			return
		}
		_, _ = w.Write([]byte(`[{"number":2}]`))
	}))
	defer srv.Close()
	got, err := list[rawAlert](GitHub{API: srv.URL, Client: srv.Client()}, "repos/x/dependabot/alerts?state=open")
	if err != nil || len(got) != 2 || got[1].Number != 2 {
		t.Errorf("two pages through the Link header: %v %v", got, err)
	}
}
