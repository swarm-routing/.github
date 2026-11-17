// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// #634: static_analysis_fixed from what blocks a merge, tests_are_added and
// test_most from a fake history; `?` with what was read wherever the
// evidence is missing.

import (
	"bytes"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// fakeHistory is a repository's pull requests (number -> title, merged_at,
// files) and its Codecov record.
type fakeHistory struct {
	pulls    []any
	files    map[string][]any
	coverage any
	err      error
}

func (f *fakeHistory) ClosedPulls(string) (any, error) { return f.pulls, f.err }
func (f *fakeHistory) PullFiles(_, n string) (any, error) {
	return f.files[n], nil
}
func (f *fakeHistory) Coverage(string) (any, error) { return f.coverage, nil }

// add records a merged pull request and its files.
func (f *fakeHistory) add(n int, title, merged string, files ...string) {
	if f.files == nil {
		f.files = map[string][]any{}
	}
	m := map[string]any{"number": n, "title": title, "merged_at": nil}
	if merged != "" {
		m["merged_at"] = merged
	}
	f.pulls = append(f.pulls, m)
	for _, x := range files {
		f.files[fmt.Sprint(n)] = append(f.files[fmt.Sprint(n)], map[string]any{"filename": x})
	}
}

var policy = map[string]any{"test_policy_status": "Met"}

func codecov(cov, stamp string) map[string]any {
	return map[string]any{"updatestamp": stamp, "totals": map[string]any{"coverage": cov}}
}

func TestTestsAreAdded(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	f := &fakeHistory{coverage: codecov("77.39", "2026-11-17T04:28:24.667665Z")}
	f.add(1, "feat(core): a", "2026-11-10T00:00:00Z", "core/a.cc", "core/test/test-a.cc")
	f.add(2, "fix: b", "2026-11-11T00:00:00Z", "tools/b.py", "tools/test_b.py")
	f.add(3, "feat!: c", "2026-11-12T00:00:00Z", "cmd/c/main.go")
	f.add(4, "docs: only words", "2026-11-13T00:00:00Z", "README.md")
	f.add(5, "feat: closed, not merged", "", "x.cc")
	f.add(6, "fix(ci): no code", "2026-11-14T00:00:00Z", ".github/workflows/ci.yml")
	f.add(7, "feat: d", "2026-11-15T00:00:00Z", "internal/d/d.go", "internal/d/d_test.go")
	h := historyAnswers(f, "X", policy)
	a, ok := h.Answers["tests_are_added"]
	if !ok || !strings.Contains(a[1], "3 of the 4 most recent merged feat/fix pull requests that change code also change tests (#7, #2, #1)") {
		t.Fatalf("a responsive history: Met with the numbers: %v %v", a, h.Blocked)
	}
	if b, ok := h.Answers["test_most"]; !ok || !strings.Contains(b[1], "77%") || !strings.Contains(b[1], "2026-11-17") {
		t.Errorf("test_most: %v %v", b, h.Blocked)
	}

	few := &fakeHistory{}
	few.add(1, "feat: a", "2026-11-10T00:00:00Z", "a.cc", "test/a.cc")
	few.add(2, "feat: b", "2026-11-11T00:00:00Z", "b.cc", "test/b.cc")
	h = historyAnswers(few, "X", policy)
	if !strings.HasPrefix(h.Blocked["tests_are_added"], "2 of the 2 ") {
		t.Errorf("fewer than %d: ?: %v", MinMajor, h.Blocked)
	}

	untested := &fakeHistory{}
	for i := 1; i <= 12; i++ {
		files := []string{fmt.Sprintf("src/%d.py", i)}
		if i > 9 { // the three most recent add tests; ten are read
			files = append(files, fmt.Sprintf("tests/test_%d.py", i))
		}
		untested.add(i, "fix: n", fmt.Sprintf("2026-10-%02dT00:00:00Z", i), files...)
	}
	h = historyAnswers(untested, "X", policy)
	if !strings.HasPrefix(h.Blocked["tests_are_added"], "3 of the 10 ") {
		t.Errorf("less than half: ?: %v", h.Blocked)
	}
	if h = historyAnswers(f, "X", map[string]any{}); !strings.HasPrefix(h.Blocked["tests_are_added"], "no written test policy") {
		t.Errorf("no policy: ?: %v", h.Blocked)
	}
	if h = historyAnswers(&fakeHistory{err: errors.New("x")}, "X", policy); !strings.HasPrefix(h.Blocked["tests_are_added"], "cannot read") {
		t.Errorf("unreadable: ?: %v", h.Blocked)
	}
	if h = historyAnswers(nil, "X", policy); len(h.Answers)+len(h.Blocked) != 0 {
		t.Error("no reader: nothing read, nothing proposed")
	}
}

func TestTestMost(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	for _, c := range []struct {
		record any
		want   string // "Met", or the start of why it stays ?
	}{
		{codecov("50.0", "2026-11-16T00:00:00Z"), "Codecov measures 50% of main covered"},
		{codecov("51.09", "2026-11-16T00:00:00Z"), "Met"},
		{codecov("90", "2026-06-01T00:00:00Z"), "Codecov's report of main is not from the last 90 days"},
		{map[string]any{"totals": nil}, "no Codecov coverage report"},
		{nil, "no Codecov coverage report"},
	} {
		h := historyAnswers(&fakeHistory{coverage: c.record}, "X", nil)
		_, met := h.Answers["test_most"]
		if (c.want == "Met") != met || (!met && !strings.HasPrefix(h.Blocked["test_most"], c.want)) {
			t.Errorf("%v: want %s, got %v %v", c.record, c.want, h.Answers, h.Blocked)
		}
	}
}

// The check proposes what the history shows, and prints what it did not.
func TestCheckReadsHistory(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	proposed := `{"test_policy_status": "Met", "tests_are_added_status": "?", "test_most_status": "?"}`
	f := &histFake{fake: &fake{
		sites: map[string]any{"7": map[string]any{"repo_url": "https://github.com/swarm-routing/X"}},
		files: map[[2]string]string{
			{"X", Config}: "bestpractices_project = \"7\"\n",
			{"X", Out}:    proposed,
		},
		tree: map[string]bool{}, repos: []string{"X"},
	}, fakeHistory: &fakeHistory{coverage: codecov("40", "2026-11-16T00:00:00Z")}}
	for i := 1; i <= 3; i++ {
		f.add(i, "feat: x", fmt.Sprintf("2026-11-1%dT00:00:00Z", i), "a.go", "a_test.go")
	}
	var out bytes.Buffer
	Check(CheckArgs{Repos: "X"}, f, nil, func(string) string { return "" }, &out)
	s := out.String()
	if !strings.Contains(s, "tests_are_added_status=Met") || strings.Contains(s, "test_most_status") {
		t.Errorf("tests_are_added proposed, test_most not:\n%s", s)
	}
	if !strings.Contains(s, "    test_most ?: Codecov measures 40% of main covered") {
		t.Errorf("the check says why test_most stays ?:\n%s", s)
	}
}

type histFake struct {
	*fake
	*fakeHistory
}

func TestHTTPCoverage(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Error("the GitHub token never goes to Codecov")
		}
		if r.URL.Path == "/api/v2/github/swarm-routing/repos/a/" {
			w.Write([]byte(`{"updatestamp": "2026-11-17T04:28:24.667665Z", "totals": {"coverage": 77.39}}`))
			return
		}
		http.NotFound(w, r)
	}))
	defer srv.Close()
	h := NewHTTP("tok", "")
	h.CodecovURL = srv.URL
	got, err := h.Coverage("a")
	if err != nil || pyStr(got.(map[string]any)["totals"].(map[string]any)["coverage"]) != "77.39" {
		t.Fatalf("coverage: %v %v", got, err)
	}
	if got, err := h.Coverage("none"); got != nil || err != nil {
		t.Fatalf("no report: (nil, nil), got %v %v", got, err)
	}
}

