// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package labels

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const taxonomy = `{"_comment": "x", "labels": [
  {"name": "bug", "color": "d73a4a", "description": "Type: defect"},
  {"name": "epic", "color": "3E4B9E", "description": "Umbrella"},
  {"name": "priority:P1", "color": "b60205", "description": "Blocks"}
]}`

// fakeGitHub holds each repository's labels and records every request.
type fakeGitHub struct {
	mu       sync.Mutex
	repos    []map[string]any
	labels   map[string][]Label // repo name -> labels
	failRepo string             // writes there answer 403
	calls    []string
	auth     []string
}

func (f *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, r.Method+" "+r.URL.Path)
	f.auth = append(f.auth, r.Header.Get("Authorization"))
	page, _ := strconv.Atoi(r.URL.Query().Get("page"))
	per, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
	slice := func(n int) (int, int) {
		lo, hi := (page-1)*per, page*per
		if lo > n {
			lo = n
		}
		if hi > n {
			hi = n
		}
		return lo, hi
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/"), "/")
	switch {
	case r.Method == "GET" && r.URL.Path == "/orgs/swarm-routing/repos":
		if r.URL.Query().Get("type") != "all" {
			http.Error(w, "type", http.StatusBadRequest)
			return
		}
		lo, hi := slice(len(f.repos))
		_ = json.NewEncoder(w).Encode(f.repos[lo:hi])
	case len(parts) >= 4 && parts[0] == "repos" && parts[1] == "swarm-routing" && parts[3] == "labels":
		repo := parts[2]
		if _, ok := f.labels[repo]; !ok {
			http.Error(w, `{"message": "Not Found"}`, http.StatusNotFound)
			return
		}
		if r.Method != "GET" && repo == f.failRepo {
			http.Error(w, `{"message": "Resource not accessible by integration"}`, http.StatusForbidden)
			return
		}
		var body map[string]string
		if r.Body != nil {
			b, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(b, &body)
		}
		switch {
		case r.Method == "GET" && len(parts) == 4:
			ls := f.labels[repo]
			lo, hi := slice(len(ls))
			_ = json.NewEncoder(w).Encode(ls[lo:hi])
		case r.Method == "POST" && len(parts) == 4:
			f.labels[repo] = append(f.labels[repo], Label{body["name"], body["color"], body["description"]})
			w.WriteHeader(http.StatusCreated)
			fmt.Fprint(w, `{}`)
		case r.Method == "PATCH" && len(parts) == 5:
			name, _ := url.PathUnescape(parts[4])
			for i, l := range f.labels[repo] {
				if l.Name == name {
					f.labels[repo][i] = Label{body["new_name"], body["color"], body["description"]}
					fmt.Fprint(w, `{}`)
					return
				}
			}
			http.Error(w, `{"message": "Not Found"}`, http.StatusNotFound)
		default:
			http.Error(w, `{"message": "unexpected"}`, http.StatusInternalServerError)
		}
	default:
		http.Error(w, `{"message": "unexpected"}`, http.StatusInternalServerError)
	}
}

func newFake() *fakeGitHub {
	return &fakeGitHub{
		repos: []map[string]any{
			{"name": "beta", "private": false},
			{"name": "alpha", "private": false},
			{"name": "secret-lib", "private": true},
			{"name": "old", "private": false, "archived": true},
		},
		labels: map[string][]Label{
			"alpha": {
				{"bug", "d73a4a", "Type: defect"},
				{"Epic", "3e4b9e", "Umbrella"},      // name's case differs: updated
				{"priority:P1", "000000", "Blocks"}, // colour differs: updated
				{"local-only", "ffffff", "kept"},    // not in the taxonomy: kept
			},
			"beta":       {{"bug", "D73A4A", "Type: defect"}, {"epic", "3e4b9e", "Umbrella"}, {"priority:P1", "b60205", "Blocks"}},
			"secret-lib": {{"wontfix", "ffffff", "private label"}},
			"old":        {},
		},
	}
}

func run(t *testing.T, f *fakeGitHub, args []string, token string) (int, string, string) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "labels.json"), []byte(taxonomy), 0o644); err != nil {
		t.Fatal(err)
	}
	wd, _ := os.Getwd()
	defer os.Chdir(wd)
	_ = os.Chdir(dir)
	var out, errb bytes.Buffer
	env := func(k string) string { return map[string]string{"GH_TOKEN": token}[k] }
	code := Main(args, env, srv.Client(), srv.URL, &out, &errb)
	return code, out.String(), errb.String()
}

