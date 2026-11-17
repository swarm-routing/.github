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
	// the issue history (#613)
	issues, comments, advisories any
	issueErr                     error
	since                        string
}

func (f *fakeHistory) ClosedPulls(string) (any, error) { return f.pulls, f.err }
func (f *fakeHistory) PullFiles(_, n string) (any, error) {
	return f.files[n], nil
}
func (f *fakeHistory) Coverage(string) (any, error) { return f.coverage, nil }
func (f *fakeHistory) Issues(_, label, since string) (any, error) {
	f.since = since
	var out []any
	il, _ := f.issues.([]any)
	for _, x := range il {
		if strings.Contains(fmt.Sprint(x.(map[string]any)["labels"]), "name:"+label+"]") {
			out = append(out, x)
		}
	}
	return out, f.issueErr
}
func (f *fakeHistory) IssueComments(_, n string) (any, error) {
	var out []any
	cl, _ := f.comments.([]any)
	for _, x := range cl {
		if strings.HasSuffix(x.(map[string]any)["issue_url"].(string), "/issues/"+n) {
			out = append(out, x)
		}
	}
	return out, nil
}
func (f *fakeHistory) Advisories(string) (any, error) { return f.advisories, nil }

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

// issue is one issue of the fake history: number, label, author
// association, opened, closed ("" open).
func issue(n int, label, assoc, opened, closed string) map[string]any {
	m := map[string]any{"number": n, "url": fmt.Sprintf("https://api.github.com/repos/swarm-routing/X/issues/%d", n),
		"author_association": assoc, "user": map[string]any{"type": "User"},
		"labels": []any{map[string]any{"name": label}}, "created_at": opened, "closed_at": nil}
	if closed != "" {
		m["closed_at"] = closed
	}
	return m
}

func comment(n int, assoc, userType, at string) map[string]any {
	return map[string]any{"issue_url": fmt.Sprintf("https://api.github.com/repos/swarm-routing/X/issues/%d", n),
		"author_association": assoc, "user": map[string]any{"type": userType}, "created_at": at}
}

// #613: a responsive history proposes Met with the numbers; an unresponsive
// or empty one leaves `?`, with the numbers.
func TestResponseTimes(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	f := &fakeHistory{
		issues: []any{
			issue(1, "bug", "NONE", "2026-09-01T00:00:00Z", ""),                            // a maintainer's comment on day 2
			issue(2, "bug", "CONTRIBUTOR", "2026-09-05T00:00:00Z", "2026-09-10T00:00:00Z"), // closed on day 5
			issue(3, "bug", "NONE", "2026-08-01T00:00:00Z", ""),                            // only a late answer
			issue(4, "bug", "MEMBER", "2026-08-01T00:00:00Z", ""),                          // the project's own: not counted
			issue(5, "bug", "NONE", "2026-11-10T00:00:00Z", ""),                            // 7 days old, unanswered: pending
			issue(6, "bug", "NONE", "2025-06-01T00:00:00Z", ""),                            // older than 12 months
			issue(7, "enhancement", "NONE", "2026-10-01T00:00:00Z", ""),                    // the author's own comment only
			map[string]any{"number": 8, "pull_request": map[string]any{}, "author_association": "NONE",
				"created_at": "2026-10-01T00:00:00Z", "labels": []any{map[string]any{"name": "bug"}}},
		},
		comments: []any{
			comment(1, "MEMBER", "User", "2026-09-03T00:00:00Z"),
			comment(3, "OWNER", "User", "2026-09-01T00:00:00Z"),
			comment(7, "NONE", "User", "2026-10-02T00:00:00Z"),
		},
		advisories: []any{
			map[string]any{"created_at": "2026-10-01T00:00:00Z", "published_at": "2026-10-08T00:00:00Z"},
			map[string]any{"created_at": "2026-09-01T00:00:00Z", "closed_at": "2026-09-03T00:00:00Z"},
			map[string]any{"created_at": "2025-09-01T00:00:00Z"}, // older than 6 months
		},
	}
	h := historyAnswers(f, "X", nil)
	if a, ok := h.Answers["report_responses"]; !ok || !strings.Contains(a[1], "2 of the 3 bug reports from outside the project") {
		t.Errorf("bugs: a majority answered within 14 days: %v %v", a, h.Blocked["report_responses"])
	}
	if !strings.HasPrefix(h.Blocked["enhancement_responses"], "0 of the 1 enhancement reports") {
		t.Errorf("enhancements: the author's comment is no response: %v", h.Blocked)
	}
	if a, ok := h.Answers["vulnerability_report_response"]; !ok || !strings.Contains(a[1], "2 of the 2 vulnerability reports") {
		t.Errorf("advisories answered in time: %v %v", a, h.Blocked)
	}
	if f.since != "2025-11-17T00:00:00Z" {
		t.Errorf("the issues of the last 12 months: since %s", f.since)
	}

	// a bot's answer counts; a late one, an empty history and a report in triage do not
	f.comments = append(f.comments.([]any), comment(7, "NONE", "Bot", "2026-10-03T00:00:00Z"))
	f.advisories = []any{map[string]any{"created_at": "2026-10-01T00:00:00Z"}}
	h = historyAnswers(f, "X", nil)
	if _, ok := h.Answers["enhancement_responses"]; !ok {
		t.Errorf("a bot's response counts: %v", h.Blocked)
	}
	if !strings.HasPrefix(h.Blocked["vulnerability_report_response"], "0 of the 1 vulnerability reports") {
		t.Errorf("a report still in triage: ?: %v", h.Blocked)
	}
	empty := historyAnswers(&fakeHistory{issues: []any{}, comments: []any{}, advisories: []any{}}, "X", nil)
	for _, c := range []string{"report_responses", "enhancement_responses", "vulnerability_report_response"} {
		if _, ok := empty.Answers[c]; ok || !strings.HasPrefix(empty.Blocked[c], "0 of the 0 ") {
			t.Errorf("%s: an empty history: ?: %v", c, empty.Blocked[c])
		}
	}
	none := historyAnswers(&fakeHistory{issueErr: errors.New("x")}, "X", nil)
	if !strings.HasPrefix(none.Blocked["report_responses"], "cannot read the bug reports") ||
		none.Blocked["vulnerability_report_response"] != "the security advisories are not available (HTTP 404)" {
		t.Errorf("unreadable: ?: %v", none.Blocked)
	}
	// proposed once Met: the owner-only list loses it, the proposal link carries it
	ans := Answers{{"description_good", "Met", "d"}, {"report_responses", "Met", "x"}, {"enhancement_responses", "?", "y"}}
	links, err := proposalURLs("7", ans, "passing", ProposalLimit, FromHistory)
	if err != nil || len(links) != 1 || !strings.Contains(links[0], "report_responses_status=Met") ||
		strings.Contains(links[0], "enhancement_responses") {
		t.Errorf("a response-time criterion the history shows is proposed: %v", links)
	}
	if links, _ := ProposalURLs("7", ans, "passing", ProposalLimit); strings.Contains(links[0], "report_responses") {
		t.Errorf("never from an answers file (register): %v", links)
	}
	m := HistoryReport{Blocked: map[string]string{"report_responses": "0 of the 0"}}.merge(
		map[string]any{"report_responses_status": "Met"})
	if m["report_responses_status"] != "?" {
		t.Error("a hand-edited Met in the file gives way to what the history shows")
	}
}