// static_analysis_fixed: a finding blocks the merge (the ruleset's CodeQL
// gate, or an analyser a required check runs), else ?.
func TestStaticAnalysisFixed(t *testing.T) {
	lint := `on:
  pull_request:
jobs:
  python:
    uses: swarm-routing/.github/.github/workflows/reusable-python-ci.yml@main
  module:
    needs: python
    uses: swarm-routing/.github/.github/workflows/reusable-ns3-ci.yml@main
  gate:
    name: CI gate
    needs: [module]
    runs-on: ubuntu-24.04
    steps:
      - run: echo ok
  shell:
    name: Shell (${{ matrix.os }})
    runs-on: ubuntu-24.04
    steps:
      - run: |
          shellcheck tools/*.sh
`
	cases := []struct {
		name, settings, want, says string
	}{
		{"ruleset", "[settings]\ncode_scanning = true\n", "Met", "CodeQL reports a high-or-higher"},
		{"required via needs", "[settings]\nrequired_checks = [\"CI gate\"]\n", "Met", `A ruff finding fails the required check "CI gate"`},
		{"required directly", "[settings]\nrequired_checks = [\"python / python\"]\n", "Met", `"python / python"`},
		{"matrix name", "[settings]\nrequired_checks = [\"Shell (ubuntu)\"]\n", "Met", "shellcheck"},
		{"not required", "[settings]\nrequired_checks = [\"title / title\"]\n", "?", "No static-analysis finding blocks a merge"},
		{"no settings", "", "?", "No static-analysis finding"},
	}
	for _, c := range cases {
		a := repoOf(t, "Lint", map[string]string{
			"README.md":                "x\n",
			Config:                     c.settings,
			".github/workflows/ci.yml": lint,
		})
		wantStatus(t, a, c.want, "static_analysis_fixed")
		if !strings.Contains(why(a, "static_analysis_fixed"), c.says) {
			t.Errorf("%s: %s", c.name, why(a, "static_analysis_fixed"))
		}
	}
	// CodeQL alone fails no run: not a gate without the ruleset
	codeql := repoOf(t, "Q", map[string]string{
		"README.md": "x\n", Config: "[settings]\nrequired_checks = [\"analyze\"]\n",
		".github/workflows/codeql.yml": "on:\n  pull_request:\njobs:\n  analyze:\n    steps:\n      - uses: github/codeql-action/analyze@v3\n",
	})
	wantStatus(t, codeql, "?", "static_analysis_fixed")
}