func TestApply(t *testing.T) {
	f := newFake()
	code, out, errs := run(t, f, nil, "tok")
	want := "swarm-routing/alpha: created 0 [], updated 2 [epic, priority:P1], 0 failed\n" +
		"swarm-routing/beta: up to date (3 labels)\n" +
		"private repository 1: created 3 [bug, epic, priority:P1], updated 0 [], 0 failed\n"
	if code != 0 || out != want {
		t.Fatalf("exit %d\nout:\n%s\nwant:\n%s\nerr: %s", code, out, want, errs)
	}
	if strings.Contains(out+errs, "secret-lib") || strings.Contains(out+errs, "wontfix") {
		t.Error("a private repository's name or labels reached the output")
	}
	for _, c := range f.calls {
		if strings.HasPrefix(c, "DELETE") {
			t.Errorf("a label was deleted: %s", c)
		}
		if strings.Contains(c, "/old/") {
			t.Errorf("an archived repository was touched: %s", c)
		}
	}
	for _, a := range f.auth {
		if a != "Bearer tok" {
			t.Errorf("token header %q", a)
		}
	}
	got := func(repo string) string {
		var s []string
		for _, l := range f.labels[repo] {
			s = append(s, l.Name+"/"+l.Color+"/"+l.Description)
		}
		sort.Strings(s)
		return strings.Join(s, " ")
	}
	if g := got("alpha"); g != "bug/d73a4a/Type: defect epic/3e4b9e/Umbrella local-only/ffffff/kept priority:P1/b60205/Blocks" {
		t.Errorf("alpha: %s", g)
	}
	if g := got("secret-lib"); g != "bug/d73a4a/Type: defect epic/3e4b9e/Umbrella priority:P1/b60205/Blocks wontfix/ffffff/private label" {
		t.Errorf("the private repository keeps its own label and gets the taxonomy: %s", g)
	}
	// idempotent: a second run writes nothing
	n := len(f.calls)
	code, out, _ = run(t, f, nil, "tok")
	if code != 0 || strings.Count(out, "up to date") != 3 {
		t.Errorf("second run:\n%s", out)
	}
	for _, c := range f.calls[n:] {
		if !strings.HasPrefix(c, "GET ") {
			t.Errorf("a second run only reads: %s", c)
		}
	}
}

func TestDryRunAndNoToken(t *testing.T) {
	f := newFake()
	code, out, _ := run(t, f, []string{"--dry-run"}, "tok")
	if code != 0 || !strings.Contains(out, "swarm-routing/alpha: dry run: would create 0 [], update 2 [epic, priority:P1]\n") ||
		!strings.Contains(out, "private repository 1: dry run: would create 3 [bug, epic, priority:P1], update 0 []\n") {
		t.Errorf("dry run:\n%s", out)
	}
	code, out, _ = run(t, f, nil, "")
	if code != 0 || !strings.HasPrefix(out, "labels: no GH_TOKEN: dry run\n") {
		t.Errorf("no token: %d\n%s", code, out)
	}
	for _, c := range f.calls {
		if !strings.HasPrefix(c, "GET ") {
			t.Errorf("a dry run only reads: %s", c)
		}
	}
}

func TestFailureAndRepos(t *testing.T) {
	f := newFake()
	f.failRepo = "alpha"
	code, out, errs := run(t, f, nil, "tok")
	if code != 1 || !strings.Contains(out, "swarm-routing/alpha: error: epic: PATCH: HTTP 403 Resource not accessible by integration\n") ||
		!strings.Contains(out, "private repository 1: created 3") || !strings.Contains(errs, "1 of 3 repositories failed") {
		t.Errorf("a failed repository is reported, the others still run: %d\n%s\n%s", code, out, errs)
	}
	f = newFake()
	code, out, _ = run(t, f, []string{"--repos", "beta, alpha"}, "tok")
	if code != 0 || strings.Contains(out, "private") || !strings.HasPrefix(out, "swarm-routing/alpha:") {
		t.Errorf("--repos: %d\n%s", code, out)
	}
	for _, args := range [][]string{{"--repos", "nope"}, {"--repos", "old"}, {"--labels", "../x"}, {"--labels", "/etc/x"}, {"--bogus"}} {
		if code, _, _ := run(t, newFake(), args, "tok"); code != 2 {
			t.Errorf("%v: exit %d", args, code)
		}
	}
}

