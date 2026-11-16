// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The Python tool's --self-test, case by case, on the same fixtures
// (testdata/repos.json, testdata/anthocnet-answers.json), plus the real
// network client against an httptest server.

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"strings"
	"testing"
	"time"
)

func derive(t *testing.T, name, slug, today string) Answers {
	t.Helper()
	d := makeRepo(t, t.TempDir(), name)
	a, err := Derive(d, slug, today)
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func status(a Answers, c string) string { x, _ := a.Get(c); return x.Status }
func why(a Answers, c string) string    { x, _ := a.Get(c); return x.Why }

func TestAnswersFull(t *testing.T) {
	ans := derive(t, "Proto", "", "2026-11-13")
	var order []string
	for _, x := range ans {
		order = append(order, x.Criterion)
	}
	if !reflect.DeepEqual(order, Passing) {
		t.Fatal("every passing criterion is answered, in order")
	}
	for c := range OwnerOnly {
		if status(ans, c) != "?" {
			t.Fatalf("owner-only %s must be ?", c)
		}
	}
	for _, c := range Crypto {
		if status(ans, c) != "N/A" {
			t.Fatalf("crypto is N/A without crypto: %s", c)
		}
	}
	for _, c := range []string{"description_good", "contribution", "floss_license", "license_location",
		"maintained", "version_semver", "release_notes", "vulnerability_report_private",
		"build", "test", "test_invocation", "test_continuous_integration",
		"test_policy", "warnings", "warnings_fixed", "static_analysis",
		"static_analysis_common_vulnerabilities", "static_analysis_often",
		"dynamic_analysis", "dynamic_analysis_unsafe", "dynamic_analysis_enable_assertions"} {
		if status(ans, c) != "Met" {
			t.Errorf("full repo: %s Met, got %s", c, status(ans, c))
		}
	}
	checks := []struct {
		name string
		ok   bool
	}{
		{"no CVE in the changelog: release_notes_vulns N/A", status(ans, "release_notes_vulns") == "N/A"},
		{"coverage measured: test_most still the owner's", status(ans, "test_most") == "?" && strings.Contains(why(ans, "test_most"), "ci.yml")},
		{"a test policy: tests_are_added still the owner's", status(ans, "tests_are_added") == "?" && strings.Contains(why(ans, "tests_are_added"), "CONTRIBUTING.md")},
		{"both licences named", strings.Contains(why(ans, "floss_license"), "GPL-2.0 and MIT")},
		{"make test is the invocation", strings.Contains(why(ans, "test_invocation"), "`make test`")},
		{"CodeQL is the vulnerability analyser", strings.Contains(why(ans, "static_analysis_common_vulnerabilities"), "CodeQL")},
		{"URLs point at main", strings.Contains(why(ans, "contribution"), "https://github.com/"+Org+"/Proto/blob/main/CONTRIBUTING.md")},
		{"the slug comes from the origin remote", strings.Contains(why(ans, "repo_public"), "github.com/"+Org+"/Proto.")},
	}
	for _, c := range checks {
		if !c.ok {
			t.Error(c.name)
		}
	}
	for _, x := range ans {
		if x.Status != "?" && !strings.Contains(x.Why, "https://") {
			t.Errorf("%s: a non-? justification carries a full https URL", x.Criterion)
		}
	}
	var js map[string]string
	if err := json.Unmarshal([]byte(ans.JSON()), &js); err != nil || len(js) != 2*len(Passing) ||
		js["build_status"] != "Met" || js["build_justification"] == "" {
		t.Fatalf(".bestpractices.json keys: %v", err)
	}
}

func TestAnswersDeterministicAndOld(t *testing.T) {
	d := makeRepo(t, t.TempDir(), "Proto")
	a, _ := Derive(d, "", "2026-11-13")
	b, _ := Derive(d, "", "2026-11-13")
	if a.JSON() != b.JSON() {
		t.Fatal("deterministic")
	}
	old, _ := Derive(d, "", "2028-01-01")
	if status(old, "maintained") != "?" {
		t.Fatal("an old last commit: maintained ?")
	}
}

func TestAnswersBare(t *testing.T) {
	b := derive(t, "Tools", Org+"/Tools", "2026-11-13")
	for name, ok := range map[string]bool{
		"no CONTRIBUTING in an org repo: the org default": strings.Contains(why(b, "contribution"), "swarm-routing/.github/blob/main/CONTRIBUTING.md"),
		"no SECURITY.md in an org repo: the org default":  status(b, "vulnerability_report_process") == "Met",
		"scripts only: build N/A":                         status(b, "build") == "N/A",
		"Python only: dynamic_analysis_unsafe N/A":        status(b, "dynamic_analysis_unsafe") == "N/A",
		"ruff: warnings Met":                              status(b, "warnings") == "Met" && strings.Contains(why(b, "warnings"), "ruff"),
		"no git: maintained ?":                            status(b, "maintained") == "?",
		"a CVE in the changelog: release_notes_vulns Met": status(b, "release_notes_vulns") == "Met",
		"no fuzzing or sanitizers: dynamic_analysis ?":    status(b, "dynamic_analysis") == "?",
		"ruff alone: no vulnerability analyser":           status(b, "static_analysis_common_vulnerabilities") == "?",
	} {
		if !ok {
			t.Error(name)
		}
	}
	if o := derive(t, "Tools", "someone/Tools", "2026-11-13"); status(o, "contribution") != "?" {
		t.Error("outside the org: no org default")
	}
}

func TestAnswersSpecialCases(t *testing.T) {
	allCrypto := func(a Answers, want string) bool {
		for _, c := range Crypto {
			if status(a, c) != want {
				return false
			}
		}
		return true
	}
	if !allCrypto(derive(t, "Hm", Org+"/Hm", ""), "?") {
		t.Error("a standard-library crypto import: crypto ?")
	}
	if !allCrypto(derive(t, "Crypt", Org+"/Crypt", ""), "?") {
		t.Error("a crypto include: crypto ?")
	}
	if !allCrypto(derive(t, "Over", Org+"/Over", ""), "?") {
		t.Error("bestpractices_crypto = true: crypto ?")
	}
	if status(derive(t, "Cc", Org+"/Cc", ""), "build") != "?" {
		t.Error("compiled code without a build file: build ?")
	}
	if status(derive(t, "Tidy", Org+"/Tidy", ""), "static_analysis_often") != "?" {
		t.Error("a .clang-tidy no workflow runs: no static analysis")
	}
	o := derive(t, "Opt", Org+"/Opt", "")
	if status(o, "dynamic_analysis") != "Met" || status(o, "dynamic_analysis_enable_assertions") != "?" {
		t.Error("python -O: assertions not claimed")
	}
}

func TestProposalURLs(t *testing.T) {
	fixture, err := LoadAnswers("testdata/anthocnet-answers.json")
	if err != nil {
		t.Fatal(err)
	}
	urls, err := ProposalURLs("16656", fixture, "passing", ProposalLimit)
	if err != nil || len(urls) < 2 {
		t.Fatalf("several links: %v %d", err, len(urls))
	}
	var got []string
	for _, u := range urls {
		if len(u) > ProposalLimit || !strings.HasPrefix(u, Site+"/en/projects/16656/passing/edit?") {
			t.Fatalf("a link over the limit or not the edit form: %s", u[:80])
		}
		q, err := url.ParseQuery(u[strings.Index(u, "?")+1:])
		if err != nil {
			t.Fatal(err)
		}
		for k := range q {
			if c, ok := strings.CutSuffix(k, "_status"); ok {
				x, _ := fixture.Get(c)
				if q.Get(c+"_justification") != x.Why {
					t.Fatalf("%s: its status and justification in the same link, intact", c)
				}
			}
		}
		for _, part := range strings.Split(u[strings.Index(u, "?")+1:], "&") {
			if k, _, _ := strings.Cut(part, "="); strings.HasSuffix(k, "_status") {
				got = append(got, strings.TrimSuffix(k, "_status"))
			}
		}
	}
	var want []string
	for _, x := range fixture {
		if !OwnerOnly[x.Criterion] && x.Status != "?" {
			want = append(want, x.Criterion)
		}
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatal("every answer once, in order, owner-only left out")
	}
	small, _ := ProposalURLs("16656", fixture, "passing", 3000)
	if len(small) <= len(urls) {
		t.Fatal("a small limit splits more")
	}
	if _, err := ProposalURLs("16656", fixture, "passing", 100); err == nil {
		t.Fatal("an answer alone over the limit is refused")
	}
}

func TestCLIErrors(t *testing.T) {
	for _, args := range [][]string{nil, {"nope"}, {"answers"}, {"register", "x"}, {"check", "extra"}, {"answers", ".", "--bogus"}, {"answers", ".", "--today"}} {
		if rc, _, errOut := run(args, Env{}); rc != 2 || !strings.Contains(errOut, "usage:") {
			t.Errorf("%v: rc %d %q", args, rc, errOut)
		}
	}
	if rc, out, _ := run([]string{"--help"}, Env{}); rc != 0 || !strings.HasPrefix(out, "usage:") {
		t.Error("--help")
	}
	if rc, _, errOut := run([]string{"register", Org + "/Proto", "--answers", "/nonexistent.json", "--dir", "/x"}, Env{Remote: &lookup{hits: []any{map[string]any{"id": json.Number("1"), "repo_url": "https://github.com/" + Org + "/Proto"}}}}); rc != 1 || !strings.Contains(errOut, "/nonexistent.json") {
		t.Errorf("a missing answers file: %d %q", rc, errOut)
	}
}

func TestPyHelpers(t *testing.T) {
	for v, want := range map[any]string{nil: "None", true: "True", false: "False", json.Number("52"): "52", json.Number("52.5"): "52.5", json.Number("1e2"): "100.0", "x": "x"} {
		if got := pyStr(v); got != want {
			t.Errorf("pyStr(%v) = %q, want %q", v, got, want)
		}
	}
	if pyStr([]any{"a", json.Number("1")}) != "['a', 1]" || pyStr(map[string]any{"b": nil}) != "{'b': None}" {
		t.Error("pyStr of a list or dict")
	}
	if !pyEqual(json.Number("1"), true) || pyEqual("1", json.Number("1")) || !pyEqual([]any{"a"}, []any{"a"}) || !pyEqual(nil, nil) {
		t.Error("pyEqual")
	}
	if truthy("") || truthy(json.Number("0")) || !truthy([]any{1}) || truthy(map[string]any{}) {
		t.Error("truthy")
	}
	if quote("https://x.y/a b~") != "https%3A%2F%2Fx.y%2Fa%20b~" {
		t.Error("quote")
	}
	if jsonString("a\"\\\n\x01é") != `"a\"\\\n\u0001é"` {
		t.Error("jsonString")
	}
	if pyJoin("a/", "b") != "a/b" || pyJoin("a", "/b") != "/b" || dirname("x/y/z") != "x/y" || dirname("z") != "" {
		t.Error("paths")
	}
	if typeName(failure("x")) != "Failure" || described(valueError("v")) != "ValueError: v" {
		t.Error("described")
	}
}

func TestHTTP(t *testing.T) {
	var methods []string
	site := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		methods = append(methods, r.Method)
		switch {
		case r.URL.Path == "/projects/1.json":
			w.Write([]byte(`{"id": 1, "badge_percentage_0": 52}`))
		case r.URL.Path == "/projects.json":
			if r.URL.Query().Get("url") != "https://github.com/swarm-routing/X" || r.Header.Get("User-Agent") != "bestpractices-check" {
				t.Errorf("search: %s", r.URL)
			}
			w.Write([]byte(`[{"id": 3, "repo_url": "https://github.com/swarm-routing/X/"}, {"id": 2, "repo_url": "https://github.com/swarm-routing/x"}]`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer site.Close()
	var slept []time.Duration
	now := time.Unix(0, 0)
	h := NewHTTP("", "")
	h.SiteURL, h.Sleep, h.Now = site.URL, func(d time.Duration) { slept = append(slept, d) }, func() time.Time { return now }
	if d, err := h.Site("1"); err != nil || pyStr(d.(map[string]any)["badge_percentage_0"]) != "52" {
		t.Fatalf("site: %v %v", d, err)
	}
	if id, err := Registered(h, Org+"/X"); err != nil || id != "2" {
		t.Fatalf("registered: %q %v", id, err)
	}
	if _, err := h.Site("9"); err == nil || described(err) != "HTTPError: HTTP Error 404: Not Found" {
		t.Fatalf("a missing project: %v", err)
	}
	if len(slept) != 2 || slept[0] != SiteInterval {
		t.Fatalf("one request a second: %v", slept)
	}
	for _, m := range methods {
		if m != http.MethodGet {
			t.Fatal("the site is only read")
		}
	}

	var api *httptest.Server
	api = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			t.Errorf("no token on %s", r.URL)
		}
		switch r.URL.Path {
		case "/orgs/swarm-routing/repos":
			if r.URL.Query().Get("page") == "" {
				w.Header().Set("Link", `<`+api.URL+`/orgs/swarm-routing/repos?page=2>; rel="next"`)
				w.Write([]byte(`[{"name": "b", "archived": false, "private": false}, {"name": "old", "archived": true, "private": false}]`))
				return
			}
			w.Write([]byte(`[{"name": "a", "archived": false, "private": false}]`))
		case "/repos/swarm-routing/a/contents/x":
			w.Write([]byte(`{"content": "aGVs\nbG8="}`))
		case "/repos/swarm-routing/a/git/trees/main":
			w.Write([]byte(`{"tree": [{"path": "docs"}, {"path": "docs/x.md"}]}`))
		case "/repos/swarm-routing/a/issues":
			if r.Method != http.MethodPost {
				t.Errorf("issues: %s", r.Method)
			}
			w.WriteHeader(http.StatusBadGateway)
			w.Write([]byte(`{"message": "bad gateway"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer api.Close()
	g := NewHTTP("tok", api.URL)
	if repos, err := g.Repos(); err != nil || !reflect.DeepEqual(repos, []string{"a", "b"}) {
		t.Fatalf("repos over two pages, archived left out: %v %v", repos, err)
	}
	if text, ok, err := g.File("a", "x"); err != nil || !ok || text != "hello" {
		t.Fatalf("file: %q %v %v", text, ok, err)
	}
	if _, ok, err := g.File("a", "missing"); err != nil || ok {
		t.Fatal("a missing file is absent, not an error")
	}
	if tree, err := g.Tree("a"); err != nil || !tree["docs/x.md"] {
		t.Fatalf("tree: %v %v", tree, err)
	}
	if _, err := g.API("POST", "repos/swarm-routing/a/issues", map[string]any{"title": "t"}, false); err == nil ||
		!strings.Contains(err.Error(), "bad gateway (HTTP 502)") || typeName(err) != "Failure" {
		t.Fatalf("a failed write: %v", err)
	}
}