// Many labels and repositories: pagination reaches all of them.
func TestPages(t *testing.T) {
	f := &fakeGitHub{labels: map[string][]Label{}}
	for i := 0; i < 230; i++ {
		n := fmt.Sprintf("r%03d", i)
		f.repos = append(f.repos, map[string]any{"name": n})
		f.labels[n] = nil
	}
	for i := 0; i < 150; i++ {
		f.labels["r007"] = append(f.labels["r007"], Label{fmt.Sprintf("l%d", i), "ffffff", ""})
	}
	f.labels["r007"] = append(f.labels["r007"], Label{"bug", "d73a4a", "Type: defect"}, Label{"epic", "3e4b9e", "Umbrella"}, Label{"priority:P1", "b60205", "Blocks"})
	code, out, errs := run(t, f, []string{"--dry-run"}, "tok")
	if code != 0 || strings.Count(out, "\n") != 230 || !strings.Contains(out, "swarm-routing/r229:") ||
		!strings.Contains(out, "swarm-routing/r007: up to date") {
		t.Errorf("pages: %d %s\n%s", code, errs, out[:200])
	}
}

func TestLoad(t *testing.T) {
	for _, c := range []struct{ name, text, want string }{
		{"empty", `{"labels": []}`, "1 to 200"},
		{"json", `{`, "unexpected end"},
		{"name", `{"labels": [{"name": " x", "color": "ffffff"}]}`, "empty, too long or padded"},
		{"color", `{"labels": [{"name": "x", "color": "#ffffff"}]}`, "not six hex digits"},
		{"desc", `{"labels": [{"name": "x", "color": "ffffff", "description": "` + strings.Repeat("d", 101) + `"}]}`, "longer than 100"},
		{"twice", `{"labels": [{"name": "Bug", "color": "ffffff"}, {"name": "bug", "color": "ffffff"}]}`, "listed twice"},
	} {
		if _, err := Load([]byte(c.text)); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v", c.name, err)
		}
	}
}

// The repository's own labels.json loads.
func TestRepositoryTaxonomy(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "labels.json"))
	if os.IsNotExist(err) {
		t.Skip("not in a checkout (the image's build stage copies only the Go code)")
	}
	if err != nil {
		t.Fatal(err)
	}
	if ls, err := Load(data); err != nil || len(ls) < 10 {
		t.Fatalf("%v %d", err, len(ls))
	}
}

type failTransport struct {
	next http.RoundTripper
	on   string
}

func (t failTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if strings.Contains(r.URL.Path, t.on) {
		return nil, fmt.Errorf("connection reset by peer")
	}
	return t.next.RoundTrip(r)
}

// A transport error (a *url.Error, which names the URL) never prints a
// private repository's name or the request's URL.
func TestTransportErrorHidesPrivateName(t *testing.T) {
	f := newFake()
	srv := httptest.NewServer(f)
	defer srv.Close()
	client := &http.Client{Transport: failTransport{srv.Client().Transport, "secret-lib"}}
	g := GitHub{API: srv.URL, Token: "tok", Client: client}
	repos, err := g.Repos()
	if err != nil {
		t.Fatal(err)
	}
	want, _ := Load([]byte(taxonomy))
	var out bytes.Buffer
	err = Run(g, want, repos, false, &out)
	all := out.String()
	if err != nil {
		all += err.Error()
	}
	if err == nil || !strings.Contains(out.String(), "private repository 1: error: reading its labels: GET: connection reset by peer\n") {
		t.Errorf("the failure is reported: %v\n%s", err, out.String())
	}
	if strings.Contains(all, "secret-lib") || strings.Contains(all, srv.URL) {
		t.Errorf("the private name or the URL reached the output:\n%s", all)
	}
}

// A rate-limit answer is waited out (Retry-After, bounded) and retried once.
func TestRateLimitCooldown(t *testing.T) {
	limited := 0
	var waits []time.Duration
	f := newFake()
	inner := http.Handler(f)
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "PATCH" && limited < 1 {
			limited++
			w.Header().Set("Retry-After", "30")
			http.Error(w, `{"message": "You have exceeded a secondary rate limit"}`, http.StatusForbidden)
			return
		}
		inner.ServeHTTP(w, r)
	})
	srv := httptest.NewServer(h)
	defer srv.Close()
	g := GitHub{API: srv.URL, Token: "tok", Client: srv.Client(), Sleep: func(d time.Duration) { waits = append(waits, d) }}
	repos, _ := g.Repos()
	want, _ := Load([]byte(taxonomy))
	var out bytes.Buffer
	if err := Run(g, want, repos, false, &out); err != nil || len(waits) != 1 || waits[0] != 30*time.Second ||
		!strings.Contains(out.String(), "swarm-routing/alpha: created 0 [], updated 2 [epic, priority:P1], 0 failed\n") {
		t.Errorf("one cooldown of 30s, then the write lands: %v %v\n%s", err, waits, out.String())
	}
	// the cooldown each answer asks for
	for _, c := range []struct {
		h    http.Header
		code int
		want time.Duration
	}{
		{http.Header{"Retry-After": {"3600"}}, http.StatusTooManyRequests, time.Hour},
		{http.Header{}, http.StatusTooManyRequests, MaxCooldown},
		{http.Header{"X-Ratelimit-Remaining": {"0"}, "X-Ratelimit-Reset": {"0"}}, http.StatusForbidden, time.Second},
		{http.Header{}, http.StatusForbidden, 0},
	} {
		if got := cooldown(&http.Response{StatusCode: c.code, Header: c.h}); got != c.want {
			t.Errorf("%d %v: cooldown %v, want %v", c.code, c.h, got, c.want)
		}
	}
	// still limited after the retry, or a cooldown past the bound: the run
	// stops there, with no request before GitHub allows it
	for _, c := range []struct {
		retryAfter string
		calls      int
		waits      int
	}{{"1", 2, 1}, {"3600", 1, 0}} {
		var paths []string
		srv2 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			paths = append(paths, r.Method+" "+r.URL.Path)
			if r.URL.Path == "/orgs/swarm-routing/repos" {
				fmt.Fprint(w, `[{"name": "alpha"}, {"name": "beta"}]`)
				return
			}
			w.Header().Set("Retry-After", c.retryAfter)
			http.Error(w, `{"message": "slow down"}`, http.StatusTooManyRequests)
		}))
		waits = nil
		g2 := GitHub{API: srv2.URL, Client: srv2.Client(), Sleep: func(d time.Duration) { waits = append(waits, d) }}
		repos, _ := g2.Repos()
		paths = nil
		var out bytes.Buffer
		err := Run(g2, want, repos, false, &out)
		srv2.Close()
		if !errors.Is(err, ErrRateLimited) || len(paths) != c.calls || len(waits) != c.waits ||
			strings.Contains(strings.Join(paths, " "), "/beta/") || !strings.Contains(out.String(), "HTTP 429 slow down") {
			t.Errorf("Retry-After %s: stop: %v paths=%v waits=%v\n%s", c.retryAfter, err, paths, waits, out.String())
		}
	}
}

type brokenBody struct{}

func (brokenBody) Read([]byte) (int, error) { return 0, fmt.Errorf("connection reset") }
func (brokenBody) Close() error             { return nil }

type limitedTransport struct{ calls *[]string }

func (t limitedTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	*t.calls = append(*t.calls, r.URL.Path)
	if r.URL.Path == "/orgs/swarm-routing/repos" {
		return &http.Response{StatusCode: http.StatusOK, Header: http.Header{},
			Body: io.NopCloser(strings.NewReader(`[{"name": "alpha"}, {"name": "beta"}]`)), Request: r}, nil
	}
	return &http.Response{StatusCode: http.StatusTooManyRequests,
		Header: http.Header{"Retry-After": {"3600"}}, Body: brokenBody{}, Request: r}, nil
}

// A rate-limit answer whose body cannot be read still stops the run.
func TestRateLimitUnreadableBody(t *testing.T) {
	var calls []string
	g := GitHub{API: "http://api.invalid", Client: &http.Client{Transport: limitedTransport{&calls}},
		Sleep: func(time.Duration) { t.Error("no wait past the bound") }}
	repos, err := g.Repos()
	if err != nil {
		t.Fatal(err)
	}
	want, _ := Load([]byte(taxonomy))
	var out bytes.Buffer
	err = Run(g, want, repos, false, &out)
	if !errors.Is(err, ErrRateLimited) || len(calls) != 2 || !strings.Contains(out.String(), "reading the answer failed") {
		t.Errorf("stops at the first repository: %v %v\n%s", err, calls, out.String())
	}
}
